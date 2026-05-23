# Code Review — 秦始皇數字人 v1.1

> 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low | 💡 Suggestion

---

## server.py

### 🔴 C1: 全局可變狀態 + 多 Worker 不安全

```python
# 行 27-36: 模块级全局变量
TTS_VOICE_ID = "Cantonese_PlayfulMan"
TTS_SPEED = 1.0
# ...
# 行 53: SYSTEM_PROMPT 也是全局可变
SYSTEM_PROMPT = """..."""
```

**問題**: `uvicorn.run(workers=4)` 啟動 4 個獨立進程，每個有各自的全局變量副本。前端通過 WebSocket 修改一個 worker 的 `TTS_SPEED` 後，下一次請求可能被路由到另一個 worker，使用舊值。

**建議**: 用 Redis 或數據庫存儲動態配置，或用單 worker（`workers=1`）。

### 🔴 C2: SSL 證書驗證完全禁用

```python
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False    # ❌ 禁用主機名驗證
ssl_context.verify_mode = ssl.CERT_NONE  # ❌ 禁用證書驗證
```

**問題**: 對 MiniMax API 的 WebSocket 連接完全跳過 TLS 驗證，容易受到中間人攻擊。

**建議**: 刪除這兩行，使用默認的 `ssl.create_default_context()` 即可。

### 🟠 H1: `/tts` 端點「假流式」— 全部緩衝後才返回

```python
async def tts_endpoint(req: TTSRequest):
    audio_chunks = []                # ← 全部收集
    async for chunk in minimax_tts_streaming(text):
        audio_chunks.append(chunk)
    audio_data = b"".join(audio_chunks)  # ← 拼接
    return Response(content=audio_data, ...)  # ← 一次性返回
```

**問題**: 雖然內部用了流式 TTS，但 `/tts` 端點把所有 chunk 全部收集完才返回，失去了流式優勢。長文本會導致內存峰值高、首幀延遲大。

**建議**: 改用 `StreamingResponse`，直接 yield 每個 chunk。

### 🟠 H2: `/ask` SSE 端點錯誤信息未正確傳遞

```python
async for chunk in minimax_llm_stream(req.query, req.history):
    yield f"data: {json.dumps({'content': chunk})}\n\n"
```

**問題**: `minimax_llm_stream` 可能 yield `"[ERROR] ..."` 字符串，但前端通過 SSE 收到後無法區分是正常內容還是錯誤——看起來都一樣是 `{"content": "..."}`。

**建議**: 增加 `type` 字段區分 `chunk` 和 `error`。

### 🟡 M1: 未使用的變量

```python
GROUP_ID = "1931670840110227663"    # ← 從未使用
MAX_CONCURRENT_TTS = 8              # ← 從未使用
```

### 🟡 M2: `global` 聲明位置不當

```python
# 行 371-373: global 放在 if 分支內部
if msg_type == "tts_config":
    global TTS_SPEED, TTS_VOL, TTS_PITCH, TTS_EMOTION
    global TTS_VOICE_MODIFY_PITCH, TTS_VOICE_MODIFY_INTENSITY, ...
```

**問題**: Python 的 `global` 雖然可以在函數內任意位置使用，但放在分支內會讓靜態分析工具報錯。而且如果 `msg_type != "tts_config"`，某些 global 聲明就跳過了。

**建議**: 將所有 `global` 移到函數頂部。

### 🟡 M3: SYSTEM_PROMPT 硬編碼

45 行 prompt 直接寫在代碼裡，三個角色的 prompt 也嵌入在 if/elif 中。

**建議**: 抽取到 `prompts/` 目錄下的獨立文件，用 `pathlib` 加載。

### 🟡 M4: 缺少 API Key 的健壯處理

```python
if not MINIMAX_API_KEY:
    yield "[ERROR] MINIMAX_API_KEY not configured"
    return
```

只有 LLM 函數做了檢查，TTS 函數直接 `return`（靜默失敗），`/ask` 端點拋 500。行為不一致。

### 🟢 L1: `dict` 類型註解風格混用

```python
voice_cfg: dict = {...}          # 行 192
task_start_payload: dict = {...}  # 行 198
```

用 `dict[str, Any]` 更準確。

### 🟢 L2: 缺少請求日誌脫敏

日誌直接打印用戶輸入全文，可能洩露敏感信息。

### 💡 S1: 考慮添加 `/tts/stream` 端點

當前 `/tts` 是非流式的，可以額外提供一個流式端點，讓前端直接流式播放 TTS 音頻。

### 💡 S2: 考慮接入速率限制

