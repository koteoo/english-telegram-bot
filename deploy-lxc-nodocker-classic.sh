#!/usr/bin/env bash
# ============================================================
# Создание LXC-контейнера Debian 12 — КЛАССИЧЕСКИЙ LXC
# (lxc-create / lxc-start, ваш случай: Kali Linux + lxc пакет).
# БЕЗ Docker и БЕЗ LXD.
#
#   sudo ./lxc-create.sh              # создать + запустить контейнер
#   sudo ./lxc-create.sh attach       # положить проект в контейнер
#                                     # и запустить установку бота
#
# Параметры через env-переменные:
#   CT_NAME=english-bot CT_DISK=15G ./lxc-create.sh
# ============================================================
set -euo pipefail

CT_NAME="${CT_NAME:-english-bot}"
CT_ROOT="/var/lib/lxc/${CT_NAME}/rootfs"
APP_DIR="/opt/english-bot"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "!! Запустите с sudo (LXC требует root)." >&2
        exit 1
    fi
}

case "${1:-create}" in
create)
    require_root

    echo "==> Проверяем зависимости..."
    for cmd in lxc-create lxc-start debootstrap; do
        command -v "$cmd" >/dev/null || {
            echo "   Ставим: apt-get install -y lxc debootstrap"
            apt-get update && apt-get install -y lxc debootstrap bridge-utils
            break
        }
    done

    if lxc-ls -f 2>/dev/null | grep -qw "${CT_NAME}"; then
        echo "!! Контейнер '${CT_NAME}' уже существует."
        echo "   Удалить: lxc-destroy -n ${CT_NAME} -f"
        echo "   Зайти:   lxc-attach -n ${CT_NAME}"
        exit 0
    fi

    echo "==> Скачиваем шаблон Debian 12 (bookworm), если нужно..."
    [ -f /usr/share/lxc/templates/lxc-debian ] || \
        apt-get install -y lxc debian-archive-keyring

    echo "==> Создаём контейнер '${CT_NAME}' (debian bookworm, minimal)..."
    # --fstype=overlayfs не везде поддержан на Kali; берём обычный dir-backend.
    lxc-create -n "${CT_NAME}" -t debian -- -r bookworm -p minimal

    echo "==> Настраиваем ресурсы (CPU/RAM/диск)..."
    cfg="/var/lib/lxc/${CT_NAME}/config"
    cat >> "${cfg}" <<CFG

# === Ресурсы для бота (2 vCPU / 3 GB RAM + 2 GB swap) ===
# ВАЖНО: у классического LXC (dir-backend) нет квот на диск — размер контейнера
# ограничен свободным местом Kali-хоста (~6 ГБ займут модели при установке).
lxc.cgroup2.memory.max = 3221225472
# swap: 2 GB, чтобы faster-whisper/Ollama не упирались в OOM при пике
lxc.cgroup2.memory.swap.max = 2147483648
CFG
    # cpu.max в cgroup v2 и quota в v1 задаём только если контроллеры доступны —
    # иначе некоторые ядра не дадут запустить CT. При проблемах закомментируйте.
    cat >> "${cfg}" <<CFG
lxc.cgroup2.cpu.max = 200000 100000
lxc.cgroup.cpu.cfs_quota_us = 200000
lxc.cgroup.cpu.cfs_period_us = 100000
lxc.cgroup.memory.limit_in_bytes = 3221225472
CFG

    echo "==> Сеть: по умолчанию lxcbr0 (NAT). Публичный IP НЕ нужен —"
    echo "    бот ходит к Telegram сам (long polling)."
    grep -q '^lxc.network' "${cfg}" || true

    # На Kali AppArmor может блокировать запуск systemd внутри непривилегированного CT.
    # Пробуем profile=unconfined; если дистрибутив не позволяет — уберите строку вручную.
    if ! grep -q 'lxc.apparmor.profile' "${cfg}"; then
        echo "lxc.apparmor.profile = unconfined" >> "${cfg}"
    fi
    # cgroup-автомонтирование помогает на нестандартных ядрах
    if ! grep -q 'lxc.mount.auto' "${cfg}"; then
        echo "lxc.mount.auto = cgroup:mixed proc:mixed sys:mixed" >> "${cfg}"
    fi

    echo "==> Включаем автозапуск контейнера при старте Kali..."
    sed -i 's/^#*lxc.start.auto = .*/lxc.start.auto = 1/' "${cfg}" 2>/dev/null || \
        echo "lxc.start.auto = 1" >> "${cfg}"
    systemctl enable lxc >/dev/null 2>&1 || true

    echo "==> Стартуем контейнер..."
    lxc-start -n "${CT_NAME}"

    echo "==> Ждём готовности (макс. 60 сек)..."
    for i in $(seq 1 30); do
        if lxc-attach -n "${CT_NAME}" -- true >/dev/null 2>&1; then
            echo "    Контейнер готов."
            break
        fi
        sleep 2
    done

    echo ""
    echo "============================================================"
    echo " ✅ Контейнер '${CT_NAME}' создан и запущен (Debian 12)."
    echo " Дальше:"
    echo "   1. sudo ./deploy-lxc-nodocker-classic.sh attach   # код+установка"
    echo "   2. lxc-attach -n ${CT_NAME} -- nano ${APP_DIR}/.env  # BOT_TOKEN, GROQ_API_KEY"
    echo "   3. lxc-attach -n ${CT_NAME} -- systemctl restart english-bot"
    echo "   Логи: lxc-attach -n ${CT_NAME} -- journalctl -u english-bot -f"
    echo "   Внутри CT: вход под root без пароля; пароль: lxc-attach -n ${CT_NAME} -- passwd"
    echo "============================================================"
    ;;

attach)
    require_root
    if ! lxc-attach -n "${CT_NAME}" -- true >/dev/null 2>&1; then
        echo "!! Контейнер '${CT_NAME}' не запущен. Сначала: sudo $0 create" >&2
        exit 1
    fi

    echo "==> Копируем проект из ${PROJECT_DIR} в ${CT_NAME}:${APP_DIR}..."
    lxc-attach -n "${CT_NAME}" -- mkdir -p "${APP_DIR}"
    tar -C "${PROJECT_DIR}" \
        --exclude='.git' --exclude='__pycache__' --exclude='*.db' \
        --exclude='models_cache' --exclude='venv' \
        -czf - . | lxc-attach -n "${CT_NAME}" -- tar -C "${APP_DIR}" -xzf -

    echo "==> Установка внутри контейнера (apt, venv, systemd-юнит)..."
    lxc-attach -n "${CT_NAME}" -- chmod +x "${APP_DIR}/install-bot.sh"
    lxc-attach -n "${CT_NAME}" -- bash "${APP_DIR}/install-bot.sh"

    echo ""
    echo " ✅ Бот установлен. Заполните ключи и стартуйте:"
    echo "   lxc-attach -n ${CT_NAME} -- nano ${APP_DIR}/.env"
    echo "   lxc-attach -n ${CT_NAME} -- systemctl restart english-bot"
    ;;

shell)
    exec sudo lxc-attach -n "${CT_NAME}" -- bash
    ;;

*)
    echo "Использование: sudo $0 [create|attach|shell]"
    exit 1
    ;;
esac
