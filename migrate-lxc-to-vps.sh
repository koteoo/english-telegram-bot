#!/usr/bin/env bash
set -euo pipefail

CT_NAME="${CT_NAME:-english-bot}"
LXC_DIR="/var/lib/lxc/${CT_NAME}"
OUT_FILE="${OUT_FILE:-/tmp/${CT_NAME}-migrate.tar.gz}"

usage() {
    echo "Использование: sudo $0 <pack|unpack|check>"
}

require_root() {
    [[ $EUID -eq 0 ]] || { echo "!! Запустите с sudo." >&2; exit 1; }
}

cmd_check() {
    require_root
    echo "== Проверка хоста =="
    for c in lxc-create lxc-start lxc-attach; do
        command -v "$c" >/dev/null && echo "  OK: $c" || echo "  НЕТ: $c (apt-get install -y lxc)"
    done
    [ -d "${LXC_DIR}/rootfs" ] && echo "  OK: ${LXC_DIR}/rootfs найден" || echo "  НЕТ: ${LXC_DIR}/rootfs"
    df -h /var | tail -1
    free -h | awk '/Mem/{print "  RAM:",$2}'
}

cmd_pack() {
    require_root
    if [ ! -d "${LXC_DIR}" ]; then
        echo "!! Контейнер '${CT_NAME}' не найден в ${LXC_DIR}" >&2
        echo "   Список контейнеров: sudo lxc-ls -f" >&2
        exit 1
    fi
    if [ ! -d "${LXC_DIR}/rootfs" ]; then
        echo "!! Нет ${LXC_DIR}/rootfs — контейнер повреждён или это LXD (не classic)." >&2
        exit 1
    fi
    echo "==> Останавливаем контейнер..."
    lxc-stop -n "${CT_NAME}" 2>/dev/null || true
    sleep 2

    echo "==> Упаковываем rootfs + config (${LXC_DIR})... (~5-8 ГБ, 10-30 минут)"
    tar -czf "${OUT_FILE}" -C "$(dirname "${LXC_DIR}")" "${CT_NAME}"
    sync

    SIZE=$(du -h "${OUT_FILE}" | cut -f1)
    echo ""
    echo "✅ Архив готов: ${OUT_FILE} (${SIZE})"
    echo ""
    echo "Дальше:"
    echo "  1) scp ${OUT_FILE} migrate-lxc-to-vps.sh root@ВАШ_VPS_IP:/root/"
    echo "  2) На VPS: apt-get update && apt-get install -y lxc debootstrap bridge-utils"
    echo "     ./migrate-lxc-to-vps.sh unpack"
}

cmd_unpack() {
    require_root
    local src="${SRC:-${OUT_FILE}}"
    if [ ! -f "${src}" ]; then
        echo "!! Архив не найден: ${src} (задайте SRC=/путь/к/архиву)" >&2
        exit 1
    fi
    if ! command -v lxc-start >/dev/null; then
        echo "==> Устанавливаем LXC..."
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y lxc lxcfs debootstrap bridge-utils ca-certificates
    fi

    if [ -d "/var/lib/lxc/${CT_NAME}" ]; then
        echo "!! /var/lib/lxc/${CT_NAME} уже существует. Сначала: lxc-destroy -n ${CT_NAME} -f" >&2
        exit 1
    fi

    echo "==> Распаковываем контейнер из ${src}..."
    mkdir -p /var/lib/lxc
    tar -xzf "${src}" -C /var/lib/lxc/

    cfg="/var/lib/lxc/${CT_NAME}/config"
    echo "==> Правим конфигурацию под нового хоста..."

    # Сетевой мост lxcbr0
    if [ -f /etc/default/lxc-net ]; then
        sed -i 's/^USE_LXC_BRIDGE=.*/USE_LXC_BRIDGE="true"/' /etc/default/lxc-net
    else
        echo 'USE_LXC_BRIDGE="true"' > /etc/default/lxc-net
    fi
    systemctl enable --now lxc-dnsmasq 2>/dev/null || true
    systemctl restart lxc-net 2>/dev/null || ip link set lxcbr0 up 2>/dev/null || true

    # Сетевая секция CT -> lxcbr0
    if grep -q '^lxc\.net\.0' "${cfg}"; then
        sed -i 's/^lxc\.net\.0\.link = .*/lxc.net.0.link = lxcbr0/' "${cfg}"
        sed -i '/^lxc\.net\.0\.veth\.name/d' "${cfg}"
        grep -q '^lxc.net.0.flags' "${cfg}" || sed -i '/^lxc.net.0.type/a lxc.net.0.flags = up' "${cfg}"
    else
        cat >> "${cfg}" <<NETCFG
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.net.0.hwaddr = 00:16:3e:$(head -c3 /dev/urandom | od -An -tx1 | tr -d ' \n'):$(head -c2 /dev/urandom | od -An -tx1 | tr -d ' \n')
NETCFG
    fi

    # AppArmor + автозапуск
    sed -i '/lxc.apparmor.profile/d' "${cfg}"
    echo "lxc.apparmor.profile = unconfined" >> "${cfg}"
    grep -q 'lxc.mount.auto' "${cfg}" || echo "lxc.mount.auto = cgroup:mixed proc:mixed sys:mixed" >> "${cfg}"
    sed -i 's/^lxc.start.auto = .*/lxc.start.auto = 1/' "${cfg}" 2>/dev/null || echo "lxc.start.auto = 1" >> "${cfg}"
    systemctl enable lxc >/dev/null 2>&1 || true

    echo "==> Стартуем контейнер..."
    lxc-start -n "${CT_NAME}"
    for i in $(seq 1 30); do
        lxc-attach -n "${CT_NAME}" -- true >/dev/null 2>&1 && break
        sleep 2
    done

    echo "==> Проверяем сервисы внутри CT..."
    lxc-attach -n "${CT_NAME}" -- systemctl daemon-reload || true
    lxc-attach -n "${CT_NAME}" -- systemctl is-active english-bot >/dev/null || \
        lxc-attach -n "${CT_NAME}" -- systemctl restart english-bot || true
    lxc-attach -n "${CT_NAME}" -- systemctl status english-bot --no-pager | head -8 || true

    echo ""
    echo "✅ Готово. Команды на VPS:"
    echo "   Логи бота:  lxc-attach -n ${CT_NAME} -- journalctl -u english-bot -f"
    echo "   Статус CT:  lxc-info -n ${CT_NAME}"
    echo "   Внутри CT:  lxc-attach -n ${CT_NAME} -- bash"
    echo ""
    echo "⚠ Проверьте доступ к Telegram без VPN:"
    echo "   curl -sI https://api.telegram.org | head -1"
}

case "${1:-}" in
    check)  cmd_check ;;
    pack)   cmd_pack ;;
    unpack) cmd_unpack ;;
    *)      usage; exit 1 ;;
esac
