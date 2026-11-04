#!/usr/bin/env bash
# Выпускает HTTPS-сертификат, когда домен уже указывает на этот сервер.
set -uo pipefail
REGION=${REGION:-$(grep '^REGION=' /etc/salespeak.env | cut -d= -f2)}
if [[ "$REGION" == "ru" ]]; then D=(salespeak.ru www.salespeak.ru); else D=(kz.salespeak.ru); fi
IP=$(curl -fsS -4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
for d in "${D[@]}"; do
  R=$(getent ahostsv4 "$d" | awk 'NR==1{print $1}')
  if [[ "$R" != "$IP" ]]; then echo "Домен $d пока указывает на ${R:-ничего}, а сервер – $IP. Поменяйте DNS и запустите salespeak-cert через 15–30 минут."; exit 1; fi
done
ARGS=(); for d in "${D[@]}"; do ARGS+=(-d "$d"); done
certbot --nginx "${ARGS[@]}" --non-interactive --agree-tos -m anastasia.gavrish@gmail.com --redirect && echo "HTTPS включен."
