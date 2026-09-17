"""Independent, authenticated control plane for the DigitalHuman main service.

This process must run separately from ``digitalhuman.service`` so an operator can
start the main site again after stopping it.  Only fixed, allow-listed actions
are passed to a root-owned helper; no user-controlled command is executed.
"""

from __future__ import annotations

import asyncio
import collections
import datetime
import hmac
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel


APP_DIR = Path(__file__).resolve().parent
CONTROL_PAGE = APP_DIR / "static" / "control.html"
AUDIT_LOG = APP_DIR / "logs" / "ops-control.log"
MAIN_SERVICE = "digitalhuman.service"
NGINX_SERVICE = "nginx.service"
MAIN_HEALTH_URL = "http://127.0.0.1:8080/health"
CONTROL_HELPER = os.getenv(
    "DIGITALHUMAN_CONTROL_HELPER",
    "/usr/local/sbin/digitalhuman-service-control",
)
OPS_TZ = datetime.timezone(datetime.timedelta(hours=8), name="UTC+8")


def _load_operator_codes() -> dict[str, str]:
    codes: dict[str, str] = {}
    for item in os.getenv("OPS_CONTROL_CODES", "").split(","):
        if ":" not in item:
            continue
        name, code = item.split(":", 1)
        if name.strip() and code.strip():
            codes[code.strip()] = name.strip()
    return codes


# 獨立於主站 USER_CODES（聊天邀請碼）——那組碼是給訪客/學生用嚟開通對話，
# 之前 ops_control 誤用同一組碼做服務控制鑒權，等於邀請碼洩露就能
# start/stop/restart 生產服務。OPS_CONTROL_CODES 必須另外喺
# /etc/systemd/system/digitalhuman.env 配置，兩者不可混用。
OPERATOR_CODES = _load_operator_codes()
UserCodeHeader = Annotated[str | None, Header(alias="X-User-Code")]
_AUTH_WINDOW_SECONDS = 300
_AUTH_MAX_FAILURES = 5
_auth_failures: dict[str, collections.deque[float]] = {}
_auth_lock = threading.Lock()

app = FastAPI(
    title="DigitalHuman Operations Control",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class ControlAction(BaseModel):
    action: Literal["start", "stop", "restart"]


def _require_operator(code: str | None, request: Request) -> str:
    if not OPERATOR_CODES:
        raise HTTPException(status_code=503, detail="ops_code_not_configured")
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _auth_lock:
        failures = _auth_failures.setdefault(client_ip, collections.deque())
        while failures and now - failures[0] > _AUTH_WINDOW_SECONDS:
            failures.popleft()
        if len(failures) >= _AUTH_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="too_many_auth_attempts")
    candidate = (code or "").strip()
    for saved_code, username in OPERATOR_CODES.items():
        if hmac.compare_digest(candidate, saved_code):
            with _auth_lock:
                _auth_failures.pop(client_ip, None)
            return username
    with _auth_lock:
        failures.append(now)
    raise HTTPException(status_code=401, detail="invalid_ops_code")


def _run(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _service_details(service: str) -> dict:
    result = _run(
        [
            "/usr/bin/systemctl",
            "show",
            service,
            "--property=ActiveState",
            "--property=SubState",
            "--property=MainPID",
            "--property=ActiveEnterTimestamp",
            "--property=UnitFileState",
            "--no-pager",
        ]
    )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return {
        "active": values.get("ActiveState") == "active",
        "active_state": values.get("ActiveState", "unknown"),
        "sub_state": values.get("SubState", "unknown"),
        "main_pid": int(values.get("MainPID", "0") or 0),
        "started_at": values.get("ActiveEnterTimestamp", ""),
        "enabled": values.get("UnitFileState") == "enabled",
        "query_ok": result.returncode == 0,
    }


async def _main_health() -> dict:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(MAIN_HEALTH_URL, headers={"Accept": "application/json"})
        elapsed = round((time.perf_counter() - started) * 1000)
        payload = response.json() if "application/json" in response.headers.get("content-type", "") else {}
        return {
            "reachable": response.status_code == 200,
            "status_code": response.status_code,
            "response_ms": elapsed,
            "details": payload if response.status_code == 200 else {},
        }
    except Exception:
        return {
            "reachable": False,
            "status_code": None,
            "response_ms": round((time.perf_counter() - started) * 1000),
            "details": {},
        }


async def _status_payload() -> dict:
    service = _service_details(MAIN_SERVICE)
    nginx = _service_details(NGINX_SERVICE)
    health = await _main_health()
    overall = "healthy" if service["active"] and health["reachable"] and nginx["active"] else "offline"
    if service["active"] and not health["reachable"]:
        overall = "degraded"
    return {
        "ok": True,
        "overall": overall,
        "checked_at": datetime.datetime.now(OPS_TZ).isoformat(),
        "service": service,
        "nginx": nginx,
        "health": health,
    }


def _audit(request: Request, operator: str, action: str, success: bool, message: str) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.datetime.now(OPS_TZ).isoformat(),
        "operator": operator,
        "action": action,
        "success": success,
        "client_ip": request.client.host if request.client else "unknown",
        "message": message[:240],
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


@app.get("/control", include_in_schema=False)
async def control_page():
    return FileResponse(CONTROL_PAGE, media_type="text/html; charset=utf-8")


@app.get("/control/", include_in_schema=False)
async def control_page_slash():
    return FileResponse(CONTROL_PAGE, media_type="text/html; charset=utf-8")


@app.get("/api/control/ping")
async def control_ping():
    """Public liveness only; it does not reveal the main-site state."""
    return {"ok": True, "service": "digitalhuman-control"}


@app.post("/api/control/verify")
async def verify_code(request: Request, x_user_code: UserCodeHeader = None):
    operator = _require_operator(x_user_code, request)
    return {"ok": True, "operator": operator}


@app.get("/api/control/status")
async def control_status(request: Request, x_user_code: UserCodeHeader = None):
    operator = _require_operator(x_user_code, request)
    return {**await _status_payload(), "operator": operator}


@app.post("/api/control/action")
async def control_action(
    body: ControlAction,
    request: Request,
    x_user_code: UserCodeHeader = None,
):
    operator = _require_operator(x_user_code, request)
    before = await _status_payload()
    result = _run(
        ["/usr/bin/sudo", "-n", CONTROL_HELPER, body.action],
        timeout=30,
    )
    success = result.returncode == 0
    message = (result.stdout or result.stderr or "systemctl completed").strip()
    _audit(request, operator, body.action, success, message)
    if not success:
        raise HTTPException(status_code=500, detail="control_action_failed")

    if body.action in {"start", "restart"}:
        for _ in range(12):
            await asyncio.sleep(0.5)
            after = await _status_payload()
            if after["health"]["reachable"]:
                break
        else:
            after = await _status_payload()
    else:
        after = await _status_payload()

    return {
        "ok": True,
        "action": body.action,
        "operator": operator,
        "before": before,
        "status": after,
    }
