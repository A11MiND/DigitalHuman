# Code Review — DigitalHuman 秦始皇 (2026-05-23)

## server.py

### 🐛 Bug: diag_test 用了浅拷贝（共享 voice_modify 引用）
```
line ~390: effective = dict(tts_config)          # ← 浅拷贝！
```
`effective["voice_modify"]` 和 `tts_config["voice_modify"]` 指向同一个 dict。
虽然 diag_test 里用 `effective.update(diag_config)` 会替换引用，
但如果 diag_config 不含 voice_modify，两个对象共享同一个可变 dict，潜在并发问题。
**Fix: `deepcopy(tts_config)`**

### ⚠️ Warning: send() 静默失败
```
line ~1030: if (!wsOk || !ws || ws.readyState !== 1) { processing = false; ...; return; }
```
WS 断线时 send() 静默重置 processing，但 sendQuery() 已经加了用户气泡，
用户看不到任何错误提示，以为消息发出去了。
**Fix: 加 toast/状态提示**

### ⚠️ Warning: WS 断开时视频状态未切换
```
ws.onclose: if (processing) { ... switchVideo('idle'); }
```
只在 processing=true 时切回 idle。如果 TTS 播完后 WS 断连，视频可能卡在 talk 状态。
**Fix: onclose 里始终 switchVideo('idle')**

### 📝 Nit: LLM context 太短
`history[-20:]` 只发最后 20 条（10 轮对话）。对话长时上下文丢失。
**可考虑 -40 或 dynamic。**

### ✅ Good
- Per-connection state + workers=1 ✓
- deepcopy(DEFAULT_TTS_CONFIG) 防全局污染 ✓
- 流式 LLM + 流式 TTS 双流 ✓
- WebSocket 心跳/超时保护 ✓

---

## static/index.html

### 🐛 Bug: 重复 connect() 已修复 ✓
之前两次 connect() 导致初始化状态混乱（已修）

### 🐛 Bug: handleMsg 'done' 的 currentAudio.onended 重复绑定
```
// MediaSource path
currentAudio.onended = () => { currentAudio = null; switchVideo('idle'); };
// Blob fallback path  
a.onended = () => { currentAudio = null; ...; switchVideo('idle'); };
currentAudio = a;
```
两处都绑定了 onended/onerror 设置了 currentAudio=null，OK。

### ⚠️ Warning: addBubble 用 innerHTML 而非 textContent
```
div.innerHTML = `<div class="label">...</div><div class="text">${escapeHtml(text)}</div>`;
```
escapeHtml 会转义 < > & " ' 但不会处理反引号等问题。不够安全。
**但 level="user" 是自己输入的文字，level="assistant" 已经过 appendLLM 的 textContent，OK**

### ⚠️ Warning: 正常模式下 sendQuery 后 recognition 自动重开
```
setTimeout(() => { if (!processing && micOn && !callActive) { ... recognition.start() ... } }, 1200);
```
1200ms 后如果 processing 仍为 true，不会重开。正常模式应该持续回环。

### 📝 Nit: 语气标签正则每次 append 都重新执行
```
llmEl.querySelector('.text').textContent = llmText.replace(/.../gi, '');
```
每收到一个 delta 都对全部 llmText 做正则替换，O(n²)。对短文本影响不大。

### 📝 Nit: MediaSource audio 的 ended/error 未绑定
`_startStreamingAudio()` 创建了 audio 但未绑定 onended。依赖 handleMsg 的 `currentAudio.onended` 绑定。
但如果 _startStreamingAudio 创建的 audio 提前结束（比如 src 无效），handleMsg 还没到 done，
currentAudio 不会被清理。

### ✅ Good
- 指数退避重连 ✓
- currentAudio 在所有路径清理 ✓
- ws.readyState 检查 ✓
- MediaSource 流式播放 ✓

---

## 总评
- **P0**: diag_test shallow copy → 用 deepcopy
- **P1**: send() 失败无提示 → 加 alert
- **P1**: WS onclose 未切 idle → 始终切  
- **P2**: LLM context -20 偏短
- **P2**: 正常模式 1200ms 重开可能失效
