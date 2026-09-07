import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["USER_CODES"] = "operator:test-code"

from fastapi.testclient import TestClient

import ops_control


class OpsControlTests(unittest.TestCase):
    def setUp(self):
        ops_control._auth_failures.clear()
        self.client = TestClient(ops_control.app)
        self.headers = {"X-User-Code": "test-code"}

    def test_status_requires_ops_code(self):
        response = self.client.get("/api/control/status")
        self.assertEqual(response.status_code, 401)

    def test_verify_rejects_wrong_code(self):
        response = self.client.post(
            "/api/control/verify",
            headers={"X-User-Code": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_repeated_wrong_codes_are_rate_limited(self):
        for _ in range(ops_control._AUTH_MAX_FAILURES):
            response = self.client.post(
                "/api/control/verify",
                headers={"X-User-Code": "wrong"},
            )
            self.assertEqual(response.status_code, 401)
        response = self.client.post(
            "/api/control/verify",
            headers={"X-User-Code": "wrong"},
        )
        self.assertEqual(response.status_code, 429)

    def test_verify_accepts_valid_code(self):
        response = self.client.post("/api/control/verify", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["operator"], "operator")

    def test_action_is_allow_listed(self):
        response = self.client.post(
            "/api/control/action",
            headers=self.headers,
            json={"action": "reboot"},
        )
        self.assertEqual(response.status_code, 422)

    def test_status_returns_sanitized_health(self):
        status = {
            "ok": True,
            "overall": "healthy",
            "checked_at": "2026-07-13T12:00:00+08:00",
            "service": {"active": True},
            "nginx": {"active": True},
            "health": {"reachable": True},
        }
        with patch.object(ops_control, "_status_payload", new=AsyncMock(return_value=status)):
            response = self.client.get("/api/control/status", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["overall"], "healthy")
        self.assertNotIn("test-code", response.text)


if __name__ == "__main__":
    unittest.main()
