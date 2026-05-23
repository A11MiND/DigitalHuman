"""
Digital Human Backend — Qin Shi Huang (秦始皇) for primary/secondary students
FastAPI + MiniMax LLM + MiniMax TTS (Streaming) + WebSocket 全双工对话
"""
import os
import asyncio
import json
import logging
import ssl

import httpx
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Config ──────────────────────────────────────────────
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_LLM_BASE = "https://api.minimaxi.com/v1"
TTS_MODEL = "speech-2.8-hd"
TTS_VOICE_ID = "Cantonese_PlayfulMan"  # 粤语音色-活泼男声
TTS_LANGUAGE = "Chinese,Yue"  # 默认粤语
GROUP_ID = "1931670840110227663"
MAX_CONCURRENT_TTS = 8

# ── TTS 可调参数（可通过前端设置面板实时修改）──────────
TTS_SPEED = 1.0                # 语速 [0.5, 2]
TTS_VOL = 1.0                  # 音量 (0, 10]
TTS_PITCH = 0                  # 语调 [-12, 12]
TTS_EMOTION = None             # 情绪 (None=自动)
TTS_VOICE_MODIFY_PITCH = 0     # 音高调整 [-100, 100]
TTS_VOICE_MODIFY_INTENSITY = 0 # 强度调整 [-100, 100]
TTS_VOICE_MODIFY_TIMBRE = 0    # 音色调整 [-100, 100]
TTS_SOUND_EFFECT = None        # 音效 (None / spacious_echo / auditorium_echo / lofi_telephone / robotic)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("digital-human")

# ── System Prompt (Qin Shi Huang persona) ───────────────
SYSTEM_PROMPT = """你是秦始皇嬴政，生活在公元前259年至公元前210年。你现在正在与中小学生对话。

## 你的身份
- 你是中国历史上第一个统一中国的皇帝
- 你13岁即位为秦王，22岁亲政，39岁统一六国
- 你自称"朕"，称呼对方面用"汝"或"尔"
- 你统一了中国、文字、货币、度量衡
- 你修建了万里长城、灵渠、驰道

## 你的性格
- 威严但不失亲和——对小朋友要有耐心，不要吓到他们
- 对自己统一六国的功绩感到自豪
- 喜欢谈论你的成就：统一天下、书同文车同轨、修建长城
- 偶尔会表露对长生不老和仙药的追求
- 说话简洁有力，有帝王风范

## 关键历史知识
- 统一六国：公元前230年至前221年，先后灭韩、赵、魏、楚、燕、齐
- 中央集权：废分封、设郡县，三公九卿制
- 书同文：以小篆为全国统一文字
- 车同轨：统一车轨宽度为六尺
- 统一度量衡和货币
- 修建长城：连接北方原有的城墙，抵御匈奴
- 焚书坑儒：公元前213年焚烧百家之书，坑杀四百六十多名方士
- 兵马俑：你的陵墓中有数千个陶俑士兵

## 说话风格
- 用古风但不要太文言，让小朋友能听懂
- 每次回答控制在三到五句以内
- 朕、寡人自称，称对方为"汝"
- 语气威严但亲善

## 重要规则
- 你是秦始皇，永远不要打破角色
- 如果有人问现代的事物，你可以表示不知情，比如说"此乃何物？朕未曾见过"
- 如果有人问你不懂的概念，诚实承认，但用秦朝的语言表达
- 适度使用感叹词如"善！""妙哉！""岂有此理！"
"""

# ── FastAPI App ─────────────────────────────────────────
app = FastAPI(title="Digital Human — Qin Shi Huang")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ──────────────────────────────────────────────
class AskRequest(BaseModel):
    query: str
    history: list[dict] = []

class TTSRequest(BaseModel):
    text: str


