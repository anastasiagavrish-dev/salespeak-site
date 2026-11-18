#!/usr/bin/env bash
# Подключение уведомлений о заявках через веб-приложение Google Apps Script (письмо на Gmail и Telegram).
# Запуск на сервере под root: bash /opt/salespeak/deploy/notify.sh
set -euo pipefail
ENVF=/etc/salespeak.env
[[ -f "$ENVF" ]] || { echo "Нет $ENVF – сначала установите сайт."; exit 1; }

read -rp "Вставьте адрес веб-приложения (https://script.google.com/macros/s/.../exec) и нажмите Enter: " URL </dev/tty
URL=$(echo "$URL" | tr -d '[:space:]')
[[ "$URL" =~ ^https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec$ ]] || { echo "Это не похоже на адрес веб-приложения. Он должен начинаться с https://script.google.com/macros/s/ и заканчиваться на /exec."; exit 1; }

sed -i '/^NOTIFY_URL=/d' "$ENVF"
echo "NOTIFY_URL=$URL" >> "$ENVF"
chmod 600 "$ENVF"
systemctl restart salespeak

if curl -fsS -L -m 30 -o /dev/null -H "Content-Type: application/json" \
     -d '{"text":"Проверка с сервера: заявки с сайта a-gavrish.com будут приходить сюда."}' "$URL"; then
  echo "Готово. Проверьте почту (и Telegram, если подключали) – должно прийти тестовое сообщение."
else
  echo "Адрес сохранен, но тестовое сообщение не ушло. Проверьте, что при развертывании выбран доступ «Все» (Anyone)."
fi
