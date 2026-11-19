#!/usr/bin/env bash
# Установка Telegram-бота «Касса тает» на отдельный сервер (Ubuntu), где доступен Telegram.
# Запуск: curl -fsSL https://raw.githubusercontent.com/anastasiagavrish-dev/salespeak-site/main/deploy/kassa-bot-standalone.sh | sudo bash
# Спросит токен бота и API-ключ DeepSeek. Символы не видны при вводе. Код бота потом обновляется с GitHub сам каждые 10 минут.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите через sudo."; exit 1; }
APP=/opt/kassa-bot
REPO=https://github.com/anastasiagavrish-dev/salespeak-site
ENVF=/etc/kassa-bot.env

echo "Ставлю нужные пакеты…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git python3-venv curl >/dev/null

if ! curl -sS -m 15 -o /dev/null https://api.telegram.org; then
  echo "С этого сервера не открывается api.telegram.org – Telegram здесь недоступен. Нужен сервер в другой стране."; exit 2
fi

if [[ -d "$APP/.git" ]]; then git -C "$APP" fetch -q origin main && git -C "$APP" reset -q --hard origin/main
else git clone -q --depth 1 "$REPO" "$APP"; fi
id -u kassabot >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -d /var/lib/kassa-bot kassabot

if [[ ! -f "$ENVF" ]] || [[ "${1:-}" == "--reset" ]]; then
  read -rsp "1/2. Вставьте токен бота от @BotFather (символы не видны) и нажмите Enter: " TOKEN </dev/tty; echo
  TOKEN=$(echo "$TOKEN" | tr -d '[:space:]')
  [[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo "Это не похоже на токен бота. Скопируйте его из @BotFather целиком и запустите снова."; exit 1; }
  ME=$(curl -fsS -m 15 "https://api.telegram.org/bot$TOKEN/getMe" || true)
  [[ "$ME" == *'"ok":true'* ]] || { echo "Telegram не принял токен. Проверьте, что скопировали его полностью."; exit 1; }

  read -rsp "2/2. Вставьте API-ключ DeepSeek (начинается на sk-, символы не видны) и нажмите Enter: " KEY </dev/tty; echo
  KEY=$(echo "$KEY" | tr -d '[:space:]')
  [[ ${#KEY} -ge 20 ]] || { echo "Ключ слишком короткий. Скопируйте его целиком и запустите снова."; exit 1; }
  echo "Проверяю доступ к DeepSeek…"
  CODE=$(curl -sS -m 60 -o /tmp/kassa-llm-test.json -w '%{http_code}' https://api.deepseek.com/chat/completions \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d '{"model":"deepseek-flash","max_tokens":20,"messages":[{"role":"user","content":"Ответь одним словом: привет"}]}' || true)
  if [[ "$CODE" != "200" ]]; then
    echo "DeepSeek ответил кодом $CODE:"; head -c 400 /tmp/kassa-llm-test.json; echo
    echo "401 – неверный ключ, 402 – на балансе DeepSeek нет денег. Если кода нет совсем – сервер не достучался до api.deepseek.com."
    rm -f /tmp/kassa-llm-test.json; exit 1
  fi
  rm -f /tmp/kassa-llm-test.json
  echo "DeepSeek отвечает."
  umask 077
  printf 'TG_BOT_TOKEN=%s\nLLM_API_KEY=%s\nLLM_BASE=https://api.deepseek.com\nLLM_MODEL_FAST=deepseek-flash\nLLM_MODEL_SMART=deepseek-v4-pro\nGAMES_PER_DAY=3\nCONTACT=gavrish_anastasiya\n' "$TOKEN" "$KEY" > "$ENVF"
  umask 022
fi
chown root:kassabot "$ENVF"; chmod 640 "$ENVF"

# --- Веб-версия игры (Telegram Mini App и сайт): nginx + HTTPS ---
WEB_DOMAIN=${WEB_DOMAIN:-game.a-gavrish.com}
apt-get install -y -qq nginx certbot python3-certbot-nginx >/dev/null
cat > /etc/nginx/sites-available/kassa-web <<NGINX
server {
    listen 80;
    server_name $WEB_DOMAIN;
    client_max_body_size 256k;
    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 180s;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/kassa-web /etc/nginx/sites-enabled/kassa-web
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx
cat > /usr/local/bin/kassa-web-cert <<CERT
#!/usr/bin/env bash
# Выпускает HTTPS для $WEB_DOMAIN, как только домен указывает на этот сервер, и включает кнопку «Играть» в боте
set -uo pipefail
if [[ ! -d /etc/letsencrypt/live/$WEB_DOMAIN ]]; then
  MY=\$(curl -s4 -m 10 https://api.ipify.org || true)
  DNS=\$(getent ahostsv4 $WEB_DOMAIN | awk 'NR==1{print \$1}')
  if [[ -z "\$MY" || "\$MY" != "\$DNS" ]]; then echo "Домен $WEB_DOMAIN пока не указывает на этот сервер (\${DNS:-нет записи} вместо \$MY)"; exit 0; fi
  certbot --nginx -d $WEB_DOMAIN --non-interactive --agree-tos --register-unsafely-without-email --redirect -q || { echo "Не удалось выпустить сертификат – проверьте, что открыты порты 80 и 443"; exit 0; }
  echo "HTTPS для $WEB_DOMAIN выпущен"
fi
if ! grep -q '^WEBAPP_URL=' $ENVF; then
  echo "WEBAPP_URL=https://$WEB_DOMAIN" >> $ENVF
  systemctl restart kassa-bot
  echo "Кнопка «Играть» в боте включена – игра открывается по адресу https://$WEB_DOMAIN"
fi
CERT
chmod 755 /usr/local/bin/kassa-web-cert

python3 -m venv "$APP-venv"
"$APP-venv/bin/pip" install -q --upgrade pip
"$APP-venv/bin/pip" install -q -r "$APP/bot/requirements.txt"
mkdir -p /var/lib/kassa-bot && chown kassabot:kassabot /var/lib/kassa-bot

cat > /etc/systemd/system/kassa-bot.service <<EOF
[Unit]
Description=Telegram-бот «Касса тает»
After=network-online.target
Wants=network-online.target

[Service]
User=kassabot
WorkingDirectory=$APP/bot
EnvironmentFile=$ENVF
Environment=BOT_DATA=/var/lib/kassa-bot
ExecStart=$APP-venv/bin/python kassa_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Автообновление кода бота с GitHub раз в 10 минут
cat > /usr/local/bin/kassa-bot-update <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd $APP
OLD=\$(git rev-parse HEAD)
git fetch -q origin main
NEW=\$(git rev-parse origin/main)
/usr/local/bin/kassa-web-cert >/dev/null 2>&1 || true
[[ "\$OLD" == "\$NEW" ]] && exit 0
git reset -q --hard origin/main
if git diff --name-only "\$OLD" "\$NEW" | grep -q '^bot/'; then
  $APP-venv/bin/pip install -q -r $APP/bot/requirements.txt
  systemctl restart kassa-bot
  echo "Бот обновлен до \$NEW"
fi
EOF
chmod 755 /usr/local/bin/kassa-bot-update
cat > /etc/systemd/system/kassa-bot-update.service <<EOF
[Unit]
Description=Бот «Касса тает» – забрать обновления с GitHub
[Service]
Type=oneshot
ExecStart=/usr/local/bin/kassa-bot-update
EOF
cat > /etc/systemd/system/kassa-bot-update.timer <<EOF
[Unit]
Description=Бот «Касса тает» – проверять обновления каждые 10 минут
[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable -q --now kassa-bot kassa-bot-update.timer
systemctl restart kassa-bot
sleep 4
/usr/local/bin/kassa-web-cert || true
sleep 3
if systemctl is-active -q kassa-bot; then
  NAME=$(curl -fsS -m 15 "https://api.telegram.org/bot$(grep '^TG_BOT_TOKEN=' "$ENVF" | cut -d= -f2)/getMe" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["username"])' || true)
  echo "Готово. Бот запущен – откройте https://t.me/$NAME и нажмите «Старт»."
else
  echo "Бот не запустился. Последние строки журнала:"; journalctl -u kassa-bot -n 20 --no-pager
fi
