#!/usr/bin/env bash
# ============================================================
# Установка бота ВНУТРИ LXC-контейнера Debian 12 — БЕЗ DOCKER.
# Системный Python + venv + systemd-сервис english-bot.
# Скачивает ВСЕ нужные модели при установке: faster-whisper (STT),
# Piper voice (TTS, офлайн без Yandex), Ollama + qwen2.5:7b (LLM-резерв).
#
# Запускать внутри контейнера (или через lxc-attach с хоста):
#   sudo lxc-attach -n english-bot -- bash /opt/english-bot/install-bot.sh
# ============================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/english-bot}"
PY_VENV="${APP_DIR}/venv"
SERVICE_USER="botuser"

echo "==> Обновляем индексы apt и ставим зависимости..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    ffmpeg \
    curl ca-certificates nano \
    build-essential python3-dev   # иногда нужен для wheels (ctranslate2)

echo "==> Настраиваем .env ДО скачивания моделей (нужны WHISPER_*/OLLAMA_MODEL)..."
if [ ! -f "${APP_DIR}/.env" ]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    echo "   (создан из .env.example — заполните BOT_TOKEN и GROQ_API_KEY!)"
fi

echo "==> Создаём пользователя ${SERVICE_USER}..."
id -u "${SERVICE_USER}" >/dev/null 2>&1 || useradd -r -m -s /usr/sbin/nologin "${SERVICE_USER}"

echo "==> Создаём виртуальное окружение и ставим пакеты проекта..."
python3 -m venv "${PY_VENV}"
"${PY_VENV}/bin/pip" install --upgrade pip setuptools wheel
"${PY_VENV}/bin/pip" install -r "${APP_DIR}/requirements.txt"

# --- Модели для офлайн-режима (качаем сразу, чтобы при старте не ждать) ---
mkdir -p "${APP_DIR}/models_cache"
export HF_HOME="${APP_DIR}/models_cache"

echo "==> Скачиваем модель faster-whisper (STT, ~150 MB)...   [1/4]"
WHISPER_MODEL="$(grep -E '^WHISPER_LOCAL_MODEL=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2 || true)"
"${PY_VENV}/bin/python" - "$WHISPER_MODEL" <<'PY'
import os, sys
from faster_whisper import WhisperModel
size = (sys.argv[1] or "").strip() or os.getenv("WHISPER_LOCAL_MODEL", "base")
WhisperModel(size, device="cpu", compute_type="int8")
print(f"    faster-whisper '{size}' — ок")
PY

echo "==> Ставим Piper TTS + английскую голосовую модель (офлайн озвучка, без Yandex)...   [2/4]"
"${PY_VENV}/bin/pip" install piper-tts huggingface_hub >/dev/null 2>&1 || \
    echo "    ⚠ piper-tts не установился (не критично, озвучка будет через API, если настроен)"
"${PY_VENV}/bin/python" - <<'PY' || echo "    ⚠ Не удалось скачать голос Piper (озвучка по API недоступна без ключей)"
from huggingface_hub import hf_hub_download
files = ["en_US-lessac-medium.onnx", "en_US-lessac-medium.onnx.json"]
paths = [hf_hub_download("rhasspy/piper-voices", f"en/en_US/lessac/medium/{f}",
                        local_dir="/opt/english-bot/models_cache/piper") for f in files]
print("    Piper voice:", paths[0])
PY
PIPER_VOICE="${APP_DIR}/models_cache/piper/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
if [ -f "${PIPER_VOICE}" ]; then
    if grep -q '^PIPER_MODEL_PATH=' "${APP_DIR}/.env" 2>/dev/null; then
        sed -i "s|^PIPER_MODEL_PATH=.*|PIPER_MODEL_PATH=${PIPER_VOICE}|" "${APP_DIR}/.env"
    fi
fi

echo "==> Устанавливаем Ollama + качаем LLM-модель qwen2.5:7b (~4.7 GB, резервный движок)...   [3/4]"
OLLAMA_BIN=""
if command -v ollama >/dev/null 2>&1 || curl -fsSL https://ollama.com/install.sh | sh; then
    OLLAMA_BIN="$(command -v ollama || true)"
fi
if [ -n "${OLLAMA_BIN}" ]; then
    cat > /etc/systemd/system/ollama.service <<EOF
[Unit]
Description=Ollama LLM server (fallback for the bot)
After=network-online.target

[Service]
Type=simple
ExecStart=${OLLAMA_BIN} serve
Environment=OLLAMA_HOST=127.0.0.1:11434
Environment=OLLAMA_MODELS=${APP_DIR}/ollama_models
Environment=OLLAMA_KEEP_ALIVE=30m
Restart=on-failure
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
    mkdir -p "${APP_DIR}/ollama_models"
    systemctl daemon-reload
    systemctl enable --now ollama
    OLLAMA_MODEL="$(grep -E '^OLLAMA_MODEL=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2 || true)"
    "${OLLAMA_BIN}" pull "${OLLAMA_MODEL:-qwen2.5:7b-instruct-q4_K_M}" || \
        echo "    ⚠ Оллama pull не выполнен (нет сети?) — failover тогда работает только Groq→офлайн"
    # включаем Ollama как резерв в .env
    if grep -q '^# OLLAMA_ENABLED=' "${APP_DIR}/.env" 2>/dev/null; then
        sed -i 's|^# OLLAMA_ENABLED=.*|OLLAMA_ENABLED=on|' "${APP_DIR}/.env"
    elif ! grep -q '^OLLAMA_ENABLED=' "${APP_DIR}/.env" 2>/dev/null; then
        printf '\nOLLAMA_ENABLED=on\n' >> "${APP_DIR}/.env"
    fi
else
    echo "    ⚠ Ollama не установился — не страшно: цепочка останется Groq → офлайн-движок"
fi

echo "==> Проверяем доступность Telegram API из контейнера...   [4/4]"
if curl -fsS --max-time 15 https://api.telegram.org >/dev/null 2>&1; then
    echo "    api.telegram.org — доступен ✅"
else
    echo "    ⚠ api.telegram.org недоступен! Проверьте сеть/прокси внутри контейнера."
fi

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"
chmod 600 "${APP_DIR}/.env"

echo "==> Устанавливаем systemd-юнит english-bot.service..."
cat > /etc/systemd/system/english-bot.service <<EOF
[Unit]
Description=English Telegram Bot (LXC, no Docker)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${PY_VENV}/bin/python ${APP_DIR}/main.py
Restart=always
RestartSec=5
# экономия памяти: модель whisper грузится лениво
Environment=HF_HOME=${APP_DIR}/models_cache

[Install]
WantedBy=multi-user.target
EOF
mkdir -p "${APP_DIR}/models_cache"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}/models_cache"

systemctl daemon-reload
systemctl enable english-bot

echo ""
echo "============================================================"
echo " ✅ Бот установлен (без Docker). Старт:"
echo "    systemctl restart english-bot && systemctl status english-bot"
echo " Логи: journalctl -u english-bot -f"
echo " Не забудьте заполнить BOT_TOKEN и GROQ_API_KEY в ${APP_DIR}/.env"
echo " Тесты логики: ${PY_VENV}/bin/python ${APP_DIR}/test_db.py"
echo "              ${PY_VENV}/bin/python ${APP_DIR}/test_plans.py"
echo "============================================================"
