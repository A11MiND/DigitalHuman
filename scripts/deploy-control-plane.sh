#!/usr/bin/env bash
set -euo pipefail

REMOTE="${REMOTE:-ec2-dh}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/DigitalHuman}"
STAMP="$(date +%Y%m%d-%H%M%S)"

files=(
  ops_control.py
  static/control.html
  static/ops.html
  deploy/digitalhuman-service-control
  deploy/digitalhuman-control.sudoers
  deploy/digitalhuman-control.service
  deploy/digitalhuman-nginx.conf
)

echo "Deploying independent control plane to ${REMOTE}:${REMOTE_DIR}"
echo "Backup stamp: ${STAMP}"

for file in "${files[@]}"; do
  [[ -f "$file" ]] || { echo "Missing local file: $file" >&2; exit 1; }
  remote_path="${REMOTE_DIR}/${file}"
  ssh "$REMOTE" "mkdir -p \"$(dirname "$remote_path")\"; if [ -f \"$remote_path\" ]; then cp \"$remote_path\" \"$remote_path.bak-${STAMP}\"; fi"
  scp "$file" "${REMOTE}:${remote_path}"
  echo "Uploaded $file"
done

ssh "$REMOTE" "
  set -e
  sudo cp /etc/nginx/sites-available/digitalhuman.conf /etc/nginx/sites-available/digitalhuman.conf.bak-${STAMP}
  sudo mkdir -p /etc/nginx/sites-available/backups
  sudo cp /etc/nginx/sites-enabled/digitalhuman.conf /etc/nginx/sites-available/backups/digitalhuman-enabled.conf.bak-${STAMP}
  sudo install -o root -g root -m 0755 ${REMOTE_DIR}/deploy/digitalhuman-service-control /usr/local/sbin/digitalhuman-service-control
  sudo install -o root -g root -m 0440 ${REMOTE_DIR}/deploy/digitalhuman-control.sudoers /etc/sudoers.d/digitalhuman-control
  sudo visudo -cf /etc/sudoers.d/digitalhuman-control
  sudo install -o root -g root -m 0644 ${REMOTE_DIR}/deploy/digitalhuman-control.service /etc/systemd/system/digitalhuman-control.service
  sudo install -o root -g root -m 0644 ${REMOTE_DIR}/deploy/digitalhuman-nginx.conf /etc/nginx/sites-available/digitalhuman.conf
  sudo install -o root -g root -m 0644 ${REMOTE_DIR}/deploy/digitalhuman-nginx.conf /etc/nginx/sites-enabled/digitalhuman.conf
  sudo nginx -t
  sudo systemctl daemon-reload
  sudo systemctl enable --now digitalhuman-control.service
  sudo systemctl restart digitalhuman-control.service
  sudo systemctl reload nginx
  systemctl is-active digitalhuman-control.service
  systemctl is-active digitalhuman.service
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS http://127.0.0.1:8081/api/control/ping; then
      exit 0
    fi
    sleep 1
  done
  echo 'Control plane did not become ready within 10 seconds' >&2
  exit 1
"

echo
echo "Control plane deployed: https://digitalhumanpalace.duckdns.org:8443/control"
