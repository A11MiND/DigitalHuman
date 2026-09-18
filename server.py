"""
Digital Human Palace backend.
FastAPI + MiniMax LLM + MiniMax TTS + WebSocket real-time conversations.
"""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
import asyncio
import base64
import csv
import json
import collections
import logging
import re
import subprocess
import socket
import time
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import httpx
import websockets
import shutil
import zipfile
import io
import tempfile
import uuid
import sqlite3
import datetime
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import accounts

# ── Config ──────────────────────────────────────────────
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")

# MiniMax 的 base URL 取决于账号注册的地区，不是请求发起地。
# 一把有效的 key 打到错误区域的端点会返回 2049 invalid api key，
# 看起来和 key 本身失效一模一样，所以区域必须配对。
MINIMAX_HOSTS = {
    "cn": "api.minimaxi.com",       # 中国大陆账号
    "global": "api.minimax.io",     # 国际账号
}
MINIMAX_REGION = os.getenv("MINIMAX_REGION", "cn").strip().lower()
if MINIMAX_REGION not in MINIMAX_HOSTS:
    MINIMAX_REGION = "cn"


def _minimax_host(region: str) -> str:
    return MINIMAX_HOSTS.get((region or "").strip().lower(), MINIMAX_HOSTS["cn"])


MINIMAX_HOST = _minimax_host(MINIMAX_REGION)
MINIMAX_LLM_BASE = f"https://{MINIMAX_HOST}/v1"
MINIMAX_IMAGE_BASE = f"https://{MINIMAX_HOST}/v1"
MINIMAX_VIDEO_BASE = f"https://{MINIMAX_HOST}/v1"
MINIMAX_TOKEN_PLAN_URL = "https://www.minimaxi.com/v1/token_plan/remains"
MINIMAX_TOKEN_PLAN_API_KEY = os.getenv("MINIMAX_TOKEN_PLAN_API_KEY", "")
TTS_MODEL = "speech-2.8-hd"
TTS_TEXT_MAX = 5000  # TTS max chars before truncation
GENERATED_DIR = Path(".generated")
CREATE_JOBS_DIR = GENERATED_DIR / "jobs"
MAX_KNOWLEDGE_FILE_BYTES = 10 * 1024 * 1024
MAX_KNOWLEDGE_CHARS = 6000
OPS_TZ = datetime.timezone(datetime.timedelta(hours=8), name="UTC+8")
GLOBAL_OUTPUT_RULES = (
    "\n\n## 输出限制\n"
    "- 不要输出任何 emoji、贴纸字符或 Unicode 表情符号。\n"
    "- 语气标签只可使用角色设定里明确列出的那几个，并严格遵守角色设定对使用场合和频率的限制；"
    "角色设定没有列出的标签（包括 (laughs)、(chuckle) 等笑声类标签）不要自行加入，"
    "专业/客服/培训等严肃场合尤其不要无缘无故加笑声。\n"
    "- 输出内容会进入语音合成，必须保证可自然朗读。"
)
_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # flags
    "\U0001F300-\U0001FAFF"  # pictographs, emoticons, symbols
    "\u2600-\u27BF"          # miscellaneous symbols / dingbats
    "\u3030\u303D\u3297\u3299"
    "\u00A9\u00AE\u2122\u2139"
    "]+"
)
_EMOJI_FORMAT_RE = re.compile("[\u200D\uFE0E\uFE0F]")

