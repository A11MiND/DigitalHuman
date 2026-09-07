# 账号体系与体验额度

登录、体验额度、付费墙、管理员后台的实现说明。

## 三种角色

| 角色 | 对话额度 | 权限 | 用途 |
| --- | --- | --- | --- |
| `trial` 体验帐户 | 默认 20 次（`TRIAL_QUOTA` 可配） | 仅对话 + 语音 | 开放日、试用客户 |
| `premium` 高级帐户 | 不限 | 对话 + 语音 + 创建角色 + 知识库导入 | 已付费客户 |
| `admin` 管理员 | 不限 | 全部权限 + 管理后台 + 对话记录 | 内部运营 |

**所有账号由管理员后台创建，前台没有注册入口。** 登录页只有登录。

## 页面

| 路径 | 说明 |
| --- | --- |
| `/login.html` | 登录页。已登录会自动跳转；`?next=` 支持登录后回到原页面（只接受站内相对路径） |
| `/admin.html` | 管理员后台。非管理员访问会看到提示而非数据 |
| `/index.html` | 数字人对话页。未登录跳登录页，右上角显示额度胶囊 |
| `/lobby.html` | 角色大厅。未登录跳登录页，右上角显示账户条 |
| `/dashboard.html` | 数据看板。现在需要管理员会话 |

## 额度是怎么算的

一次「对话」= 一轮成功的问答（用户发言 → 模型产出回复）。

- 扣次数发生在 `server.py` 的 WebSocket 处理里，位置在回复成功落库之后。
- **上游失败的轮次不扣次数**：`if full_response and not full_response.startswith("[ERROR]")` 这个条件同时守着落库和扣费。
- 额度耗尽时**不会调用 LLM**，直接下发 `quota_exceeded`，所以不会浪费 token。
- 每一轮都重新读一次账号，管理员在后台做的停用／升级／加额度会在下一句话立即生效，不需要用户重新登录。

## 额度耗尽后的流程

1. 前端收到 `quota_exceeded`，弹出付费墙（`static/index.html` 里的 `.paywall`）。
2. 用户点「申請追加額度」→ `POST /api/quota/request`，同一账号同时只允许一条待处理申请。
3. 管理员后台「額度申請」区出现待办，可填写追加次数后批准，或直接拒绝。
4. 批准即刻把次数加到该账号的 `quota_limit` 上，用户无需重新登录。

管理员也可以直接在账号列表点「升級」，把体验帐户一键改成高级帐户（额度自动改为不限）。

## 会话令牌

- 登录成功返回 `token`，前端存 localStorage 的 `dh_session_token`。
- HTTP 请求走 `X-Session-Token` 请求头。
- WebSocket 走 `?token=` 查询参数（浏览器无法给 WebSocket 设置请求头）。
- 默认有效期 7 天（`SESSION_TTL_DAYS`），令牌存在 `sessions` 表，可服务端吊销。
- 停用账号、改密码、改角色都会**立即清掉该账号的全部会话**。

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `MINIMAX_REGION` | 否 | 主 Key 所属区域：`cn`（默认，api.minimaxi.com）或 `global`（api.minimax.io） |
| `PREMIUM_API_KEY` | 否 | 高级用户使用的服务 Key。留空则回退到 `MINIMAX_API_KEY` |
| `PREMIUM_MINIMAX_REGION` | 否 | 高级 Key 所属区域，留空则跟随 `MINIMAX_REGION` |
| `TRIAL_QUOTA` | 否 | 体验帐户默认额度，默认 20 |
| `SESSION_TTL_DAYS` | 否 | 会话有效期天数，默认 7 |
| `ADMIN_USERNAME` | 否 | 首次启动创建的管理员账号名，默认 `admin` |
| `ADMIN_PASSWORD` | 否 | 管理员初始密码。**不配置则随机生成并在启动日志里打印一次** |

`ADMIN_USERNAME` / `ADMIN_PASSWORD` 只在库中一个管理员都没有时生效，之后改这两个变量不会影响已有账号。