# ── MiniMax LLM ──────────────────────────────────────────
async def minimax_llm_stream(query: str, history: list[dict] = None):
    """Call MiniMax LLM with streaming, yield text chunks."""
    if not MINIMAX_API_KEY:
        yield "[ERROR] MINIMAX_API_KEY not configured"
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        for msg in history[-20:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": query})

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{MINIMAX_LLM_BASE}/text/chatcompletion_v2",
                headers={
                    "Authorization": f"Bearer {MINIMAX_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "MiniMax-M2.7",
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.8,
                    "max_tokens": 500,
                },
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error(f"MiniMax LLM error {response.status_code}: {body}")
                    yield f"[ERROR] MiniMax API error: {response.status_code}"
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices and len(choices) > 0:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

        except httpx.ReadTimeout:
            yield "[ERROR] Request timeout"
        except Exception as e:
            logger.error(f"MiniMax LLM stream error: {e}")
            yield f"[ERROR] {str(e)}"


# ── MiniMax TTS WebSocket Streaming ──────────────────────────────────────────
async def minimax_tts_streaming(text: str):
    """MiniMax TTS WebSocket streaming, yields audio chunks as they arrive."""
    if not MINIMAX_API_KEY:
        return

    text = text.strip()
    if not text or len(text) > 5000:
        return

    url = "wss://api.minimaxi.com/ws/v1/t2a_v2"
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}"}

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        async with websockets.connect(url, additional_headers=headers, ssl=ssl_context) as ws:
            # Wait for connection success
            connected_msg = await ws.recv()
            connected_data = json.loads(connected_msg)
            if connected_data.get("event") != "connected_success":
                logger.error(f"TTS WebSocket connection failed: {connected_data}")
                return

            # Build voice_setting
            voice_cfg: dict = {
                "voice_id": TTS_VOICE_ID,
                "speed": TTS_SPEED,
                "vol": TTS_VOL,
                "pitch": TTS_PITCH,
            }
            if TTS_EMOTION:
                voice_cfg["emotion"] = TTS_EMOTION

            # Build task_start payload
            task_start_payload: dict = {
                "event": "task_start",
                "model": TTS_MODEL,
                "language_boost": TTS_LANGUAGE,
                "voice_setting": voice_cfg,
                "audio_setting": {
                    "sample_rate": 32000,
                    "bitrate": 128000,
                    "format": "mp3",
                    "channel": 1
                }
            }

            # voice_modify (独立顶层字段)
            voice_modify: dict = {}
            if TTS_VOICE_MODIFY_PITCH != 0:
                voice_modify["pitch"] = TTS_VOICE_MODIFY_PITCH
            if TTS_VOICE_MODIFY_INTENSITY != 0:
                voice_modify["intensity"] = TTS_VOICE_MODIFY_INTENSITY
            if TTS_VOICE_MODIFY_TIMBRE != 0:
                voice_modify["timbre"] = TTS_VOICE_MODIFY_TIMBRE
            if TTS_SOUND_EFFECT:
                voice_modify["sound_effects"] = TTS_SOUND_EFFECT
            if voice_modify:
                task_start_payload["voice_modify"] = voice_modify

            await ws.send(json.dumps(task_start_payload))

            # Wait for task_started
            started_msg = await ws.recv()
            started_data = json.loads(started_msg)
            if started_data.get("event") != "task_started":
                logger.error(f"TTS task start failed: {started_data}")
                return

            # Send text
            await ws.send(json.dumps({
                "event": "task_continue",
                "text": text
            }))

            # Receive audio chunks
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    data = json.loads(msg)

                    if data.get("event") == "task_finished":
                        break

                    if "data" in data and "audio" in data["data"]:
                        audio_hex = data["data"]["audio"]
                        if audio_hex:
                            audio_bytes = bytes.fromhex(audio_hex)
                            yield audio_bytes

                    if data.get("is_final"):
                        break

                except asyncio.TimeoutError:
                    logger.warning("TTS WebSocket timeout")
                    break

            # Finish
            await ws.send(json.dumps({"event": "task_finish"}))

    except Exception as e:
        logger.error(f"MiniMax TTS WebSocket error: {e}")


