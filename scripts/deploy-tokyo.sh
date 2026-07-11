#!/usr/bin/env bash
set -euo pipefail

REMOTE="${REMOTE:-ec2-dh}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/DigitalHuman}"
HEALTH_URL="${HEALTH_URL:-http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/health}"
STAMP="$(date +%Y%m%d-%H%M%S)"
RESTART=auto

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-tokyo.sh [--restart|--no-restart] [files...]

Examples:
  scripts/deploy-tokyo.sh static/ops.html
  scripts/deploy-tokyo.sh server.py static/ops.html
  scripts/deploy-tokyo.sh --restart server.py static/ops.html

Defaults:
  - If no files are provided, deploy server.py and static/ops.html.
  - The service restarts automatically when server.py is deployed.
EOF
}

files=()
while (($#)); do
  case "$1" in
    --restart) RESTART=yes ;;
    --no-restart) RESTART=no ;;
    -h|--help) usage; exit 0 ;;
    *) files+=("$1") ;;
  esac
  shift
done

if ((${#files[@]} == 0)); then
  files=(server.py static/ops.html)
fi

needs_restart=false
if [[ "$RESTART" == "yes" ]]; then
  needs_restart=true
elif [[ "$RESTART" == "auto" ]]; then
  for f in "${files[@]}"; do
    [[ "$f" == "server.py" ]] && needs_restart=true
  done
fi

echo "Deploying to ${REMOTE}:${REMOTE_DIR}"
echo "Backup stamp: ${STAMP}"

for f in "${files[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing local file: $f" >&2
    exit 1
  fi
  remote_path="${REMOTE_DIR}/${f}"
  ssh "$REMOTE" "mkdir -p \"$(dirname "$remote_path")\" && if [ -f \"$remote_path\" ]; then cp \"$remote_path\" \"$remote_path.bak-$STAMP\"; fi"
  scp "$f" "${REMOTE}:${remote_path}"
  echo "Uploaded $f"
done

if [[ "$needs_restart" == true && "$RESTART" != "no" ]]; then
  ssh "$REMOTE" "sudo systemctl restart digitalhuman.service && systemctl is-active digitalhuman.service"
else
  echo "Static-only deploy: service restart skipped"
fi

for attempt in {1..12}; do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    echo "Health OK: $HEALTH_URL"
    exit 0
  fi
  echo "Health not ready, retrying (${attempt}/12)..."
  sleep 2
done

echo "Health check failed after restart: $HEALTH_URL" >&2
exit 1
