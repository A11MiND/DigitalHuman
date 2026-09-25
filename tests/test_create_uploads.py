import asyncio
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from server_fixture import TMP, USER_DIR, client, make_account, server

import knowledge_agent

MEDIA = TMP / "media"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _image(name, w, h):
    path = MEDIA / name
    _ffmpeg("-f", "lavfi", "-i", f"color=c=orange:s={w}x{h}", "-frames:v", "1", str(path))
    return path


def _video(name, seconds, size="640x480"):
    path = MEDIA / name
    _ffmpeg("-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=24", "-pix_fmt", "yuv420p", str(path))
    return path


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class UploadAndFinalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MEDIA.mkdir(exist_ok=True)
        cls.token = make_account("creator", "premium")
        cls.h = {"X-Session-Token": cls.token}
        cls.portrait = _image("portrait.png", 600, 800)
        cls.tiny = _image("tiny.jpg", 200, 200)
        cls.wide = _image("wide.jpg", 1600, 300)
        cls.idle = _video("idle.mp4", 3, "1280x720")
        cls.talk = _video("talk.mov", 5)
        cls.long = _video("long.mp4", 25)

    def _upload_image(self, path, ack=True, job_id=""):
        with path.open("rb") as fh:
            return client.post("/api/create/images/upload", headers=self.h,
                               data={"rights_ack": "true" if ack else "false", "job_id": job_id},
                               files={"file": (path.name, fh)})

    def _upload_video(self, path, kind, job_id, ack=True):
        with path.open("rb") as fh:
            return client.post("/api/create/videos/upload", headers=self.h,
                               data={"kind": kind, "job_id": job_id, "rights_ack": "true" if ack else "false"},
                               files={"file": (path.name, fh)})

    def test_image_upload_validation(self):
        self.assertEqual(self._upload_image(self.portrait, ack=False).status_code, 400)
        self.assertEqual(self._upload_image(self.tiny).status_code, 400)
        self.assertEqual(self._upload_image(self.wide).status_code, 400)
        res = client.post("/api/create/images/upload", headers=self.h, data={"rights_ack": "true"},
                          files={"file": ("x.gif", b"GIF89a")})
        self.assertEqual(res.status_code, 400)

    def test_video_upload_validation(self):
        job_id = self._upload_image(self.portrait).json()["job_id"]
        self.assertEqual(self._upload_video(self.idle, "idle", job_id, ack=False).status_code, 400)
        self.assertEqual(self._upload_video(self.long, "idle", job_id).status_code, 400)
        self.assertEqual(self._upload_video(self.idle, "other", job_id).status_code, 400)

    def test_full_upload_flow_creates_private_character(self):
        res = self._upload_image(self.portrait)
        self.assertEqual(res.status_code, 200, res.text)
        job_id, image = res.json()["job_id"], res.json()["image"]
        self.assertEqual(image["source"], "upload")
        self.assertEqual(client.get(image["url"]).status_code, 200)
        # job.json 里有 Prompt，不能经 /generated 下载
        self.assertEqual(client.get(f"/generated/jobs/{job_id}/job.json").status_code, 404)

        for path, kind in ((self.idle, "idle"), (self.talk, "talk")):
            res = self._upload_video(path, kind, job_id)
            self.assertEqual(res.status_code, 200, res.text)
        info = server._ffprobe(server._job_dir(job_id) / "videos" / "idle.mp4")
        self.assertEqual(info["width"], 720)

        res = client.post("/api/create/finalize", headers=self.h, json={
            "job_id": job_id, "image_id": image["id"], "name": "測試角色", "name_en": "Test Hero",
            "system_prompt": "you are a test", "knowledge_text": "事实一\n事实二",
        })
        self.assertEqual(res.status_code, 200, res.text)
        char_id = res.json()["id"]
        self.assertRegex(char_id, r"^test-hero-[0-9a-f]{6}$")
        cfg = json.loads((USER_DIR / char_id / "character.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["owner"], "creator")
        self.assertEqual(cfg["visibility"], "private")
        self.assertEqual(cfg["knowledge_file"], "knowledge.md")
        self.assertEqual(cfg["image_rights_ack"]["image"]["by"], "creator")
        self.assertIn("idle", cfg["image_rights_ack"]["videos"])
        self.assertIn("事实一", server.char_mgr.get_system_prompt(char_id))
        self.assertFalse(server._job_dir(job_id).exists())

    def test_finalize_without_image_uses_idle_frame(self):
        job_id = ""
        for path, kind in ((self.idle, "idle"), (self.talk, "talk")):
            res = self._upload_video(path, kind, job_id)
            self.assertEqual(res.status_code, 200, res.text)
            job_id = res.json()["job_id"]
        res = client.post("/api/create/finalize", headers=self.h, json={
            "job_id": job_id, "name": "無圖角色", "system_prompt": "p",
        })
        self.assertEqual(res.status_code, 200, res.text)
        char_dir = USER_DIR / res.json()["id"]
        self.assertTrue((char_dir / "portrait.jpg").stat().st_size > 0)
        self.assertNotIn("knowledge_file", json.loads((char_dir / "character.json").read_text()))

    def test_finalize_requires_both_videos(self):
        job_id = self._upload_image(self.portrait).json()["job_id"]
        self._upload_video(self.idle, "idle", job_id)
        res = client.post("/api/create/finalize", headers=self.h, json={"job_id": job_id, "name": "x", "system_prompt": "p"})
        self.assertEqual(res.status_code, 400)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
class RegenerationTests(unittest.TestCase):
    """平台生成的图 / 视频可以带反馈重新生成；MiniMax 调用全部 mock，不花钱。"""

    @classmethod
    def setUpClass(cls):
        MEDIA.mkdir(exist_ok=True)
        cls.h = {"X-Session-Token": make_account("regen-user", "premium"), "X-MiniMax-API-Key": "test-key"}
        cls.portrait = _image("regen.png", 600, 800)
        cls.sample = _video("regen-sample.mp4", 3)
        cls.jpeg_b64 = __import__("base64").b64encode(cls.portrait.with_suffix(".jpg").read_bytes()
                                                       if cls.portrait.with_suffix(".jpg").exists()
                                                       else _image("regen.jpg", 600, 800).read_bytes()).decode()

    def _job_with_image(self):
        with self.portrait.open("rb") as fh:
            res = client.post("/api/create/images/upload", headers=self.h, data={"rights_ack": "true"},
                              files={"file": ("regen.png", fh)})
        return res.json()["job_id"], res.json()["image"]["id"]

    def _generate(self, job_id, image_id, **extra):
        prompts = []

        async def fake_generate_video(self_, prompt, first_frame_url, download_path, duration):
            prompts.append((prompt, first_frame_url))
            download_path.parent.mkdir(parents=True, exist_ok=True)  # 真实下载函数也会先建目录
            shutil.copy(MEDIA / "regen-sample.mp4", download_path)
            return {}

        with patch.object(server.MiniMaxProvider, "generate_video", fake_generate_video):
            res = client.post("/api/create/videos", headers=self.h, json={
                "job_id": job_id, "image_id": image_id, "character_name": "測試", "image_prompt": "一位老師", **extra})
        return res, prompts

    def test_feedback_reaches_prompts_and_data_url_used_for_uploaded_image(self):
        job_id, image_id = self._job_with_image()
        res, prompts = self._generate(job_id, image_id, feedback="動作幅度小一點")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(prompts), 2)
        self.assertTrue(all("動作幅度小一點" in p for p, _ in prompts))
        self.assertTrue(all(url.startswith("data:image/jpeg;base64,") for _, url in prompts))
        self.assertEqual(set(res.json()["videos"]), {"idle", "talk"})
        self.assertEqual(res.json()["videos_image_id"], image_id)

    def test_regenerate_single_clip_only_touches_that_clip(self):
        job_id, image_id = self._job_with_image()
        self._generate(job_id, image_id)
        idle = server._job_dir(job_id) / "videos" / "idle.mp4"
        before = idle.stat().st_mtime_ns
        res, prompts = self._generate(job_id, image_id, which="talk", feedback="嘴型自然一點")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(prompts), 1)
        self.assertIn("嘴型自然一點", prompts[0][0])
        self.assertEqual(idle.stat().st_mtime_ns, before)
        self.assertEqual(set(res.json()["videos"]), {"idle", "talk"})

    def test_single_clip_regeneration_rejected_for_a_different_image(self):
        job_id, image_id = self._job_with_image()
        self._generate(job_id, image_id)
        with self.portrait.open("rb") as fh:
            other = client.post("/api/create/images/upload", headers=self.h,
                                data={"rights_ack": "true", "job_id": job_id},
                                files={"file": ("regen.png", fh)}).json()["image"]["id"]
        res, prompts = self._generate(job_id, other, which="idle")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(prompts, [])
        res, _ = self._generate(job_id, other, which="both")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["videos_image_id"], other)

    def test_bad_which_and_single_clip_without_prior_videos_rejected(self):
        job_id, image_id = self._job_with_image()
        self.assertEqual(self._generate(job_id, image_id, which="both2")[0].status_code, 400)
        self.assertEqual(self._generate(job_id, image_id, which="talk")[0].status_code, 400)

    def test_failed_reencode_keeps_previous_clip(self):
        job_id, image_id = self._job_with_image()
        self._generate(job_id, image_id)
        talk = server._job_dir(job_id) / "videos" / "talk.mp4"
        good = talk.read_bytes()

        async def broken_generate_video(self_, prompt, first_frame_url, download_path, duration):
            download_path.parent.mkdir(parents=True, exist_ok=True)
            download_path.write_bytes(b"not a video")

        with patch.object(server.MiniMaxProvider, "generate_video", broken_generate_video):
            res = client.post("/api/create/videos", headers=self.h, json={
                "job_id": job_id, "image_id": image_id, "character_name": "x", "which": "talk"})
        self.assertEqual(res.status_code, 500)
        self.assertEqual(talk.read_bytes(), good)

    def test_regenerated_images_get_new_ids_and_uploads_survive(self):
        job_id, upload_id = self._job_with_image()

        def handler(request):
            return httpx.Response(200, json={"data": {"image_urls": [f"data:image/jpeg;base64,{self.jpeg_b64}"] * 2}})

        real_client = httpx.AsyncClient

        def generate():
            with patch.object(server.httpx, "AsyncClient",
                              lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
                res = client.post("/api/create/images", headers=self.h,
                                  json={"prompt": "老師", "count": 2, "job_id": job_id})
            self.assertEqual(res.status_code, 200, res.text)
            return res.json()["images"]

        first = generate()
        second = generate()
        ids1 = {i["id"] for i in first if i["source"] == "minimax"}
        ids2 = {i["id"] for i in second if i["source"] == "minimax"}
        self.assertEqual(len(ids1), 2)
        self.assertTrue(ids1.isdisjoint(ids2))
        self.assertIn(upload_id, {i["id"] for i in second})
        self.assertEqual(len(second), 3)  # 1 张上传 + 新一批 2 张，上一批被替换
        for img in second:
            self.assertEqual(client.get(img["url"]).status_code, 200)


class FieldAssistValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = {"X-Session-Token": make_account("assist-user", "premium")}

    def test_rejects_bad_requests_before_calling_llm(self):
        cases = [
            {"field": "nope", "action": "write"},
            {"field": "role", "action": "dance"},
            {"field": "background", "action": "polish", "value": "  "},
            {"field": "background", "action": "custom", "value": "x"},
        ]
        for body in cases:
            self.assertEqual(client.post("/api/create/field-assist", headers=self.h, json=body).status_code, 400, body)

    def test_smart_knowledge_is_premium_only(self):
        with patch.object(server, "USER_CODES", {"invite-1": "invited"}):
            res = client.post("/api/create/knowledge/agent", headers={"X-User-Code": "invite-1"},
                              data={"request": "三體"})
        self.assertEqual(res.status_code, 403)


class TokenEstimateTests(unittest.TestCase):
    def test_estimate(self):
        self.assertEqual(knowledge_agent.estimate_tokens(""), 0)
        self.assertEqual(knowledge_agent.estimate_tokens("一二三四"), 4)
        self.assertEqual(knowledge_agent.estimate_tokens("abcdefgh"), 2)

    def test_truncate_and_split(self):
        text = "字" * 100
        self.assertEqual(len(knowledge_agent.truncate_to_tokens(text, 30)), 30)
        chunks = knowledge_agent.split_by_tokens("\n\n".join(["段" * 40] * 10), 100)
        self.assertTrue(all(knowledge_agent.estimate_tokens(c) <= 100 for c in chunks))
        self.assertEqual(sum(c.count("段") for c in chunks), 400)


class SafeFetchTests(unittest.TestCase):
    def _run(self, url):
        return asyncio.run(knowledge_agent.safe_fetch(url))

    def test_rejects_internal_and_non_http(self):
        for url in ("http://127.0.0.1:8080/", "http://169.254.169.254/latest/meta-data",
                    "http://localhost/", "file:///etc/passwd", "ftp://example.com/"):
            with self.assertRaises(knowledge_agent.FetchError, msg=url):
                self._run(url)

    def test_rejects_redirect_into_internal_network(self):
        async def fake_check(host, port):
            if host != "public.test":
                raise knowledge_agent.FetchError("internal")

        def handler(request):
            return httpx.Response(302, headers={"location": "http://internal.test/admin"})

        real_client = httpx.AsyncClient
        with patch.object(knowledge_agent, "_assert_public_host", fake_check), \
             patch.object(knowledge_agent.httpx, "AsyncClient",
                          lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            with self.assertRaises(knowledge_agent.FetchError):
                self._run("http://public.test/page")

    def test_html_to_text(self):
        title, text = knowledge_agent.html_to_text(
            "<html><head><title>T</title><style>x{}</style></head><body><nav>menu</nav><p>Hello</p><script>bad()</script></body></html>")
        self.assertEqual(title, "T")
        self.assertEqual(text, "Hello")


class KnowledgeAgentFlowTests(unittest.TestCase):
    def _agent(self, name, llm):
        task_dir = TMP / "agent-tests" / name
        task_dir.mkdir(parents=True, exist_ok=True)

        async def web_search(instruction, query):
            return f"搜索结果 {query} https://example.com/{query}"

        agent = knowledge_agent.KnowledgeAgent(
            task_dir, llm=llm, web_search=web_search,
            extract_file=lambda p: p.read_text(encoding="utf-8"), budget=1500)
        agent.init_status("tester")
        return agent, task_dir

    def test_vague_request_asks_for_directions(self):
        async def llm(system, user, max_tokens=0, temperature=0):
            return '{"needs_clarification": true, "suggestions": ["生平", "作品"], "queries": [], "topics": []}'

        agent, task_dir = self._agent("vague", llm)
        asyncio.run(agent.run(request="不知道", context={"name": "李白"}, files=[], urls=[], directions=[]))
        status = knowledge_agent.load_status(task_dir)
        self.assertEqual(status["state"], "needs_input")
        self.assertEqual(status["suggestions"], ["生平", "作品"])

    def test_full_run_respects_budget(self):
        async def llm(system, user, max_tokens=0, temperature=0):
            if "规划员" in system:
                return '```json\n{"needs_clarification": false, "queries": ["李白"], "topics": ["生平"]}\n```'
            if "大纲" in system:
                return '{"sections": [{"title": "生平", "focus": "生平"}, {"title": "作品", "focus": "作品"}]}'
            return "- 要点 " * 2000

        agent, task_dir = self._agent("full", llm)
        doc = task_dir / "book.txt"
        doc.write_text("第一章\n\n" + "长文本内容。" * 3000, encoding="utf-8")
        asyncio.run(agent.run(request="李白", context={"name": "李白", "language": "Chinese"},
                              files=[("book.txt", doc)], urls=[], directions=[]))
        status = knowledge_agent.load_status(task_dir)
        self.assertEqual(status["state"], "done", status.get("error"))
        self.assertLessEqual(status["tokens"], 1500)
        self.assertIn("## 生平", status["text"])
        self.assertEqual({s["kind"] for s in status["sources"]}, {"file", "search"})
        self.assertFalse(doc.exists())  # 上传的原文件跑完就删


if __name__ == "__main__":
    unittest.main()
