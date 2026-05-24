# 角色系统实施计划 — 2026-05-24

## 目标
把秦始皇的硬编码配置抽成可插拔的角色系统，支持多角色切换 + zip 导入导出。

---

## 架构概览

```
characters/
  qin-shihuang/
    character.json        ← 角色定义
    portrait.png           ← 立绘（大厅卡片用）
    idle.mp4               ← 5s 静态循环
    talk.mp4               ← 8s 说话动态

浏览器                    服务器
┌──────────┐    HTTP     ┌─────────────────────┐
│ lobby    │──GET /api/  │ CharacterManager     │
│ 角色大厅  │   characters│  ├ load_all()        │
│          │             │  └ get(id)           │
│ 点击角色  │             │                     │
└────┬─────┘             │ FastAPI              │
     │ ?char=qin         │  ├ /api/characters   │
     ▼                   │  ├ /api/characters/  │
┌──────────┐   WebSocket │    {id}              │
│ index    │──/ws?char=  │  └ /ws?char={id}     │
│ 对话页面  │   qin       │     ↓               │
│          │             │  per-connection:     │
│ 动态加载  │             │  char_config +       │
│ 角色配置  │             │  SYSTEM_PROMPT       │
└──────────┘             └─────────────────────┘
```

---

## 实施步骤

### Step 1: 创建角色目录 + character.json（不破坏现有功能）

```bash
mkdir -p characters/qin-shihuang
```

**`characters/qin-shihuang/character.json`:**
```json
{
  "id": "qin-shihuang",
  "name": "秦始皇嬴政",
  "name_en": "Qin Shi Huang",
  "icon": "portrait.png",
  "avatar_idle": "idle.mp4",
  "avatar_talk": "talk.mp4",
  "system_prompt": "你是秦始皇嬴政...",
  "tts_voice_id": "Cantonese_PlayfulMan",
  "tts_language": "Chinese,Yue",
  "theme_color": "#8A6D3B"
}
```

把现有 `static/videos/idle.mp4` → `characters/qin-shihuang/idle.mp4`，同理 talk.mp4。
系统提示词从 server.py 的 `SYSTEM_PROMPT` 常量移到 json 里。

### Step 2: server.py — CharacterManager

```python
# 新增类
class CharacterManager:
    def __init__(self, base_dir="characters"):
        self.base_dir = Path(base_dir)
        self.characters: dict[str, dict] = {}
        self.load_all()
    
    def load_all(self):
        """扫描 characters/ 下所有子目录，读取 character.json"""
        for d in self.base_dir.iterdir():
            if d.is_dir():
                cfg = d / "character.json"
                if cfg.exists():
                    ch = json.loads(cfg.read_text())
                    ch["_dir"] = str(d)
                    self.characters[ch["id"]] = ch
    
    def get(self, char_id: str) -> dict | None:
        return self.characters.get(char_id)
    
    def list_all(self) -> list[dict]:
        return [{"id": c["id"], "name": c["name"], "icon": f"/characters/{c['id']}/{c['icon']}"}
                for c in self.characters.values()]
```

**API 新增:**
- `GET /api/characters` → `list_all()`
- `GET /api/characters/{char_id}` → `get(char_id)` 返回完整配置（不含 system_prompt 给前端）
- 获取角色视频资源的 URL 规则：`/characters/{id}/idle.mp4`

**WebSocket 改造:**
- 连接时接受 `?char=qin-shihuang` 参数
- 不再从模块级 `SYSTEM_PROMPT` 取提示词，而是从 `CharacterManager.get(char_id).system_prompt`
- per-connection 的 `tts_config` 初始值从角色的 `tts_voice_id` / `tts_language` 读取

**StaticFiles:**
```python
# 挂载角色资源目录
app.mount("/characters", StaticFiles(directory="characters"), name="characters")
```

### Step 3: 前端 — 动态加载角色

**`index.html` 改动:**
1. 页面加载时检查 `?char=xxx` 参数
2. `fetch('/api/characters/qin-shihuang')` 获取角色配置
3. 用返回的数据设置：
   - 视频源：`<source src="/characters/xxx/idle.mp4">` 等
   - 初始 `ttsLanguage` / `ttsVoiceId`
   - 占位符文字 `placeholder="問秦始皇..."`
4. 如果没有 `?char=` 参数 → 跳转到 `lobby.html`

**`lobby.html` — 新页面:**
```
┌─────────────────────────────────┐
│        🏯 選擇角色                │
│                                 │
│  ┌──────┐  ┌──────┐  ┌──────┐  │
│  │ 头像 │  │ 头像 │  │  +   │  │
│  │秦皇  │  │ ...  │  │导入  │  │
│  └──────┘  └──────┘  └──────┘  │
│                                 │
└─────────────────────────────────┘
```
- `fetch('/api/characters')` 获取角色列表
- 渲染卡片：每个角色显示 icon + 名字
- 点击卡片 → `window.location = '/?char=qin-shihuang'`
- 「导入」按钮：上传 .zip 文件 → `POST /api/characters/import`

### Step 4: 导入/导出 .zip

**导出 `GET /api/characters/{id}/export`:**
```python
# 把 characters/{id}/ 整个目录打包成 zip，stream 返回
import zipfile, io
buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as zf:
    for f in char_dir.rglob('*'):
        zf.write(f, f.relative_to(char_dir))
return StreamingResponse(buf, media_type="application/zip", 
                         headers={"Content-Disposition": f"attachment; filename={id}.zip"})
```

**导入 `POST /api/characters/import`:**
```python
# 接收上传的 .zip，解压到 characters/<id>/
# 校验：必须含 character.json 且 id/name 不为空
# 如果 id 已存在 → 询问覆盖
# 成功后调用 CharacterManager.reload()
```

---

## 工时估计

| 步骤 | 内容 | 预计 |
|------|------|------|
| Step 1 | 目录 + json 迁移 | 15min |
| Step 2 | CharacterManager + API | 40min |
| Step 3 | 前端动态加载 + lobby.html | 40min |
| Step 4 | zip 导入导出 | 30min |
| **合计** | | **~2h** |

---

## 风险点
- WebSocket `?char=` 参数：FastAPI WebSocket 支持 query_params ✓
- 视频文件迁移后，旧浏览器缓存可能 404 → 用新路径 `/characters/` 避免
- `run.sh` 中的视频路径引用需更新（如有）
- 前端视频 `<source>` 需动态设置，不能写死在 HTML 里