## MiniMax 区域必须和 Key 配对

MiniMax 的 base URL 取决于**账号注册的地区**，不是请求发起地：

| 账号地区 | Base URL |
| --- | --- |
| 中国大陆 | `https://api.minimaxi.com` |
| 国际 / 全球 | `https://api.minimax.io` |

两个域名只差一个字母，而**一把有效的 Key 打到错误区域的端点会返回 `2049 invalid api key`**，和 Key 本身失效的表现完全一样。所以排查 Key 问题时，两个区域都要试过才能下结论。

代码里 `server.py` 的 `MINIMAX_HOSTS` 是唯一的映射表，`MINIMAX_REGION` 和 `PREMIUM_MINIMAX_REGION` 分别控制主 Key 和高级 Key 的落点。对话、TTS、`/ask`、`/tts` 都会按当前账号解析凭证，所以高级帐户可以用与主 Key 不同区域的 Key。

其他常见状态码：`2056` 是 Token Plan 用量打满，`2061` 是当前套餐不支持该模型。

## 数据表

三张新表与 `conversations` 共用 `data/conversations.db`：

- `accounts` — 账号、密码哈希、角色、状态、额度、备注、到期时间
- `sessions` — 会话令牌
- `quota_requests` — 额度追加申请

另外给 `conversations` 加了 `username` 列（`ALTER TABLE ADD COLUMN`，对既有数据无损），后台由此可以按账号统计用量。

密码用标准库的 `pbkdf2_hmac('sha256', ..., 200000)` 加盐哈希，没有引入新依赖，也不可逆——忘记密码只能由管理员重置。

## API

### 登录

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/auth/login` | POST | 登录，返回令牌与账户信息 |
| `/api/auth/logout` | POST | 登出，吊销当前令牌 |
| `/api/auth/session` | GET | 查询当前会话与剩余额度 |
| `/api/auth/password` | POST | 用户自助改密码（需原密码） |

### 额度

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/quota/request` | POST | 提交追加额度申请 |
| `/api/quota/request` | GET | 查询自己最近一条申请的状态 |

### 管理后台

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/api/admin/accounts` | GET | 账号列表，支持 `q` / `role` / `status` 筛选 |
| `/api/admin/accounts` | POST | 创建账号 |
| `/api/admin/accounts/{username}` | PATCH | 改角色、状态、额度、备注、到期时间 |
| `/api/admin/accounts/{username}` | DELETE | 删除账号 |
| `/api/admin/accounts/{username}/password` | POST | 重置密码 |
| `/api/admin/accounts/{username}/quota/reset` | POST | 已用次数清零 |
| `/api/admin/quota-requests` | GET | 额度申请列表 |
| `/api/admin/quota-requests/{id}` | POST | 批准（可指定追加次数）或拒绝 |
| `/api/admin/stats` | GET | 后台概览统计 |

后台接口一律要求管理员会话；唯一的管理员不能被降级、停用或删除。

## 与原有邀请码系统的关系

原来的 `USER_CODES` 邀请码机制**保留不动**，用于运维接口和历史流程。变化只有一处：角色创建类接口（`/api/create/*`、`/api/characters/import`）现在接受**邀请码或高级／管理员会话**二选一，所以高级帐户不需要再单独配一个邀请码。

## 一并收紧的接口

`/api/conversations`、`/api/conversations/stats`、`/api/conversations/analytics`、`/api/logs` 之前是完全公开的，会返回访客 IP 和对话原文。加了账号体系之后这些记录还会带上账号名，因此统一加了守卫：**运维邀请码或管理员会话二选一**。

## 本地跑

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export MINIMAX_API_KEY="..."
export ADMIN_PASSWORD="换成你自己的强密码"
python3 server.py
```

打开 `http://localhost:8080/login.html`，用 `admin` 和 `ADMIN_PASSWORD` 登录即可进入后台建号。
