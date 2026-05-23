"""
Digital Human Backend — Qin Shi Huang (秦始皇) for primary/secondary students
FastAPI + MiniMax LLM + MiniMax TTS (Streaming) + WebSocket 全双工对话
"""
import os
import asyncio
import json
import logging
import time
from copy import deepcopy

import httpx
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Config ──────────────────────────────────────────────
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_LLM_BASE = "https://api.minimaxi.com/v1"
TTS_MODEL = "speech-2.8-hd"
TTS_TEXT_MAX = 5000  # TTS max chars before truncation

# 默认 TTS 配置（可被 WebSocket tts_config 覆盖）
DEFAULT_TTS_CONFIG = {
    "voice_id": "Cantonese_PlayfulMan",
    "language_boost": "Chinese,Yue",
    "speed": 1.0,
    "vol": 1.0,
    "pitch": 0,
    "emotion": None,
    "voice_modify": {
        "pitch": 0,
        "intensity": 0,
        "timbre": 0,
    },
    "sound_effect": None,
}

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

## 语音表达（语气标签）
你可以在对话中插入以下 MiniMax 语气标签，TTS 引擎会将它们渲染成真实人声：
- (laughs) 得意大笑 — 如："朕一统六国！(laughs)"
- (sighs) 感慨叹息 — 如："长生不老药…终究难求。(sighs)"
- (emm) 沉吟思考 — 如："(emm) 此问甚好，容朕思之。"
- (chuckle) 轻轻一笑 — 如："汝这小童，倒有几分见识。(chuckle)"
- (breath) 自然换气 — 长句中途停顿
- 标签在句中自然穿插，每次最多用 1 个
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
    history: list[dict] = []  # noqa: pydantic handles mut default

class TTSRequest(BaseModel):
    text: str


# ── MiniMax LLM ──────────────────────────────────────────
async def minimax_llm_stream(query: str, history: list[dict] | None = None, system_prompt: str | None = None):
    """Call MiniMax LLM with streaming, yield text chunks."""
    if not MINIMAX_API_KEY:
        yield "[ERROR] MINIMAX_API_KEY not configured"
        return

    messages = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]

    history = history or []
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
async def minimax_tts_streaming(text: str, tts_config: dict | None = None):
    """MiniMax TTS WebSocket streaming, yields audio chunks as they arrive.

    Args:
        text: Text to synthesize (truncated to TTS_TEXT_MAX).
        tts_config: Optional per-call overrides (voice_id, speed, vol, etc.).
    """
    if not MINIMAX_API_KEY:
        return

    text = text.strip()
    if not text:
        return

    # Truncate long text with log warning
    if len(text) > TTS_TEXT_MAX:
        logger.warning(f"TTS text truncated from {len(text)} to {TTS_TEXT_MAX} chars")
        text = text[:TTS_TEXT_MAX]

    cfg = deepcopy(DEFAULT_TTS_CONFIG)
    if tts_config:
        cfg.update({k: v for k, v in tts_config.items() if k != "voice_modify"})
        if "voice_modify" in tts_config:
            cfg["voice_modify"].update(tts_config["voice_modify"])

    url = "wss://api.minimaxi.com/ws/v1/t2a_v2"
    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}"}

    ws = None
    try:
        ws = await websockets.connect(url, additional_headers=headers)

        # Wait for connection success
        connected_msg = await ws.recv()
        connected_data = json.loads(connected_msg)
        if connected_data.get("event") != "connected_success":
            logger.error(f"TTS WebSocket connection failed: {connected_data}")
            return

        # Build voice_setting from config
        voice_cfg: dict[str, object] = {
            "voice_id": cfg["voice_id"],
            "speed": cfg["speed"],
            "vol": cfg["vol"],
            "pitch": cfg["pitch"],
        }
        if cfg["emotion"]:
            voice_cfg["emotion"] = cfg["emotion"]

        # Build task_start payload
        task_start_payload: dict[str, object] = {
            "event": "task_start",
            "model": TTS_MODEL,
            "language_boost": cfg["language_boost"],
            "voice_setting": voice_cfg,
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }

        # voice_modify: only include non-zero/non-null values
        vm = cfg["voice_modify"]
        voice_modify_payload: dict[str, object] = {}
        if vm.get("pitch", 0) != 0:
            voice_modify_payload["pitch"] = vm["pitch"]
        if vm.get("intensity", 0) != 0:
            voice_modify_payload["intensity"] = vm["intensity"]
        if vm.get("timbre", 0) != 0:
            voice_modify_payload["timbre"] = vm["timbre"]
        if cfg.get("sound_effect"):
            voice_modify_payload["sound_effects"] = cfg["sound_effect"]
        if voice_modify_payload:
            task_start_payload["voice_modify"] = voice_modify_payload

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
        raise
    finally:
        if ws is not None:
            await ws.close()


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


