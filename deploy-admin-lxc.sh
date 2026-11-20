#!/usr/bin/env bash
# Веб-панель мониторинга бота внутри LXC-контейнера (классический LXC).
# Панель — отдельный сервис: БД бота только на чтение, код бота не изменяется.
# Слушает ЧАСТНЫЙ адрес контейнера; доступ — через SSH-туннель, наружу не выставляем.
#
#   sudo lxc-attach -n english-bot -- bash /opt/english-bot/deploy-admin-lxc.sh
#   PORT=9000 ADMIN_HOST=10.0.3.7 bash deploy-admin-lxc.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/english-bot}"
PORT="${PORT:-8080}"
ADMIN_USER="${ADMIN_USER:-admin}"

[ -f "${APP_DIR}/admin/server.py" ] || { echo "!! нет admin/server.py — сначала git pull"; exit 1; }

# Путь к базе берём из .env самого бота, а не угадываем
BOT_DB="$(grep -E '^DB_PATH=' "${APP_DIR}/.env" | tail -1 | cut -d= -f2- || true)"
BOT_DB="${BOT_DB:-english_bot.db}"
case "$BOT_DB" in /*) ;; *) BOT_DB="${APP_DIR}/${BOT_DB}";; esac
[ -f "$BOT_DB" ] || { echo "!! база не найдена: $BOT_DB"; exit 1; }

HOST_IP="${ADMIN_HOST:-$(hostname -I | awk '{print $1}')}"
HOST_IP="${HOST_IP:-127.0.0.1}"

ENVF="${APP_DIR}/.env.admin"
if [ -f "$ENVF" ] && grep -q '^ADMIN_PASSWORD=..*' "$ENVF"; then
    ADMIN_PASSWORD="$(grep '^ADMIN_PASSWORD=' "$ENVF" | cut -d= -f2-)"
    echo "==> используем существующий пароль из ${ENVF}"
else
    ADMIN_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 18)"
fi

cat > "$ENVF" <<EOF
ADMIN_USER=${ADMIN_USER}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
DB_PATH=${BOT_DB}
BOT_SERVICE=english-bot
PROJECT_WRITE=off
ADMIN_HOST=${HOST_IP}
ADMIN_PORT=${PORT}
EOF
chmod 600 "$ENVF"
grep -q '^\.env\.admin$' "${APP_DIR}/.gitignore" 2>/dev/null || echo ".env.admin" >> "${APP_DIR}/.gitignore"

PY="${APP_DIR}/venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"

cat > /etc/systemd/system/english-admin.service <<EOF
[Unit]
Description=English Bot Admin Panel (private address only)
After=network-online.target english-bot.service

[Service]
Type=simple
EnvironmentFile=${ENVF}
WorkingDirectory=${APP_DIR}
ExecStart=${PY} ${APP_DIR}/admin/server.py --host ${HOST_IP} --port ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now english-admin
sleep 2
systemctl is-active english-admin

cat <<TXT

Панель: http://${HOST_IP}:${PORT}  (частный адрес, снаружи недоступна)
  логин:  ${ADMIN_USER}
  пароль: ${ADMIN_PASSWORD}   (в ${ENVF}, chmod 600)

Доступ с ноутбука — SSH-туннель через хост VPS:
  ssh -L ${PORT}:${HOST_IP}:${PORT} root@IP_ХОСТА
  браузер: http://localhost:${PORT}

Запись кода из панели выключена (PROJECT_WRITE=off) — правки через git.
Логи: journalctl -u english-admin -f
TXT
