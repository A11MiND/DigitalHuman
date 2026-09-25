"""账号体系 — 登录、体验额度、管理员后台。

设计要点：
  - 账号全部由管理员后台创建，前台没有注册入口。
  - trial 角色带对话额度（默认 20 次），用尽后锁定并提示购买，可提交追加申请。
  - premium / admin 不限额度，走 PREMIUM_API_KEY 配置的完整服务。
  - 会话令牌存库，HTTP 走 X-Session-Token 头，WebSocket 走连接后首帧传送。

表结构与 conversations 共用 data/conversations.db，方便后台按账号统计用量。
"""

import os
import base64
import collections
import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import datetime
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, Field
from typing import Annotated

logger = logging.getLogger("digitalhuman.accounts")

DB_PATH = Path("data/conversations.db")

# 高级用户使用的服务 Key。留空则回退到主 MINIMAX_API_KEY。
PREMIUM_API_KEY = os.getenv("PREMIUM_API_KEY", "")
# 该 Key 所属的 MiniMax 区域：cn = api.minimaxi.com，global = api.minimax.io。
# 区域必须和 Key 配对，否则会返回 2049 invalid api key。
PREMIUM_REGION = os.getenv("PREMIUM_MINIMAX_REGION", "").strip().lower()
# 平台主 Key，仅用于判断「服务端是否有可用 Key」，值本身不会离开服务端。
PLATFORM_API_KEY = os.getenv("MINIMAX_API_KEY", "")

TRIAL_QUOTA_DEFAULT = int(os.getenv("TRIAL_QUOTA", "20"))
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
PBKDF2_ITERATIONS = 200_000

ROLES = ("trial", "premium", "admin")
UNLIMITED = -1

# 时区跟 server.py 保持一致
OPS_TZ = datetime.timezone(datetime.timedelta(hours=8))


def _now() -> str:
    return datetime.datetime.now(OPS_TZ).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ── 密码哈希 ────────────────────────────────────────────
def hash_password(password: str) -> str:
    """pbkdf2_sha256$iterations$salt_b64$hash_b64 — 只用标准库，不引入新依赖。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iterations)
        )
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except Exception:
        return False


# ── 建表 ────────────────────────────────────────────────
def init_accounts_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                role TEXT NOT NULL DEFAULT 'trial',
                status TEXT NOT NULL DEFAULT 'active',
                quota_limit INTEGER NOT NULL DEFAULT 20,
                quota_used INTEGER NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT DEFAULT '',
                expires_at TEXT DEFAULT '',
                allowed_characters TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                client_ip TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(username)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quota_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                message TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                handled_at TEXT DEFAULT '',
                handled_by TEXT DEFAULT '',
                granted INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quota_requests_status ON quota_requests(status, requested_at DESC)"
        )
        # 创作管线（生图/生视频/网络搜索知识库）用平台共享 Key 时嘅每日用量，
        # 防止一个邀请码无限烧平台额度。自带 Key 嘅调用唔计入呢度。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS creation_usage (
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (username, action, day)
            )
        """)
        # conversations 加 username 列，便于后台按账号看用量（旧库安全迁移）
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)")}
        if cols and "username" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN username TEXT DEFAULT ''")
            logger.info("conversations 表已添加 username 列")
        # accounts 加 allowed_characters 列，控制账号可见/可用的数字人角色（旧库安全迁移）
        acct_cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
        if acct_cols and "allowed_characters" not in acct_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN allowed_characters TEXT DEFAULT ''")
            logger.info("accounts 表已添加 allowed_characters 列")
    _bootstrap_admin()
    logger.info("Accounts DB ready: %s", DB_PATH)


