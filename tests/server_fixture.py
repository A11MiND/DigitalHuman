"""Import server.py against a throwaway database and user-character folder.

server.py opens the accounts DB and scans character folders at import time, so
the patching has to happen before the first `import server`. Every test module
that needs the app imports it from here.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

TMP = Path(tempfile.mkdtemp(prefix="dh-tests-"))

import accounts  # noqa: E402

accounts.DB_PATH = TMP / "test.db"

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

USER_DIR = TMP / "user-characters"
USER_DIR.mkdir()
server.USER_CHARACTERS_DIR = USER_DIR
server.GENERATED_DIR = TMP / "generated"
server.CREATE_JOBS_DIR = server.GENERATED_DIR / "jobs"
server.AGENT_TASKS_DIR = server.GENERATED_DIR / "agent"
server.CREATE_JOBS_DIR.mkdir(parents=True)
# 静态挂载在 import 时已经指向真实目录，改指到临时目录
for route in server.app.routes:
    if getattr(route, "name", "") == "generated":
        route.app = route._base_app = server.MediaStaticFiles(directory=str(server.GENERATED_DIR))
    elif getattr(route, "name", "") == "user-characters":
        route.app = route._base_app = server.MediaStaticFiles(directory=str(USER_DIR))
server.CharacterManager.SOURCES = (
    (server.SYSTEM_CHARACTERS_DIR, "/characters"),
    (USER_DIR, "/user-characters"),
)
server.char_mgr.reload()

client = TestClient(server.app)


def make_account(username: str, role: str = "trial", allowed: list[str] | None = None) -> str:
    """Create (or replace) an account and return a session token for it."""
    with accounts._connect() as conn:
        conn.execute("DELETE FROM accounts WHERE username = ?", (username,))
        ts = accounts._now()
        conn.execute(
            "INSERT INTO accounts (username, password_hash, role, status, quota_limit, quota_used, "
            "created_at, updated_at, allowed_characters) VALUES (?, 'x', ?, 'active', -1, 0, ?, ?, ?)",
            (username, role, ts, ts, json.dumps(allowed) if allowed else ""),
        )
    token, _ = accounts.create_session(username)
    return token


def make_user_character(char_id: str, owner: str, visibility: str = "private") -> Path:
    d = USER_DIR / char_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "character.json").write_text(json.dumps({
        "id": char_id, "name": char_id, "owner": owner, "visibility": visibility,
        "system_prompt": "secret prompt", "knowledge_file": "knowledge.md",
    }), encoding="utf-8")
    (d / "knowledge.md").write_text("secret knowledge", encoding="utf-8")
    (d / "portrait.jpg").write_bytes(b"\xff\xd8\xff")
    server.char_mgr.reload()
    return d


def cleanup() -> None:
    shutil.rmtree(TMP, ignore_errors=True)
