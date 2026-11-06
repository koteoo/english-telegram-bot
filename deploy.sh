#!/usr/bin/env bash
# Деплой бота на VPS в РФ (Timeweb, Selectel, Beget, reg.ru, Yandex Cloud…) за ~5 минут.
# Требуется: Debian 12 (или Ubuntu 22.04/24.04), root/sudo.
# Связка по умолчанию «почти бесплатно»: Groq (LLM) + SpeechKit test (TTS)
# + faster-whisper локально (STT) — код менять не нужно, только .env.
set -euo pipefail

echo "==> Установка Docker"
if ! command -v docker >/dev/null; then
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg git
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

echo "==> Клонирование проекта (замените URL на свой репозиторий)"
REPO_URL="${REPO_URL:-https://github.com/USERNAME/english-telegram-bot.git}"
git clone "$REPO_URL" /opt/english-bot || (cd /opt/english-bot && git pull)
cd /opt/english-bot

if [ ! -f .env ]; then
    cp .env.example .env
    echo "!! Заполните /opt/english-bot/.env (BOT_TOKEN, GROQ_API_KEY, YANDEX_SPEECHKIT_*), затем перезапустите скрипт"
    exit 1
fi

docker compose up -d --build
docker compose ps
echo "✅ Готово. Логи: docker compose logs -f bot"
echo "ℹ️  Модель faster-whisper (base, ~150 MB) скачается при первом голосовом сообщении"
echo "   и сохранится в volume models_cache — следующие запросы будут быстрее."
