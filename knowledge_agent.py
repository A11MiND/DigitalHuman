"""创角精灵 · 智能知识库 Agent。

用户给一句需求（「《三体》三部曲」「我们公司的产品手册」「不知道」）、若干文件
和网址，Agent 在后台跑完：规划 → 收集 → 分段摘要 → 按大纲汇总，产出一份不超过
token 预算的 markdown 知识文档。进度写在任务目录的 status.json，前端轮询。

这里不 import server.py（避免循环依赖）：LLM 调用、文件抽取都由调用方注入。
"""

import asyncio
import html.parser
import ipaddress
import json
import logging
import re
import socket
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger("digitalhuman.knowledge_agent")

MAX_AGENT_FILES = 10
MAX_AGENT_URLS = 10
MAX_SEARCH_QUERIES = 3
CHUNK_TOKENS = 6000
MAX_CHUNKS = 40
# 小于这个量的来源（例如 web search 已经总结好的结果）不再单独摘要
SKIP_MAP_TOKENS = 2000
LLM_CONCURRENCY = 3
FETCH_MAX_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 15.0
FETCH_MAX_REDIRECTS = 3
# 运行中的任务超过这么久没有更新进度，视为服务重启丢失
STALE_SECONDS = 10 * 60


# ── Token 估算 ──────────────────────────────────────────
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中日韩字符每个算 1，其余每 4 个字符算 1（偏保守）。

    MiniMax 没有公开的本地 tokenizer，这个估算只用来做上限控制和界面显示；
    前端 lobby.html 里有同一套算法，两边必须保持一致。
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return cjk + (len(text) - cjk + 3) // 4


