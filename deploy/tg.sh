#!/usr/bin/env bash
# Подключение Telegram-уведомлений о заявках.
# Перед запуском: создать бота у @BotFather и написать ему любое сообщение со своего аккаунта.
# Запуск на сервере под root: bash /opt/salespeak/deploy/tg.sh
set -euo pipefail
ENVF=/etc/salespeak.env
[[ -f "$ENVF" ]] || { echo "Нет $ENVF – сначала установите сайт."; exit 1; }

read -rsp "Вставьте токен бота от @BotFather (символы не видны) и нажмите Enter: " TOKEN </dev/tty; echo
TOKEN=$(echo "$TOKEN" | tr -d '[:space:]')
[[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo "Это не похоже на токен бота. Скопируйте его из @BotFather целиком и запустите снова."; exit 1; }

if ! curl -sS -m 15 -o /dev/null https://api.telegram.org; then
  echo "Сервер не может достучаться до Telegram (api.telegram.org). Похоже, доступ к Telegram из этого дата-центра ограничен."
  exit 2
fi
ME=$(curl -fsS -m 15 "https://api.telegram.org/bot$TOKEN/getMe" || true)
[[ "$ME" == *'"ok":true'* ]] || { echo "Telegram не принял токен. Проверьте, что скопировали его полностью."; exit 1; }

CHAT=$(curl -fsS -m 15 "https://api.telegram.org/bot$TOKEN/getUpdates" | python3 -c '
import sys, json
d = json.load(sys.stdin).get("result", [])
ids = [u["message"]["chat"]["id"] for u in d if "message" in u and u["message"]["chat"].get("type") == "private"]
print(ids[-1] if ids else "")')
if [[ -z "$CHAT" ]]; then
  echo "Бот пока не видит ваших сообщений. Откройте бота в Telegram, нажмите «Старт» или напишите ему «привет» и запустите команду снова."
  exit 1
fi

sed -i '/^TG_BOT_TOKEN=/d; /^TG_CHAT_ID=/d' "$ENVF"
printf 'TG_BOT_TOKEN=%s\nTG_CHAT_ID=%s\n' "$TOKEN" "$CHAT" >> "$ENVF"
chmod 600 "$ENVF"
systemctl restart salespeak

curl -fsS -m 15 -o /dev/null "https://api.telegram.org/bot$TOKEN/sendMessage" \
  --data-urlencode "chat_id=$CHAT" --data-urlencode "text=Готово: заявки с сайта a-gavrish.com будут приходить сюда." \
  && echo "Готово. Проверьте Telegram – бот прислал тестовое сообщение."
