# 秦始皇数字人 - 当前工作记录

## Proposed Plan 1：AI 视频驱动的数字人展示

### 方案
用 AI 视频生成工具（Runway / HeyGen / Pika / Kling）将角色侧脸立绘生成 2 段 loop 视频：
- **idle 视频**：静态呼吸 + 眨眼循环（3-5 秒 loop）
- **talk 视频**：嘴巴张合说话循环（5-10 秒 loop，不跟实际音频同步）

前端用 `<video>` 替换静态图，根据状态切换播放：
- 在线/聆听中/思考中 → idle 视频
- 说话中 → talk 视频

### 优点
- 零代码实现眨眼 + 嘴型效果
- 不依赖 Live2D / 摄像头
- 前端改造量极小

### 待定
- AI 工具选择（先用免费额度试效果）
- 视频效果是否可接受

---

## 最近更新 (2026-05-23)

### 气泡淡出动画修复

**问题**: 气泡只是被新消息顶上去消失，没有缩小淡出的动画效果。

**原因**: 代码同时用了 CSS 类和内联样式设置动画，导致冲突。

**修复内容**:

1. CSS 简化（`static/index.html` 第160-171行）:
```css
.bubble.fading {
  animation: bubbleFadeOut 0.5s ease forwards;
}
.bubble.fading .text {
  opacity: 0;
  transition: opacity 0.3s ease 0.1s;
}

@keyframes bubbleFadeOut {
  0% { opacity: 1; transform: scale(1) translateY(0); }
  100% { opacity: 0; transform: scale(0.8) translateY(-20px); }
}
```

2. JavaScript 简化（`static/index.html` 第431-439行）:
```javascript
function checkBubblesFade() {
  const threshold = window.innerHeight * 0.4;
  document.querySelectorAll('.bubble:not(.fading)').forEach(bubble => {
    const rect = bubble.getBoundingClientRect();
    if (rect.top < threshold) {
      bubble.classList.add('fading');
      setTimeout(() => bubble.remove(), 800);
    }
  });
}
```

**动画流程**:
- 文字先淡出（0.3s，延迟0.1s）
- 气泡缩小+上移+消失（0.5s）
- 0.8s 后从 DOM 移除

### 服务器状态
- 运行中: http://localhost:8080
- MiniMax API: 已配置
- DeepSeek API: 未配置（但项目已改用 MiniMax）

### 待测试
- [ ] 气泡淡出动画是否正常触发
- [ ] 刷新浏览器后动画是否正常