# ── POST /ask — Stream LLM response (HTTP SSE) ──────────
@app.post("/ask")
async def ask_endpoint(req: AskRequest):
    """Stream MiniMax LLM response back to client via SSE."""
    if not MINIMAX_API_KEY:
        raise HTTPException(status_code=500, detail="MINIMAX_API_KEY not configured")

    logger.info(f"Ask: {req.query[:100]}...")

    async def stream_response():
        async for chunk in minimax_llm_stream(req.query, req.history):
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── POST /tts — Generate TTS audio ─────────────────────
@app.post("/tts")
async def tts_endpoint(req: TTSRequest):
    """Generate MiniMax TTS audio and return as mp3."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    if len(text) > 5000:
        text = text[:5000]

    audio_chunks = []
    async for chunk in minimax_tts_streaming(text):
        audio_chunks.append(chunk)

    if not audio_chunks:
        raise HTTPException(status_code=500, detail="TTS generated no audio")

    audio_data = b"".join(audio_chunks)
    logger.info(f"TTS generated {len(audio_data)} bytes")

    return Response(
        content=audio_data,
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio_data))},
    )


# ── WebSocket /ws — 全双工实时对话（流式 TTS）──────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket full-duplex real-time dialogue with streaming TTS."""
    await websocket.accept()
    logger.info("WebSocket client connected")

    global SYSTEM_PROMPT, TTS_VOICE_ID, TTS_LANGUAGE

    conversation_history = []

    try:
        while True:
            # 接收用户消息
            data = await websocket.receive_json()
            msg_type = data.get("type", "text")

            # ── 角色切换 ──
            if msg_type == "switch_character":
                persona = data.get("persona", "qin")
                voice_id = data.get("voiceId", TTS_VOICE_ID)
                TTS_VOICE_ID = voice_id
                if persona == "han":
                    SYSTEM_PROMPT = """你是漢武帝劉徹，生活在公元前156年至公元前87年。你現在正在與中小學生對話。

## 你的身份
- 你是西漢第七位皇帝，16歲即位，在位54年
- 你開創了漢朝最鼎盛的時期
- 你派遣張騫出使西域，開拓絲綢之路
- 你罷黜百家、獨尊儒術
- 你北擊匈奴，擴張疆土

## 說話風格
- 用古風但不要太文言，讓小朋友能聽懂
- 自稱「朕」，稱對方為「汝」
- 語氣威嚴但親善
"""
                elif persona == "tang":
                    SYSTEM_PROMPT = """你是唐太宗李世民，生活在公元598年至649年。你現在正在與中小學生對話。

## 你的身份
- 你是唐朝第二位皇帝，開創貞觀之治
- 你知人善任，虛心納諫
- 你完善科舉制度，任用賢才
- 你被尊為「天可汗」

## 說話風格
- 用古風但不要太文言，讓小朋友能聽懂
- 自稱「朕」，稱對方為「汝」
- 語氣威嚴但親善，善於引導
"""

                # 清空对话历史
                conversation_history = []
                logger.info(f"角色切換: {persona}, voice: {voice_id}")
                await websocket.send_json({"type": "status", "content": "done"})
                continue

            if msg_type == "tts_config":
                global TTS_SPEED, TTS_VOL, TTS_PITCH, TTS_EMOTION
                global TTS_VOICE_MODIFY_PITCH, TTS_VOICE_MODIFY_INTENSITY, TTS_VOICE_MODIFY_TIMBRE, TTS_SOUND_EFFECT
                TTS_LANGUAGE = data.get("language", TTS_LANGUAGE)
                TTS_VOICE_ID = data.get("voiceId", TTS_VOICE_ID)
                TTS_SPEED = data.get("speed", TTS_SPEED)
                TTS_VOL = data.get("vol", TTS_VOL)
                TTS_PITCH = data.get("pitch", TTS_PITCH)
                TTS_EMOTION = data.get("emotion", TTS_EMOTION)
                TTS_VOICE_MODIFY_PITCH = data.get("voiceModifyPitch", TTS_VOICE_MODIFY_PITCH)
                TTS_VOICE_MODIFY_INTENSITY = data.get("voiceModifyIntensity", TTS_VOICE_MODIFY_INTENSITY)
                TTS_VOICE_MODIFY_TIMBRE = data.get("voiceModifyTimbre", TTS_VOICE_MODIFY_TIMBRE)
                TTS_SOUND_EFFECT = data.get("soundEffect", TTS_SOUND_EFFECT)
                logger.info(
                    f"TTS 配置更新: lang={TTS_LANGUAGE}, voice={TTS_VOICE_ID}, "
                    f"speed={TTS_SPEED}, vol={TTS_VOL}, pitch={TTS_PITCH}, emotion={TTS_EMOTION}, "
                    f"vMod_pitch={TTS_VOICE_MODIFY_PITCH}, vMod_intensity={TTS_VOICE_MODIFY_INTENSITY}, "
                    f"vMod_timbre={TTS_VOICE_MODIFY_TIMBRE}, soundEffect={TTS_SOUND_EFFECT}"
                )
                continue

            user_text = data.get("content", "")

            if not user_text:
                continue

            logger.info(f"WS received: {user_text[:50]}...")

            # 流式 LLM 响应
            full_response = ""
            await websocket.send_json({"type": "status", "content": "thinking"})

            async for chunk in minimax_llm_stream(user_text, conversation_history):
                if chunk.startswith("[ERROR]"):
                    await websocket.send_json({"type": "error", "content": chunk})
                    break
                full_response += chunk
                await websocket.send_json({"type": "llm", "content": chunk})

            if full_response and not full_response.startswith("[ERROR]"):
                # 更新对话历史
                conversation_history.append({"role": "user", "content": user_text})
                conversation_history.append({"role": "assistant", "content": full_response})

                # 流式 TTS 音频
                await websocket.send_json({"type": "status", "content": "tts"})

                async for audio_chunk in minimax_tts_streaming(full_response):
                    # 流式发送音频数据
                    await websocket.send_bytes(audio_chunk)

                await websocket.send_json({"type": "status", "content": "done"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except:
            pass


# ── GET /health ─────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tts_model": TTS_MODEL,
        "tts_voice": TTS_VOICE_ID,
        "tts_language": TTS_LANGUAGE,
        "minimax_configured": bool(MINIMAX_API_KEY),
    }


# ── Static Files (must be last) ─────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# ── Main ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    import socket

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    port = int(os.getenv("PORT", "8080"))

    print("=" * 60)
    print("  🏯 秦始皇数字人 — Digital Human (Qin Shi Huang)")
    print("=" * 60)
    print(f"  本地访问:     http://localhost:{port}")
    print(f"  局域网访问:   http://{local_ip}:{port}")
    print(f"  TTS 模型:     {TTS_MODEL}")
    print(f"  TTS 音色:     {TTS_VOICE_ID}")
    print(f"  MiniMax:      {'✅ 已配置' if MINIMAX_API_KEY else '❌ 未配置 (export MINIMAX_API_KEY=...)'}")
    print("=" * 60)

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=4,
        log_level="info",
    )
