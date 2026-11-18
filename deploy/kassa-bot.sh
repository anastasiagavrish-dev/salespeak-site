#!/usr/bin/env bash
# Установка Telegram-бота «Касса тает» (игра по продажам).
# Запуск на сервере под root: bash /opt/salespeak/deploy/kassa-bot.sh
# Спросит токен бота и API-ключ DeepSeek. Символы не видны при вводе.
set -euo pipefail
APP=/opt/salespeak
ENVF=/etc/kassa-bot.env
cd "$APP" && git fetch -q origin main && git reset -q --hard origin/main
[[ -f "$APP/bot/kassa_bot.py" ]] || { echo "Нет кода бота в $APP/bot – обновление с GitHub не прошло."; exit 1; }

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
chown root:salespeak "$ENVF"; chmod 640 "$ENVF"
umask 022

python3 -m venv "$APP/bot-venv"
"$APP/bot-venv/bin/pip" install -q --upgrade pip
"$APP/bot-venv/bin/pip" install -q -r "$APP/bot/requirements.txt"
mkdir -p /var/lib/kassa-bot && chown salespeak:salespeak /var/lib/kassa-bot
install -m 644 "$APP/deploy/kassa-bot.service" /etc/systemd/system/kassa-bot.service
install -m 755 "$APP/deploy/update.sh" /usr/local/bin/salespeak-update
systemctl daemon-reload
systemctl enable -q --now kassa-bot
systemctl restart kassa-bot
sleep 4
if systemctl is-active -q kassa-bot; then
  NAME=$(echo "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["username"])')
  echo "Готово. Бот запущен – откройте https://t.me/$NAME и нажмите «Старт»."
else
  echo "Бот не запустился. Последние строки журнала:"; journalctl -u kassa-bot -n 20 --no-pager
fi
