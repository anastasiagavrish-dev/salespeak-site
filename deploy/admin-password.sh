#!/usr/bin/env bash
# Смена пароля админки заявок. Запуск на сервере под root: bash /opt/salespeak/deploy/admin-password.sh
set -euo pipefail
APP=/opt/salespeak
ENVF=/etc/salespeak.env
[[ -f "$ENVF" ]] || { echo "Нет $ENVF – сначала установите сайт."; exit 1; }
while true; do
  read -rsp "Новый пароль для админки (не меньше 10 символов, символы не видны): " P1 </dev/tty; echo
  read -rsp "Повторите пароль: " P2 </dev/tty; echo
  if [[ "$P1" == "$P2" && ${#P1} -ge 10 ]]; then break; fi
  echo "Пароли не совпали или короче 10 символов, еще раз."
done
HASH=$(cd "$APP/backend" && P="$P1" "$APP/venv/bin/python" -c 'import os,main;print(main.make_hash(os.environ["P"]))')
unset P1 P2
H="$HASH" python3 - "$ENVF" <<'PY'
import os, sys
p = sys.argv[1]
lines = [l for l in open(p).read().splitlines() if not l.startswith("ADMIN_PASSWORD_HASH=")]
lines.append("ADMIN_PASSWORD_HASH=" + os.environ["H"])
open(p, "w").write("\n".join(lines) + "\n")
PY
chmod 600 "$ENVF"
systemctl restart salespeak
echo "Готово. Входите в a-gavrish.com/admin с новым паролем."
