#!/bin/bash
# ── 數字人殿堂 一鍵啟動 ──
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

USE_TUNNEL=false
for arg in "$@"; do
  case "$arg" in
    --tunnel|-t) USE_TUNNEL=true ;;
    --help|-h)
      echo "Usage: ./run.sh [--tunnel]"
      exit 0 ;;
  esac
done

PORT="${PORT:-8080}"

echo "╔══════════════════════════════════════════════════╗"
echo "║  🏛️ 數字人殿堂 — Digital Human Hall              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Find Python 3.10+ ──
PYTHON=""
for py in python3.13 python3.12 python3.11 python3.10; do
  if command -v "$py" &>/dev/null; then
    PYTHON="$py"; break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "❌ 需要 Python 3.10+，请安装"; exit 1
fi
echo "🐍 Python: $($PYTHON --version)"

# ── API Key ──
if [ -z "${MINIMAX_API_KEY:-}" ]; then
  echo "⚠️  未設 MINIMAX_API_KEY，语音/TTS 将不可用"
  echo "   export MINIMAX_API_KEY='your-key'"
fi

# ── Venv ──
if [ ! -f ".venv/bin/activate" ]; then
  echo "📦 建立虛擬環境..."
  rm -rf .venv
  $PYTHON -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt 2>/dev/null

# ── Local IP ──
LOCAL_IP=$($PYTHON -c "
import socket
try:
 s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
 s.connect(('8.8.8.8',80))
 print(s.getsockname()[0])
except:
 print('127.0.0.1')
")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 服務已啟動"
echo "  🌐 本機:    http://localhost:$PORT"
echo "  📱 區域網:  http://$LOCAL_IP:$PORT"
echo ""
if $USE_TUNNEL; then
  if ! command -v cloudflared &>/dev/null; then
    echo "  ❌ 未安裝 cloudflared"; echo "     brew install cloudflared"; exit 1
  fi
  echo "  🔒 啟動 HTTPS 隧道（等幾秒出連結）..."
  echo ""
  export PORT
  $PYTHON server.py &
  sleep 3
  cloudflared tunnel --url "http://localhost:$PORT" 2>&1
  kill %1 2>/dev/null || true
else
  echo "  💡 手機需語音？用 ./run.sh --tunnel"
  echo "  ⌨️  按 Ctrl+C 關閉"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  export PORT
  exec $PYTHON server.py
fi
