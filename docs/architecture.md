# 秦始皇數字人 — 系統架構

```mermaid
graph TB
    subgraph Browser["🖥️ 瀏覽器 (Frontend)"]
        UI["index.html<br/>SPA 单页应用"]
        Video["🎬 Video Player<br/>idle.mp4 / talk.mp4"]
        SR["🎤 SpeechRecognition<br/>Web Speech API"]
        WS_Client["🔌 WebSocket Client"]
        Audio["🔊 Audio Playback<br/>Blob → Audio()"]
        Settings["⚙️ 設定面板<br/>語言/音色/TTS參數/畫面調整"]
    end

    subgraph FastAPI["🐍 FastAPI Server (Python)"]
        direction TB
        HTTP_Routes["📡 HTTP Routes"]
        POST_ask["POST /ask<br/>SSE 流式 LLM"]
        POST_tts["POST /tts<br/>TTS 音頻合成"]
        WS_Server["🔌 WebSocket /ws<br/>全雙工實時對話"]
        GET_health["GET /health<br/>健康檢查"]
        Static["📁 Static Files<br/>index.html + videos"]

        LLM_Fn["🧠 minimax_llm_stream()<br/>SSE 流式調用"]
        TTS_Fn["🗣️ minimax_tts_streaming()<br/>WebSocket 流式 TTS"]

        SystemPrompt["📝 SYSTEM_PROMPT<br/>角色人設 (秦始皇/漢武帝/唐太宗)"]
        TTSConfig["🎛️ TTS Config<br/>speed/vol/pitch/emotion<br/>voice_modify/sound_effect"]
    end

    subgraph MiniMax["☁️ MiniMax API"]
        LLM_API["MiniMax-M2.7<br/>chatcompletion_v2<br/>(HTTP SSE)"]
        TTS_API["speech-2.8-hd/turbo<br/>t2a_v2<br/>(WebSocket)"]
    end

    %% User interactions
    User["👤 用戶"] -->|語音/文字| UI
    UI --> SR
    UI --> Video
    UI --> Settings
    UI --> Audio

    %% Frontend → Backend
    UI -->|文字對話| POST_ask
    UI -->|單次TTS| POST_tts
    WS_Client <-->|全雙工: JSON + Binary Audio| WS_Server

    %% Backend internal
    POST_ask --> LLM_Fn
    POST_tts --> TTS_Fn
    WS_Server --> LLM_Fn
    WS_Server --> TTS_Fn
    WS_Server --> SystemPrompt
    WS_Server --> TTSConfig
    LLM_Fn --> SystemPrompt

    %% Backend → MiniMax
    LLM_Fn -->|Bearer Token| LLM_API
    TTS_Fn -->|Bearer Token| TTS_API

    %% Data flow
    LLM_API -.->|"SSE: text chunks"| LLM_Fn
    TTS_API -.->|"WS: hex audio chunks"| TTS_Fn
    LLM_Fn -.->|"SSE: content Δ"| POST_ask
    TTS_Fn -.->|"binary mp3"| POST_tts
    WS_Server -.->|"JSON: llm events"| WS_Client
    WS_Server -.->|"Binary: audio data"| WS_Client

    %% Styles
    classDef frontend fill:#f5e6d3,stroke:#8a6d3b,color:#3d3028
    classDef backend fill:#e8dcc8,stroke:#6a5028,color:#3d3028
    classDef cloud fill:#d4c4a8,stroke:#8a6d3b,color:#3d3028
    classDef user fill:#c9a84c,stroke:#8a6d3b,color:#fff

    class UI,Video,SR,WS_Client,Audio,Settings frontend
    class FastAPI,POST_ask,POST_tts,WS_Server,GET_health,Static,LLM_Fn,TTS_Fn,SystemPrompt,TTSConfig,HTTP_Routes backend
    class MiniMax,LLM_API,TTS_API cloud
    class User user
```

## 通訊流程

### 1. WebSocket 全雙工對話流程

```mermaid
sequenceDiagram
    participant U as 👤 用戶
    participant F as 前端 Browser
    participant B as 後端 /ws
    participant L as MiniMax LLM
    participant T as MiniMax TTS

    U->>F: 語音/文字輸入
    F->>B: WebSocket JSON {"type":"text","content":"..."}

    B->>B: 載入 SYSTEM_PROMPT + 歷史
    B->>F: JSON {"type":"status","content":"thinking"}
    B->>L: POST chatcompletion_v2 (SSE)
    L-->>B: SSE stream: text chunks
    B-->>F: JSON {"type":"llm","content":"朕..."}

    Note over B: LLM 完成後開始 TTS
    B->>F: JSON {"type":"status","content":"tts"}
    F->>F: 切換 talk.mp4 視頻
    B->>T: WebSocket t2a_v2 (task_start)
    T-->>B: connected_success
    B->>T: task_continue {"text":"..."}
    T-->>B: hex audio chunks
    B-->>F: Binary audio data
    F->>F: 緩存 → Blob → Audio.play()

    B->>F: JSON {"type":"status","content":"done"}
    F->>F: 切回 idle.mp4 視頻
```

### 2. TTS 配置實時同步

```mermaid
sequenceDiagram
    participant F as 前端 Settings
    participant B as 後端 /ws

    F->>F: 用戶拖動 slider
    F->>B: JSON {"type":"tts_config","speed":1.5,...}
    B->>B: 更新全局 TTS 變量
    Note over B: 下次 TTS 調用時生效
```

### 3. 角色切換

```mermaid
sequenceDiagram
    participant F as 前端
    participant B as 後端 /ws

    F->>B: JSON {"type":"switch_character","persona":"han"}
    B->>B: 切換 SYSTEM_PROMPT
    B->>B: 清空 conversation_history
    B-->>F: JSON {"type":"status","content":"done"}
```

## 技術棧

| 層 | 技術 |
|---|------|
| 後端框架 | FastAPI (Python) |
| LLM | MiniMax-M2.7 (HTTP SSE Streaming) |
| TTS | MiniMax speech-2.8-hd (WebSocket Streaming) |
| 前端 | Vanilla HTML/CSS/JS (SPA) |
| 語音識別 | Web Speech API (SpeechRecognition) |
| 視頻 | HTML5 Video (idle.mp4 / talk.mp4) |
| 部署 | uvicorn + 4 workers |