def _bootstrap_admin() -> None:
    """首次启动时创建管理员账号。密码来自环境变量，未配置则随机生成并打印一次。"""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM accounts WHERE role = 'admin'").fetchone()
        if row["c"] > 0:
            return
        username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
        password = os.getenv("ADMIN_PASSWORD", "").strip()
        generated = False
        if not password:
            password = secrets.token_urlsafe(12)
            generated = True
        ts = _now()
        conn.execute(
            "INSERT OR IGNORE INTO accounts (username, password_hash, display_name, role, status, "
            "quota_limit, quota_used, note, created_at, updated_at) "
            "VALUES (?, ?, ?, 'admin', 'active', ?, 0, ?, ?, ?)",
            (username, hash_password(password), "系統管理員", UNLIMITED, "系統自動建立", ts, ts),
        )
    if generated:
        logger.warning(
            "已创建管理员账号 %s，随机初始密码：%s —— 请立即登录后台修改，此密码只显示这一次",
            username, password,
        )
    else:
        logger.info("已创建管理员账号 %s（密码来自 ADMIN_PASSWORD）", username)


def _parse_allowed_characters(raw: str | None) -> list[str]:
    """空字符串/无法解析 = 不限制（可用全部角色）。"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except Exception:
        return []


# ── 账号查询 ────────────────────────────────────────────
def _row_to_account(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or "",
        "role": row["role"],
        "status": row["status"],
        "quota_limit": row["quota_limit"],
        "quota_used": row["quota_used"],
        "quota_left": (
            UNLIMITED if row["quota_limit"] == UNLIMITED
            else max(0, row["quota_limit"] - row["quota_used"])
        ),
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login_at": row["last_login_at"] or "",
        "expires_at": row["expires_at"] or "",
        "allowed_characters": _parse_allowed_characters(row["allowed_characters"]),
    }


def character_allowed(account: dict | None, char_id: str) -> bool:
    """账号是否可以使用某个数字人角色。allowed_characters 为空列表 = 不限制。"""
    if not account:
        return True
    allowed = account.get("allowed_characters") or []
    if not allowed:
        return True
    return char_id in allowed


def get_account(username: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE username = ?", (username,)).fetchone()
    return _row_to_account(row) if row else None


def _is_expired(account: dict) -> bool:
    if not account.get("expires_at"):
        return False
    try:
        return datetime.datetime.fromisoformat(account["expires_at"]) < datetime.datetime.now(OPS_TZ)
    except Exception:
        return False


def account_usable(account: dict | None) -> tuple[bool, str]:
    """账号是否可用于登录/对话。返回 (可用, 原因)。"""
    if not account:
        return False, "账号不存在"
    if account["status"] != "active":
        return False, "账号已被停用"
    if _is_expired(account):
        return False, "账号已过期"
    return True, ""


def has_quota(account: dict) -> bool:
    if account["quota_limit"] == UNLIMITED:
        return True
    return account["quota_used"] < account["quota_limit"]


def consume_quota(username: str) -> int:
    """成功完成一轮对话后计数。返回消耗后的已用次数。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE accounts SET quota_used = quota_used + 1, updated_at = ? "
            "WHERE username = ? AND quota_limit != ?",
            (_now(), username, UNLIMITED),
        )
        row = conn.execute("SELECT quota_used FROM accounts WHERE username = ?", (username,)).fetchone()
    return row["quota_used"] if row else 0


def reserve_quota(account: dict) -> tuple[bool, int]:
    """开始一轮对话前先占位，返回 (是否放行, 占位后的已用次数)。

    用一条 SQL 同时做「检查」和「自增」，两者之间没有间隙，因此并发的
    多个连接不会各自读到同一个旧值而集体放行。占位发生在推流之前，
    所以客户端拿到回复后立刻断线也已经计过费。
    不限额度的帐户直接放行，不计数。
    """
    if account["quota_limit"] == UNLIMITED:
        return True, 0
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE accounts SET quota_used = quota_used + 1, updated_at = ? "
            "WHERE username = ? AND quota_limit != ? AND quota_used < quota_limit",
            (_now(), account["username"], UNLIMITED),
        )
        if cur.rowcount == 0:
            return False, account["quota_used"]
        row = conn.execute(
            "SELECT quota_used FROM accounts WHERE username = ?", (account["username"],)
        ).fetchone()
    return True, (row["quota_used"] if row else 0)


