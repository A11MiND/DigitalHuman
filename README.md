# 数字人殿堂 / Digital Human Palace

<p align="center">
  <img src="static/images/libai-cover.png" alt="李白 / Li Bai digital human cover" width="420">
</p>

<p align="center">
  <strong>面向校园、历史人物与展陈场景的实时 AI 数字人平台。</strong><br>
  <strong>A real-time AI digital human platform for education, historical characters, and interactive exhibitions.</strong>
</p>

<p align="center">
  <a href="#中文">中文</a> ·
  <a href="#english">English</a>
</p>

---

## 中文

### 项目简介

数字人殿堂是一个基于 FastAPI、WebSocket 与 MiniMax 的轻量级数字人平台。它支持多角色配置、知识库问答、实时语音合成、头像/待机/说话视频切换，以及面向运维的可视化监控入口。

当前角色包括秦始皇、李白、Queen Elizabeth I 与小瑪老師。项目既可以作为历史人物互动体验，也可以作为校园开放日、展厅导览和招生接待的数字人底座。

### 核心功能

- **实时对话**：WebSocket 双工通信，支持流式回复与 TTS 音频分片播放。
- **多角色系统**：每个角色独立维护 `character.json`、`knowledge.md`、头像与视频素材。
- **知识库注入**：角色知识库自动拼接进系统提示词，适合校园资料、人物传记和活动说明。
- **MiniMax 语音**：使用 MiniMax `speech-2.8-hd`，支持普通话、粤语与英文语音配置。
- **对话数据库**：SQLite 自动记录时间、角色、用户 IP、用户消息、回复和耗时。
- **数据看板**：`/dashboard.html` 展示对话量、角色热度、时段分布和响应延迟。
- **运维平台**：`/ops` 聚合服务状态、资源监控、异常诊断、实时日志、对话记录导出和只读运维助手。
- **双语界面**：运维平台支持中文 / English 切换。
- **账号与额度**：体验帐户 20 次对话额度，用尽弹出升级引导并可申请追加；高级帐户不限次数、可用全套服务；账号统一由管理员后台开通与管理。详见 [`docs/account-system.md`](docs/account-system.md)。

### 运维入口

| 入口 | 说明 |
| --- | --- |
| `/login.html` | 登录页（体验帐户 / 高级帐户） |
| `/admin.html` | 管理员后台：账号、额度、申请审批 |
| `/` | 数字人主站（需登录） |
| `/dashboard.html` | 数据看板 |
| `/logs` | 实时日志查看器 |
| `/ops` | 合并后的运维平台 |
| `/health` | 服务健康检查 |
| `/api/conversations` | 对话记录 API |
| `/api/conversations/stats` | 对话统计 API |

运维平台中的资源监控、异常诊断、导出和 Chatbot 会复用项目现有的用户码机制。若配置了 `USER_CODES`，请求需要带有效运维码；若未配置，则本地部署默认开放只读运维能力。

### 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | FastAPI, Uvicorn, WebSocket |
| AI | MiniMax Chat Completion, MiniMax TTS |
| 存储 | SQLite |
| 前端 | HTML, CSS, JavaScript, ECharts |
| 运维 | systemd, journalctl, Nginx 反向代理可选 |

