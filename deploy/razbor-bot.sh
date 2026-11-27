#!/usr/bin/env bash
# Установка бота «Разбор переписки» на сервер, где уже работает «Касса тает» (Yandex Cloud, Казахстан).
# Запуск: curl -fsSL https://raw.githubusercontent.com/anastasiagavrish-dev/salespeak-site/main/deploy/razbor-bot.sh | sudo bash
# Спросит токен нового бота от @BotFather (символы не видны). Код потом обновляется с GitHub вместе с «Кассой».
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите через sudo."; exit 1; }
APP=/opt/kassa-bot
ENVF=/etc/razbor-bot.env
[[ -d "$APP/.git" && -x "$APP-venv/bin/python" ]] || { echo "Не нашла установленный бот «Касса тает» в $APP – этот бот ставится на тот же сервер."; exit 1; }

echo "Забираю свежий код с GitHub…"
git -C "$APP" fetch -q origin main && git -C "$APP" reset -q --hard origin/main
"$APP-venv/bin/pip" install -q -r "$APP/bot/requirements.txt"

if [[ ! -f "$ENVF" ]] || [[ "${1:-}" == "--reset" ]]; then
  read -rsp "Вставьте токен нового бота от @BotFather (символы не видны) и нажмите Enter: " TOKEN </dev/tty; echo
  TOKEN=$(echo "$TOKEN" | tr -d '[:space:]')
  [[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo "Это не похоже на токен бота. Скопируйте его из @BotFather целиком и запустите снова."; exit 1; }
  ME=$(curl -fsS -m 15 "https://api.telegram.org/bot$TOKEN/getMe" || true)
  [[ "$ME" == *'"ok":true'* ]] || { echo "Telegram не принял токен. Проверьте, что скопировали его полностью."; exit 1; }
  if grep -q "TG_BOT_TOKEN=$TOKEN" /etc/kassa-bot.env 2>/dev/null; then
    echo "Это токен бота «Касса тает». Для разборов нужен новый бот – создайте его в @BotFather командой /newbot."; exit 1
  fi
  umask 077
  printf 'RAZBOR_BOT_TOKEN=%s\nADMIN_USERNAMES=gavrish_anastasiya\nANSWER_DAYS=3–5 дней\n' "$TOKEN" > "$ENVF"
  umask 022
fi
chown root:kassabot "$ENVF"; chmod 640 "$ENVF"
mkdir -p /var/lib/razbor-bot && chown kassabot:kassabot /var/lib/razbor-bot

cat > /etc/systemd/system/razbor-bot.service <<EOF
[Unit]
Description=Telegram-бот «Разбор переписки»
After=network-online.target
Wants=network-online.target

[Service]
User=kassabot
WorkingDirectory=$APP/bot
EnvironmentFile=$ENVF
Environment=BOT_DATA=/var/lib/razbor-bot
ExecStart=$APP-venv/bin/python razbor_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Автообновление: «Касса» уже забирает код каждые 10 минут – добавляем перезапуск и этого бота
UPD=/usr/local/bin/kassa-bot-update
if [[ -f "$UPD" ]] && ! grep -q razbor-bot "$UPD"; then
  sed -i 's/^\(\s*\)systemctl restart kassa-bot$/&\n\1systemctl try-restart razbor-bot 2>\/dev\/null || true/' "$UPD"
fi

systemctl daemon-reload
systemctl enable -q --now razbor-bot
systemctl restart razbor-bot
sleep 4
if systemctl is-active -q razbor-bot; then
  NAME=$(curl -fsS -m 15 "https://api.telegram.org/bot$(grep '^RAZBOR_BOT_TOKEN=' "$ENVF" | cut -d= -f2)/getMe" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["username"])' || true)
  echo "Готово. Бот запущен: https://t.me/$NAME"
  echo "Откройте его со своего аккаунта @gavrish_anastasiya и нажмите «Старт» – после этого заявки начнут приходить вам."
else
  echo "Бот не запустился. Последние строки журнала:"; journalctl -u razbor-bot -n 20 --no-pager
fi