# ── POST /tts — Generate TTS audio (streaming) ─────────
@app.post("/tts")
async def tts_endpoint(req: TTSRequest):
    """Generate MiniMax TTS audio, stream response as mp3."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    async def stream_audio():
        chunk_count = 0
        async for chunk in minimax_tts_streaming(text):
            chunk_count += 1
            yield chunk
        logger.info(f"TTS streamed {chunk_count} chunks")

    return StreamingResponse(
        stream_audio(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── WebSocket /ws — 全双工实时对话（流式 TTS）──────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket full-duplex real-time dialogue with streaming TTS."""
    await websocket.accept()
    logger.info("WebSocket client connected")

    # Per-connection state — no global mutation
    tts_config: dict = dict(DEFAULT_TTS_CONFIG)
    conversation_history: list[dict[str, str]] = []

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "text")

            if msg_type == "tts_config":
                tts_config["language_boost"] = data.get("language", tts_config["language_boost"])
                tts_config["voice_id"] = data.get("voiceId", tts_config["voice_id"])
                tts_config["speed"] = data.get("speed", tts_config["speed"])
                tts_config["vol"] = data.get("vol", tts_config["vol"])
                tts_config["pitch"] = data.get("pitch", tts_config["pitch"])
                tts_config["emotion"] = data.get("emotion", tts_config["emotion"])
                tts_config["sound_effect"] = data.get("soundEffect", tts_config["sound_effect"])
                vm: dict = tts_config.setdefault("voice_modify", {})
                vm["pitch"] = data.get("voiceModifyPitch", vm.get("pitch", 0))
                vm["intensity"] = data.get("voiceModifyIntensity", vm.get("intensity", 0))
                vm["timbre"] = data.get("voiceModifyTimbre", vm.get("timbre", 0))
                tts_config["voice_modify"] = vm
                continue

            if msg_type == "diag_test":
                # 用当前 tts_config 参数做一次真实 TTS 调用
                diag_start = time.time()
                diag_config: dict = dict(data.get("ttsConfig", {}))  # 前端可选参数
                diag_lang: str = str(data.get("language", tts_config["language_boost"]))
                diag_voice: str = str(data.get("voiceId", tts_config["voice_id"]))
                # 合并前端传来的值
                effective = dict(tts_config)
                if diag_config:
                    effective.update(diag_config)
                effective["language_boost"] = diag_lang
                effective["voice_id"] = diag_voice
                try:
                    first_chunk = None
                    async for chunk in minimax_tts_streaming("測試", effective):
                        if chunk:
                            first_chunk = chunk
                            break
                    diag_ms = int((time.time() - diag_start) * 1000)
                    if first_chunk:
                        await websocket.send_json({
                            "type": "diag_result",
                            "ok": True,
                            "ttsMs": diag_ms,
                            "voiceId": effective["voice_id"],
                            "language": effective["language_boost"],
                            "model": TTS_MODEL,
                        })
                    else:
                        await websocket.send_json({
                            "type": "diag_result",
                            "ok": False,
                            "error": "TTS 返回空白音頻",
                            "ttsMs": diag_ms,
                        })
                except Exception as diag_err:
                    diag_ms = int((time.time() - diag_start) * 1000)
                    await websocket.send_json({
                        "type": "diag_result",
                        "ok": False,
                        "error": str(diag_err),
                        "ttsMs": diag_ms,
                    })
                continue

            user_text = data.get("content", "")
            if not user_text:
                continue

            logger.info(f"WS received: {user_text[:50]}...")

            full_response = ""
            await websocket.send_json({"type": "status", "content": "thinking"})

            async for chunk in minimax_llm_stream(user_text, conversation_history, SYSTEM_PROMPT):
                if chunk.startswith("[ERROR]"):
                    await websocket.send_json({"type": "error", "content": chunk})
                    break
                full_response += chunk
                await websocket.send_json({"type": "llm", "content": chunk})

            if full_response and not full_response.startswith("[ERROR]"):
                conversation_history.append({"role": "user", "content": user_text})
                conversation_history.append({"role": "assistant", "content": full_response})
                if len(conversation_history) > 50:
                    conversation_history = conversation_history[-50:]

                await websocket.send_json({"type": "status", "content": "tts"})
                try:
                    async for audio_chunk in minimax_tts_streaming(full_response, tts_config):
                        await websocket.send_bytes(audio_chunk)
                except Exception as tts_err:
                    logger.error(f"TTS streaming failed: {tts_err}")
                    await websocket.send_json({"type": "error", "content": f"TTS failed: {tts_err}"})
                await websocket.send_json({"type": "status", "content": "done"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


# ── GET /health ─────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tts_model": TTS_MODEL,
        "tts_voice": DEFAULT_TTS_CONFIG["voice_id"],
        "tts_language": DEFAULT_TTS_CONFIG["language_boost"],
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
    print(f"  TTS 音色:     {DEFAULT_TTS_CONFIG['voice_id']}")
    print(f"  MiniMax:      {'✅ 已配置' if MINIMAX_API_KEY else '❌ 未配置 (export MINIMAX_API_KEY=...)'}")
    print("=" * 60)

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=1,  # single worker for per-connection state safety
        log_level="info",
    )
