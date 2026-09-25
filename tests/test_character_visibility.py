import unittest

from server_fixture import client, make_account, make_user_character, server

CUSTOMER = "you-beauty-advisor"   # one of the four private customer characters
SYSTEM = "qin-shihuang"


def _ids(token=None):
    headers = {"X-Session-Token": token} if token else {}
    res = client.get("/api/characters", headers=headers)
    return {c["id"]: c for c in res.json()}


class CharacterVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alice = make_account("alice", "premium")
        cls.bob = make_account("bob", "premium")
        cls.plain = make_account("plain", "trial")
        cls.customer = make_account("beauty-client", "trial", allowed=[CUSTOMER])
        cls.admin = make_account("root", "admin")
        make_user_character("alice-char-abc123", owner="alice")

    def test_existing_characters_default_to_system(self):
        for char_id in (SYSTEM, "elizabeth-i", "maryknoll-teacher", "character-49fd372d"):
            self.assertEqual(server._character_visibility(server.char_mgr.get(char_id)), "system", char_id)
        for char_id in ("you-beauty-advisor", "you-beauty-newclient", "munich-airport", "vienna-airport"):
            self.assertEqual(server._character_visibility(server.char_mgr.get(char_id)), "private", char_id)

    def test_lobby_list_matrix(self):
        anon = _ids()
        self.assertIn(SYSTEM, anon)
        self.assertNotIn(CUSTOMER, anon)
        self.assertNotIn("alice-char-abc123", anon)

        plain = _ids(self.plain)
        self.assertIn(SYSTEM, plain)
        self.assertNotIn(CUSTOMER, plain)

        # 白名单对系统角色是「限制」，对私有角色是「授权」
        customer = _ids(self.customer)
        self.assertEqual(set(customer), {CUSTOMER})

        alice = _ids(self.alice)
        self.assertTrue(alice["alice-char-abc123"]["owned"])
        self.assertFalse(alice[SYSTEM]["owned"])
        self.assertNotIn("alice-char-abc123", _ids(self.bob))

        admin = _ids(self.admin)
        self.assertIn(CUSTOMER, admin)
        self.assertIn("alice-char-abc123", admin)

    def test_public_user_character_visible_to_all_but_export_owner_only(self):
        make_user_character("alice-public-def456", owner="alice", visibility="public")
        self.assertIn("alice-public-def456", _ids())
        self.assertIn("alice-public-def456", _ids(self.bob))
        self.assertNotIn("alice-public-def456", _ids(self.customer))  # 白名单账号仍只看名单内
        res = client.get("/api/characters/alice-public-def456", headers={"X-Session-Token": self.bob})
        self.assertEqual(res.status_code, 200)
        res = client.get("/api/characters/alice-public-def456/export", headers={"X-Session-Token": self.bob})
        self.assertEqual(res.status_code, 404)
        res = client.get("/api/characters/alice-public-def456/export", headers={"X-Session-Token": self.alice})
        self.assertEqual(res.status_code, 200)

    def test_list_does_not_leak_owner(self):
        for c in _ids(self.alice).values():
            self.assertNotIn("owner", c)
            self.assertNotIn("created_by", c)

    def test_detail_hides_invisible_private_characters(self):
        res = client.get("/api/characters/alice-char-abc123", headers={"X-Session-Token": self.bob})
        self.assertEqual(res.status_code, 404)
        res = client.get("/api/characters/alice-char-abc123", headers={"X-Session-Token": self.alice})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["icon"].startswith("/user-characters/alice-char-abc123/"))
        self.assertEqual(client.get(f"/api/characters/{CUSTOMER}").status_code, 404)

    def test_whitelisted_account_still_blocked_from_other_system_characters(self):
        res = client.get(f"/api/characters/{SYSTEM}", headers={"X-Session-Token": self.customer})
        self.assertEqual(res.status_code, 403)

    def test_export_requires_visibility(self):
        res = client.get("/api/characters/alice-char-abc123/export", headers={"X-Session-Token": self.bob})
        self.assertEqual(res.status_code, 404)
        res = client.get(f"/api/characters/{CUSTOMER}/export", headers={"X-Session-Token": self.alice})
        self.assertEqual(res.status_code, 404)
        res = client.get("/api/characters/alice-char-abc123/export", headers={"X-Session-Token": self.alice})
        self.assertEqual(res.status_code, 200)

    def test_static_mount_serves_media_only(self):
        self.assertEqual(client.get(f"/characters/{CUSTOMER}/character.json").status_code, 404)
        self.assertEqual(client.get("/characters/maryknoll-teacher/knowledge.md").status_code, 404)
        res = client.get(f"/characters/{SYSTEM}/idle.mp4", headers={"Range": "bytes=0-99"})
        self.assertEqual(res.status_code, 206)

    def test_health_lists_only_system_characters(self):
        ids = client.get("/health").json()["characters"]
        self.assertIn(SYSTEM, ids)
        self.assertNotIn(CUSTOMER, ids)
        self.assertNotIn("alice-char-abc123", ids)

    def test_new_character_ids_are_unique_and_slugged(self):
        a, b = server._new_character_id("Li Bai"), server._new_character_id("Li Bai")
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^li-bai-[0-9a-f]{6}$")
        self.assertRegex(server._new_character_id("李白"), r"^character-[0-9a-f]{6}$")


if __name__ == "__main__":
    unittest.main()