# 创作管线用平台共享 Key 时嘅每日限额——自带 Key 嘅调用（用户自己出钱）唔受限
CREATION_DAILY_LIMITS = {
    "image": 30,
    "video": 10,
    "knowledge_search": 20,
    # 智能知识库一次会调用几十次 LLM；输入框 AI 辅助单次很便宜，只防滥用
    "knowledge_agent": 10,
    "field_assist": 200,
}


def reserve_creation_action(username: str, action: str) -> tuple[bool, int]:
    """创作类接口（生图/生视频/网络搜索知识库）按用户+日限额占位。

    只喺调用方冇自带 MiniMax Key、实际烧平台共享 Key 嗰阵先应该调用呢个
    函数（睇 server.py 嘅 used_platform_key）。同 reserve_quota 一样用
    一条 UPDATE 做原子检查+自增，避免并发请求集体放行。
    """
    limit = CREATION_DAILY_LIMITS.get(action)
    if not limit:
        return True, 0
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO creation_usage (username, action, day, count) VALUES (?, ?, ?, 0)",
            (username, action, day),
        )
        cur = conn.execute(
            "UPDATE creation_usage SET count = count + 1 "
            "WHERE username = ? AND action = ? AND day = ? AND count < ?",
            (username, action, day, limit),
        )
        row = conn.execute(
            "SELECT count FROM creation_usage WHERE username = ? AND action = ? AND day = ?",
            (username, action, day),
        ).fetchone()
    used = row["count"] if row else limit
    return cur.rowcount > 0, used


def refund_quota(username: str) -> None:
    """本轮没能产出回复时退回占位，保持「失败不计费」。"""
    with _connect() as conn:
        conn.execute(
            "UPDATE accounts SET quota_used = MAX(quota_used - 1, 0), updated_at = ? "
            "WHERE username = ? AND quota_limit != ?",
            (_now(), username, UNLIMITED),
        )


# ── 会话 ────────────────────────────────────────────────
def create_session(username: str, client_ip: str = "") -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.now(OPS_TZ)
    expires = now + datetime.timedelta(days=SESSION_TTL_DAYS)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, username, created_at, expires_at, client_ip) VALUES (?, ?, ?, ?, ?)",
            (token, username, now.isoformat(), expires.isoformat(), client_ip[:80]),
        )
        conn.execute("UPDATE accounts SET last_login_at = ? WHERE username = ?", (now.isoformat(), username))
    return token, expires.isoformat()


def resolve_session(token: str | None) -> dict | None:
    """令牌 → 账号。令牌过期或账号不可用都返回 None。"""
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token.strip(),)).fetchone()
        if not row:
            return None
        try:
            if datetime.datetime.fromisoformat(row["expires_at"]) < datetime.datetime.now(OPS_TZ):
                conn.execute("DELETE FROM sessions WHERE token = ?", (token.strip(),))
                return None
        except Exception:
            return None
        username = row["username"]
    account = get_account(username)
    ok, _ = account_usable(account)
    return account if ok else None


def destroy_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token.strip(),))


def _drop_sessions_for(username: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))


def purge_expired_sessions() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
        return cur.rowcount or 0


# ── 依赖：鉴权 ──────────────────────────────────────────
SessionHeader = Annotated[str | None, Header(alias="X-Session-Token")]


def require_account(token: str | None) -> dict:
    account = resolve_session(token)
    if not account:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return account