當前沒有任何速率限制，惡意用戶可以無限調用 API 消耗配額。

---

## static/index.html

### 🟠 H3: 語音識別回聲處理脆弱

```javascript
recognition.onresult = e => {
  if (processing || currentAudio) return;  // ← 靠標誌位過濾
  // ...
  setTimeout(() => {
    if (!processing && micOn) {
      listening = true;
      try { recognition.start(); } catch(e) {}
    }
  }, 1200);  // ← 硬編碼 1.2 秒
};
```

**問題**: 用 `processing` 標誌 + 1.2 秒延遲來防止 TTS 音頻觸發語音識別（回聲）。這在網絡延遲波動時不可靠——如果 TTS 在 1.2 秒後才開始播放，識別會捕獲到自己的語音。

**建議**: 使用 AudioContext 監聽實際音頻輸出狀態，在播放期間暫停識別。

### 🟠 H4: WebSocket 重連無退避

```javascript
ws.onclose = () => { wsOk = false; setTimeout(connect, 3000); };
```

固定 3 秒重連，無指數退避、無限重試。服務器宕機時會產生大量無效連接請求。

**建議**: 實現指數退避（1s → 2s → 4s → 8s → max 30s），並在頁面卸載時清理。

### 🟡 M5: `history` 數組無上限

```javascript
history.push({ role: 'user', content: text });
// ...
history.push({ role: 'assistant', content: full_response });
```

前端 `history` 數組無限增長，雖然後端只取最後 20 條（`history[-20:]`），但前端內存持續增長。

### 🟡 M6: 音頻緩衝後一次性播放—非真正流式

```javascript
function playAudio(data) {
  if (!audioOn) return;
  audioBuffer.push(data);           // ← 全部收集
}

function playBufferedAudio() {
  const blob = new Blob(audioBuffer, { type: 'audio/mpeg' });  // ← 拼接
  const audio = new Audio(url);     // ← 一次性播放
}
```

後端通過 WebSocket 流式發送音頻 chunk，但前端全部緩衝後才播放，失去了流式低延遲優勢。

**建議**: 使用 `MediaSource API` 實現真正的流式播放。

### 🟡 M7: 元素查詢無空值檢查

```javascript
const $ = id => document.getElementById(id);
// 多處直接使用返回值：
$('btnSend').onclick = ...  // 如果元素不存在 → TypeError
```

### 🟡 M8: 設置面板打開時強制 `htmlEl.style.overflow = 'hidden'`

每次打開設置面板都設置 `overflow: hidden`，但關閉時只有兩個地方恢復（`btnSettingsClose` 和 overlay 點擊）。如果用戶通過其他方式離開（如刷新），body overflow 狀態會丟失。

### 🟢 L3: 未使用的變量

```javascript
let pendingVoiceResult = false;  // ← 從未使用
```

### 🟢 L4: 硬編碼的縮略圖背景圖

```html
<div class="crop-thumb" id="thumbIdle"
     style="background-image:url(/videos/idle_thumb.jpg);...">
```

縮略圖路徑硬編碼在 HTML 中，無法隨角色切換而改變。

### 💡 S3: 考慮使用 `<template>` 元素

泡泡消息和設置面板的 HTML 結構可以抽成 `<template>` 元素，更易維護。

### 💡 S4: 添加 Service Worker 快取

視頻文件（idle.mp4 / talk.mp4）體積較大，添加 Service Worker 快取可顯著提升二次加載速度。

---

## 總體評估

| 維度 | 評分 | 說明 |
|------|------|------|
| 功能完整性 | ⭐⭐⭐⭐ | 核心對話 + TTS + 多人設 + 參數調試 |
| 代碼質量 | ⭐⭐⭐ | 全局狀態、SSL 禁用、錯誤處理不一致 |
| 安全性 | ⭐⭐ | SSL 驗證禁用、無速率限制、日誌洩露 |
| 流式體驗 | ⭐⭐ | 後端流式 → 前端緩衝 → 非真正流式 |
| 可維護性 | ⭐⭐⭐ | 混合內聯樣式、硬編碼 prompt、Magic numbers |

### 優先修復建議

1. **修復 SSL 驗證**（C2）— 1 行改動
2. **改 workers=1 或引入共享狀態**（C1）— 配置改動或引入 Redis
3. **前端音頻改 MediaSource 流式播放**（M6）— 體驗提升最大
4. **語音回聲處理改用 AudioContext**（H3）— 可靠性提升
5. **WebSocket 重連加退避**（H4）— 穩定性提升
