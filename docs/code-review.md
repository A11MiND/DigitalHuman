# Code Review — 秦始皇數字人 v1.2

> 🤖 **Copilot CLI** + 👨‍💻 **Pi Agent** 雙審合併
>
> 🟣 = Copilot 發現 | 🟢 = Pi 發現 | 🔵 = 雙方共同發現

---

## 🔴 Critical

| # | 來源 | 文件:行 | 問題 | 建議 |
|---|------|---------|------|------|
| C1 | 🔵 | `server.py:177-179` | SSL 證書驗證完全禁用（`check_hostname=False`, `CERT_NONE`），API Key 可被 MITM 截獲 | 刪除自定義 ssl_context，使用默認 SSL |
| C2 | 🟢 | `server.py:27-36,371-400` | 全局可變狀態 + `workers=4`，前端修改 worker A 的 TTS 參數，下一次請求可能路由到 worker B | `workers=1` 或引入 Redis 共享狀態 |
| C3 | 🟣 | `server.py:329-392` | 全局 `SYSTEM_PROMPT`/`TTS_*` 被任意 WebSocket 連接修改，多用戶串話/配置污染 | 改為 per-session 狀態，避免 `global` |

---

## 🟠 High

| # | 來源 | 文件:行 | 問題 | 建議 |
|---|------|---------|------|------|
| H1 | 🔵 | `server.py:84-89`, `server.py:272-324` | CORS `allow_origins=["*"]` + 無鑒權/限流，任何站點可調用 API 消耗配額 | 限制 origin、校驗 WebSocket Origin、加速率限制 |
| H2 | 🔵 | `server.py:305-318` | `/tts` 端點「假流式」— 全部 chunk 收集完才返回，長文本內存峰值高 | 改 `StreamingResponse`，直接 yield chunk |
| H3 | 🟢 | `static/index.html:1037-1052` | 語音識別回聲處理靠 `processing` 標誌 + 1.2s 硬編碼延遲，網絡波動時不可靠 | 用 AudioContext 監聽實際音頻輸出狀態 |
| H4 | 🟢 | `static/index.html:815` | WebSocket `onclose` 固定 3s 重連，無退避、無上限 | 指數退避（1s→2s→4s→...→30s max） |

---

## 🟡 Medium

| # | 來源 | 文件:行 | 問題 | 建議 |
|---|------|---------|------|------|
| M1 | 🟣 | `static/index.html:691-695` | `voiceId` 使用全角括號（`（F)` 而非 `(F)`），可能與 API 不匹配 | 改用 ASCII 括號 |
| M2 | 🟣 | `server.py:170-172,424-431` | TTS 文本 >5000 時靜默返回，無錯誤提示，用戶無感知失敗 | 服務端截斷並發送警告 |
| M3 | 🔵 | `static/index.html:905-983` | 音頻全部緩存在 `audioBuffer`，非真正流式播放 | MediaSource API 實現流式播放 |
| M4 | 🟢 | `static/index.html:900` | `history` 數組無上限，前端內存持續增長 | 限制最大長度（如 50 條） |
| M5 | 🟢 | `server.py:94` | `history: list[dict] = []` 可變默認值 | `Field(default_factory=list)` |
| M6 | 🟢 | `server.py:25-26` | `GROUP_ID`、`MAX_CONCURRENT_TTS` 未使用 | 刪除或實現對應邏輯 |
| M7 | 🟢 | `server.py:371-373` | `global` 聲明放在 `if` 分支內 | 移到函數頂部 |
| M8 | 🟢 | `server.py:53-79` | SYSTEM_PROMPT 硬編碼在代碼中（含三個角色） | 抽取到 `prompts/` 目錄 |

---

## 🟢 Low

| # | 來源 | 文件:行 | 問題 | 建議 |
|---|------|---------|------|------|
| L1 | 🟣 | `static/index.html:879-883` | `JSON.parse` 無 try/catch，非法消息導致崩潰 | 捕獲異常並忽略 |
| L2 | 🟣 | `static/index.html:857,1028-1030` | `history` 只記錄用戶消息，導出缺少 AI 回復 | 追加 assistant 消息 |
| L3 | 🔵 | `static/index.html:1105` | `pendingVoiceResult` 未使用 | 刪除 |
| L4 | 🟣 | `static/index.html:1035` | "思考中" 狀態樣式用 `listening` 類而非 `thinking` | 改 `thinking` 類 |
| L5 | 🟢 | `server.py:192-198` | `dict` 類型註解不完整 | 改 `dict[str, Any]` |
| L6 | 🟢 | `static/index.html:754-759` | 縮略圖背景路徑硬編碼，角色切換後仍顯示舊圖 | 動態切換 |

---

## 💡 Suggestions

| # | 來源 | 建議 |
|---|------|------|
| S1 | 🟢 | 添加 `GET /tts/stream` 流式端點 |
| S2 | 🟢 | 接入速率限制（token bucket） |
| S3 | 🟢 | Service Worker 快取視頻文件 |
| S4 | 🟢 | 前端 `<template>` 元素管理重複 HTML |
| S5 | 🟣 | 日誌脫敏——不要打印完整用戶輸入 |

---

## 📊 評分矩陣

| 維度 | Pi 評分 | Copilot 發現 | 共識 |
|------|---------|-------------|------|
| 安全 | ⭐⭐ | 🔴 C1 C3 | ✅ 一致：SSL 禁用是最嚴重問題 |
| 流式體驗 | ⭐⭐ | 🟠 H2 M3 | ✅ 一致：前後端都不是真流式 |
| 代碼質量 | ⭐⭐⭐ | 🟡 M1 M5 L1 | ✅ 互補：Copilot 發現了全角括號 Bug |
| 可維護性 | ⭐⭐⭐ | 🟡 M8 L2 | ✅ 一致：配置需外部化 |

## 🔢 統計

| | Critical | High | Medium | Low | Suggestions | 總計 |
|---|----------|------|--------|-----|-------------|------|
| Pi 發現 | 1 | 3 | 5 | 4 | 4 | 17 |
| Copilot 發現 | 2 | 2 | 3 | 4 | 1 | 12 |
| 共同發現 | 1 | 1 | 1 | 1 | 0 | 4 |
| **總計** | **3** | **4** | **8** | **6** | **5** | **26** |

> 🟣 Copilot 獨特發現：**全角括號 voiceId Bug (M1)**、**JSON.parse 無異常處理 (L1)**、**history 導出不完整 (L2)**、**狀態樣式不一致 (L4)**
>
> 🟢 Pi 獨特發現：**workers 安全問題 (C2)**、**回聲處理 (H3)**、**重連退避 (H4)**、**語音識別 1.2s 硬編碼 (H3)**