# TTS 会把裸 "$" 读成美元，粤语角色报价必须先转成「港幣XXX蚊」再送去合成。
# 光靠 system_prompt 教 LLM 自己转不可靠（模型会照抄 knowledge.md 或历史记录里的原始 "$" 文字），
# 所以在进 TTS 前用规则做一次保底转换，覆盖 "$688"、"HK$688"、"HKD688" 等写法。
_HKD_PRICE_RE = re.compile(r"(?:HK\$|HKD\$?|\$)\s?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)


def _normalize_currency_for_tts(text: str) -> str:
    """Rewrite bare $/HK$ price mentions as 「港幣XXX蚊」 so TTS never reads them as USD."""
    return _HKD_PRICE_RE.sub(lambda m: f"港幣{m.group(1)}蚊", text or "")


def _with_global_output_rules(prompt: str) -> str:
    """Append global speech-safe output rules once."""
    prompt = prompt or SYSTEM_PROMPT
    if "不要输出任何 emoji" in prompt:
        return prompt
    return prompt.rstrip() + GLOBAL_OUTPUT_RULES


def _strip_emoji_for_tts(text: str) -> str:
    """Remove emoji-only glyphs before TTS while preserving the displayed reply."""
    cleaned = _EMOJI_RE.sub("", text or "")
    cleaned = _EMOJI_FORMAT_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

# ── Conversation Database ──────────────────────────────
DB_PATH = Path("data/conversations.db")

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                char_id TEXT NOT NULL,
                user_ip TEXT,
                user_msg TEXT NOT NULL,
                assistant_msg TEXT NOT NULL,
                llm_ms INTEGER DEFAULT 0,
                tts_ms INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_time
            ON conversations(time DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_char_time
            ON conversations(char_id, time DESC)
        """)
    logger.info(f"Conversation DB ready: {DB_PATH}")

def _save_conversation(char_id: str, user_ip: str, user_msg: str,
                       assistant_msg: str, llm_ms: int = 0, tts_ms: int = 0,
                       username: str = ""):
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
            if "username" in cols:
                conn.execute(
                    "INSERT INTO conversations (time, char_id, user_ip, user_msg, assistant_msg, llm_ms, tts_ms, username) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (datetime.datetime.now(OPS_TZ).isoformat(), char_id, user_ip,
                     user_msg[:2000], assistant_msg[:2000], llm_ms, tts_ms, username[:64])
                )
            else:
                conn.execute(
                    "INSERT INTO conversations (time, char_id, user_ip, user_msg, assistant_msg, llm_ms, tts_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (datetime.datetime.now(OPS_TZ).isoformat(), char_id, user_ip,
                     user_msg[:2000], assistant_msg[:2000], llm_ms, tts_ms)
                )
    except Exception as e:
        logger.warning(f"Failed to save conversation: {e}")


def _client_ip_from_headers(headers, fallback: str = "unknown") -> str:
    """Return the original client IP when behind nginx, falling back to socket peer."""
    for name in ("x-forwarded-for", "x-real-ip", "cf-connecting-ip", "fastly-client-ip"):
        value = headers.get(name) if headers else ""
        if value:
            return value.split(",")[0].strip()[:80] or fallback
    return fallback or "unknown"

# ── User Codes ──────────────────────────────────────────
# Format: "username:code,username:code"
_raw_codes = os.getenv("USER_CODES", "")
USER_CODES: dict[str, str] = {}
for pair in _raw_codes.split(","):
    pair = pair.strip()
    if ":" in pair:
        name, code = pair.split(":", 1)
        USER_CODES[code.strip()] = name.strip()


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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("digital-human")


# ── 运行平台识别 ────────────────────────────────────────
# systemd / journalctl 只存在于自管服务器；容器平台（Railway）需要另一套采集方式。
RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_ENVIRONMENT", "")
IS_RAILWAY = bool(RAILWAY_ENV)
PLATFORM = "railway" if IS_RAILWAY else "systemd"
PROCESS_STARTED_AT = time.time()


class _RingLogHandler(logging.Handler):
    """把日志留在内存里，供容器环境的 /api/logs 读取（无 journalctl 可用）。"""

    def __init__(self, capacity: int = 4000):
        super().__init__()
        self.capacity = capacity
        self.buf: collections.deque = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.datetime.fromtimestamp(record.created, OPS_TZ).isoformat(timespec="seconds")
            self.buf.append(f"{ts} {record.levelname:<5} {record.getMessage()}")
        except Exception:
            pass

    def dump(self, lines: int) -> str:
        items = list(self.buf)
        return "\n".join(items[-lines:]) if items else ""


RING_LOGS = _RingLogHandler()
RING_LOGS.setLevel(logging.INFO)
logging.getLogger().addHandler(RING_LOGS)

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
"""  # kept as fallback


# ── Character Manager ───────────────────────────────────
class CharacterManager:
    """Scan characters/ directory, provide per-character config."""

    def __init__(self, base_dir: str = "characters"):
        self.base_dir = Path(base_dir)
        self._chars: dict[str, dict] = {}
        self.reload()

    def reload(self):
        """Re-scan characters/ for character.json files."""
        self._chars.clear()
        if not self.base_dir.is_dir():
            logger.warning(f"Character dir not found: {self.base_dir}")
            return
        loaded = []
        for d in sorted(self.base_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                cfg = d / "character.json"
                if cfg.is_file():
                    try:
                        ch = json.loads(cfg.read_text(encoding="utf-8"))
                        ch["_dir"] = str(d)
                        self._chars[ch["id"]] = ch
                        loaded.append(ch["id"])
                    except (json.JSONDecodeError, KeyError) as err:
                        logger.error(f"Failed to load character {cfg}: {err}")
        if loaded:
            logger.info(f"Loaded {len(loaded)} character(s): {', '.join(loaded)}")

    def list_all(self) -> list[dict]:
        """Return summary list for lobby display."""
        return [
            {
                "id": c["id"],
                "name": c.get("name", c["id"]),
                "name_en": c.get("name_en", ""),
                "role": c.get("role", ""),
                "icon": f"/characters/{c['id']}/{c.get('icon', 'portrait.jpg')}",
                "avatar_idle": f"/characters/{c['id']}/{c.get('avatar_idle', 'idle.mp4')}",
                "theme_color": c.get("theme_color", "#8A6D3B"),
                "created_by": c.get("created_by", ""),
            }
            for c in self._chars.values()
        ]

    def get(self, char_id: str) -> dict | None:
        """Return full character config."""
        return self._chars.get(char_id)

    def get_system_prompt(self, char_id: str) -> str:
        """Return system prompt for a character, with optional knowledge injection."""
        ch = self._chars.get(char_id)
        prompt = ch["system_prompt"] if ch and ch.get("system_prompt") else SYSTEM_PROMPT

        # Inject knowledge file if configured — no RAG, full context
        knowledge_file = (ch or {}).get("knowledge_file")
        if knowledge_file:
            kpath = Path(ch["_dir"]) / knowledge_file
            if kpath.is_file():
                try:
                    knowledge = kpath.read_text(encoding="utf-8").strip()
                    if knowledge:
                        prompt += f"\n\n## 参考资料（回答时必须基于以下内容，不要编造）\n{knowledge}"
                except Exception as e:
                    logger.warning(f"Failed to load knowledge file {kpath}: {e}")

        return prompt

    def get_tts_defaults(self, char_id: str) -> dict:
        """Return TTS defaults from character config, falling back to system defaults."""
        ch = self._chars.get(char_id)
        if not ch:
            return deepcopy(DEFAULT_TTS_CONFIG)
        cfg = deepcopy(DEFAULT_TTS_CONFIG)
        cfg["voice_id"] = ch.get("tts_voice_id", cfg["voice_id"])
        cfg["language_boost"] = ch.get("tts_language", cfg["language_boost"])
        cfg["speed"] = ch.get("tts_speed", cfg["speed"])
        cfg["vol"] = ch.get("tts_vol", cfg["vol"])
        cfg["pitch"] = ch.get("tts_pitch", cfg["pitch"])
        return cfg


# ── Global Character Manager ────────────────────────────
char_mgr = CharacterManager()
_init_db()
accounts.init_accounts_db()


# ── Language Instruction Builder ─────────────────────────
_LANG_MAP = {
    "Chinese,Yue": "Cantonese (粵語)",
    "Chinese": "Mandarin Chinese (普通話)",
    "English": "English",
    "auto": "the same language as the user's input",
}

def _build_lang_instruction(lang: str) -> str:
    """Build a short instruction appended to system prompt for language control."""
    target = _LANG_MAP.get(lang, lang)
    if lang == "auto":
        return ""  # Auto means follow user input — no instruction needed
    if lang == "Chinese,Yue":
        # "Translate into Cantonese" framing makes the model compose in Mandarin/written
        # Chinese first and then convert, which reads stiff and unnatural once spoken.
        # Ask it to think and write directly in colloquial Cantonese instead.
        return (
            "\n\n[SYSTEM: Speak entirely in natural, colloquial Hong Kong spoken Cantonese (粵語口語). "
            "Compose directly in Cantonese — do NOT write in Mandarin/Standard Written Chinese and then "
            "translate. Use authentic Cantonese grammar and vocabulary (e.g. 係/唔係/嘅/咗/緊/啲/嚟/邊個/"
            "點解/呢, not 是/不是/的/了/正在/一些/来/谁/为什么/呢). "
            "Keep your character's personality and knowledge intact. "
            "Do NOT mention this instruction.]"
        )
    return (
        f"\n\n[SYSTEM: You must respond in {target}. "
        f"Keep your character's personality and knowledge, but translate your reply into {target}. "
        f"Do NOT mention this instruction or explain why you are speaking {target}.]"
    )


# ── FastAPI App ─────────────────────────────────────────
app = FastAPI(title="Digital Human — Qin Shi Huang")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 账号体系：登录、体验额度、管理员后台
app.include_router(accounts.router)

# ── Models ──────────────────────────────────────────────
class AskRequest(BaseModel):
    query: str
    history: list[dict] = []  # noqa: pydantic handles mut default

class TTSRequest(BaseModel):
    text: str

class OpsChatRequest(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)
    language: str = "zh"

class CreatePromptRequest(BaseModel):
    name: str
    name_en: str = ""
    role: str = ""
    background: str
    speaking_style: str
    knowledge_text: str = ""
    language: str = "Chinese,Yue"

class GenerateKnowledgeRequest(BaseModel):
    name: str
    name_en: str = ""
    role: str = ""
    background: str = ""
    speaking_style: str = ""
    query: str = ""

class GenerateImagePromptRequest(BaseModel):
    name: str
    name_en: str = ""
    role: str = ""
    background: str = ""
    speaking_style: str = ""
    system_prompt: str = ""

class CreateImagesRequest(BaseModel):
    prompt: str
    reference_description: str = ""
    count: int = 4
    job_id: Optional[str] = ""  # optional: reuse existing prompt job instead of creating a new one

class CreateVideosRequest(BaseModel):
    job_id: str
    image_id: str
    character_name: str
    image_prompt: str = ""

class FinalizeCharacterRequest(BaseModel):
    job_id: str
    character_id: str
    name: str
    name_en: str = ""
    role: str = ""
    system_prompt: str
    tts_voice_id: str = DEFAULT_TTS_CONFIG["voice_id"]
    tts_language: str = DEFAULT_TTS_CONFIG["language_boost"]
    theme_color: str = "#8A6D3B"


ApiKeyHeader = Annotated[str | None, Header(alias="X-MiniMax-API-Key")]
UserCodeHeader = Annotated[str | None, Header(alias="X-User-Code")]


def _verify_user_code(code: str | None) -> str | None:
    """Return username if code is valid, None otherwise."""
    if not code or not USER_CODES:
        return None
    return USER_CODES.get(code.strip())


def _require_user_code(code: str | None) -> str:
    """Raise 401 if code is invalid or missing."""
    if not USER_CODES:
        raise HTTPException(status_code=503, detail="Invite code system not configured")
    username = _verify_user_code(code)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid invite code")
    return username


def _require_ops_access(code: str | None, token: str | None = None) -> str:
    """运维接口的守卫 — 只认管理员会话。

    管理平台已并入 /ops，统一走账号密码登录，运维码已废弃。
    参数 code 保留只是为了不改动各 handler 的签名，不再参与鉴权。
    """
    account = accounts.resolve_session(token)
    if account and account["role"] == "admin":
        return account["username"]
    raise HTTPException(status_code=401, detail="需要管理员登录")


def _minimax_credentials(account: dict | None) -> tuple[str, str, str]:
    """按账号解析上游凭证 → (api_key, llm_base, ws_host)。

    高级帐户走 PREMIUM_API_KEY 及其所属区域；其余走全局配置。
    区域与 Key 必须成对使用，打错区域会被 MiniMax 判为 invalid api key。
    """
    key, region = accounts.premium_credentials(account)
    if not key:
        return MINIMAX_API_KEY, MINIMAX_LLM_BASE, MINIMAX_HOST
    host = _minimax_host(region) if region else MINIMAX_HOST
    return key, f"https://{host}/v1", host


def _require_creator_access(code: str | None, token: str | None) -> str:
    """角色创建类接口的守卫 — 邀请码或高级/管理员会话二选一。

    高级帐户的「全套服务」包含创建角色，所以新账号体系里的 premium/admin
    不需要再单独配一个邀请码。
    """
    account = accounts.resolve_session(token)
    if account and account["role"] in ("premium", "admin"):
        return account["username"]
    return _require_user_code(code)


def _require_data_access(code: str | None, token: str | None) -> str:
    """对话记录与日志接口的守卫 — 只认管理员会话。

    这些接口会返回访客 IP、对话原文和账号名，不能对匿名请求开放；
    与运维接口一样统一走账号密码登录，运维码已废弃。
    """
    return _require_ops_access(code, token)


def _effective_minimax_key(api_key: str | None = None) -> str:
    """Request header key first, env key as fallback. Never log the value."""
    return (api_key or "").strip() or MINIMAX_API_KEY


def _creation_credentials(api_key: str | None, token: str | None) -> tuple[str, str, bool]:
    """创建流水线的上游凭证 → (api_key, llm_base, used_platform_key)。

    调用方自带 Key 时优先用它（走全局区域端点）；没带则按帐户回退到服务端
    配置：高级/管理员用 PREMIUM_API_KEY 及其所属区域，其余用平台主 Key。
    Key 只在服务端使用，任何响应都不会把它回传给前端。
    used_platform_key=True 表示烧嘅係平台自己嘅 Key（而唔係调用方自带），
    呢啲请求先需要计入 accounts.reserve_creation_action 嘅每日限额，
    否则一个邀请码可以无限生图/生视频/用平台 Key 做 web search。
    """
    supplied = (api_key or "").strip()
    if supplied:
        return supplied, MINIMAX_LLM_BASE, False
    key, base, _ = _minimax_credentials(accounts.resolve_session(token))
    if not key:
        raise HTTPException(status_code=400, detail="MiniMax API Key required for character creation")
    return key, base, True


def _safe_character_id(raw: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw.strip().lower()).strip("-")
    if not slug:
        slug = f"character-{uuid.uuid4().hex[:8]}"
    return slug[:64]


def _safe_job_id(raw: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", raw or ""):
        raise HTTPException(status_code=400, detail="Invalid job_id")
    return raw


def _safe_display_text(raw: str, max_len: int = 80) -> str:
    """Strip HTML angle brackets from a user-supplied display field.

    Frontend templates escape on render, but a custom character's name/role
    is echoed into several pages (chat bubble label, lobby cards) — stripping
    '<'/'>' at creation time is defense in depth in case any render path
    ever forgets to escape.
    """
    return (raw or "").replace("<", "").replace(">", "").strip()[:max_len]


def _job_dir(job_id: str) -> Path:
    return CREATE_JOBS_DIR / _safe_job_id(job_id)


def _load_job(job_id: str) -> dict:
    meta = _job_dir(job_id) / "job.json"
    if not meta.is_file():
        raise HTTPException(status_code=404, detail="Creation job not found")
    return json.loads(meta.read_text(encoding="utf-8"))


def _save_job(job_id: str, data: dict) -> None:
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def _download_file(url: str, dest: Path, api_key: str | None = None) -> None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        res = await client.get(url, headers=headers)
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Failed to download generated asset: {res.status_code}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(res.content)


def _extract_text_from_txt(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _extract_docx_text(path: Path) -> str:
    try:
        import docx
    except Exception as exc:
        raise HTTPException(status_code=500, detail="python-docx is not installed") from exc
    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_pdf_text(path: Path) -> str:
    try:
        import PyPDF2
    except Exception as exc:
        raise HTTPException(status_code=500, detail="PyPDF2 is not installed") from exc
    text_parts = []
    with path.open("rb") as fh:
        reader = PyPDF2.PdfReader(fh)
        for page in reader.pages[:80]:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def _ffmpeg_process_video(src: Path, dest: Path, duration: int) -> None:
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="ffmpeg is required to process generated videos")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src), "-t", str(duration), "-an",
        "-vf", "scale=720:-2,fps=24,format=yuv420p",
        "-movflags", "+faststart",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if result.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        logger.error("ffmpeg video processing failed: %s", result.stderr[-1200:])
        raise HTTPException(status_code=500, detail="Generated video post-processing failed")


def _copy_or_make_portrait(src: Path, dest: Path) -> None:
    if src.is_file():
        shutil.copy2(src, dest)
        return
    raise HTTPException(status_code=500, detail="Selected portrait image missing")


def _existing_prompt_examples() -> str:
    examples = []
    for char_id in ("qin-shihuang", "elizabeth-i"):
        ch = char_mgr.get(char_id)
        if ch and ch.get("system_prompt"):
            examples.append(f"### {ch.get('name', char_id)}\n{ch['system_prompt'][:3500]}")
    return "\n\n".join(examples)


_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _extract_minimax_text(data: dict) -> str:
    # M2 系模型冇得关闭思考（thinking），思考本身要食 tokens；如果 max_tokens
    # 批得太紧，模型可能思考到一半就截断，content 会係空字符串。呢种情况落去
    # reasoning_content 只会攞到未完成嘅思考过程，唔係真正答案——不如识别出嚟
    # 当做冇答案，好过静静鸡将思考过程当正常回复吐畀用户睇。
    choices = data.get("choices") or []
    if choices:
        first = choices[0] or {}
        msg = first.get("message") or {}
        content = (msg.get("content") or first.get("text") or first.get("delta", {}).get("content") or "").strip()
        content = _THINK_TAG_RE.sub("", content).strip()
        if content:
            return content
        finish_reason = first.get("finish_reason") or ""
        if finish_reason == "length" or not content:
            logger.warning("MiniMax 回复被截断或为空，可能思考用晒 max_tokens：finish_reason=%s", finish_reason)
        return ""
    return (data.get("reply") or data.get("text") or data.get("content") or "").strip()


def _clamp_knowledge(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.strip())[:MAX_KNOWLEDGE_CHARS]


class _DuckResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self._in_link = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        href = attrs_d.get("href", "")
        cls = attrs_d.get("class", "")
        if tag == "a" and href and ("result-link" in cls or "/l/?" in href):
            self._in_link = True
            self._href = href
            self._text = []

    def handle_data(self, data):
        if self._in_link:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            title = " ".join(" ".join(self._text).split())
            url = self._href
            if "/l/?" in url:
                qs = parse_qs(urlparse(url).query)
                if qs.get("uddg"):
                    url = unquote(qs["uddg"][0])
            if title and url:
                self.results.append({"title": title, "url": url})
            self._in_link = False


async def _search_web(query: str) -> list[dict]:
    if not query.strip():
        return []
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Web search failed: {res.status_code}")
    parser = _DuckResultParser()
    parser.feed(res.text)
    dedup = []
    seen = set()
    for item in parser.results:
        key = item["url"]
        if key not in seen:
            seen.add(key)
            dedup.append(item)
        if len(dedup) >= 6:
            break
    return dedup


class MiniMaxProvider:
    def __init__(self, api_key: str, llm_base: str | None = None):
        self.api_key = api_key
        # 区域必须和 Key 配对，打错区域会被 MiniMax 判为 2049 invalid api key。
        self.llm_base = (llm_base or "").strip() or MINIMAX_LLM_BASE
        # 图像/视频与文本同源，跟随同一个区域端点。
        self.api_base = self.llm_base
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def improve_prompt(self, req: CreatePromptRequest) -> str:
        examples = _existing_prompt_examples()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是数字人角色提示词设计师。请把用户给出的角色背景、说话设定和知识库内容整理成"
                    "可直接作为 system_prompt 使用的角色提示词。要求结构清晰、事实约束明确、可用于中小学生互动，"
                    "保留角色身份，不编造知识库外的具体事实。每次回答建议 3-5 句，并包含 MiniMax TTS 语气标签使用规则。"
                    "输出格式要参考下面已有角色样例的章节结构、身份/性格/知识/说话风格/重要规则组织方式。\n\n"
                    f"{examples}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"角色名：{req.name}\n英文/副标题：{req.name_en}\n角色定位：{req.role}\n"
                    f"回复语言：{req.language}\n\n背景设定：\n{req.background}\n\n说话设定：\n{req.speaking_style}\n\n"
                    f"知识库摘录（最多6000字）：\n{req.knowledge_text[:MAX_KNOWLEDGE_CHARS]}"
                ),
            },
        ]
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{self.llm_base}/text/chatcompletion_v2",
                headers=self.headers,
                json={
                    "model": "MiniMax-M2.7-highspeed",
                    "messages": messages,
                    "stream": False,
                    "temperature": 0.4,
                    "max_tokens": 1800,
                },
            )
        if res.status_code >= 400:
            logger.error("MiniMax prompt API failed: %s", res.status_code)
            raise HTTPException(status_code=502, detail=f"MiniMax prompt API failed: {res.status_code}")
        data = res.json()
        content = _extract_minimax_text(data)
        if not content:
            raise HTTPException(status_code=502, detail="MiniMax prompt API returned empty content")
        return content

    async def simple_text(self, system: str, user: str, max_tokens: int = 800, temperature: float = 0.3) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{self.llm_base}/text/chatcompletion_v2",
                headers=self.headers,
                json={
                    "model": "MiniMax-M2.7-highspeed",
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "stream": False,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        if res.status_code >= 400:
            logger.error("MiniMax text API failed: %s", res.status_code)
            raise HTTPException(status_code=502, detail=f"MiniMax text API failed: {res.status_code}")
        text = _extract_minimax_text(res.json())
        if not text:
            raise HTTPException(status_code=502, detail="MiniMax text API returned empty content")
        return text

    async def generate_images(self, prompt: str, count: int, job_id: str) -> list[dict]:
        count = max(1, min(count, 5))
        job = _load_job(job_id)
        out_dir = _job_dir(job_id) / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": "image-01",
            "prompt": prompt,
            "aspect_ratio": "3:4",
            "n": count,
            "response_format": "url",
            "prompt_optimizer": True,
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            res = await client.post(f"{self.api_base}/image_generation", headers=self.headers, json=payload)
        if res.status_code >= 400:
            logger.error("MiniMax image API failed: %s", res.status_code)
            raise HTTPException(status_code=502, detail=f"MiniMax image API failed: {res.status_code}")
        data = res.json()
        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            raise HTTPException(status_code=502, detail=f"MiniMax image API error: {base_resp.get('status_msg', 'unknown')}")
        urls = []
        if isinstance(data.get("data"), dict):
            urls.extend(data["data"].get("image_urls") or data["data"].get("images") or [])
        urls.extend(data.get("image_urls") or data.get("images") or [])
        normalized = []
        for item in urls:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(item.get("url") or item.get("image_url") or item.get("base64"))
        urls = [u for u in normalized if u]
        if not urls:
            raise HTTPException(status_code=502, detail="MiniMax image API returned no images")

        images = []
        for idx, url in enumerate(urls[:count], start=1):
            image_id = f"img-{idx}"
            local = out_dir / f"{image_id}.jpg"
            if url.startswith("data:") or len(url) > 500 and not url.startswith("http"):
                b64 = url.split(",", 1)[-1]
                local.write_bytes(base64.b64decode(b64))
                source_url = ""
            else:
                await _download_file(url, local)
                source_url = url
            item = {
                "id": image_id,
                "url": f"/generated/jobs/{job_id}/images/{local.name}",
                "source_url": source_url,
            }
            images.append(item)
        job["images"] = images
        job["image_prompt"] = prompt
        _save_job(job_id, job)
        return images

    async def generate_video(self, prompt: str, first_frame_url: str, download_path: Path, duration: int) -> dict:
        if not first_frame_url:
            raise HTTPException(status_code=400, detail="MiniMax video requires a generated image URL as first frame")
        payload = {
            "model": "MiniMax-Hailuo-2.3-Fast",
            "prompt": prompt,
            "first_frame_image": first_frame_url,
            "duration": 6 if duration <= 6 else 10,
            "resolution": "768P",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(f"{self.api_base}/video_generation", headers=self.headers, json=payload)
        if res.status_code >= 400:
            logger.error("MiniMax video API failed: %s", res.status_code)
            raise HTTPException(status_code=502, detail=f"MiniMax video API failed: {res.status_code}")
        data = res.json()
        logger.info("MiniMax video_generation response: %s", json.dumps(data, ensure_ascii=False)[:800])

        # Check for API-level errors (e.g. usage limits)
        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            err_msg = base_resp.get("status_msg", "unknown error")
            raise HTTPException(status_code=502, detail=f"MiniMax video API error: {err_msg}")

        task_id = (
            data.get("task_id") or data.get("taskId")
            or data.get("data", {}).get("task_id") or data.get("data", {}).get("taskId")
        )
        direct_url = data.get("video_url") or data.get("data", {}).get("video_url")
        if direct_url:
            await _download_file(direct_url, download_path, self.api_key)
            return {"task_id": task_id, "url": direct_url}
        if not task_id:
            raise HTTPException(status_code=502, detail="MiniMax video API returned no task id")

        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(90):
                await asyncio.sleep(5)
                try:
                    q = await client.get(
                        f"{self.api_base}/query/video_generation",
                        headers=self.headers,
                        params={"task_id": task_id},
                    )
                    if q.status_code >= 400:
                        continue
                    qd = q.json()
                except Exception as e:
                    logger.warning("Video poll request failed, retrying: %s", e)
                    continue
                status = str(qd.get("status") or qd.get("data", {}).get("status") or "").lower()
                file_id = qd.get("file_id") or qd.get("data", {}).get("file_id")
                video_url = qd.get("video_url") or qd.get("data", {}).get("video_url")
                if video_url:
                    await _download_file(video_url, download_path, self.api_key)
                    return {"task_id": task_id, "url": video_url}
                if file_id:
                    try:
                        dl = await client.get(
                            f"{self.api_base}/files/retrieve",
                            headers=self.headers,
                            params={"file_id": file_id},
                        )
                        if dl.status_code < 400:
                            dd = dl.json()
                            video_url = dd.get("file", {}).get("download_url") or dd.get("download_url")
                            if video_url:
                                await _download_file(video_url, download_path, self.api_key)
                                return {"task_id": task_id, "file_id": file_id}
                    except Exception as e:
                        logger.warning("Video file retrieve failed, retrying: %s", e)
                if status in {"failed", "fail", "error"}:
                    raise HTTPException(status_code=502, detail="MiniMax video generation failed")
        raise HTTPException(status_code=504, detail="MiniMax video generation timed out")



# ── MiniMax LLM ──────────────────────────────────────────
async def minimax_llm_stream(query: str, history: list[dict] | None = None, system_prompt: str | None = None,
                             api_key: str | None = None, llm_base: str | None = None, history_window: int = 20):
    """Call MiniMax LLM with streaming, yield text chunks.

    api_key / llm_base 留空则用全局配置；高级帐户会传入自己的 Key 与所属区域端点。
    history_window: 实际传给模型的最近消息条数（默认20条=10轮）。角色可在 character.json
    用 "history_window" 覆写，用于需要更长记忆的场景（例如销售培训陪练角色）。
    """
    key = (api_key or "").strip() or MINIMAX_API_KEY
    base = (llm_base or "").strip() or MINIMAX_LLM_BASE
    if not key:
        yield "[ERROR] MINIMAX_API_KEY not configured"
        return

    messages = [{"role": "system", "content": _with_global_output_rules(system_prompt or SYSTEM_PROMPT)}]

    history = history or []
    window = max(1, int(history_window or 20))
    for msg in history[-window:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": query})

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{base}/text/chatcompletion_v2",
                headers={
                    "Authorization": f"Bearer {key}",
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
async def minimax_tts_streaming(text: str, tts_config: dict | None = None,
                                api_key: str | None = None, ws_host: str | None = None):
    """MiniMax TTS WebSocket streaming, yields audio chunks as they arrive.

    Args:
        text: Text to synthesize (truncated to TTS_TEXT_MAX).
        tts_config: Optional per-call overrides (voice_id, speed, vol, etc.).
    """
    key = (api_key or "").strip() or MINIMAX_API_KEY
    host = (ws_host or "").strip() or MINIMAX_HOST
    if not key:
        return

    raw_text_len = len(text or "")
    text = _strip_emoji_for_tts(text)
    if not text:
        return
    if len(text) != raw_text_len:
        logger.info(f"TTS text sanitized for speech: {raw_text_len} -> {len(text)} chars")

    lang_boost = (tts_config or {}).get("language_boost", DEFAULT_TTS_CONFIG["language_boost"])
    if lang_boost in ("Chinese,Yue", "Chinese"):
        normalized = _normalize_currency_for_tts(text)
        if normalized != text:
            logger.info("TTS currency normalized: %s -> %s", text[:80], normalized[:80])
            text = normalized

    # Truncate long text with log warning
    if len(text) > TTS_TEXT_MAX:
        logger.warning(f"TTS text truncated from {len(text)} to {TTS_TEXT_MAX} chars")
        text = text[:TTS_TEXT_MAX]

    cfg = deepcopy(DEFAULT_TTS_CONFIG)
    if tts_config:
        cfg.update({k: v for k, v in tts_config.items() if k != "voice_modify"})
        if "voice_modify" in tts_config:
            cfg["voice_modify"].update(tts_config["voice_modify"])

    logger.debug(f"TTS start: voice={cfg['voice_id']} lang={cfg['language_boost']} text_len={len(text)}")

    url = f"wss://{host}/ws/v1/t2a_v2"
    headers = {"Authorization": f"Bearer {key}"}

    ws = None
    audio_chunk_count = 0
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
        logger.info(f"TTS task_start sent: voice={cfg.get('voice_id')} lang={cfg.get('language_boost')}")

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
                        audio_chunk_count += 1
                        yield audio_bytes

                if data.get("is_final"):
                    break

            except asyncio.TimeoutError:
                logger.warning("TTS WebSocket timeout")
                break

        # Finish
        await ws.send(json.dumps({"event": "task_finish"}))

        logger.info(f"TTS finished: voice={cfg['voice_id']} chunks={audio_chunk_count}")
    except Exception as e:
        logger.error(f"TTS WebSocket failed: voice={cfg['voice_id']} error={e}", exc_info=True)
        raise
    finally:
        if ws is not None:
            await ws.close()


# ── Sentence-level splitting for pipelined LLM→TTS ───────
# 原本 /ws 是等 LLM 全部生成完先送去 TTS 再送去前端，等于把「LLM 生成时间 + TTS
# 合成时间」串行相加，这是「回答等好耐」的主要来源之一。改成边收 LLM 流边按句
# 切开，句子一凑齐就马上送去 TTS（同时 LLM 继续在背景生成下一句），把两段时间
# 重叠起来，缩短由提问到开始有声音的总等待时间。
_SENTENCE_END_RE = re.compile(r"[。！？!?\n]+")
_MIN_TTS_CHUNK_CHARS = 4


def _split_ready_sentences(buffer: str) -> tuple[list[str], str]:
    """Split buffer into complete sentences ending in terminal punctuation, plus remainder.

    Fragments shorter than _MIN_TTS_CHUNK_CHARS are merged into the next sentence so we
    don't fire off a TTS call for a lone punctuation mark or a couple of stray characters.
    """
    sentences: list[str] = []
    pos = 0
    for m in _SENTENCE_END_RE.finditer(buffer):
        end = m.end()
        piece = buffer[pos:end]
        pos = end
        if not piece.strip():
            continue
        if sentences and len(piece.strip()) < _MIN_TTS_CHUNK_CHARS:
            sentences[-1] += piece
        else:
            sentences.append(piece)
    return sentences, buffer[pos:]


# ── POST /ask — Stream LLM response (HTTP SSE) ──────────
@app.post("/ask")
async def ask_endpoint(req: AskRequest, x_session_token: accounts.SessionHeader = None):
    """Stream MiniMax LLM response back to client via SSE."""
    if not MINIMAX_API_KEY:
        raise HTTPException(status_code=500, detail="MINIMAX_API_KEY not configured")

    account = accounts.require_account(x_session_token)
    # 推流前先原子占位：并发抢不出额度，客户端提前断线也已计费
    allowed, _used = accounts.reserve_quota(account)
    if not allowed:
        raise HTTPException(status_code=402, detail="體驗次數已用完，請升級後繼續使用")

    ask_key, ask_base, _ = _minimax_credentials(account)
    t0 = time.time()
    logger.info(f"POST /ask: user={account['username']} {req.query[:80]}...")

    async def stream_response():
        n = 0
        first_at = None
        try:
            async for chunk in minimax_llm_stream(req.query, req.history,
                                                  api_key=ask_key, llm_base=ask_base):
                if first_at is None:
                    first_at = time.time()
                n += 1
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            # 一个字都没产出才退回占位，保持「失败不计费」
            if n == 0:
                accounts.refund_quota(account["username"])
            ttft = int(((first_at or t0) - t0) * 1000)
            total = int((time.time() - t0) * 1000)
            logger.info(f"POST /ask done: {n} chunks, ttft={ttft}ms, total={total}ms")

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
async def tts_endpoint(req: TTSRequest, x_session_token: accounts.SessionHeader = None):
    """Generate MiniMax TTS audio, stream response as mp3."""
    # TTS 属于一轮对话的组成部分，只校验登录、不单独扣次数
    tts_account = accounts.require_account(x_session_token)
    tts_key, _, tts_ws_host = _minimax_credentials(tts_account)
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    t0 = time.time()

    async def stream_audio():
        chunk_count = 0
        async for chunk in minimax_tts_streaming(text, api_key=tts_key, ws_host=tts_ws_host):
            chunk_count += 1
            yield chunk
        total_ms = int((time.time() - t0) * 1000)
        logger.info(f"POST /tts done: {chunk_count} chunks, {total_ms}ms")

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
    char_id = websocket.query_params.get("char", "qin-shihuang")
    await websocket.accept()
    ws_start = time.time()
    req_id = uuid.uuid4().hex[:8]
    socket_ip = websocket.client.host if websocket.client else "unknown"
    client_ip = _client_ip_from_headers(websocket.headers, socket_ip)

    # 令牌改行首帧传输，唔再喺 URL query——query 会原样进 uvicorn access
    # log，而日志本身可以被 /api/ops/export/logs 导出，等于 token 明文外泄
    try:
        first_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except Exception:
        logger.info(f"[{req_id}] WS rejected (未收到鑑權首帧) ip={client_ip}")
        await websocket.close(code=4401)
        return
    if first_msg.get("type") != "auth":
        logger.info(f"[{req_id}] WS rejected (首帧非 auth) ip={client_ip}")
        await websocket.close(code=4401)
        return
    session_account = accounts.resolve_session(first_msg.get("token", ""))
    if not session_account:
        logger.info(f"[{req_id}] WS rejected (未登录) ip={client_ip}")
        await websocket.send_json({
            "type": "auth_required",
            "content": "请先登录后再开始对话",
        })
        await websocket.close(code=4401)
        return

    if not accounts.character_allowed(session_account, char_id):
        logger.info(f"[{req_id}] WS rejected (无权限) char={char_id} user={session_account['username']} ip={client_ip}")
        await websocket.send_json({
            "type": "auth_required",
            "content": "你的帳號未獲授權使用呢個數字人角色",
        })
        await websocket.close(code=4403)
        return

    session_user = session_account["username"]
    mm_key, mm_llm_base, mm_ws_host = _minimax_credentials(session_account)
    logger.info(
        f"[{req_id}] WS connected  char={char_id} ip={client_ip} "
        f"user={session_user} role={session_account['role']}"
    )
    await websocket.send_json({
        "type": "quota",
        "role": session_account["role"],
        "quota_limit": session_account["quota_limit"],
        "quota_used": session_account["quota_used"],
        "quota_left": session_account["quota_left"],
    })

    # Per-connection state — no global mutation
    tts_config: dict = char_mgr.get_tts_defaults(char_id)
    conversation_history: list[dict[str, str]] = []
    base_system_prompt: str = char_mgr.get_system_prompt(char_id)
    _lang_instruction: str = _build_lang_instruction(tts_config["language_boost"])
    # 角色可在 character.json 用 "history_window" 覆写送去模型嘅最近消息条数（默认20=10轮）
    _char_cfg = char_mgr.get(char_id) or {}
    history_window: int = int(_char_cfg.get("history_window") or 20)
    history_keep: int = max(50, history_window)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "text")

            if msg_type == "tts_config":
                new_lang = data.get("language", tts_config["language_boost"])
                if new_lang != tts_config.get("language_boost"):
                    tts_config["language_boost"] = new_lang
                    _lang_instruction = _build_lang_instruction(new_lang)
                    logger.info(f"Language instruction updated: {new_lang}")
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
                # 合并前端传来的值 — deepcopy 防止共享 voice_modify
                effective = deepcopy(tts_config)
                if diag_config:
                    if "voice_modify" in diag_config and isinstance(diag_config["voice_modify"], dict):
                        effective["voice_modify"].update(diag_config["voice_modify"])
                        del diag_config["voice_modify"]
                    effective.update(diag_config)
                effective["language_boost"] = diag_lang
                effective["voice_id"] = diag_voice
                try:
                    first_chunk = None
                    async for chunk in minimax_tts_streaming("測試", effective,
                                                             api_key=mm_key, ws_host=mm_ws_host):
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

            # 每轮都重新读账号 — 管理员在后台的停用/升级/加额度要立即生效
            live_account = accounts.get_account(session_user)
            usable, reason = accounts.account_usable(live_account)
            if not usable:
                await websocket.send_json({"type": "auth_required", "content": reason})
                await websocket.close(code=4403)
                return
            mm_key, mm_llm_base, mm_ws_host = _minimax_credentials(live_account)
            # 出话前先原子占位：并发抢不出额度，拿到回复就断线也已计费
            allowed, quota_used_now = accounts.reserve_quota(live_account)
            if not allowed:
                logger.info(f"[{req_id}] 额度用尽 user={session_user}")
                await websocket.send_json({
                    "type": "quota_exceeded",
                    "role": live_account["role"],
                    "quota_limit": live_account["quota_limit"],
                    "quota_used": live_account["quota_used"],
                    "content": "體驗次數已用完，升級後可繼續無限暢聊",
                })
                continue
            quota_charged = live_account["quota_limit"] != accounts.UNLIMITED

            t_turn = time.time()
            turn_num = len(conversation_history) // 2 + 1
            logger.info(f"[{req_id}][turn-{turn_num}] {user_text[:60]}...")

            full_response = ""
            sentence_buffer = ""
            await websocket.send_json({"type": "status", "content": "thinking"})

            ttft = None
            tts_started = False
            tts_chunks = 0
            tts_ms_total = 0

            async def _speak(piece: str):
                # 边生成边按句读出：句子一凑齐就马上合成，唔使等成个回复出晒先开始
                # TTS，等 LLM 生成下一句同呢一句嘅语音合成时间重叠，缩短开口前嘅等待。
                nonlocal tts_started, tts_chunks, tts_ms_total
                piece = piece.strip()
                if not piece:
                    return
                if not tts_started:
                    tts_started = True
                    await websocket.send_json({"type": "status", "content": "tts"})
                t_piece = time.time()
                piece_chunks = 0
                try:
                    async for audio_chunk in minimax_tts_streaming(piece, tts_config,
                                                                  api_key=mm_key, ws_host=mm_ws_host):
                        tts_chunks += 1
                        piece_chunks += 1
                        await websocket.send_bytes(audio_chunk)
                except Exception as tts_err:
                    logger.error(f"[{req_id}] TTS streaming failed: {tts_err}", exc_info=True)
                    await websocket.send_json({"type": "error", "content": f"TTS failed: {tts_err}"})
                if piece_chunks:
                    # 呢句嘅音頻 bytes 已經全部送晒，前端可以將呢一段完整解碼播放；
                    # 連埋原文一齊送，等前端可以將字幕同呢句聲音真正開始播放嘅一刻對齊，
                    # 唔再係文字一串先流晒出嚟、聲音先至慢慢跟上。
                    await websocket.send_json({"type": "tts_segment_end", "text": piece})
                tts_ms_total += int((time.time() - t_piece) * 1000)

            async for chunk in minimax_llm_stream(user_text, conversation_history,
                                                 base_system_prompt + _lang_instruction,
                                                 api_key=mm_key, llm_base=mm_llm_base,
                                                 history_window=history_window):
                if ttft is None:
                    ttft = int((time.time() - t_turn) * 1000)
                if chunk.startswith("[ERROR]"):
                    await websocket.send_json({"type": "error", "content": chunk})
                    break
                full_response += chunk
                sentence_buffer += chunk
                await websocket.send_json({"type": "llm", "content": chunk})

                ready_sentences, sentence_buffer = _split_ready_sentences(sentence_buffer)
                for sentence in ready_sentences:
                    await _speak(sentence)

            # 收尾：读出冇终止标点嘅残余文字（例如全程冇句号嘅短回覆）
            await _speak(sentence_buffer)
            sentence_buffer = ""

            if not (full_response and not full_response.startswith("[ERROR]")):
                # 这一轮没能产出回复，退回出话前的占位，保持「失败不计费」
                if quota_charged:
                    accounts.refund_quota(session_user)
                    logger.info(f"[{req_id}] 本轮无回复，已退回额度 user={session_user}")

            if full_response and not full_response.startswith("[ERROR]"):
                conversation_history.append({"role": "user", "content": user_text})
                conversation_history.append({"role": "assistant", "content": full_response})
                if len(conversation_history) > history_keep:
                    conversation_history = conversation_history[-history_keep:]

                llm_total = int((time.time() - t_turn) * 1000)
                logger.info(f"[{req_id}] LLM done: {len(full_response)}chars, ttft={ttft or 0}ms, total={llm_total}ms")
                logger.info(f"[{req_id}] TTS done (pipelined): {tts_chunks} chunks, {tts_ms_total}ms")
                await websocket.send_json({"type": "status", "content": "done"})

                # Save conversation to DB (fire and forget)
                _save_conversation(
                    char_id=char_id,
                    user_ip=client_ip,
                    user_msg=user_text,
                    assistant_msg=full_response,
                    llm_ms=llm_total,
                    tts_ms=tts_ms_total,
                    username=session_user,
                )

                # 额度已在出话前占位，这里只把最新用量同步给前端
                if quota_charged:
                    left = max(0, live_account["quota_limit"] - quota_used_now)
                    await websocket.send_json({
                        "type": "quota",
                        "role": live_account["role"],
                        "quota_limit": live_account["quota_limit"],
                        "quota_used": quota_used_now,
                        "quota_left": left,
                    })

    except WebSocketDisconnect:
        elapsed = int(time.time() - ws_start)
        turns = len(conversation_history) // 2
        logger.info(f"[{req_id}] WS disconnected after {elapsed}s  turns={turns}")
    except Exception as e:
        elapsed = int(time.time() - ws_start)
        logger.error(f"[{req_id}] WS error after {elapsed}s: {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


# ── Character Creation Pipeline API ─────────────────────
@app.post("/api/create/test-key")
async def create_test_key(x_minimax_api_key: ApiKeyHeader = None, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    _require_creator_access(x_user_code, x_session_token)
    api_key, llm_base, _used_platform_key = _creation_credentials(x_minimax_api_key, x_session_token)
    provider = MiniMaxProvider(api_key, llm_base)
    t0 = time.time()
    text = await provider.simple_text(
        "You are a health check endpoint. Reply with exactly OK.",
        "Check this API key.",
        max_tokens=300,  # M2 思考模型冇得关闭思考，太紧会思考到一半就冇晒 budget 畀真正答案
        temperature=0.1,
    )
    # 只回连通性与延迟，绝不回传 Key 本身或它的任何片段。
    return {
        "ok": True,
        "latency_ms": int((time.time() - t0) * 1000),
        "sample": text[:20],
        "server_key": not (x_minimax_api_key or "").strip(),
    }


@app.post("/api/create/knowledge")
async def create_extract_knowledge(file: UploadFile = File(...), x_user_code: UserCodeHeader = None,
                     x_session_token: accounts.SessionHeader = None):
    """Extract plain text from txt/pdf/docx for the prompt builder."""
    _require_creator_access(x_user_code, x_session_token)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".txt", ".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="Only .txt, .pdf, and .docx knowledge files are supported")

    raw = await file.read()
    if len(raw) > MAX_KNOWLEDGE_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Knowledge file is too large; max 10MB")

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / f"knowledge{suffix}"
        p.write_bytes(raw)
        if suffix == ".txt":
            text = _extract_text_from_txt(raw)
        elif suffix == ".docx":
            text = _extract_docx_text(p)
        else:
            text = _extract_pdf_text(p)

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    truncated = len(text) > MAX_KNOWLEDGE_CHARS
    text = _clamp_knowledge(text)
    return {
        "ok": True,
        "filename": file.filename,
        "chars": len(text),
        "truncated": truncated,
        "text": text,
        "preview": text[:1000],
    }


@app.post("/api/create/knowledge/search")
async def create_search_knowledge(req: GenerateKnowledgeRequest, x_minimax_api_key: ApiKeyHeader = None, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    username = _require_creator_access(x_user_code, x_session_token)
    api_key, llm_base, used_platform_key = _creation_credentials(x_minimax_api_key, x_session_token)
    if used_platform_key:
        allowed, used = accounts.reserve_creation_action(username, "knowledge_search")
        if not allowed:
            raise HTTPException(status_code=429, detail="今日使用平台服務生成知識庫次數已達上限，請稍後再試或改用自己嘅 MiniMax Key")
    query = req.query.strip() or " ".join(x for x in [req.name, req.name_en, req.role, req.background[:120]] if x).strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query or role context is required")
    results = await _search_web(query)
    if not results:
        raise HTTPException(status_code=502, detail="Web search returned no usable results")

    provider = MiniMaxProvider(api_key, llm_base)
    result_text = "\n".join(f"- {r['title']} ({r['url']})" for r in results)
    text = await provider.simple_text(
        "你是数字人角色知识库整理员。根据搜索结果和角色设定，输出不超过6000字的事实型知识库文本。"
        "内容要直接可放入角色上下文，不要写搜索过程，不要编造搜索结果之外的具体事实。",
        (
            f"角色名：{req.name}\n英文/副标题：{req.name_en}\n角色定位：{req.role}\n"
            f"背景：{req.background}\n说话设定：{req.speaking_style}\n搜索词：{query}\n\n搜索结果：\n{result_text}"
        ),
        max_tokens=10000,
        temperature=0.2,
    )
    return {"ok": True, "query": query, "text": _clamp_knowledge(text), "sources": results}


@app.post("/api/create/image-prompt")
async def create_image_prompt(req: GenerateImagePromptRequest, x_minimax_api_key: ApiKeyHeader = None, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    _require_creator_access(x_user_code, x_session_token)
    api_key, llm_base, _used_platform_key = _creation_credentials(x_minimax_api_key, x_session_token)
    provider = MiniMaxProvider(api_key, llm_base)
    prompt = await provider.simple_text(
        "你是数字人角色视觉提示词设计师。输出一段可直接用于图像生成的中文 prompt。"
        "要求 3:4 半身肖像、正面或微侧脸、背景干净、电影级暖色调打光、适合作为后续视频 first frame。"
        "不要输出解释，只输出 prompt 本身。",
        (
            f"角色名：{req.name}\n英文/副标题：{req.name_en}\n角色定位：{req.role}\n"
            f"背景：{req.background}\n说话设定：{req.speaking_style}\nSystem Prompt 摘要：{req.system_prompt[:1200]}"
        ),
        max_tokens=1500,  # 之前 450 太紧，M2 思考模型会思考到截断、content 变空
        temperature=0.5,
    )
    return {"ok": True, "prompt": prompt.strip()}


@app.post("/api/create/prompt")
async def create_prompt(req: CreatePromptRequest, x_minimax_api_key: ApiKeyHeader = None, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    _require_creator_access(x_user_code, x_session_token)
    api_key, llm_base, _used_platform_key = _creation_credentials(x_minimax_api_key, x_session_token)
    if not req.name.strip() or not req.background.strip() or not req.speaking_style.strip():
        raise HTTPException(status_code=400, detail="Name, background, and speaking style are required")

    provider = MiniMaxProvider(api_key, llm_base)
    prompt = await provider.improve_prompt(req)
    job_id = uuid.uuid4().hex
    _save_job(job_id, {
        "id": job_id,
        "created_at": time.time(),
        "name": req.name.strip(),
        "name_en": req.name_en.strip(),
        "role": req.role.strip(),
        "system_prompt": prompt,
        "knowledge_chars": len(req.knowledge_text or ""),
        "status": "prompt_ready",
    })
    return {"ok": True, "job_id": job_id, "system_prompt": prompt}


@app.post("/api/create/images")
async def create_images(req: CreateImagesRequest, x_minimax_api_key: ApiKeyHeader = None, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    username = _require_creator_access(x_user_code, x_session_token)
    api_key, llm_base, used_platform_key = _creation_credentials(x_minimax_api_key, x_session_token)
    if used_platform_key:
        allowed, used = accounts.reserve_creation_action(username, "image")
        if not allowed:
            raise HTTPException(status_code=429, detail="今日使用平台服務生成圖片次數已達上限，請稍後再試或改用自己嘅 MiniMax Key")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Image prompt is required")
    provider = MiniMaxProvider(api_key, llm_base)

    # Reuse existing prompt job if provided, otherwise create a new one
    if req.job_id:
        job_id = req.job_id
        job = _load_job(job_id)
        job["status"] = "image_generation_started"
        _save_job(job_id, job)
    else:
        job_id = uuid.uuid4().hex
        _save_job(job_id, {"id": job_id, "created_at": time.time(), "status": "image_generation_started"})

    try:
        full_prompt = req.prompt.strip()
        if req.reference_description.strip():
            full_prompt += "\n\nReference / user description: " + req.reference_description.strip()
        images = await provider.generate_images(full_prompt, req.count, job_id)
    except Exception:
        if not req.job_id:
            shutil.rmtree(_job_dir(job_id), ignore_errors=True)
        raise
    return {"ok": True, "job_id": job_id, "images": images}


@app.post("/api/create/videos")
async def create_videos(req: CreateVideosRequest, x_minimax_api_key: ApiKeyHeader = None, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    username = _require_creator_access(x_user_code, x_session_token)
    api_key, llm_base, used_platform_key = _creation_credentials(x_minimax_api_key, x_session_token)
    if used_platform_key:
        allowed, used = accounts.reserve_creation_action(username, "video")
        if not allowed:
            raise HTTPException(status_code=429, detail="今日使用平台服務生成視頻次數已達上限，請稍後再試或改用自己嘅 MiniMax Key")
    job = _load_job(req.job_id)
    images = job.get("images") or []
    selected = next((img for img in images if img.get("id") == req.image_id), None)
    if not selected:
        raise HTTPException(status_code=400, detail="Selected image not found in creation job")

    provider = MiniMaxProvider(api_key, llm_base)

    first_frame_url = selected.get("source_url", "")
    raw_dir = _job_dir(req.job_id) / "videos"
    idle_raw = raw_dir / "idle_raw.mp4"
    talk_raw = raw_dir / "talk_raw.mp4"
    idle_final = raw_dir / "idle.mp4"
    talk_final = raw_dir / "talk.mp4"

    base_identity = req.image_prompt.strip() or req.character_name.strip()
    idle_prompt = (
        f"{base_identity} 人物轻微呼吸，胸膛缓缓起伏，眼睛每隔3-4秒缓慢闭合再睁开，"
        "头部有极其轻微的随呼吸摆动。背景保持完全静止。画面保持电影级暖色调打光，"
        "无缝循环，画面无抖动"
    )
    talk_prompt = (
        f"{base_identity} 人物正在说话，嘴巴自然微微张合，节奏如同从容对话，下颌和面部肌肉有轻微联动。"
        "偶尔眨眼。头部有自然的说话伴随微动。身体和手臂保持静止，仅面部动画。背景保持完全静止。"
        "画面保持电影级暖色调打光，无缝循环，画面无抖动，无字幕"
    )

    job["status"] = "video_generation_started"
    job["selected_image"] = selected
    _save_job(req.job_id, job)

    await provider.generate_video(idle_prompt, first_frame_url, idle_raw, 5)
    _ffmpeg_process_video(idle_raw, idle_final, 5)
    await provider.generate_video(talk_prompt, first_frame_url, talk_raw, 8)
    _ffmpeg_process_video(talk_raw, talk_final, 8)

    job["status"] = "videos_ready"
    job["videos"] = {
        "idle": f"/generated/jobs/{req.job_id}/videos/idle.mp4",
        "talk": f"/generated/jobs/{req.job_id}/videos/talk.mp4",
    }
    _save_job(req.job_id, job)
    return {"ok": True, "job_id": req.job_id, "videos": job["videos"]}


@app.post("/api/create/finalize")
async def create_finalize(req: FinalizeCharacterRequest, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    username = _require_creator_access(x_user_code, x_session_token)
    job = _load_job(req.job_id)
    if job.get("status") != "videos_ready":
        raise HTTPException(status_code=400, detail="Videos must be generated before finalizing the character")

    char_id = _safe_character_id(req.character_id or req.name)
    dest = Path("characters") / char_id
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"Character '{char_id}' already exists")

    job_path = _job_dir(req.job_id)
    selected = job.get("selected_image") or {}
    selected_name = Path(selected.get("url", "")).name
    portrait_src = job_path / "images" / selected_name
    idle_src = job_path / "videos" / "idle.mp4"
    talk_src = job_path / "videos" / "talk.mp4"
    if not idle_src.is_file() or not talk_src.is_file():
        raise HTTPException(status_code=500, detail="Generated video files are missing")

    tmp_dest = dest.with_name(f".{dest.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        tmp_dest.mkdir(parents=True, exist_ok=False)
        _copy_or_make_portrait(portrait_src, tmp_dest / "portrait.jpg")
        shutil.copy2(idle_src, tmp_dest / "idle.mp4")
        shutil.copy2(talk_src, tmp_dest / "talk.mp4")
        cfg = {
            "id": char_id,
            "name": _safe_display_text(req.name),
            "name_en": _safe_display_text(req.name_en),
            "role": _safe_display_text(req.role, max_len=160),
            "icon": "portrait.jpg",
            "avatar_idle": "idle.mp4",
            "avatar_talk": "talk.mp4",
            "theme_color": req.theme_color or "#8A6D3B",
            "tts_voice_id": req.tts_voice_id or DEFAULT_TTS_CONFIG["voice_id"],
            "tts_language": req.tts_language or DEFAULT_TTS_CONFIG["language_boost"],
            "created_by": username,
            "tts_speed": 1.0,
            "tts_vol": 1.0,
            "tts_pitch": 0,
            "system_prompt": req.system_prompt,
        }
        (tmp_dest / "character.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_dest.rename(dest)
    except Exception:
        shutil.rmtree(tmp_dest, ignore_errors=True)
        raise

    char_mgr.reload()
    return {"ok": True, "id": char_id, "name": req.name, "url": f"/?char={char_id}"}


# ── Character API ───────────────────────────────────────
@app.get("/api/characters")
async def list_characters(x_session_token: accounts.SessionHeader = None):
    """List all available characters for the lobby page.

    已登录且账号设有 allowed_characters 白名单时，只返回名单内的角色；
    未登录或账号不受限时返回完整列表（保持向后兼容）。
    """
    all_chars = char_mgr.list_all()
    account = accounts.resolve_session(x_session_token)
    if account and account.get("allowed_characters"):
        allowed = set(account["allowed_characters"])
        return [c for c in all_chars if c["id"] in allowed]
    return all_chars


@app.get("/api/characters/{char_id}")
async def get_character(char_id: str, x_session_token: accounts.SessionHeader = None):
    """Get full character config (without system_prompt)."""
    ch = char_mgr.get(char_id)
    if not ch:
        raise HTTPException(status_code=404, detail=f"Character '{char_id}' not found")
    account = accounts.resolve_session(x_session_token)
    if account and not accounts.character_allowed(account, char_id):
        raise HTTPException(status_code=403, detail="你的帳號未獲授權使用呢個數字人角色")
    # Return config without system_prompt (only sent via WS)
    return {
        "id": ch["id"],
        "name": ch.get("name", ch["id"]),
        "name_en": ch.get("name_en", ""),
        "icon": f"/characters/{ch['id']}/{ch.get('icon', 'portrait.jpg')}",
        "avatar_idle": f"/characters/{ch['id']}/{ch.get('avatar_idle', 'idle.mp4')}",
        "avatar_talk": f"/characters/{ch['id']}/{ch.get('avatar_talk', 'talk.mp4')}",
        "theme_color": ch.get("theme_color", "#8A6D3B"),
        "tts_voice_id": ch.get("tts_voice_id", DEFAULT_TTS_CONFIG["voice_id"]),
        "tts_language": ch.get("tts_language", DEFAULT_TTS_CONFIG["language_boost"]),
        "asr_lang": ch.get("asr_lang", ""),
    }


@app.post("/api/characters/import")
async def import_character(file: UploadFile = File(...), x_user_code: UserCodeHeader = None,
                     x_session_token: accounts.SessionHeader = None):
    """Import a character from a .zip file.
    Expected structure: char_id/character.json + resource files.
    """
    username = _require_creator_access(x_user_code, x_session_token)
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files accepted")

    try:
        contents = await file.read()
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            # Find the character directory (first subfolder)
            char_dirs: set[str] = set()
            for name in zf.namelist():
                parts = name.split("/")
                if len(parts) >= 2 and parts[0] and not parts[0].startswith("."):
                    char_dirs.add(parts[0])

            if not char_dirs:
                raise HTTPException(status_code=400, detail="Zip must contain a character folder")

            char_id = sorted(char_dirs)[0]  # Use first folder as char_id

            # Validate: must have character.json
            cfg_path = f"{char_id}/character.json"
            if cfg_path not in zf.namelist():
                raise HTTPException(status_code=400, detail="character.json not found in zip")

            cfg_data = json.loads(zf.read(cfg_path))
            if not cfg_data.get("id"):
                raise HTTPException(status_code=400, detail="character.json missing 'id' field")
            if not cfg_data.get("name"):
                raise HTTPException(status_code=400, detail="character.json missing 'name' field")
            if cfg_data["id"] != char_id:
                raise HTTPException(status_code=400, detail="character.json id must match the zip folder name")
            for name in zf.namelist():
                target = (Path(tempfile.gettempdir()) / name).resolve()
                expected = Path(tempfile.gettempdir()).resolve()
                if not str(target).startswith(str(expected)) or name.startswith("/") or ".." in Path(name).parts:
                    raise HTTPException(status_code=400, detail="Unsafe path found in zip")

            # Extract to temp directory first, validate, then move
            dest = Path("characters") / char_id
            if dest.exists():
                raise HTTPException(status_code=409, detail=f"Character '{char_id}' already exists")

            with tempfile.TemporaryDirectory() as tmp:
                for member in zf.namelist():
                    if member.endswith("/"):
                        continue
                    target = (Path(tmp) / member).resolve()
                    if not str(target).startswith(str(Path(tmp).resolve())):
                        raise HTTPException(status_code=400, detail="Unsafe path found in zip")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))
                src = Path(tmp) / char_id
                if src.is_dir():
                    await asyncio.to_thread(shutil.copytree, src, dest)
                else:
                    raise HTTPException(status_code=400, detail="Invalid zip structure")

        # Reload character manager
        char_mgr.reload()
        return {"ok": True, "id": char_id, "name": cfg_data.get("name")}

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import character failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/characters/{char_id}/export")
async def export_character(char_id: str, x_user_code: UserCodeHeader = None,
                            x_session_token: accounts.SessionHeader = None):
    """Export a character as a .zip file.

    The archive includes character.json (system_prompt, TTS config) and the
    knowledge base, so this needs the same guard as character creation —
    invite code or a premium/admin session — not anonymous access.
    """
    _require_creator_access(x_user_code, x_session_token)
    ch = char_mgr.get(char_id)
    if not ch:
        raise HTTPException(status_code=404, detail=f"Character '{char_id}' not found")

    char_dir = Path(ch["_dir"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(char_dir.rglob("*")):
            if f.is_file():
                arcname = str(f.relative_to(char_dir.parent))
                zf.write(f, arcname)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={char_id}.zip"},
    )


# ── GET /health ─────────────────────────────────────────
@app.get("/health")
async def health():
    chars = char_mgr.list_all()
    return {
        "status": "ok",
        "tts_model": TTS_MODEL,
        "characters_loaded": len(chars),
        "characters": [c["id"] for c in chars],
        "minimax_configured": bool(MINIMAX_API_KEY),
    }


# ── Auth API ──────────────────────────────────────────
@app.post("/api/auth/verify")
async def auth_verify(body: dict):
    """Verify an invite code. Returns username if valid."""
    code = (body.get("code") or "").strip()
    username = _verify_user_code(code)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid invite code")
    return {"ok": True, "username": username}


@app.get("/api/auth/me")
async def auth_me(x_user_code: UserCodeHeader = None):
    """Check current auth status from header."""
    username = _verify_user_code(x_user_code)
    return {
        "authenticated": bool(username),
        "username": username or "",
        "codes_configured": bool(USER_CODES),
    }


# ── Ops API helpers ────────────────────────────────────
def _run_ops_cmd(args: list[str], timeout: int = 4) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as e:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(e)}


def _human_duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _read_cgroup_int(path: str) -> int | None:
    """读 cgroup 数值文件；"max"（无限制）与读取失败都返回 None。"""
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if raw in ("max", ""):
        return None
    try:
        return int(raw.split()[0])
    except (ValueError, IndexError):
        return None


def _container_memory() -> dict | None:
    """容器自身的内存额度与用量（cgroup v2 优先，回退 v1）。

    容器里读 /proc/meminfo 拿到的是宿主机数据，对运维毫无意义，
    所以这里优先按 cgroup 限额统计。
    """
    limit = _read_cgroup_int("/sys/fs/cgroup/memory.max")
    current = _read_cgroup_int("/sys/fs/cgroup/memory.current")
    if limit is None:
        limit = _read_cgroup_int("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        current = _read_cgroup_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    # v1 无限制时会给一个接近 2^63 的哨兵值
    if limit and limit > (1 << 62):
        limit = None
    if not limit or current is None:
        return None
    return {
        "total": limit,
        "available": max(limit - current, 0),
        "used": current,
        "percent": round((current / limit) * 100, 1) if limit else 0,
        "scope": "container",
    }


def _container_cpu_quota() -> float | None:
    """容器可用的 CPU 核数（cpu.max = "quota period"）。"""
    try:
        raw = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").strip().split()
        if len(raw) == 2 and raw[0] != "max":
            return round(int(raw[0]) / int(raw[1]), 2)
    except Exception:
        pass
    quota = _read_cgroup_int("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period = _read_cgroup_int("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if quota and period and quota > 0:
        return round(quota / period, 2)
    return None


def _read_meminfo() -> dict:
    container = _container_memory()
    if container:
        return container
    data: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            data[key] = int(raw.strip().split()[0]) * 1024
    except Exception:
        return {"total": 0, "available": 0, "used": 0, "percent": 0, "scope": "host"}
    total = data.get("MemTotal", 0)
    available = data.get("MemAvailable", 0)
    used = max(total - available, 0)
    percent = round((used / total) * 100, 1) if total else 0
    return {"total": total, "available": available, "used": used, "percent": percent, "scope": "host"}


def _system_resources() -> dict:
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except Exception:
        uptime_seconds = 0
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        load1 = load5 = load15 = 0
    host_cores = os.cpu_count() or 1
    quota = _container_cpu_quota()
    cores = quota or host_cores
    # 容器里 / 是镜像层，运维真正关心的是数据卷所在的挂载点
    disk_path = str(DB_PATH.parent) if DB_PATH.parent.exists() else "/"
    disk = shutil.disk_usage(disk_path)
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    # 容器内 /proc/uptime 是宿主机的，改用本进程存活时长
    proc_uptime = max(time.time() - PROCESS_STARTED_AT, 0)
    if IS_RAILWAY:
        uptime_seconds = proc_uptime
    return {
        "time": datetime.datetime.now(OPS_TZ).isoformat(),
        "timezone": "UTC+8",
        "platform": PLATFORM,
        "uptime_seconds": int(uptime_seconds),
        "uptime": _human_duration(uptime_seconds),
        "uptime_scope": "process" if IS_RAILWAY else "host",
        "cpu": {
            "cores": cores,
            "scope": "container" if quota else "host",
            "load_1": round(load1, 2),
            "load_5": round(load5, 2),
            "load_15": round(load15, 2),
            "load_percent": round(min((load1 / max(cores, 0.1)) * 100, 999), 1),
        },
        "memory": _read_meminfo(),
        "disk": {
            "mount": disk_path,
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": round((disk.used / disk.total) * 100, 1) if disk.total else 0,
        },
        "database": {
            "path": str(DB_PATH),
            "exists": DB_PATH.exists(),
            "size": db_size,
        },
        "process": {
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "python": ".".join(map(str, os.sys.version_info[:3])),
        },
        "deployment": _deployment_info(),
    }


def _deployment_info() -> dict:
    """当前部署的身份信息。Railway 通过环境变量注入这些值。"""
    if not IS_RAILWAY:
        return {"platform": "systemd", "host": socket.gethostname()}
    return {
        "platform": "railway",
        "project": os.getenv("RAILWAY_PROJECT_NAME", ""),
        "service": os.getenv("RAILWAY_SERVICE_NAME", ""),
        "environment": RAILWAY_ENV,
        "region": os.getenv("RAILWAY_REPLICA_REGION", ""),
        "replica": os.getenv("RAILWAY_REPLICA_ID", "")[:12],
        "deployment": os.getenv("RAILWAY_DEPLOYMENT_ID", "")[:12],
        "url": os.getenv("RAILWAY_PUBLIC_DOMAIN", ""),
    }


def _service_state(name: str) -> dict:
    active = _run_ops_cmd(["systemctl", "is-active", name])
    enabled = _run_ops_cmd(["systemctl", "is-enabled", name])
    status = "ok" if active["stdout"] == "active" else "error"
    return {
        "name": name,
        "active": active["stdout"] or "unknown",
        "enabled": enabled["stdout"] or "unknown",
        "status": status,
    }


def _service_list() -> list[dict]:
    """按运行平台给出有意义的服务清单。

    容器平台没有 systemd —— 去问 systemctl 只会得到一串假的「未运行」告警。
    Railway 上真正能反映健康度的是进程自身与平台注入的部署信息。
    """
    if not IS_RAILWAY:
        return [_service_state("digitalhuman.service"), _service_state("nginx.service")]
    dep = _deployment_info()
    detail = " · ".join(x for x in (dep.get("service"), dep.get("environment"), dep.get("region")) if x)
    return [
        {
            "name": "digitalhuman (Railway)",
            "active": "active",
            "enabled": detail or "railway",
            "status": "ok",
            "managed": "railway",
        },
        {
            "name": "Railway Edge / TLS",
            "active": "active" if dep.get("url") else "unknown",
            "enabled": dep.get("url") or "platform-managed",
            "status": "ok",
            "managed": "railway",
        },
    ]


_JOURNAL_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z))(\s+)(.*)$")


def _journal_to_hkt(text: str) -> str:
    """Convert journalctl short-iso timestamps to explicit HKT/UTC+8 for operators."""
    out = []
    for line in (text or "").splitlines():
        m = _JOURNAL_TS_RE.match(line)
        if not m:
            out.append(line)
            continue
        raw_ts, gap, rest = m.groups()
        try:
            normalized = raw_ts.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(normalized).astimezone(OPS_TZ)
            out.append(f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}+08:00 HKT{gap}{rest}")
        except ValueError:
            out.append(line)
    return "\n".join(out)


def _recent_journal(lines: int = 200) -> str:
    """最近日志。容器平台没有 journalctl，改用进程内的环形缓冲。"""
    if IS_RAILWAY:
        return RING_LOGS.dump(lines)
    result = _run_ops_cmd(
        ["journalctl", "-u", "digitalhuman.service", "--no-pager", "-n", str(lines), "-o", "short-iso"],
        timeout=6,
    )
    if result["ok"] or result["stdout"]:
        return _journal_to_hkt(result["stdout"])
    # 自管机器上 journalctl 不可用时，退回内存缓冲而不是把报错当日志显示
    fallback = RING_LOGS.dump(lines)
    return fallback or _journal_to_hkt(result["stderr"])


def _conversation_summary() -> dict:
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            today = datetime.datetime.now(OPS_TZ).date()
            tomorrow = today + datetime.timedelta(days=1)
            today = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE time >= ? AND time < ?",
                (f"{today.isoformat()}T00:00:00", f"{tomorrow.isoformat()}T00:00:00"),
            ).fetchone()[0]
            per_char = conn.execute(
                "SELECT char_id, COUNT(*) as cnt FROM conversations GROUP BY char_id ORDER BY cnt DESC"
            ).fetchall()
            recent = conn.execute(
                "SELECT time, char_id, user_ip, user_msg, assistant_msg, llm_ms, tts_ms "
                "FROM conversations ORDER BY time DESC LIMIT 12"
            ).fetchall()
        return {
            "ok": True,
            "total": total,
            "today": today,
            "per_character": dict(per_char),
            "recent": [dict(r) for r in recent],
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "total": 0, "today": 0, "per_character": {}, "recent": []}


def _diagnose(logs: str, resources: dict, services: list[dict]) -> list[dict]:
    items = []
    lines = [line for line in logs.splitlines() if line.strip()]
    ws_keepalive_lines = [
        line for line in lines
        if (
            "ConnectionClosedError" in line
            or "keepalive ping timeout" in line
            or "CloseCode.INTERNAL_ERROR" in line
        )
    ]
    error_lines = [
        line for line in lines
        if ("ERROR" in line or "CRITICAL" in line)
        and line not in ws_keepalive_lines
    ]
    warn_lines = [line for line in lines if "WARNING" in line]

    for service in services:
        if service["active"] != "active":
            items.append({
                "status": "error",
                "code": f"service-{service['name']}",
                "title": f"{service['name']} is not active",
                "description": (f"Railway reports {service['active']}." if IS_RAILWAY
                                else f"systemctl reports {service['active']}."),
                "root_cause": "The process may have crashed, failed during boot, or been stopped manually.",
                "advice": ("Check the deployment logs in the Railway dashboard before redeploying."
                           if IS_RAILWAY
                           else f"Run journalctl -u {service['name']} -n 100 before restarting."),
                "log": "",
            })

    if resources["disk"]["percent"] >= 85:
        items.append({
            "status": "warning",
            "code": "disk-high",
            "title": "Disk usage is high",
            "description": f"Root disk is {resources['disk']['percent']}% used.",
            "root_cause": "Logs, generated media, or SQLite backups may be accumulating.",
            "advice": "Archive old reports/media and check journal size before it reaches 95%.",
            "log": "",
        })

    if resources["memory"]["percent"] >= 85:
        items.append({
            "status": "warning",
            "code": "memory-high",
            "title": "Memory pressure is high",
            "description": f"Memory usage is {resources['memory']['percent']}%.",
            "root_cause": "Long sessions, media generation, or another process may be holding memory.",
            "advice": "Check top processes and recent traffic before restarting the app.",
            "log": "",
        })

    if resources["cpu"]["load_percent"] >= 90:
        items.append({
            "status": "warning",
            "code": "cpu-load-high",
            "title": "CPU load is high",
            "description": f"1-minute load is {resources['cpu']['load_1']} on {resources['cpu']['cores']} cores.",
            "root_cause": "Concurrent TTS/LLM traffic or background jobs may be saturating the instance.",
            "advice": "Check active WebSocket sessions and consider rate limiting if this repeats.",
            "log": "",
        })

    if ws_keepalive_lines:
        items.append({
            "status": "warning",
            "code": "ws-keepalive-timeout",
            "title": "WebSocket idle connection closed",
            "description": f"{len(ws_keepalive_lines)} keepalive timeout log line(s) detected.",
            "root_cause": "A browser tab or network path stopped responding to WebSocket ping frames; the app process stayed healthy.",
            "advice": "If this repeats during events, keep the client page active and check visitor network stability. Server timeouts have been relaxed.",
            "log": ws_keepalive_lines[-1][:260],
        })

    for line in error_lines[:6]:
        lower = line.lower()
        if "tts" in lower:
            root = "MiniMax TTS request, voice config, or network latency likely failed."
            advice = "Verify MINIMAX_API_KEY, voice_id, and upstream TTS status; retry a short diagnostic TTS."
        elif "llm" in lower or "chatcompletion" in lower:
            root = "MiniMax LLM request likely failed or timed out."
            advice = "Check API key validity, quota, and outbound network; inspect the full stack trace."
        elif "sqlite" in lower or "database" in lower or "conversation" in lower:
            root = "SQLite write/read path may be unavailable or locked."
            advice = "Check data directory permissions and database file size/locks."
        elif "websocket" in lower or " ws " in lower:
            root = "Client WebSocket disconnected or the dialogue loop raised an exception."
            advice = "Compare the log timestamp with traffic spikes and client browser errors."
        else:
            root = "Application log contains an unclassified error."
            advice = "Open the related log line and inspect surrounding entries."
        items.append({
            "status": "error",
            "code": "log-error",
            "title": "Recent application error",
            "description": line[:180],
            "root_cause": root,
            "advice": advice,
            "log": line,
        })

    for line in warn_lines[:3]:
        items.append({
            "status": "warning",
            "code": "log-warning",
            "title": "Recent warning",
            "description": line[:180],
            "root_cause": "The application recovered but reported a degraded condition.",
            "advice": "Review repeated warnings; a single warning may be harmless.",
            "log": line,
        })

    if not items:
        items.append({
            "status": "ok",
            "code": "healthy",
            "title": "No active exceptions detected",
            "description": "Services are active and recent logs do not show ERROR entries.",
            "root_cause": "No immediate root cause to investigate.",
            "advice": "Keep monitoring response latency, disk usage, and weekly report delivery.",
            "log": "",
        })
    return items


@app.get("/api/ops/resources")
async def ops_resources(x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Return system resource data for the ops console."""
    _require_ops_access(x_user_code, x_session_token)
    return {"ok": True, "resources": _system_resources()}


@app.get("/api/ops/status")
async def ops_status(x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Return service and app status for the ops console."""
    _require_ops_access(x_user_code, x_session_token)
    chars = char_mgr.list_all()
    services = _service_list()
    return {
        "ok": True,
        "app": {
            "status": "ok",
            "tts_model": TTS_MODEL,
            "characters_loaded": len(chars),
            "characters": [c["id"] for c in chars],
            "minimax_configured": bool(MINIMAX_API_KEY),
        },
        "services": services,
        "resources": _system_resources(),
        "conversations": _conversation_summary(),
    }


@app.get("/api/ops/diagnostics")
async def ops_diagnostics(lines: int = 300, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Return recent logs plus rule-based operational diagnostics."""
    _require_ops_access(x_user_code, x_session_token)
    lines = max(50, min(lines, 2000))
    resources = _system_resources()
    services = _service_list()
    logs = _recent_journal(lines)
    return {
        "ok": True,
        "items": _diagnose(logs, resources, services),
        "logs": logs,
        "resources": resources,
        "services": services,
    }


@app.get("/api/ops/token-plan")
async def ops_token_plan(response: Response, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Proxy MiniMax token plan usage without exposing the API key to the browser."""
    _require_ops_access(x_user_code, x_session_token)
    response.headers["Cache-Control"] = "no-store"
    api_key = (MINIMAX_TOKEN_PLAN_API_KEY or "").strip()
    if not api_key:
        return {"ok": False, "configured": False, "error": "MINIMAX_TOKEN_PLAN_API_KEY is not configured"}

    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            res = await client.get(
                MINIMAX_TOKEN_PLAN_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        payload = res.json() if "application/json" in res.headers.get("content-type", "") else {"text": res.text[:2000]}
        return {
            "ok": res.is_success,
            "configured": True,
            "source": "minimax.token_plan.remains",
            "key_source": "MINIMAX_TOKEN_PLAN_API_KEY",
            "fetched_at": datetime.datetime.now(OPS_TZ).isoformat(),
            "status_code": res.status_code,
            "data": payload,
        }
    except Exception as e:
        logger.warning(f"MiniMax token plan query failed: {e}")
        return {"ok": False, "configured": True, "error": str(e)}


def _build_ops_chat_prompt(req: OpsChatRequest) -> tuple[str, str, list[dict]]:
    """Build a bounded, read-only ops prompt for JSON and streaming chat responses."""
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    resources = _system_resources()
    services = _service_list()
    logs = _recent_journal(180)
    diagnostics = _diagnose(logs, resources, services)
    conversations = _conversation_summary()
    chars = char_mgr.list_all()

    context = {
        "services": services,
        "app": {
            "tts_model": TTS_MODEL,
            "characters_loaded": len(chars),
            "characters": [c["id"] for c in chars],
            "minimax_configured": bool(MINIMAX_API_KEY),
        },
        "resources": resources,
        "conversations": {
            "total": conversations.get("total", 0),
            "today": conversations.get("today", 0),
            "per_character": conversations.get("per_character", {}),
        },
        "diagnostics": diagnostics[:8],
        "recent_log_excerpt": "\n".join(logs.splitlines()[-40:]),
    }
    safe_history = []
    for item in (req.history or [])[-6:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            safe_history.append({"role": role, "content": content[:800]})

    answer_language = "English" if (req.language or "").lower().startswith("en") else "中文"
    system = (
        "你是 Digital Human 东京服务器的只读运维 Chatbot。"
        "只能基于提供的 JSON 运维上下文回答服务状态、日志异常、对话统计、角色配置路径和排查建议。"
        "不要编造未提供的数据，不要声称已经连接 SSH、重启服务、修改配置、扩缩容或执行任何命令。"
        "如果用户要求写操作，只给出需要人工二次确认的建议命令，并明确你没有执行。"
        f"回答要简洁、专业，使用{answer_language}；必要时列 2-4 条要点。"
        "不要输出密钥、密码、App Password、完整环境变量或敏感凭据。"
    )
    user_payload = (
        "用户问题：\n"
        f"{message[:1200]}\n\n"
        "运维上下文 JSON：\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)[:12000]}"
    )
    if safe_history:
        user_payload += "\n\n最近对话上下文：\n" + json.dumps(safe_history, ensure_ascii=False)

    return system, user_payload, safe_history


@app.post("/api/ops/chat")
async def ops_chat(req: OpsChatRequest, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Simple read-only ops chatbot backed by the configured MiniMax API key."""
    _require_ops_access(x_user_code, x_session_token)
    if not MINIMAX_API_KEY:
        raise HTTPException(status_code=503, detail="MINIMAX_API_KEY not configured")

    system, user_payload, _safe_history = _build_ops_chat_prompt(req)
    provider = MiniMaxProvider(MINIMAX_API_KEY)
    answer = await provider.simple_text(system, user_payload, max_tokens=700, temperature=0.2)
    return {"ok": True, "answer": answer}


@app.post("/api/ops/chat/stream")
async def ops_chat_stream(req: OpsChatRequest, x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Stream the read-only ops chatbot response as Server-Sent Events."""
    _require_ops_access(x_user_code, x_session_token)
    if not MINIMAX_API_KEY:
        raise HTTPException(status_code=503, detail="MINIMAX_API_KEY not configured")

    system, user_payload, safe_history = _build_ops_chat_prompt(req)

    async def event_stream():
        full_answer: list[str] = []
        try:
            async for chunk in minimax_llm_stream(user_payload, safe_history, system_prompt=system):
                if not chunk:
                    continue
                full_answer.append(chunk)
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'answer': ''.join(full_answer)}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Ops chatbot stream failed: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/ops")
async def ops_console():
    """Canonical ops console entrypoint."""
    return RedirectResponse("/ops.html")


# ── Conversation History API ────────────────────────────
def _conversation_where(char: str = "", start: str = "", end: str = "") -> tuple[str, list]:
    clauses = []
    params: list = []
    if char:
        clauses.append("char_id=?")
        params.append(char)
    if start:
        clauses.append("time >= ?")
        params.append(f"{start[:10]}T00:00:00")
    if end:
        try:
            end_next = datetime.date.fromisoformat(end[:10]) + datetime.timedelta(days=1)
            clauses.append("time < ?")
            params.append(f"{end_next.isoformat()}T00:00:00")
        except ValueError:
            clauses.append("time <= ?")
            params.append(f"{end[:10]}T23:59:59")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _fetch_conversations(limit: int = 200, char: str = "", start: str = "", end: str = "", offset: int = 0) -> tuple[int, list[dict]]:
    limit = max(1, min(int(limit), 20000))
    offset = max(0, int(offset))
    where, params = _conversation_where(char, start, end)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM conversations{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM conversations{where} ORDER BY time DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return total, [dict(r) for r in rows]


def _conversation_analytics(char: str = "", start: str = "", end: str = "") -> dict:
    where, params = _conversation_where(char, start, end)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM conversations{where}", params).fetchone()[0]
        per_char = conn.execute(
            f"SELECT char_id, COUNT(*) as cnt FROM conversations{where} GROUP BY char_id ORDER BY cnt DESC",
            params,
        ).fetchall()
        daily = conn.execute(
            f"SELECT substr(time, 1, 10) as day, COUNT(*) as cnt FROM conversations{where} GROUP BY day ORDER BY day",
            params,
        ).fetchall()
        hourly_rows = conn.execute(
            f"SELECT substr(time, 12, 2) as hour, COUNT(*) as cnt FROM conversations{where} GROUP BY hour ORDER BY hour",
            params,
        ).fetchall()
        latency_expr = "COALESCE(llm_ms, 0) + COALESCE(tts_ms, 0)"
        latency_where = where + (" AND " if where else " WHERE ") + f"{latency_expr} > 0"
        avg_latency = conn.execute(
            f"SELECT AVG({latency_expr}) FROM conversations{latency_where}",
            params,
        ).fetchone()[0]
        latency_rows = conn.execute(
            f"SELECT {latency_expr} as ms FROM conversations{latency_where} ORDER BY time DESC LIMIT ?",
            [*params, 5000],
        ).fetchall()

    hourly = [0] * 24
    for row in hourly_rows:
        try:
            hour = int(row["hour"])
        except (TypeError, ValueError):
            continue
        if 0 <= hour < 24:
            hourly[hour] = row["cnt"]

    return {
        "total": total,
        "per_character": {r["char_id"]: r["cnt"] for r in per_char},
        "daily": {r["day"]: r["cnt"] for r in daily if r["day"]},
        "hourly": hourly,
        "avg_latency_ms": round(avg_latency or 0),
        "latencies": [r["ms"] for r in latency_rows],
        "latencies_truncated": len(latency_rows) >= 5000,
    }


@app.get("/api/conversations")
async def list_conversations(limit: int = 20, offset: int = 0, char: str = "", start: str = "", end: str = "",
                            x_user_code: UserCodeHeader = None,
                            x_session_token: accounts.SessionHeader = None):
    """Return recent conversation records. Optionally filter by char_id/date."""
    _require_data_access(x_user_code, x_session_token)
    try:
        total, rows = _fetch_conversations(limit, char, start, end, offset)
        return {"ok": True, "total": total, "limit": limit, "offset": offset, "conversations": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/conversations/analytics")
async def conversation_analytics(char: str = "", start: str = "", end: str = "",
                                 x_user_code: UserCodeHeader = None,
                                 x_session_token: accounts.SessionHeader = None):
    """Return aggregate conversation metrics for dashboards without row sampling."""
    _require_data_access(x_user_code, x_session_token)
    try:
        return {"ok": True, **_conversation_analytics(char, start, end)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/conversations/stats")
async def conversation_stats(x_user_code: UserCodeHeader = None,
                             x_session_token: accounts.SessionHeader = None):
    """Show simple stats about saved conversations."""
    _require_data_access(x_user_code, x_session_token)
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            per_char = conn.execute(
                "SELECT char_id, COUNT(*) as cnt FROM conversations GROUP BY char_id ORDER BY cnt DESC"
            ).fetchall()
            today_key = datetime.datetime.now(OPS_TZ).date()
            tomorrow_key = today_key + datetime.timedelta(days=1)
            today = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE time >= ? AND time < ?",
                (f"{today_key.isoformat()}T00:00:00", f"{tomorrow_key.isoformat()}T00:00:00"),
            ).fetchone()[0]
        return {"ok": True, "total": total, "today": today, "per_character": dict(per_char)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ops/export/conversations")
async def export_conversations(start: str = "", end: str = "", char: str = "", fmt: str = "csv", x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Export conversation records for the selected date range."""
    _require_ops_access(x_user_code, x_session_token)
    total, rows = _fetch_conversations(20000, char, start, end)
    stamp = datetime.datetime.now(OPS_TZ).strftime("%Y%m%d-%H%M%S")
    if fmt.lower() == "json":
        payload = json.dumps({"ok": True, "total": total, "conversations": rows}, ensure_ascii=False, indent=2).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=conversations-{stamp}.json"},
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["time", "char_id", "user_ip", "user_msg", "assistant_msg", "llm_ms", "tts_ms"])
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=conversations-{stamp}.csv"},
    )


@app.get("/api/ops/export/logs")
async def export_logs(lines: int = 8000, start: str = "", end: str = "", level: str = "all", q: str = "", x_user_code: UserCodeHeader = None, x_session_token: accounts.SessionHeader = None):
    """Export filtered service logs."""
    _require_ops_access(x_user_code, x_session_token)
    raw = _recent_journal(max(10, min(lines, 20000)))
    q_l = q.lower().strip()
    level_l = level.lower().strip()
    out_lines = []
    for line in raw.splitlines():
        day = line[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", line) else ""
        if start and day and day < start[:10]:
            continue
        if end and day and day > end[:10]:
            continue
        lower = line.lower()
        if q_l and q_l not in lower:
            continue
        if level_l != "all" and level_l not in lower:
            continue
        out_lines.append(line)
    stamp = datetime.datetime.now(OPS_TZ).strftime("%Y%m%d-%H%M%S")
    data = ("\n".join(out_lines) + ("\n" if out_lines else "")).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=digitalhuman-logs-{stamp}.txt"},
    )


# ── Log Viewer ────────────────────────────────────────
@app.get("/api/logs")
async def api_logs(lines: int = 30,
                   x_user_code: UserCodeHeader = None,
                   x_session_token: accounts.SessionHeader = None):
    """Return recent service logs (journalctl)."""
    _require_data_access(x_user_code, x_session_token)
    try:
        lines = max(10, min(lines, 8000))
        return {"logs": _recent_journal(lines).strip(), "stderr": ""}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}", "stderr": ""}


@app.get("/logs")
async def log_viewer():
    """Simple auto-refreshing log viewer page."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DigitalHuman Logs</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0a0a12; color:#c8d6e5; font:13px/1.5 'SF Mono', 'Fira Code', monospace; padding:16px; min-height:100vh; }
  .bar { position:sticky; top:0; background:rgba(10,10,18,.9); padding:8px 0; border-bottom:1px solid rgba(255,255,255,.06); margin-bottom:12px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  .bar a { color:#6b8ab0; text-decoration:none; font-size:11px; }
  .bar a:hover { color:#a0c4e8; }
  .bar select, .bar button { background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1); color:#a0b8d0; padding:4px 10px; border-radius:4px; font:inherit; cursor:pointer; }
  .bar button:hover { background:rgba(255,255,255,.1); }
  pre { white-space:pre-wrap; word-break:break-all; }
  .e { color:#ff6b6b; } .w { color:#ffd93d; } .i { color:#48dbfb; } .m { color:#888; }
</style>
</head>
<body>
<div class="bar">
  <b>DigitalHuman Logs</b>
  <label>行数: <select id="lines" onchange="fetchLogs()">
    <option>20</option><option selected>30</option><option>50</option><option>100</option>
  </select></label>
  <button onclick="fetchLogs()">重新整理</button>
  <label><input type="checkbox" id="auto" checked onchange="toggleAuto()"> 自動更新 (5s)</label>
  <span style="font-size:11px;color:#555;" id="ts"></span>
  <a href="/lobby.html">← 返回</a>
</div>
<pre id="out">載入中...</pre>
<script>
let timer = null;
// /api/logs 現在只認管理員會話，帶上 token 否則會一直 401
let SESSION_TOKEN = '';
try { SESSION_TOKEN = localStorage.getItem('dh_session_token') || ''; } catch(_) {}
// 日誌原文可能含使用者輸入（對話內容等），塞入 innerHTML 前必須轉義
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function highlight(line) {
  const safe = escapeHtml(line);
  if (/ERROR|CRITICAL|FATAL/.test(line)) return '<span class="e">'+safe+'</span>';
  if (/WARNING/.test(line)) return '<span class="w">'+safe+'</span>';
  if (/INFO/.test(line)) return '<span class="i">'+safe+'</span>';
  return '<span class="m">'+safe+'</span>';
}
async function fetchLogs() {
  const n = document.getElementById('lines').value;
  try {
    const r = await fetch('/api/logs?lines='+n, { headers: SESSION_TOKEN ? {'X-Session-Token': SESSION_TOKEN} : {} });
    const d = await r.json();
    document.getElementById('out').innerHTML = d.logs.split('\\n').map(highlight).join('\\n') || '(no logs)';
    document.getElementById('ts').textContent = new Date().toLocaleTimeString();
  } catch(e) {
    document.getElementById('out').textContent = '無法載入 (後端未啟用 journalctl)';
  }
}
function toggleAuto() {
  if (document.getElementById('auto').checked) { timer = setInterval(fetchLogs, 5000); }
  else { clearInterval(timer); }
}
fetchLogs();
toggleAuto();
</script>
</body>
</html>""")


# ── Static Files ───────────────────────────────────────
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
# Mount characters/ for avatar resources (videos, icons)
app.mount("/characters", StaticFiles(directory="characters"), name="characters")
# Mount generated previews for the creation wizard
app.mount("/generated", StaticFiles(directory=str(GENERATED_DIR)), name="generated")
# Mount the SPA (must be last)
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

    B = "\033[1m"; G = "\033[32m"; Y = "\033[33m"; R = "\033[31m"; C = "\033[36m"; D = "\033[0m"
    print(f"{Y}{'═' * 50}{D}")
    print(f"  {B}🏯 数字人平台 — Digital Human Platform{D}")
    print(f"{Y}{'═' * 50}{D}")
    print(f"  {C}本地访问:{D}     http://localhost:{port}")
    print(f"  {C}局域网访问:{D}   http://{local_ip}:{port}")
    chars = char_mgr.list_all()
    print(f"  {C}已加载角色:{D}   {len(chars)} 个 ({', '.join(c['id'] for c in chars)})")
    print(f"  {C}TTS 模型:{D}     {TTS_MODEL}")
    mm_status = f"{G}✅ 已配置{D}" if MINIMAX_API_KEY else f"{R}❌ 未配置{D}"
    print(f"  {C}MiniMax:{D}      {mm_status}")
    print(f"{Y}{'═' * 50}{D}")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=1,  # single worker for per-connection state safety
        log_level="info",
    )