def require_admin(token: str | None) -> dict:
    account = require_account(token)
    if account["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return account


def is_premium(account: dict | None) -> bool:
    return bool(account) and account["role"] in ("premium", "admin")


def premium_credentials(account: dict | None) -> tuple[str, str]:
    """高级帐户的 (api_key, region)。

    未配置 PREMIUM_API_KEY 或非高级帐户时返回 ("", "")，
    调用方据此回退到全局配置。
    """
    if is_premium(account) and PREMIUM_API_KEY:
        return PREMIUM_API_KEY, PREMIUM_REGION
    return "", ""


def server_key_available(account: dict | None) -> bool:
    """服务端是否已为该帐户备好 MiniMax Key，前端因此无需手填。

    只回传布尔值 —— Key 本身永远不下发到浏览器。高级/管理员帐户走
    PREMIUM_API_KEY，未单独配置时回退到平台主 Key。
    """
    return is_premium(account) and bool(PREMIUM_API_KEY or PLATFORM_API_KEY)


def account_features(account: dict) -> dict:
    """角色 → 功能开关。前端据此显示/隐藏入口。"""
    premium = account["role"] in ("premium", "admin")
    return {
        "chat": True,
        "tts": True,
        "unlimited": account["quota_limit"] == UNLIMITED,
        "create_character": premium,
        "all_characters": premium,
        "admin_console": account["role"] == "admin",
        # 前端据此跳过「手填 API Key」，只保留连结稳定性测试。
        "server_key": server_key_available(account),
    }


def session_payload(account: dict) -> dict:
    return {
        "ok": True,
        "username": account["username"],
        "display_name": account["display_name"] or account["username"],
        "role": account["role"],
        "quota_limit": account["quota_limit"],
        "quota_used": account["quota_used"],
        "quota_left": account["quota_left"],
        "expires_at": account["expires_at"],
        "features": account_features(account),
    }


# ── 请求模型 ────────────────────────────────────────────
class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class QuotaRequestBody(BaseModel):
    message: str = Field(default="", max_length=500)


class AccountCreateBody(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=64)
    role: str = Field(default="trial")
    quota_limit: int | None = None
    note: str = Field(default="", max_length=200)
    expires_at: str = Field(default="", max_length=40)
    allowed_characters: list[str] | None = None


class AccountUpdateBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    role: str | None = None
    status: str | None = None
    quota_limit: int | None = None
    quota_used: int | None = None
    note: str | None = Field(default=None, max_length=200)
    expires_at: str | None = Field(default=None, max_length=40)
    allowed_characters: list[str] | None = None


class PasswordBody(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class SelfPasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class QuotaDecisionBody(BaseModel):
    action: str  # approve | reject
    grant: int = 20


router = APIRouter()


def _client_ip(request: Request) -> str:
    for name in ("x-forwarded-for", "x-real-ip"):
        value = request.headers.get(name)
        if value:
            return value.split(",")[0].strip()[:80]
    return request.client.host if request.client else "unknown"


# ── 登录相关 ────────────────────────────────────────────
# 同 ops_control.py 一样嘅滑动窗口锁定：防止暴力破解，亦都防止 PBKDF2（20万次
# 迭代）畀人拿嚟做廉价 CPU DoS —— 命中锁定要喺算密码 hash 之前拦截先有意义。
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_FAILURES = 5
_login_failures: dict[str, collections.deque[float]] = {}
_login_lock = threading.Lock()


def _login_locked(key: str) -> bool:
    now = time.monotonic()
    with _login_lock:
        failures = _login_failures.setdefault(key, collections.deque())
        while failures and now - failures[0] > _LOGIN_WINDOW_SECONDS:
            failures.popleft()
        return len(failures) >= _LOGIN_MAX_FAILURES


def _login_record_failure(key: str) -> None:
    with _login_lock:
        _login_failures.setdefault(key, collections.deque()).append(time.monotonic())


def _login_clear(key: str) -> None:
    with _login_lock:
        _login_failures.pop(key, None)


@router.post("/api/auth/login")
async def login(body: LoginBody, request: Request):
    username = body.username.strip()
    client_ip = _client_ip(request)
    # 用户名+IP 组合做锁定键：单一帐号被扫码撞库时唔会连累同网段其他人登录
    lock_key = f"{username.lower()}|{client_ip}"
    if _login_locked(lock_key):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试")

    account = get_account(username)
    # 恒定代价的密码校验，避免用响应时间区分「用户不存在」和「密码错误」
    stored = ""
    if account:
        with _connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM accounts WHERE username = ?", (username,)
            ).fetchone()
        stored = row["password_hash"] if row else ""
    password_ok = verify_password(body.password, stored) if stored else False

    if not account or not password_ok:
        _login_record_failure(lock_key)
        logger.info("登录失败 user=%s ip=%s", username[:40], client_ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _login_clear(lock_key)

    ok, reason = account_usable(account)
    if not ok:
        raise HTTPException(status_code=403, detail=reason)

    token, expires = create_session(username, client_ip)
    logger.info("登录成功 user=%s role=%s ip=%s", username, account["role"], client_ip)
    payload = session_payload(get_account(username))
    payload["token"] = token
    payload["token_expires_at"] = expires
    return payload


@router.post("/api/auth/logout")
async def logout(x_session_token: SessionHeader = None):
    destroy_session(x_session_token)
    return {"ok": True}


@router.get("/api/auth/session")
async def session_info(x_session_token: SessionHeader = None):
    account = resolve_session(x_session_token)
    if not account:
        return {"ok": False, "authenticated": False}
    payload = session_payload(account)
    payload["authenticated"] = True
    return payload


@router.post("/api/auth/password")
async def change_own_password(body: SelfPasswordBody, x_session_token: SessionHeader = None):
    account = require_account(x_session_token)
    with _connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM accounts WHERE username = ?", (account["username"],)
        ).fetchone()
    if not row or not verify_password(body.old_password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="原密码不正确")
    with _connect() as conn:
        conn.execute(
            "UPDATE accounts SET password_hash = ?, updated_at = ? WHERE username = ?",
            (hash_password(body.new_password), _now(), account["username"]),
        )
    _drop_sessions_for(account["username"])
    return {"ok": True, "message": "密码已修改，请重新登录"}


# ── 额度申请 ────────────────────────────────────────────
@router.post("/api/quota/request")
async def request_more_quota(body: QuotaRequestBody, x_session_token: SessionHeader = None):
    account = require_account(x_session_token)
    with _connect() as conn:
        pending = conn.execute(
            "SELECT id FROM quota_requests WHERE username = ? AND status = 'pending'",
            (account["username"],),
        ).fetchone()
        if pending:
            return {"ok": True, "already_pending": True, "message": "已有一条待处理的申请，请等待管理员审核"}
        conn.execute(
            "INSERT INTO quota_requests (username, requested_at, message, status) VALUES (?, ?, ?, 'pending')",
            (account["username"], _now(), body.message.strip()[:500]),
        )
    logger.info("额度申请 user=%s", account["username"])
    return {"ok": True, "already_pending": False, "message": "申请已提交，管理员审核后额度会立即到账"}


@router.get("/api/quota/request")
async def my_quota_request(x_session_token: SessionHeader = None):
    account = require_account(x_session_token)
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM quota_requests WHERE username = ? ORDER BY id DESC LIMIT 1",
            (account["username"],),
        ).fetchone()
    if not row:
        return {"ok": True, "request": None}
    return {
        "ok": True,
        "request": {
            "id": row["id"],
            "status": row["status"],
            "requested_at": row["requested_at"],
            "handled_at": row["handled_at"] or "",
            "granted": row["granted"] or 0,
        },
    }


