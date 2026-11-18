#!/usr/bin/env bash
# Выпускает HTTPS-сертификаты для доменов, которые уже указывают на этот сервер, и подключает их в nginx.
# Группы: main – основной сайт, old – старый домен с редиректом. Уже выпущенные пропускает.
# Запуск: salespeak-cert (EMAIL=... для первой регистрации в Let's Encrypt берется из install.sh).
set -uo pipefail
# Не запускаться параллельно (установка и таймер обновлений могут стартовать одновременно)
exec 9>/run/salespeak-cert.lock
flock -w 120 9 || { echo "salespeak-cert уже выполняется, попробуйте через пару минут."; exit 0; }
REGION=${REGION:-$(grep '^REGION=' /etc/salespeak.env | cut -d= -f2)}
if [[ "$REGION" == "ru" ]]; then
  GROUPS_LIST=("main:a-gavrish.com www.a-gavrish.com" "old:salespeak.ru www.salespeak.ru")
else
  GROUPS_LIST=("main:kz.a-gavrish.com")
fi
EMAIL=${EMAIL:-$(grep '^CERT_EMAIL=' /etc/salespeak.env 2>/dev/null | cut -d= -f2)}
SSL_DIR=/etc/nginx/salespeak-ssl
WEBROOT=/var/www/certbot
mkdir -p "$SSL_DIR" "$WEBROOT"
IP=$(curl -fsS -4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

ACC=(--agree-tos)
if [[ ! -d /etc/letsencrypt/accounts ]]; then
  if [[ -n "${EMAIL:-}" ]]; then ACC+=(-m "$EMAIL"); else ACC+=(--register-unsafely-without-email); fi
fi

changed=0; fail=0
for g in "${GROUPS_LIST[@]}"; do
  name=${g%%:*}; read -ra D <<< "${g#*:}"
  if [[ -f "$SSL_DIR/$name.conf" && -f "/etc/letsencrypt/live/$name/fullchain.pem" ]]; then
    echo "HTTPS для ${D[*]} уже работает."; continue
  fi
  ok=1
  for d in "${D[@]}"; do
    R=$(getent ahostsv4 "$d" | awk 'NR==1{print $1}')
    if [[ "$R" != "$IP" ]]; then echo "Домен $d пока указывает на ${R:-ничего}, а сервер – $IP. Поменяйте DNS и запустите salespeak-cert через 15–30 минут."; ok=0; fi
  done
  [[ $ok == 1 ]] || { fail=1; continue; }
  ARGS=(); for d in "${D[@]}"; do ARGS+=(-d "$d"); done
  if certbot certonly --webroot -w "$WEBROOT" --cert-name "$name" "${ARGS[@]}" --non-interactive "${ACC[@]}" \
       --deploy-hook "systemctl reload nginx" >/dev/null; then
    cat > "$SSL_DIR/$name.conf" <<EOF
listen 443 ssl http2;
ssl_certificate /etc/letsencrypt/live/$name/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/$name/privkey.pem;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_session_cache shared:salespeak_$name:5m;
if (\$scheme = http) { return 301 https://\$host\$request_uri; }
EOF
    changed=1; echo "HTTPS включен для ${D[*]}."
  else
    echo "Не удалось выпустить сертификат для ${D[*]}."; fail=1
  fi
done
if [[ $changed == 1 ]]; then nginx -t -q && systemctl reload nginx; fi
exit $fail
