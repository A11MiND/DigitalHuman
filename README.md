# 秦始皇數字人 Digital Human - Qin Shi Huang

面向中小學生的 AI 歷史人物互動數字人。

## 技術棧
- **LLM**: MiniMax M2.7
- **TTS**: MiniMax speech-2.8-hd（支援粵語/普通話/English）
- **ASR**: Web Speech API
- **後端**: FastAPI + WebSocket
- **前端**: 純 HTML/CSS/JS，暖色 UI，桌面豎版適配

## 快速啟動

```bash
pip install -r requirements.txt
export MINIMAX_API_KEY='your-key'
python3 server.py
```

打開 http://localhost:8080

## Demo

<!-- TODO: 補充 demo 截圖/影片 -->

## License

MIT
