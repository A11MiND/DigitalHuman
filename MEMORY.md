# DigitalHuman 專案記憶

## 專案定位
秦始皇 AI 數字人，面向中小學生，角色扮演歷史人物問答。

## 當前技術棧（v1）

```
DigitalHuman/
├── server.py          # FastAPI + MiniMax LLM (M2.7) + MiniMax TTS (speech-2.8-hd)
├── static/index.html  # 暖色 UI + 聊天氣泡 + 設置面板 + 桌面豎版適配
├── requirements.txt   # fastapi, uvicorn, httpx, websockets
└── run.sh            # 一鍵啟動
```

### LLM & TTS
- **LLM**: MiniMax M2.7（流式，WebSocket 全雙工）
- **TTS**: MiniMax speech-2.8-hd（WebSocket 流式），支援粵語/普通話/English + 多音色切換
- **ASR**: 瀏覽器 Web Speech API，支援 zh-HK / zh-CN / en-US

### 部署
- MacBook Air 作為伺服器，手機掃碼訪問
- 需設定 `MINIMAX_API_KEY` 環境變數

## 下一步計劃

### Proposed Plan 1：AI 視頻驅動數字人
- 用 AI 工具生成 idle + talk 兩段 loop 視頻替換靜態圖
- 根據狀態（在線/說話）切換播放

### 可能的擴展
- Live2D / MediaPipe 面部追蹤
- 學校內聯網無外網場景（Ollama）