def truncate_to_tokens(text: str, budget: int) -> str:
    """截到不超过 budget 个估算 token 的最长前缀。"""
    if estimate_tokens(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def split_by_tokens(text: str, size: int) -> list[str]:
    """按段落切块，每块不超过 size 个估算 token；超长段落硬切。"""
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        t = estimate_tokens(para)
        while t > size:
            head = truncate_to_tokens(para, size)
            chunks.append(head)
            para = para[len(head):]
            t = estimate_tokens(para)
        if buf_tokens + t > size and buf:
            chunks.append("\n\n".join(buf))
            buf, buf_tokens = [], 0
        buf.append(para)
        buf_tokens += t
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


# ── 安全抓取网页 ─────────────────────────────────────────
class FetchError(Exception):
    pass


async def _assert_public_host(host: str, port: int) -> None:
    """解析 DNS，任何一个地址落在内网/回环/链路本地/保留段都拒绝（防 SSRF）。"""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"無法解析網域 {host}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if not addr.is_global or addr.is_multicast:
            raise FetchError(f"不允許訪問內網地址 {host}")


async def safe_fetch(url: str) -> tuple[str, str, bytes]:
    """抓取用户提供的网址 → (最终网址, content-type, 内容)。

    只允许 http/https；每次跳转都重新检查目标地址；最多读 5MB。
    """
    current = url.strip()
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=False,
                                 headers={"User-Agent": "Mozilla/5.0 (DigitalHuman knowledge agent)"}) as client:
        for _ in range(FETCH_MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise FetchError("只支援 http/https 網址")
            await _assert_public_host(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            async with client.stream("GET", current) as res:
                if res.status_code in (301, 302, 303, 307, 308) and res.headers.get("location"):
                    current = urljoin(current, res.headers["location"])
                    continue
                if res.status_code >= 400:
                    raise FetchError(f"網頁返回 {res.status_code}")
                body = bytearray()
                async for part in res.aiter_bytes():
                    body.extend(part)
                    if len(body) > FETCH_MAX_BYTES:
                        break
                return current, res.headers.get("content-type", ""), bytes(body[:FETCH_MAX_BYTES])
    raise FetchError("跳轉次數過多")


class _TextExtractor(html.parser.HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)


def html_to_text(raw: str) -> tuple[str, str]:
    """→ (标题, 正文)。只做去标签和空白整理，正文筛选交给后面的 LLM 摘要。"""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
    except Exception:
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return parser.title.strip(), text.strip()


# ── 任务状态 ─────────────────────────────────────────────
def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_status(task_dir: Path) -> dict | None:
    path = task_dir / "status.json"
    if not path.is_file():
        return None
    status = json.loads(path.read_text(encoding="utf-8"))
    if status.get("state") == "running" and time.time() - status.get("updated_at", 0) > STALE_SECONDS:
        status["state"] = "failed"
        status["error"] = "任務中斷（服務可能已重啟），請重新提交"
        _write_json(path, status)
    return status


def _parse_json_block(text: str) -> dict:
    """LLM 偶尔会在 JSON 外面包 ```json 或者多说一句，取第一个 {...}。"""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


_URL_RE = re.compile(r"https?://[^\s\)\]，,。<>\"']+")


# ── Agent ────────────────────────────────────────────────
TextFn = Callable[..., Awaitable[str]]


class KnowledgeAgent:
    """一次智能知识库任务。

    llm(system, user, max_tokens=..., temperature=...) -> str
    web_search(instruction, query) -> str
    extract_file(path: Path) -> str   （同步函数，会放进线程池跑）
    """

    def __init__(self, task_dir: Path, *, llm: TextFn, web_search: TextFn,
                 extract_file: Callable[[Path], str], budget: int):
        self.task_dir = task_dir
        self.llm = llm
        self.web_search = web_search
        self.extract_file = extract_file
        self.budget = budget
        self.status: dict = {}
        self._sem = asyncio.Semaphore(LLM_CONCURRENCY)

    # 进度 ------------------------------------------------
    def init_status(self, owner: str) -> dict:
        now = time.time()
        self.status = {
            "id": self.task_dir.name, "owner": owner, "created_at": now, "updated_at": now,
            "state": "running", "steps": [], "suggestions": [],
            "text": "", "sources": [], "tokens": 0, "truncated": False, "error": "",
        }
        self._save()
        return self.status

    def _save(self) -> None:
        self.status["updated_at"] = time.time()
        _write_json(self.task_dir / "status.json", self.status)

    def _step(self, code: str, **params) -> dict:
        step = {"code": code, "state": "running", **params}
        self.status["steps"].append(step)
        self._save()
        return step

    def _done(self, step: dict, state: str = "done", error: str = "") -> None:
        step["state"] = state
        if error:
            step["error"] = error[:200]
        self._save()

    async def _llm(self, system: str, user: str, max_tokens: int, temperature: float = 0.3) -> str:
        async with self._sem:
            return await self.llm(system, user, max_tokens=max_tokens, temperature=temperature)

    # 主流程 ----------------------------------------------
    async def run(self, *, request: str, context: dict, files: list[tuple[str, Path]],
                  urls: list[str], directions: list[str]) -> None:
        try:
            await self._run(request=request, context=context, files=files, urls=urls, directions=directions)
        except Exception as exc:
            logger.exception("knowledge agent %s failed", self.task_dir.name)
            self.status["state"] = "failed"
            self.status["error"] = str(getattr(exc, "detail", "") or exc)[:300]
            self._save()
        finally:
            for _, path in files:
                path.unlink(missing_ok=True)

    async def _run(self, *, request, context, files, urls, directions) -> None:
        language = context.get("language") or "Chinese"
        role_desc = (
            f"角色名：{context.get('name', '')}\n角色定位：{context.get('role', '')}\n"
            f"背景：{(context.get('background') or '')[:800]}"
        )

        # 1. 规划
        step = self._step("plan")
        plan = _parse_json_block(await self._llm(
            "你是数字人角色的知识库规划员。根据用户需求、角色设定和用户提供的材料清单，"
            "决定还需要上网搜索什么、知识库要覆盖哪些重点主题。只输出 JSON，不要解释：\n"
            '{"needs_clarification": bool, "queries": ["搜索词", ...], "topics": ["重点主题", ...], '
            '"suggestions": ["建议方向", ...]}\n'
            f"- queries 最多 {MAX_SEARCH_QUERIES} 个；用户材料已经足够时给空数组。\n"
            "- topics 3-8 个。\n"
            "- 用户需求为空、含糊或者明说不知道要什么，并且没有提供任何文件/网址时，"
            "needs_clarification 为 true，并在 suggestions 给出 3-5 个适合这个角色的知识方向（每个一句话）。",
            f"{role_desc}\n\n用户需求：{request or '（空）'}\n"
            f"用户已选方向：{'；'.join(directions) or '（无）'}\n"
            f"文件：{', '.join(n for n, _ in files) or '（无）'}\n网址：{', '.join(urls) or '（无）'}\n"
            f"输出语言：{language}",
            max_tokens=2500,
        ))
        self._done(step)
        if plan.get("needs_clarification") and not (files or urls or directions):
            self.status["suggestions"] = [str(s) for s in (plan.get("suggestions") or [])][:5]
            self.status["state"] = "needs_input"
            self._save()
            return
        topics = [str(t) for t in (plan.get("topics") or [])][:8] or directions or [request or context.get("name", "")]
        queries = [str(q) for q in (plan.get("queries") or [])][:MAX_SEARCH_QUERIES]

        # 2. 收集
        sources: list[dict] = []
        for i, (name, path) in enumerate(files, start=1):
            step = self._step("read_file", name=name, i=i, n=len(files))
            try:
                text = await asyncio.to_thread(self.extract_file, path)
                if text.strip():
                    sources.append({"kind": "file", "title": name, "url": "", "text": text})
                    self._done(step)
                else:
                    self._done(step, "failed", "沒有可提取的文字（可能是掃描版 PDF）")
            except Exception as exc:
                self._done(step, "failed", str(getattr(exc, "detail", "") or exc))

        for i, url in enumerate(urls, start=1):
            step = self._step("fetch_url", url=url, i=i, n=len(urls))
            try:
                final_url, ctype, body = await safe_fetch(url)
                if "pdf" in ctype or final_url.lower().endswith(".pdf"):
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                        fh.write(body)
                    tmp = Path(fh.name)
                    try:
                        title, text = final_url, await asyncio.to_thread(self.extract_file, tmp)
                    finally:
                        tmp.unlink(missing_ok=True)
                elif "html" in ctype or not ctype:
                    title, text = html_to_text(body.decode("utf-8", errors="ignore"))
                else:
                    title, text = final_url, body.decode("utf-8", errors="ignore")
                if text.strip():
                    sources.append({"kind": "url", "title": title or final_url, "url": final_url, "text": text})
                    self._done(step)
                else:
                    self._done(step, "failed", "網頁沒有可提取的文字")
            except Exception as exc:
                self._done(step, "failed", str(exc))

        for i, query in enumerate(queries, start=1):
            step = self._step("search", query=query, i=i, n=len(queries))
            try:
                text = await self.web_search(
                    "你是资料搜集员。用 web search 搜集下面主题的事实性资料，按要点整理，"
                    f"不要写搜索过程，不要编造，结尾列出来源网址。输出语言：{language}。\n\n{role_desc}",
                    query,
                )
                sources.append({"kind": "search", "title": query, "url": "", "text": text})
                self._done(step)
            except Exception as exc:
                self._done(step, "failed", str(getattr(exc, "detail", "") or exc))

        if not sources:
            raise RuntimeError("沒有收集到任何可用內容，請檢查文件或網址")

        # 3. 分段摘要
        pieces: list[tuple[dict, str]] = []
        for src in sources:
            if estimate_tokens(src["text"]) <= SKIP_MAP_TOKENS:
                pieces.append((src, ""))
            else:
                pieces.extend((src, chunk) for chunk in split_by_tokens(src["text"], CHUNK_TOKENS))
        truncated = sum(1 for _, c in pieces if c) > MAX_CHUNKS
        kept, n_chunks = [], 0
        for src, chunk in pieces:
            if chunk:
                if n_chunks >= MAX_CHUNKS:
                    continue
                n_chunks += 1
            kept.append((src, chunk))

        map_step = self._step("summarize", i=0, n=n_chunks)
        topic_line = "；".join(topics)

        async def _map(src: dict, chunk: str) -> str:
            if not chunk:
                return f"### {src['title']}\n{src['text']}"
            note = await self._llm(
                "你是知识整理员。从下面这段材料里提取和重点主题相关的事实，用 markdown 要点列出，"
                "保留人名、地名、日期、数字、专有名词和关键原话；不相关的内容直接略过，不要编造，"
                f"不要写开场白。输出语言：{language}。",
                f"重点主题：{topic_line}\n来源：{src['title']}\n\n材料：\n{chunk}",
                max_tokens=4000,
            )
            map_step["i"] += 1
            self._save()
            return f"### {src['title']}\n{note}"

        notes = await asyncio.gather(*(_map(src, chunk) for src, chunk in kept))
        self._done(map_step)
        notes_text = truncate_to_tokens("\n\n".join(n for n in notes if n.strip()), 80000)

        # 4. 按大纲汇总
        step = self._step("outline")
        outline = _parse_json_block(await self._llm(
            "你是知识库编辑。根据下面的资料笔记，为数字人角色的知识库拟一个大纲。"
            '只输出 JSON：{"sections": [{"title": "章节标题", "focus": "这一节要写什么"}]}，3-8 节。'
            f"章节标题使用 {language}。",
            f"{role_desc}\n重点主题：{topic_line}\n\n资料笔记：\n{notes_text}",
            max_tokens=3000,
        ))
        sections = [s for s in (outline.get("sections") or []) if isinstance(s, dict) and s.get("title")][:8]
        if not sections:
            sections = [{"title": t, "focus": t} for t in topics[:6]]
        self._done(step)

        source_list = self._source_list(sources, language)
        reserve = estimate_tokens(source_list) + 200
        per_section = max(300, (self.budget - reserve) // len(sections))
        write_step = self._step("write", i=0, n=len(sections))

        async def _write(sec: dict) -> str:
            body = await self._llm(
                "你是知识库编辑，为数字人角色撰写知识库中的一节，角色对话时会以此为事实依据。"
                "只根据资料笔记写，不要编造；条理清晰，多用要点；保留具体事实和数字；"
                f"不要写本节标题，不要写开场白。输出语言：{language}。"
                f"长度控制在约 {per_section} tokens 以内（中文约 {per_section} 字，英文约 {int(per_section * 0.75)} 词）。",
                f"本节标题：{sec['title']}\n本节要写：{sec.get('focus', '')}\n\n资料笔记：\n{notes_text}",
                max_tokens=min(per_section * 2 + 3000, 16000),
            )
            write_step["i"] += 1
            self._save()
            return f"## {sec['title']}\n\n{truncate_to_tokens(body.strip(), per_section)}"

        bodies = await asyncio.gather(*(_write(sec) for sec in sections))
        self._done(write_step)

        doc = "\n\n".join(bodies) + ("\n\n" + source_list if source_list else "")
        if estimate_tokens(doc) > self.budget:
            doc = truncate_to_tokens(doc, self.budget)
            truncated = True
        self.status.update({
            "state": "done",
            "text": doc,
            "tokens": estimate_tokens(doc),
            "truncated": truncated,
            "sources": [{"kind": s["kind"], "title": s["title"], "url": s["url"]} for s in sources],
        })
        self._save()

    @staticmethod
    def _source_list(sources: list[dict], language: str) -> str:
        lines = []
        for s in sources:
            if s["kind"] == "file":
                lines.append(f"- {s['title']}")
            elif s["kind"] == "url":
                lines.append(f"- {s['title']}: {s['url']}")
            else:
                lines.extend(f"- {u}" for u in dict.fromkeys(_URL_RE.findall(s["text"])))
        heading = "参考来源" if language.lower().startswith("chinese") else "Sources"
        return (f"## {heading}\n" + "\n".join(dict.fromkeys(lines))) if lines else ""
