#!/bin/bash
# ── 秦始皇數字人 一鍵啟動 ──
# Digital Human — Qin Shi Huang for primary/secondary students
#
# Usage:
#   ./run.sh              # 本地 HTTP 啟動（桌面端）
#   ./run.sh --tunnel      # 啟動 cloudflared HTTPS 隧道（手機可用）
#   PORT=8080 ./run.sh     # 自訂端口

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

USE_TUNNEL=false
for arg in "$@"; do
  case "$arg" in
    --tunnel|-t) USE_TUNNEL=true ;;
    --help|-h)
      echo "Usage: ./run.sh [--tunnel]"
      echo "  --tunnel  啟動 cloudflared HTTPS 隧道（手機語音對話必須）"
      exit 0
      ;;
  esac
done

PORT="${PORT:-8080}"
MINIMAX_API_KEY="${MINIMAX_API_KEY:-}"

echo "╔══════════════════════════════════════════════════╗"
echo "║  🏯 秦始皇數字人 — Digital Human                  ║"
echo "║  MiniMax LLM + TTS 流式 + WebSocket 全雙工        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Check Python ──
if ! command -v python3 &>/dev/null; then
    echo "❌ 未安裝 Python 3"
    exit 1
fi

# ── Check API Key ──
if [ -z "$MINIMAX_API_KEY" ]; then
    echo "⚠️  未設定 MINIMAX_API_KEY 環境變數"
    echo "   export MINIMAX_API_KEY='your-key-here'"
    echo ""
fi

# ── Create venv if needed ──
if [ ! -d ".venv" ]; then
    echo "📦 建立虛擬環境..."
    python3 -m venv .venv
fi

# ── Activate venv ──
source .venv/bin/activate

# ── Install dependencies ──
echo "📥 安裝依賴..."
pip install -q -r requirements.txt 2>&1 | tail -1

# ── Get local IP ──
LOCAL_IP=$(python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    ip = s.getsockname()[0]
    s.close()
    print(ip)
except:
    print('127.0.0.1')
")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 服務已啟動"
echo ""
echo "  🌐 本機訪問:  http://localhost:$PORT"
echo "  📱 區域網路:  http://$LOCAL_IP:$PORT"
echo ""

if $USE_TUNNEL; then
    # ── Start cloudflared tunnel for HTTPS ──
    if ! command -v cloudflared &>/dev/null; then
        echo "  ❌ 未安裝 cloudflared"
        echo "     brew install cloudflared"
        echo "     或 https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/"
        exit 1
    fi

    export PORT
    /opt/homebrew/bin/python3.13 server.py &
    SERVER_PID=$!
    sleep 2

    echo "  🔒 啟動 Cloudflare HTTPS 隧道..."
    echo "  ─────────────────────────────────────────────"
    cloudflared tunnel --url "http://localhost:$PORT" 2>&1 | while IFS= read -r line; do
        echo "  $line"
        if [[ "$line" == *"trycloudflare.com"* ]]; then
            URL=$(echo "$line" | grep -o 'https://[^ ]*trycloudflare\.com')
            echo ""
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "  📱 手機訪問這個網址即可語音對話："
            echo "  $URL"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        fi
    done

    kill $SERVER_PID 2>/dev/null || true
else
    echo "  💡 手機需語音? 用 ./run.sh --tunnel 啟動 HTTPS 隧道"
    echo ""
    echo "  ⌨️  按 Ctrl+C 關閉"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    export PORT
    exec /opt/homebrew/bin/python3.13 server.py
fi
