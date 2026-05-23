#!/bin/bash
# ── 秦始皇數字人 一鍵啟動 ──
# Digital Human — Qin Shi Huang for primary/secondary students

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ── Config ──
PORT="${PORT:-8080}"
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"

echo "╔══════════════════════════════════════════════════╗"
echo "║  🏯 秦始皇數字人 — Digital Human                  ║"
echo "║  粵語 TTS + DeepSeek + Canvas 角色動畫             ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Check Python ──
if ! command -v python3 &>/dev/null; then
    echo "❌ 未安裝 Python 3。請先安裝：https://www.python.org/"
    exit 1
fi

# ── Check API Key ──
if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "⚠️  未設定 DEEPSEEK_API_KEY 環境變數"
    echo ""
    echo "   請設定："
    echo "   export DEEPSEEK_API_KEY='sk-your-key-here'"
    echo ""
    echo "   取得 API Key: https://platform.deepseek.com/api_keys"
    echo ""
    # Don't exit — allow running without key for testing
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
echo "  💡 用你嘅手機掃以下 QR Code 就可以打開："
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Generate QR code in terminal ──
python3 -c "
import sys
try:
    import qrcode
    qr = qrcode.QRCode(border=1)
    qr.add_data('http://$LOCAL_IP:$PORT')
    qr.make(fit=True)
    qr.print_ascii(invert=True)
except ImportError:
    # Fallback: simple text-based QR
    url = 'http://$LOCAL_IP:$PORT'
    print(f'  ╔══════════════════════════╗')
    print(f'  ║  {url:<24s}  ║')
    print(f'  ╚══════════════════════════╝')
    print('  (pip install qrcode 可以顯示 QR Code)')
" 2>/dev/null || echo "  http://$LOCAL_IP:$PORT"

echo ""
echo "  ⌨️  按 Ctrl+C 關閉伺服器"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Start server ──
export PORT
exec python3 server.py
