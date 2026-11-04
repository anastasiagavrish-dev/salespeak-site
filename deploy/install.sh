#!/usr/bin/env bash
# Установка сайта salespeak.ru на чистый сервер Ubuntu 22.04/24.04.
# Запуск из консоли сервера под root:
#   curl -fsSL https://raw.githubusercontent.com/anastasiagavrish-dev/salespeak-site/main/deploy/install.sh | bash -s -- ru
#   curl -fsSL https://raw.githubusercontent.com/anastasiagavrish-dev/salespeak-site/main/deploy/install.sh | bash -s -- kz
set -euo pipefail

REGION="${1:-}"
if [[ "$REGION" != "ru" && "$REGION" != "kz" ]]; then echo "Укажите регион: ru или kz"; exit 1; fi
REPO="https://github.com/anastasiagavrish-dev/salespeak-site.git"
APP=/opt/salespeak
DATA=/var/lib/salespeak
ENVF=/etc/salespeak.env
EMAIL="anastasia.gavrish@gmail.com"
if [[ "$REGION" == "ru" ]]; then DOMAINS=(salespeak.ru www.salespeak.ru); ADMIN_BASE="https://salespeak.ru/admin"
else DOMAINS=(kz.salespeak.ru); ADMIN_BASE="https://kz.salespeak.ru/admin"; fi

say(){ printf '\n\033[1;35m▶ %s\033[0m\n' "$1"; }

say "1/8 Устанавливаю пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx python3-venv sqlite3 git ufw certbot python3-certbot-nginx curl >/dev/null

say "2/8 Скачиваю сайт"
id salespeak >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin salespeak
if [[ -d "$APP/.git" ]]; then git -C "$APP" pull --ff-only -q; else git clone -q "$REPO" "$APP"; fi
git config --global --add safe.directory "$APP"
mkdir -p "$DATA/backups"; chown -R salespeak:salespeak "$DATA"

say "3/8 Готовлю бэкенд заявок"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/backend/requirements.txt"

say "4/8 Настройки и пароль админки"
if [[ ! -f "$ENVF" ]]; then
  while true; do
    read -rsp "Придумайте пароль для админки заявок (не меньше 10 символов): " P1 </dev/tty; echo
    read -rsp "Повторите пароль: " P2 </dev/tty; echo
    if [[ "$P1" == "$P2" && ${#P1} -ge 10 ]]; then break; fi
    echo "Пароли не совпали или короче 10 символов, еще раз."
  done
  HASH=$(cd "$APP/backend" && P="$P1" "$APP/venv/bin/python" -c 'import os,main;print(main.make_hash(os.environ["P"]))')
  unset P1 P2
  read -rp "Токен Telegram-бота (Enter – пропустить, можно добавить позже): " TG </dev/tty
  read -rp "Ваш chat_id в Telegram (Enter – пропустить): " TGC </dev/tty
  umask 077
  cat > "$ENVF" <<EOF
REGION=$REGION
DB_PATH=$DATA/leads.sqlite3
SITE_ORIGIN=https://salespeak.ru
ADMIN_BASE=$ADMIN_BASE
ADMIN_PASSWORD_HASH=$HASH
SESSION_SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
TG_BOT_TOKEN=$TG
TG_CHAT_ID=$TGC
CONSENT_VERSION=2026-11-03
EOF
  chmod 600 "$ENVF"
else
  echo "Настройки уже есть в $ENVF, оставляю как есть."
fi

say "5/8 Запускаю сервис"
cp "$APP/deploy/salespeak.service" /etc/systemd/system/salespeak.service
cp "$APP/deploy/salespeak-update.service" "$APP/deploy/salespeak-update.timer" /etc/systemd/system/
install -m 755 "$APP/deploy/update.sh" /usr/local/bin/salespeak-update
install -m 755 "$APP/deploy/cert.sh" /usr/local/bin/salespeak-cert
systemctl daemon-reload
systemctl enable --now salespeak.service salespeak-update.timer >/dev/null
sleep 2; systemctl is-active --quiet salespeak && echo "Бэкенд работает."

say "6/8 Настраиваю nginx"
cp "$APP/deploy/nginx-$REGION.conf" /etc/nginx/sites-available/salespeak
ln -sf /etc/nginx/sites-available/salespeak /etc/nginx/sites-enabled/salespeak
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx

say "7/8 Файрвол и бэкапы"
ufw allow OpenSSH >/dev/null; ufw allow 'Nginx Full' >/dev/null; ufw --force enable >/dev/null
cat > /etc/cron.d/salespeak-backup <<EOF
0 4 * * * salespeak sqlite3 $DATA/leads.sqlite3 ".backup $DATA/backups/leads-\$(date +\%F).sqlite3" && ls -t $DATA/backups/*.sqlite3 | tail -n +31 | xargs -r rm -f
EOF

say "8/8 HTTPS"
REGION="$REGION" /usr/local/bin/salespeak-cert || true

IP=$(curl -fsS -4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo
echo "Готово. IP сервера: $IP"
echo "Если HTTPS еще не выпущен, направьте домен ${DOMAINS[*]} на $IP и выполните: salespeak-cert"
