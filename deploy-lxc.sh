#!/usr/bin/env bash
# ============================================================
# Деплой Telegram-бота изучения английского в LXC-контейнер.
# Вариант 1 (рекомендуется): Proxmox VE — LXC с внутри Docker.
# Вариант 2: чистый Debian/Ubuntu c LXD — контейнер без Docker
#            (бот ставится системным Python + systemd, см. ниже).
#
# Запускать на ХОСТЕ (Proxmox / LXD-хосте), а не внутри контейнера!
# ============================================================
set -euo pipefail

CTID="${1:-200}"                 # ID контейнера (аргумент скрипта)
HOSTNAME_LXC="english-bot"       # имя контейнера
TEMPLATE="local:vztmpl/debian-12-standard_*.tar.zst"  # шаблон Proxmox
STORAGE="local-lvm"              # где хранить диск контейнера
MEM_MB=3072                      # RAM: 3 GB — с запасом под faster-whisper
SWAP_MB=1024                     # swap для модели Whisper при пиковой нагрузке
CORES=2                          # vCPU
DISK_GB=25                       # диск: образы Docker + кэш моделей (~10-15 GB)
REPO_URL="${REPO_URL:-https://github.com/ВАШ_USERNAME/english-telegram-bot.git}"
UNPRIVILEGED=yes                 # unprivileged + nesting=1 нужно для Docker внутри LXC

echo "==> Создаём LXC-контейнер CTID=${CTID} (${CORES} CPU / ${MEM_MB} MB RAM / ${DISK_GB} GB)"
pct create "${CTID}" ${TEMPLATE} \
  --hostname "${HOSTNAME_LXC}" \
  --storage "${STORAGE}" \
  --cores "${CORES}" \
  --memory "${MEM_MB}" \
  --swap "${SWAP_MB}" \
  --rootfs "${STORAGE}:${DISK_GB}" \
  --net0 name=eth0,bridge=vmbr0,ip=DHCP \
  --unprivileged "${UNPRIVILEGED}" \
  --features nesting=1 \
  --onboot 1 \
  --start 1

echo "==> Контейнер запущен. Ждём сеть..."
sleep 8

echo "==> Ставим Docker и git ВНУТРИ контейнера"
pct exec "${CTID}" -- bash -ec '
  apt-get update
  apt-get install -y curl git ca-certificates ffmpeg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
'

echo "==> Клонируем проект и запускаем бота"
pct exec "${CTID}" -- bash -ec "
  git clone ${REPO_URL} /opt/english-bot
  cd /opt/english-bot
  cp .env.example .env
  echo '>>> Отредактируйте ключи: pct exec ${CTID} -- nano /opt/english-bot/.env'
  echo '>>> Затем:           pct exec ${CTID} -- \"cd /opt/english-bot && docker compose up -d --build\"'
"

cat <<EOF

Готово! Полезные команды с хоста (Proxmox):
  pct enter ${CTID}                                   # зайти в контейнер
  pct exec ${CTID} -- nano /opt/english-bot/.env      # вписать BOT_TOKEN / GROQ_API_KEY
  pct exec ${CTID} -- 'cd /opt/english-bot && docker compose up -d --build'   # собрать и запустить
  pct exec ${CTID} -- docker compose -f /opt/english-bot/docker-compose.yml logs -f bot  # логи
  pct status ${CTID}                                  # состояние; onboot=1 — стартует сам после ребута хоста

Обновление бота:
  pct exec ${CTID} -- 'cd /opt/english-bot && git pull && docker compose up -d --build'

Если НЕ используете Docker внутри LXC (вариант 2, легче по ресурсам):
  pct exec ${CTID} -- apt-get install -y python3-venv ffmpeg
  pct exec ${CTID} -- 'git clone ${REPO_URL} /opt/english-bot && cd /opt/english-bot && \
    python3 -m venv venv && venv/bin/pip install -r requirements.txt'
  затем скопируйте systemd.service в /etc/systemd/system/ внутри контейнера
  (WorkingDirectory=/opt/english-bot, ExecStart=/opt/english-bot/venv/bin/python main.py)
  и: systemctl enable --now english-bot
EOF
