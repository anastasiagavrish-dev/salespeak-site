#!/usr/bin/env bash
# Забирает обновления сайта с GitHub. Перезапускает бэкенд, только если менялся его код.
# Сам обновляет служебные скрипты и выпускает HTTPS, как только домен начинает указывать на сервер.
set -euo pipefail
APP=/opt/salespeak
cd "$APP"
OLD=$(git rev-parse HEAD)
git fetch -q origin main
NEW=$(git rev-parse origin/main)
if [[ "$OLD" != "$NEW" ]]; then
  # Копия текущего рабочего сайта: git reset вернет в public/ старые файлы из репозитория,
  # и если новая сборка не пройдет проверку, сайт восстановится из этой копии
  LAST=/opt/salespeak-public.last
  if [[ -f "$APP/public/index.html" ]]; then
    rm -rf "$LAST" && cp -a "$APP/public" "$LAST" || true
  fi
  git reset -q --hard origin/main
  install -m 755 "$APP/deploy/update.sh" /usr/local/bin/salespeak-update
  install -m 755 "$APP/deploy/cert.sh" /usr/local/bin/salespeak-cert
  # Страницы собираются на сервере из gen.py и content.py. Сборка подменяет public/ только целиком
  # и после проверки (sitemap.xml, robots.txt, все страницы в карте). Если проверка не прошла, причина
  # пишется в журнал (journalctl -u salespeak-update), а остальное обновление продолжается.
  if ! python3 gen.py >/dev/null; then
    if [[ -f "$LAST/index.html" ]]; then
      rm -rf "$APP/public" && cp -a "$LAST" "$APP/public"
      echo "ОШИБКА: сборка сайта не прошла, восстановлена предыдущая рабочая версия"
    else
      echo "ОШИБКА: сборка сайта не прошла"
    fi
  fi
  if git diff --name-only "$OLD" "$NEW" | grep -q '^backend/'; then
    "$APP/venv/bin/pip" install -q -r "$APP/backend/requirements.txt"
    systemctl restart salespeak
  fi
  # Бот «Касса тает» – только если он уже установлен (deploy/kassa-bot.sh)
  if [[ -f /etc/kassa-bot.env ]] && git diff --name-only "$OLD" "$NEW" | grep -q -e '^bot/' -e '^deploy/kassa-bot.service'; then
    "$APP/bot-venv/bin/pip" install -q -r "$APP/bot/requirements.txt"
    install -m 644 "$APP/deploy/kassa-bot.service" /etc/systemd/system/kassa-bot.service && systemctl daemon-reload
    systemctl restart kassa-bot
  fi
  if git diff --name-only "$OLD" "$NEW" | grep -q '^deploy/nginx-'; then
    REGION=$(grep '^REGION=' /etc/salespeak.env | cut -d= -f2)
    mkdir -p /etc/nginx/salespeak-ssl /var/www/certbot
    cp "$APP/deploy/nginx-$REGION.conf" /etc/nginx/sites-available/salespeak && nginx -t -q && systemctl reload nginx
  fi
  echo "Обновлено до $NEW"
fi
# Сертификаты: пробуем раз в 10 минут, пока не выпустятся все (тихо, без ошибок в журнале)
/usr/local/bin/salespeak-cert >/dev/null 2>&1 || true
