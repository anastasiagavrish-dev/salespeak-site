#!/usr/bin/env bash
# Забирает обновления сайта с GitHub. Перезапускает бэкенд, только если менялся его код.
set -euo pipefail
APP=/opt/salespeak
cd "$APP"
OLD=$(git rev-parse HEAD)
git fetch -q origin main
NEW=$(git rev-parse origin/main)
[[ "$OLD" == "$NEW" ]] && exit 0
git reset -q --hard origin/main
if git diff --name-only "$OLD" "$NEW" | grep -q '^backend/'; then
  "$APP/venv/bin/pip" install -q -r "$APP/backend/requirements.txt"
  systemctl restart salespeak
fi
if git diff --name-only "$OLD" "$NEW" | grep -q '^deploy/nginx-'; then
  REGION=$(grep '^REGION=' /etc/salespeak.env | cut -d= -f2)
  cp "$APP/deploy/nginx-$REGION.conf" /etc/nginx/sites-available/salespeak && nginx -t -q && systemctl reload nginx
fi
echo "Обновлено до $NEW"
