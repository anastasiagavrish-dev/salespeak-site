#!/usr/bin/env bash
# Установка Telegram-бота «Касса тает» (игра по продажам).
# Запуск на сервере под root: bash /opt/salespeak/deploy/kassa-bot.sh
# Спросит токен бота, ID каталога и API-ключ Yandex Cloud. Символы токена и ключа не видны при вводе.
set -euo pipefail
APP=/opt/salespeak
ENVF=/etc/kassa-bot.env
cd "$APP" && git fetch -q origin main && git reset -q --hard origin/main
[[ -f "$APP/bot/kassa_bot.py" ]] || { echo "Нет кода бота в $APP/bot – обновление с GitHub не прошло."; exit 1; }

read -rsp "1/3. Вставьте токен бота от @BotFather (символы не видны) и нажмите Enter: " TOKEN </dev/tty; echo
TOKEN=$(echo "$TOKEN" | tr -d '[:space:]')
[[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo "Это не похоже на токен бота. Скопируйте его из @BotFather целиком и запустите снова."; exit 1; }
ME=$(curl -fsS -m 15 "https://api.telegram.org/bot$TOKEN/getMe" || true)
[[ "$ME" == *'"ok":true'* ]] || { echo "Telegram не принял токен. Проверьте, что скопировали его полностью."; exit 1; }

read -rp "2/3. Вставьте идентификатор каталога Yandex Cloud (из адресной строки консоли, после /folders/) и нажмите Enter: " FOLDER </dev/tty
FOLDER=$(echo "$FOLDER" | tr -d '[:space:]')
[[ "$FOLDER" =~ ^[a-z0-9]{10,}$ ]] || { echo "Это не похоже на идентификатор каталога. Скопируйте его из консоли Yandex Cloud."; exit 1; }

read -rsp "3/3. Вставьте API-ключ сервисного аккаунта (символы не видны) и нажмите Enter: " KEY </dev/tty; echo
KEY=$(echo "$KEY" | tr -d '[:space:]')
[[ ${#KEY} -ge 20 ]] || { echo "Ключ слишком короткий. Скопируйте его целиком и запустите снова."; exit 1; }

echo "Проверяю доступ к YandexGPT…"
CODE=$(curl -sS -m 60 -o /tmp/kassa-yc-test.json -w '%{http_code}' https://ai.api.cloud.yandex.net/v1/chat/completions \
  -H "Authorization: Api-Key $KEY" -H "OpenAI-Project: $FOLDER" -H 'Content-Type: application/json' \
  -d "{\"model\":\"gpt://$FOLDER/yandexgpt/latest\",\"max_tokens\":20,\"messages\":[{\"role\":\"user\",\"content\":\"Ответь одним словом: привет\"}]}" || true)
if [[ "$CODE" != "200" ]]; then
  echo "YandexGPT ответил кодом $CODE:"; head -c 400 /tmp/kassa-yc-test.json; echo
  echo "Проверьте ключ, идентификатор каталога, роль ai.languageModels.user у сервисного аккаунта и привязку платежного аккаунта."
  rm -f /tmp/kassa-yc-test.json; exit 1
fi
rm -f /tmp/kassa-yc-test.json
echo "YandexGPT отвечает."

umask 077
printf 'TG_BOT_TOKEN=%s\nYC_FOLDER_ID=%s\nYC_API_KEY=%s\nYC_MODEL=yandexgpt/latest\nGAMES_PER_DAY=3\nCONTACT=gavrish_anastasiya\n' "$TOKEN" "$FOLDER" "$KEY" > "$ENVF"
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
