#!/usr/bin/env bash
# ============================================================
# Установка ВЕБ-ПАНЕЛИ МОНИТОРИНГА бота внутри LXC-контейнера
# (классический LXC: запускать через lxc-attach с хоста Kali).
#
# Панель — ОТДЕЛЬНЫЙ сервис. Код бота НЕ изменяется и НЕ перезапускается;
# панель только читает SQLite-БД бота (режим read-only), показывает её
# статистику, логи, состояние сервиса и даёт браузерный редактор кода
# для модернизации (+ кнопка «перезапустить бота» по желанию админа).
#
#   sudo ./deploy-admin-lxc.sh              # установить в контейнер english-bot
#   CT_NAME=myct PORT=9000 ./deploy-admin-lxc.sh
#
# С хоста можно вызвать и так:
#   sudo lxc-attach -n english-bot -- bash /opt/english-bot/deploy-admin-lxc.sh
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/english-bot}"
PORT="${PORT:-8080}"
ADMIN_USER="${ADMIN_USER:-admin}"

if [ ! -f "${APP_DIR}/admin/server.py" ]; then
    echo "!! ${APP_DIR}/admin/server.py не найден. Сначала скопируйте проект:"
    echo "   sudo ./deploy-lxc-nodocker-classic.sh attach"
    exit 1
fi

echo "==> Копируем файлы панели в ${APP_DIR} (если скрипт запускается не из папки проекта)..."
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${SRC}" != "${APP_DIR}" ] && [ -d "${SRC}/admin" ]; then
    mkdir -p "${APP_DIR}/admin"
    cp -f "${SRC}/admin/"*.py "${APP_DIR}/admin/" 2>/dev/null || true
    cp -f "${SRC}/deploy-admin-lxc.sh" "${APP_DIR}/" 2>/dev/null || true
fi

# Пароль: существующий сохраняем, иначе генерируем
ENVF="${APP_DIR}/.env.admin"
if [ -f "${ENVF}" ] && grep -q '^ADMIN_PASSWORD=' "${ENVF}"; then
    ADMIN_PASSWORD="$(grep '^ADMIN_PASSWORD=' "${ENVF}" | cut -d= -f2-)"
    echo "==> Используем существующий пароль из ${ENVF}"
else
    ADMIN_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 16)"
    cat > "${ENVF}" <<EOF
# Секреты веб-панели мониторинга (не коммитить!)
ADMIN_USER=${ADMIN_USER}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
DB_PATH=${APP_DIR}/db/english_bot.db
BOT_SERVICE=english-bot
PROJECT_WRITE=on
EOF
    chmod 600 "${ENVF}"
    echo "==> Создан ${ENVF} (пароль сгенерирован автоматически)."
fi

echo "==> Ставим systemd-юнит english-admin.service (порт ${PORT})..."
cat > /etc/systemd/system/english-admin.service <<EOF
[Unit]
Description=English Bot Admin Web Panel (monitoring + DB stats)
After=network-online.target

[Service]
Type=simple
EnvironmentFile=${ENVF}
Environment=ADMIN_PORT=${PORT}
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/python3 ${APP_DIR}/admin/server.py --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now english-admin

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "============================================================"
echo " ✅ Панель мониторинга запущена внутри контейнера."
echo "    URL:        http://${IP:-<IP-контейнера>}:${PORT}"
echo "    логин:      ${ADMIN_USER}"
echo "    пароль:     ${ADMIN_PASSWORD}"
echo "    (пароль также в ${ENVF})"
echo ""
echo " Из хоста (Kali) открыть на localhost:"
echo "    sudo lxc-attach -n ${CT_NAME:-english-bot} -- true  # контейнер запущен?"
echo "    CT_IP=\$(lxc-info -n ${CT_NAME:-english-bot} -H -i | awk '{print \$1}') && echo http://\$CT_IP:${PORT}"
echo ""
echo " Логи панели:  journalctl -u english-admin -f"
echo " Перезапуск:   systemctl restart english-admin"
echo " Смена пароля: отредактируйте ${ENVF}, затем systemctl restart english-admin"
echo "============================================================"
