#!/usr/bin/env bash
# ============================================================
# Полный цикл деплоя бота в LXC БЕЗ DOCKER (ваш случай:
# Kali Linux хост + установленный LXC/LXD).
#
#   ./deploy-lxc-nodocker.sh            # создать CT + установить бота
#   ./deploy-lxc-nodocker.sh update     # перенести код в существующий CT
#   ./deploy-lxc-nodocker.sh shell      # зайти в контейнер
#
# Параметры контейнера задаются env-переменными:
#   CT_NAME=english-bot CT_MEM=3G CT_CORES=2 CT_DISK=15G ./deploy-lxc-nodocker.sh
# ============================================================
set -euo pipefail

CT_NAME="${CT_NAME:-english-bot}"
CT_DISTRO="${CT_DISTRO:-debian:12}"
CT_MEM="${CT_MEM:-3G}"          # 3 GB RAM: бот + faster-whisper base (~0.5–1 GB)
CT_CORES="${CT_CORES:-2}"       # 2 vCPU — polling лёгкий, узкое место не CPU
CT_DISK="${CT_DISK:-15G}"       # ОС ~1 GB + venv/модели ~4–6 GB + кэш pip
APP_DIR="/opt/english-bot"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

copy_project() {
    echo "==> Копируем проект в ${CT_NAME}:${APP_DIR}..."
    lxc exec "${CT_NAME}" -- mkdir -p "${APP_DIR}"
    tar -C "${PROJECT_DIR}" \
        --exclude='.git' --exclude='__pycache__' --exclude='*.db' \
        --exclude='models_cache' --exclude='venv' \
        -czf - . | lxc exec "${CT_NAME}" -- tar -C "${APP_DIR}" -xzf -
    lxc exec "${CT_NAME}" -- chmod +x "${APP_DIR}/install-bot.sh"
}

case "${1:-install}" in
update)
    copy_project
    echo "==> Обновление зависимостей внутри контейнера..."
    lxc exec "${CT_NAME}" -- bash "${APP_DIR}/install-bot.sh"
    echo "✅ Код обновлён. Бот перезапустится автоматически при следующем рестарте сервиса:"
    echo "   lxc exec ${CT_NAME} -- systemctl restart english-bot"
    ;;
shell)
    exec lxc exec "${CT_NAME}" -- bash
    ;;
install|*)
    if lxc info "${CT_NAME}" >/dev/null 2>&1; then
        echo "!! Контейнер '${CT_NAME}' уже существует — пропускаю создание,"
        echo "   просто копирую проект и переустанавливаю зависимости."
    else
        echo "==> Создаём LXC-контейнер '${CT_NAME}' (${CT_CORES} CPU / ${CT_MEM} RAM / ${CT_DISK} disk)..."
        # systemd нужен для сервиса english-bot => привилегированный контейнер проще всего.
        # Сеть по умолчанию NAT: исходящие к Telegram API работают, публичный IP НЕ нужен.
        lxc launch "${CT_DISTRO}" "${CT_NAME}" \
            -c limits.cpu="${CT_CORES}" \
            -c limits.memory="${CT_MEM}" \
            -c security.privileged=true
        lxc config device set "${CT_NAME}" root size="${CT_DISK}" 2>/dev/null || \
            echo "(квоту диска можно задать вручную: lxc config device set ${CT_NAME} root size=${CT_DISK})"
        # автозапуск контейнера вместе с Kali
        lxc config set "${CT_NAME}" boot.autostart true
    fi

    echo "==> Ждём готовности контейнера..."
    for i in $(seq 1 30); do
        if lxc exec "${CT_NAME}" -- true >/dev/null 2>&1; then break; fi
        sleep 2
    done

    copy_project

    echo "==> Запускаем установку ВНУТРИ контейнера (apt, venv, systemd-юнит)..."
    lxc exec "${CT_NAME}" -- bash "${APP_DIR}/install-bot.sh"

    echo ""
    echo "============================================================"
    echo " ✅ Готово: LXC + Debian 12, БЕЗ Docker, бот как systemd-сервис."
    echo "============================================================"
    echo " Дальше:"
    echo "  1. lxc exec ${CT_NAME} -- nano ${APP_DIR}/.env     # BOT_TOKEN, GROQ_API_KEY"
    echo "  2. lxc exec ${CT_NAME} -- systemctl restart english-bot"
    echo "  3. Логи:  lxc exec ${CT_NAME} -- journalctl -u english-bot -f"
    echo "  Проверка: lxc exec ${CT_NAME} -- systemctl status english-bot"
    echo "  Тесты:    lxc exec ${CT_NAME} -- ${APP_DIR}/venv/bin/python ${APP_DIR}/test_db.py"
    echo "  Обновление кода:  ./deploy-lxc-nodocker.sh update"
    echo "  Выйти из CT: Ctrl+D (в shell) / контейнер живёт сам (boot.autostart)."
    echo "============================================================"
    ;;
esac
