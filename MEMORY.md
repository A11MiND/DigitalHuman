# DigitalHuman 專案記憶

## 專案定位
秦始皇 AI 數字人，面向中小學生，角色扮演歷史人物問答。

## 技術決策歷史

### 已搭建版本（當前代碼）
```
DigitalHuman/
├── server.py          # FastAPI + 4 uvicorn workers, 支持 50 併發
├── static/index.html  # Canvas 秦始皇動畫 + 聊天 UI + 粵語語音
├── requirements.txt   # fastapi, uvicorn, httpx, edge-tts
└── run.sh            # 一鍵啟動，自動顯示 QR Code
```

架構：MacBook Air → Flask 代理 → DeepSeek API + Edge TTS（粵語 zh-HK-WanLungNeural）

### 關鍵技術選擇
- **角色動畫**：Canvas 2D 手繪秦始皇（冕冠、黑袍紅邊、呼吸眨眼、TTS 嘴型同步）
- **語音識別**：瀏覽器 Web Speech API（zh-HK 粵語）
- **TTS**：Edge TTS（zh-HK-WanLungNeural 粵語男聲，免費）
- **LLM**：DeepSeek Chat（API），System Prompt 裝入秦始皇角色設定 + 歷史知識
- **部署**：MacBook Air 作為伺服器，學生手機掃碼訪問，MacBook 需能上外網調 API
- **前端**：行動端優先，純聊天界面，無需安裝

### 已去掉的舊方案組件
- ❌ 小冰 RTC SDK（慢、卡、不穩定）
- ❌ AnythingLLM（多餘的中間層）
- ❌ RAG 知識庫（385KB 資料用 System Prompt 替代即可）

### 討論中但未實施的改進方向
- 🔄 MiniMax 星野：LLM 角色扮演更自然 + TTS 情感更豐富，一個 API 解決 LLM + TTS
- 🔄 Live2D：如能找到合適的秦始皇模型可替代 Canvas 繪製
- 🔄 學校內聯網無外網場景：尚待確認需求，可能需要本地 Ollama 模型

## 用戶偏好
- 不要 Brave Search / SerpAPI
- TTS 必須支援粵語（輸入輸出都要粵語）
- DeepSeek 可用，MiniMax 也在考慮中
- 部署終端：MacBook Air（無 GPU 算力，依賴 API）
- 面向中小學生，課本級知識即可

## 環境變數
- DEEPSEEK_API_KEY：需要設定
- Google API Key（已廢棄，不用的網頁搜尋功能）：AIzaSyC3GomY3rtnVO-hpwV6Gq7fGidbhzlooSg
- Google CSE ID：20afae6496bff4ebf
