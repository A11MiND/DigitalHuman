# Code Review v2 — 流式對話性能審查

> 🤖 **Copilot CLI** + 👨‍💻 **Pi Agent** — 重點：端到端流式流暢性
>
> 🟣 = Copilot 發現 | 🟢 = Pi 發現 | 🔵 = 雙方一致

---

## 🔴 Critical

| # | 來源 | 文件:行 | 問題 |
|---|------|---------|------|
| **C1** | 🔵 | `index.html:893-895,907-985` | **前端不是真流式播放！** 所有 TTS 音頻 chunk 只進 `audioBuffer`，等 `status: done` 後才 `new Blob()` → `Audio.play()`。後端 WebSocket 流式發送完全白費，首音延遲 = 整段TTS完成時間。這是破壞對話流暢性的核心問題。 |

## 🟠 High

| # | 來源 | 文件:行 | 問題 |
|---|------|---------|------|
| **H1** | 🔵 | `index.html:871-879` | **WebSocket 退避無效**：`_wsDelay` 在 `connect()` 內部聲明，每次調用都重置為 1000。`onclose` 閉包持有一個 `_wsDelay`，但下次 `connect()` 創建新閉包且重置。實際行為：永遠 ~1s 重連。 |
| **H2** | 🔵 | `server.py:203-205,310-312,432-435` | **TTS 錯誤被吞**：`minimax_tts_streaming()` 異常只 log，不向上傳遞。WebSocket 仍發 `status: done`。用戶看到"完成"但沒聲音。 |
| **H3** | 🟣 | `index.html:902-905` | **斷線時 `processing=true` 鎖死 UI**：`send()` 檢查 `!wsOk` 直接 return，但 `processing` 已設為 true 且永不清除，按鈕卡死。 |

## 🟡 Medium

| # | 來源 | 文件:行 | 問題 |
|---|------|---------|------|
| **M1** | 🔵 | `server.py:25-37,380` | **`dict(DEFAULT_TTS_CONFIG)` 淺拷貝**：嵌套 `voice_modify` dict 被所有連接共享。連接 A 改 `vm["pitch"]` 會污染連接 B。 |
| **M2** | 🟣 | `index.html:880-886` | **Binary WS 幀無協議校驗**：所有非文本幀直接當音頻。協議變動或混入其他 binary 會破壞播放。 |
| **M3** | 🟢 | `server.py:375-445` | **大 try/catch 吞異常類型**：payload parse、upstream、send 三段全在一個 try 裡，無法針對性恢復。 |

## 🟢 Low

| # | 來源 | 文件:行 | 問題 |
|---|------|---------|------|
| **L1** | 🟣 | `index.html:881-884` | **JSON 解析失敗僅 warn 不恢復**：發生在處理期中會造成"假在線真卡死"。 |
| **L2** | 🟢 | `server.py:116-117` | `minimax_llm_stream` 無 `history` 時 `history[-20:]` 會報錯（`None` 不可切片）。雖然調用方現在都傳了空列表，但函數簽名允許 None。 |

---

## 📊 合併統計

| 來源 | Critical | High | Medium | Low | 合計 |
|------|----------|------|--------|-----|------|
| 🔵 雙方一致 | 1 | 2 | 1 | 0 | 4 |
| 🟣 Copilot 獨特 | 0 | 1 | 1 | 1 | 3 |
| 🟢 Pi 獨特 | 0 | 0 | 1 | 1 | 2 |
| **總計** | **1** | **3** | **3** | **2** | **9** |

---

## 🎯 整改計劃

### 第一優先：端到端真流式（解決對話卡頓）

**C1 — 前端改 MediaSource 流式播放**

當前架構：
```
TTS WS chunk → audioBuffer.push() → 等 done → Blob → Audio.play()
                                  ↑ 首音等待 2-5 秒 ↑
```

目標架構：
```
TTS WS chunk → SourceBuffer.appendBuffer() → 收到第一個 chunk 即開始播放
               ↑ 首音 < 200ms ↑
```

具體做法：
1. WebSocket `onmessage` 收到 binary 時直接 `sourceBuffer.appendBuffer(chunk)`
2. 無需等 `done`，`status: tts` 時就創建 `MediaSource` 並開始播放
3. 保留 `audioBuffer` 作為降級方案（iOS Safari 等不支援 MediaSource 的場合）

### 第二優先：可靠性修復

**H1** — `_wsDelay` 移到 `connect()` 外部  
**H2** — TTS 異常時發 `error` 事件，不發 `done`  
**H3** — `send()` 失敗時重置 `processing` + UI 提示

### 第三優先：並發安全 + 防禦

**M1** — `copy.deepcopy(DEFAULT_TTS_CONFIG)`  
**L2** — `history or []` 防禦  
**M3/L1** — 拆細 try/catch + 恢復邏輯