# ── 管理员后台 ──────────────────────────────────────────
@router.get("/api/admin/accounts")
async def admin_list_accounts(
    q: str = "", role: str = "", status: str = "", x_session_token: SessionHeader = None
):
    require_admin(x_session_token)
    sql = "SELECT * FROM accounts WHERE 1=1"
    args: list = []
    if q:
        sql += " AND (username LIKE ? OR display_name LIKE ? OR note LIKE ?)"
        args += [f"%{q}%"] * 3
    if role in ROLES:
        sql += " AND role = ?"
        args.append(role)
    if status in ("active", "disabled"):
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'premium' THEN 1 ELSE 2 END, id DESC"
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {"ok": True, "total": len(rows), "accounts": [_row_to_account(r) for r in rows]}


@router.post("/api/admin/accounts")
async def admin_create_account(body: AccountCreateBody, x_session_token: SessionHeader = None):
    require_admin(x_session_token)
    username = body.username.strip()
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"role 必须是 {', '.join(ROLES)} 之一")
    if get_account(username):
        raise HTTPException(status_code=409, detail="用户名已存在")

    quota = body.quota_limit
    if quota is None:
        quota = TRIAL_QUOTA_DEFAULT if body.role == "trial" else UNLIMITED
    ts = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO accounts (username, password_hash, display_name, role, status, quota_limit, "
            "quota_used, note, created_at, updated_at, expires_at, allowed_characters) "
            "VALUES (?, ?, ?, ?, 'active', ?, 0, ?, ?, ?, ?, ?)",
            (username, hash_password(body.password), body.display_name.strip(), body.role,
             quota, body.note.strip(), ts, ts, body.expires_at.strip(),
             json.dumps(body.allowed_characters) if body.allowed_characters else ""),
        )
    logger.info("管理员创建账号 user=%s role=%s quota=%s", username, body.role, quota)
    return {"ok": True, "account": get_account(username)}