### 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export MINIMAX_API_KEY="your-minimax-api-key"
python3 server.py
```

启动后访问：

```text
http://localhost:8080
http://localhost:8080/ops
```

### 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `MINIMAX_API_KEY` | 是 | MiniMax API Key，用于 LLM、TTS、图像和视频生成 |
| `MINIMAX_TOKEN_PLAN_API_KEY` | 否 | MiniMax Token Plan 查询 Key，用于 `/api/ops/token-plan` |
| `USER_CODES` | 否 | 用户码配置，格式为 `name:code,name2:code2` |
| `MINIMAX_REGION` | 否 | Key 所属区域：`cn`（api.minimaxi.com，默认）或 `global`（api.minimax.io）。区域必须与 Key 配对 |
| `PREMIUM_API_KEY` | 否 | 高级用户使用的服务 Key，留空则回退到 `MINIMAX_API_KEY` |
| `PREMIUM_MINIMAX_REGION` | 否 | 高级 Key 所属区域，留空则跟随 `MINIMAX_REGION` |
| `TRIAL_QUOTA` | 否 | 体验帐户默认对话额度，默认 20 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 否 | 首次启动创建的管理员账号；未配置密码则随机生成并在日志打印一次 |
| `SESSION_TTL_DAYS` | 否 | 登录会话有效期天数，默认 7 |
| `PYTHONUNBUFFERED` | 否 | 部署时建议设为 `1`，方便日志实时输出 |

不要把 `.env`、数据库、日志、服务器密钥或邮件密码提交到 Git。

### 项目结构

```text
.
├── server.py                    # FastAPI 服务入口
├── characters/                  # 数字人角色配置与素材
│   ├── qin-shihuang/
│   ├── character-49fd372d/      # 李白
│   ├── elizabeth-i/
│   └── maryknoll-teacher/
├── static/
│   ├── index.html               # 主站
│   ├── dashboard.html           # 数据看板
│   ├── ops.html                 # 运维平台
│   └── images/
├── data/                        # SQLite 运行态数据，默认不提交
└── requirements.txt
```

### API 摘要

| API | 方法 | 说明 |
| --- | --- | --- |
| `/ws?char=<id>` | WebSocket | 数字人实时对话 |
| `/ask` | POST | 文本问答 |
| `/tts` | POST | 文本转语音 |
| `/api/characters` | GET | 角色列表 |
| `/api/conversations` | GET | 分页查询对话记录，支持 `limit/offset/start/end/char` |
| `/api/conversations/analytics` | GET | 聚合对话统计，供看板图表使用 |
| `/api/ops/status` | GET | 服务状态总览 |
| `/api/ops/resources` | GET | CPU、内存、磁盘与数据库状态 |
| `/api/ops/diagnostics` | GET | 异常诊断与关联日志 |
| `/api/ops/chat` | POST | 只读运维 Chatbot |
| `/api/ops/chat/stream` | POST | 只读运维 Chatbot 流式输出 |
| `/api/ops/token-plan` | GET | MiniMax Token Plan 用量查询 |
| `/api/ops/export/logs` | GET | 导出日志 |
| `/api/ops/export/conversations` | GET | 导出聊天记录 |
| `/api/auth/login` | POST | 账号登录，返回会话令牌 |
| `/api/auth/session` | GET | 查询当前会话与剩余额度 |
| `/api/quota/request` | POST | 体验用户申请追加额度 |
| `/api/admin/accounts` | GET/POST | 管理员：账号列表与创建 |
| `/api/admin/quota-requests` | GET | 管理员：额度申请与审批 |

### 部署建议

生产环境建议使用 systemd 管理 `server.py`，并通过 Nginx 处理 HTTPS、反向代理、真实 IP 透传和限流。Nginx 需要传递 `X-Forwarded-For` 与 `X-Real-IP`，否则应用日志中只能看到本机回环地址。

最小反向代理示例：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### 安全说明

- 不提交 `.env`、API Key、PEM、数据库、日志、邮件密码和 VPN 凭据。
- 运维接口默认只读；重启服务等写操作应保留人工确认。
- 对外部署时建议配置 HTTPS、访问控制和 Nginx 限流。
- 对话记录可能包含用户输入，应按学校或机构的数据合规要求保存、导出和清理。
- `/api/conversations`、`/api/logs` 等会返回访客 IP、对话原文和账号名，必须携带运维码或管理员会话才能访问。

---

## English

### Overview

Digital Human Palace is a lightweight real-time digital human platform powered by FastAPI, WebSocket, and MiniMax. It supports multiple character profiles, knowledge-grounded responses, speech synthesis, portrait/video assets, conversation logging, and an integrated operations console.

The current character set includes Qin Shi Huang, Li Bai, Queen Elizabeth I, and a Maryknoll teacher persona. The platform is suitable for historical education, campus open days, exhibition guides, and admissions reception scenarios.

### Features

- **Real-time conversation** with WebSocket streaming and TTS audio chunks.
- **Multi-character architecture** with independent prompts, knowledge files, portraits, and video assets.
- **Knowledge-grounded replies** for biographies, campus information, event guides, and FAQs.
- **MiniMax TTS** with configurable voices for Mandarin, Cantonese, and English.
- **Conversation database** backed by SQLite, recording timestamp, character, client IP, messages, and latency.
- **Analytics dashboard** at `/dashboard.html` for usage, role heat, hourly distribution, and latency.
- **Ops console** at `/ops` for service status, resources, diagnostics, live logs, exports, and a read-only ops chatbot.
- **Bilingual UI** for Chinese / English operations workflows.

### Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export MINIMAX_API_KEY="your-minimax-api-key"
python3 server.py
```

Open:

```text
http://localhost:8080
http://localhost:8080/ops
```

### Environment

| Variable | Required | Description |
| --- | --- | --- |
| `MINIMAX_API_KEY` | Yes | MiniMax API key for LLM, TTS, image, and video generation |
| `MINIMAX_TOKEN_PLAN_API_KEY` | No | MiniMax Token Plan key for `/api/ops/token-plan` |
| `USER_CODES` | No | Optional access codes in `name:code,name2:code2` format |
| `PYTHONUNBUFFERED` | No | Recommended as `1` in production for real-time logs |

### Production Notes

Use systemd for process management and Nginx for HTTPS termination, reverse proxying, real-client-IP forwarding, and rate limiting. Keep all secrets, runtime databases, logs, PEM files, and email credentials outside Git.

### License

MIT