@router.patch("/api/admin/accounts/{username}")
async def admin_update_account(
    username: str, body: AccountUpdateBody, x_session_token: SessionHeader = None
):
    admin = require_admin(x_session_token)
    account = get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    updates: dict = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name.strip()
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(status_code=400, detail=f"role 必须是 {', '.join(ROLES)} 之一")
        if account["role"] == "admin" and body.role != "admin" and _last_admin(username):
            raise HTTPException(status_code=400, detail="不能降级唯一的管理员账号")
        updates["role"] = body.role
        # 升级为高级用户时自动放开额度，除非同一请求里显式指定
        if body.role in ("premium", "admin") and body.quota_limit is None:
            updates["quota_limit"] = UNLIMITED
    if body.status is not None:
        if body.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="status 必须是 active 或 disabled")
        if body.status == "disabled" and account["role"] == "admin" and _last_admin(username):
            raise HTTPException(status_code=400, detail="不能停用唯一的管理员账号")
        updates["status"] = body.status
    if body.quota_limit is not None:
        updates["quota_limit"] = body.quota_limit
    if body.quota_used is not None:
        updates["quota_used"] = max(0, body.quota_used)
    if body.note is not None:
        updates["note"] = body.note.strip()
    if body.expires_at is not None:
        updates["expires_at"] = body.expires_at.strip()
    if body.allowed_characters is not None:
        updates["allowed_characters"] = json.dumps(body.allowed_characters) if body.allowed_characters else ""

    if not updates:
        return {"ok": True, "account": account}

    updates["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(f"UPDATE accounts SET {sets} WHERE username = ?", [*updates.values(), username])

    # 停用或降级后立即踢掉在线会话
    if updates.get("status") == "disabled" or "role" in updates:
        _drop_sessions_for(username)
    logger.info("管理员 %s 修改账号 %s: %s", admin["username"], username, list(updates))
    return {"ok": True, "account": get_account(username)}


def _last_admin(username: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM accounts WHERE role = 'admin' AND status = 'active' AND username != ?",
            (username,),
        ).fetchone()
    return row["c"] == 0


@router.post("/api/admin/accounts/{username}/password")
async def admin_reset_password(
    username: str, body: PasswordBody, x_session_token: SessionHeader = None
):
    require_admin(x_session_token)
    if not get_account(username):
        raise HTTPException(status_code=404, detail="账号不存在")
    with _connect() as conn:
        conn.execute(
            "UPDATE accounts SET password_hash = ?, updated_at = ? WHERE username = ?",
            (hash_password(body.password), _now(), username),
        )
    _drop_sessions_for(username)
    logger.info("管理员重置密码 user=%s", username)
    return {"ok": True, "message": "密码已重置，该账号需要重新登录"}


@router.post("/api/admin/accounts/{username}/quota/reset")
async def admin_reset_quota(username: str, x_session_token: SessionHeader = None):
    require_admin(x_session_token)
    if not get_account(username):
        raise HTTPException(status_code=404, detail="账号不存在")
    with _connect() as conn:
        conn.execute(
            "UPDATE accounts SET quota_used = 0, updated_at = ? WHERE username = ?", (_now(), username)
        )
    return {"ok": True, "account": get_account(username)}


@router.delete("/api/admin/accounts/{username}")
async def admin_delete_account(username: str, x_session_token: SessionHeader = None):
    admin = require_admin(x_session_token)
    account = get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account["role"] == "admin" and _last_admin(username):
        raise HTTPException(status_code=400, detail="不能删除唯一的管理员账号")
    if username == admin["username"]:
        raise HTTPException(status_code=400, detail="不能删除自己当前登录的账号")
    with _connect() as conn:
        conn.execute("DELETE FROM accounts WHERE username = ?", (username,))
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
    logger.info("管理员 %s 删除账号 %s", admin["username"], username)
    return {"ok": True}


@router.get("/api/admin/quota-requests")
async def admin_quota_requests(status: str = "pending", x_session_token: SessionHeader = None):
    require_admin(x_session_token)
    sql = "SELECT * FROM quota_requests"
    args: list = []
    if status in ("pending", "approved", "rejected"):
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT 200"
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {
        "ok": True,
        "requests": [
            {
                "id": r["id"],
                "username": r["username"],
                "requested_at": r["requested_at"],
                "message": r["message"] or "",
                "status": r["status"],
                "handled_at": r["handled_at"] or "",
                "handled_by": r["handled_by"] or "",
                "granted": r["granted"] or 0,
            }
            for r in rows
        ],
    }


@router.post("/api/admin/quota-requests/{req_id}")
async def admin_handle_quota_request(
    req_id: int, body: QuotaDecisionBody, x_session_token: SessionHeader = None
):
    admin = require_admin(x_session_token)
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须是 approve 或 reject")
    with _connect() as conn:
        row = conn.execute("SELECT * FROM quota_requests WHERE id = ?", (req_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="申请不存在")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="该申请已处理过")
        granted = 0
        if body.action == "approve":
            granted = max(1, body.grant)
            conn.execute(
                "UPDATE accounts SET quota_limit = quota_limit + ?, updated_at = ? "
                "WHERE username = ? AND quota_limit != ?",
                (granted, _now(), row["username"], UNLIMITED),
            )
        conn.execute(
            "UPDATE quota_requests SET status = ?, handled_at = ?, handled_by = ?, granted = ? WHERE id = ?",
            ("approved" if body.action == "approve" else "rejected", _now(), admin["username"], granted, req_id),
        )
    logger.info("管理员 %s %s 了额度申请 #%s", admin["username"], body.action, req_id)
    return {"ok": True, "granted": granted, "account": get_account(row["username"])}


@router.get("/api/admin/stats")
async def admin_stats(x_session_token: SessionHeader = None):
    require_admin(x_session_token)
    with _connect() as conn:
        by_role = {
            r["role"]: r["c"]
            for r in conn.execute("SELECT role, COUNT(*) AS c FROM accounts GROUP BY role")
        }
        total = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
        disabled = conn.execute(
            "SELECT COUNT(*) AS c FROM accounts WHERE status = 'disabled'"
        ).fetchone()["c"]
        exhausted = conn.execute(
            "SELECT COUNT(*) AS c FROM accounts WHERE quota_limit != ? AND quota_used >= quota_limit",
            (UNLIMITED,),
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM quota_requests WHERE status = 'pending'"
        ).fetchone()["c"]
        active_sessions = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE expires_at > ?", (_now(),)
        ).fetchone()["c"]
        try:
            convo_by_user = [
                {"username": r["username"] or "(未登录)", "count": r["c"]}
                for r in conn.execute(
                    "SELECT username, COUNT(*) AS c FROM conversations GROUP BY username ORDER BY c DESC LIMIT 10"
                )
            ]
        except sqlite3.OperationalError:
            convo_by_user = []
    return {
        "ok": True,
        "total": total,
        "by_role": {"trial": by_role.get("trial", 0), "premium": by_role.get("premium", 0),
                    "admin": by_role.get("admin", 0)},
        "disabled": disabled,
        "quota_exhausted": exhausted,
        "pending_requests": pending,
        "active_sessions": active_sessions,
        "top_users": convo_by_user,
        "premium_key_configured": bool(PREMIUM_API_KEY),
        "premium_region": PREMIUM_REGION or "(跟随全局)",
        "trial_quota_default": TRIAL_QUOTA_DEFAULT,
    }
