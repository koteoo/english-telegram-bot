# 🇬🇧 English Learning Bot — Telegram-бот для изучения английского

Бот на **Python + aiogram 3** с интервальным повторением слов (в стиле Anki), мини-квизами по грамматике и статистикой прогресса. Данные хранятся в SQLite.

## Возможности

| Кнопка / команда | Что делает |
|---|---|
| `/start` | Регистрация и главное меню |
| 📚 Word of the Day | Случайное слово уровня: перевод + пример, автоматически добавляется в колоду |
| 🃏 Flashcards | Повторение слов, которые «пора вспомнить» (интервалы: 0 → 1 → 3 → 7 → 14 → 30 дней) |
| ✍️ Quiz | Мини-тест на грамматику с кнопками A/B, ведётся рекорд |
| ➕ Add word | Отправь английское слово текстом — попадёт в твою колоду |
| 📊 Progress | Выученные слова, размер колоды, рекорд квиза |
| 🎯 Level | Выбор уровня: Beginner / Intermediate / Advanced |
| `/help` | Инструкция |

Словарная база (60 слов по 3 уровням) лежит в `data/vocabulary.py` — легко расширить.

## Быстрый старт

1. Получите токен бота у [@BotFather](https://t.me/BotFather) (команда `/newbot`).
2. Установите зависимости и запустите:

```bash
pip install -r requirements.txt
export BOT_TOKEN="123456:ваш_токен"
python main.py
```

3. Откройте чат с ботом и нажмите `/start`.

## Структура проекта

```
main.py              # точка входа (Bot + Dispatcher)
config.py            # токен, путь к БД, интервалы повторения
db.py                # SQLite-хранилище: users, cards (leitner boxes), stats
keyboards.py         # reply/inline-клавиатуры
data/vocabulary.py   # словарь по уровням + вопросы квиза
handlers/start.py    # /start, /help
handlers/learning.py # карточки, квиз, добавление слов, прогресс, уровень
test_db.py           # смоук-тест логики БД: python test_db.py
```

## Как работает интервальное повторение

Каждое слово находится в одной из «коробок» (leitner boxes). Верный ответ поднимает коробку выше и увеличивает интервал до следующего повтора (1, 3, 7, 14, 30 дней); ошибка возвращает слово в первую коробку — бот предложит его сразу. Слово засчитывается «выученным» при первом успешном повторении.

## Заметки по продакшену

- Для постоянной работы запускайте через `systemd`, Docker или `pm2`; БД (`english_bot.db`) кладите на volume.
- Токен никогда не коммитьте в git — только через переменную окружения.
- Хотите пуш «Word of the Day» по расписанию? Добавьте APScheduler (`AsyncIOScheduler`) и `bot.send_message()` на всех пользователей из таблицы `users`. Могу добавить это следующим шагом.


## 📚 Темы и 🗣 разговор (новое)

**12 тем для изучения** (`data/topics.py`): Travel, Food, Work, Hobbies, Family,
Health, Technology, Movies & Music, Culture, Daily Routine, Shopping, Education.
По каждой теме бот показывает:
- 💡 **Ideas** — 5 идей/подтем для обсуждения;
- 🎓 **Useful phrases** — полезные фразы EN→RU;
- ❓ **Questions** — вопросы для разговорной практики.

**Интерактивный диалог** (`handlers/chat.py`, `chat_engine.py`):
- Кнопки «💬 Topics» / «🗣 Chat with me» или команды `/topics`, `/chat`;
- После выбора темы бот поддерживает непрерывный разговор: реагирует на ответы,
  хвалит за развёрнутые фразы, подбадривает короткие, подсказывает лексику;
- «🙋 Ask for help» — напиши по-русски, что хочешь сказать, бот подскажет английскую фразу;
- Режим **Free conversation** — болтай о чём угодно;
- «💬 Change topic» / «🏠 Main menu» — выход из диалога.

**Два движка диалога:**
1. **LLM (опционально)** — задай `OPENAI_API_KEY` (и при желании `OPENAI_BASE_URL`
   и `OPENAI_MODEL` для любого OpenAI-совместимого сервиса) — и бот будет вести
   по-настоящему живой разговор с исправлением ошибок под уровень ученика.
2. **Локальный rule-based** — работает без интернета и API-ключей: вопросы,
   реакции и лексика из банков тем.


## 🇷🇺 Работа из РФ + бесплатные LLM + голос

### Сервер в России
Бот работает через **long polling** (исходящие соединения), поэтому Telegram-доступ не нужен — сервер может быть любым VPS в РФ: **Timeweb Cloud, Selectel, Beget, reg.ru, Yandex Cloud** (от ~150–300 ₽/мес, минимальной конфигурации 1 CPU / 1 GB RAM достаточно).

Два способа запуска на сервере:
```bash
# 1) Docker (рекомендуется): клонируйте репозиторий и выполните
./deploy.sh                       # установит Docker, соберёт образ, запустит контейнер
docker compose logs -f            # смотреть логи

# 2) Без Docker — systemd-сервис
cp systemd.service /etc/systemd/system/english-bot.service
systemctl daemon-reload && systemctl enable --now english-bot
```
Настройки берутся из файла `.env` (шаблон — `.env.example`).

### Бесплатные LLM (все доступны из РФ)
| Сервис | Как включить | Особенности |
|---|---|---|
| **Groq** (рекомендую) | `GROQ_API_KEY=...` | бесплатный ключ, Llama 3.3 70B, очень быстрый, из РФ без прокси |
| **Selectel Select AI / Cloud.ru** | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | российские облака, есть бесплатные пакеты/гранты |
| **YandexGPT API** | через совместимый эндпоинт | 1 млн символов бесплатно |
| **Ollama локально** | `OPENAI_BASE_URL=http://localhost:11434/v1` | полностью бесплатно и офлайн; нужен VPS от 2 CPU / 4 GB RAM |

Без ключей бот автоматически переключается на встроенный офлайн-движок диалога.

### Голосовые сообщения 🎙
* **Распознавание (STT)** — пользователь говорит голосом, бот понимает:
  * бесплатно и офлайн: `pip install faster-whisper` (модель `base` качается сама, ~74 МБ);
  * или Whisper-совместимый API: `SPEECH_API_KEY` + `SPEECH_BASE_URL`.
* **Озвучка ответов (TTS)** — кнопка «🎙 Voice reply» в режиме чата:
  * **Yandex SpeechKit** — бесплатный пакет ~2000 символов/сутки, стабильно из РФ
    (`YANDEX_SPEECHKIT_API_KEY` + `YANDEX_SPEECHKIT_FOLDER_ID`);
  * или OpenAI-совместимый `/audio/speech` (Selectel/Cloud.ru), или локальный Piper.
* Если TTS не настроен — бот отвечает текстом, распознавание голоса продолжает работать.

Минимальная связка «всё бесплатно, из РФ»: **VPS в РФ + Groq API + faster-whisper + Yandex SpeechKit**.

## 💎 Монетизация: Telegram Stars и тарифные планы

Три плана доступа (настраиваются через .env, см. `.env.example`):

| Возможность | 🆓 Free | 💠 Plus (120⭐/мес) | 👑 Premium (250⭐/мес) |
|---|---|---|---|
| Словарь | только Beginner | все уровни | все уровни |
| Новые слова в день | 5 | без лимита | без лимита |
| Квизы | 3 вопроса/день | без лимита | без лимита |
| Темы для изучения | 4 из 12 | все 12 | все 12 |
| Разговор с ботом (текст) | 15 сообщений/день | без лимита | без лимита |
| Голосовые сообщения (STT/TTS) | ❌ | ✅ с лимитами (15 вход / 10 озвучек в день) | ✅ без лимитов |
| Авто-повторения (бот сам присылает слова) | ❌ | ✅ | ✅ |

Оплата — прямо в чате через **Telegram Stars** (`/premium` → invoice, валюта `XTR`).
Зачисление плана — автоматически по `successful_payment`. Вывод звёзд: ≥1000 ⭐,
через Fragment (TON) или криптобиржу Bybit.

Код: `plans.py` (тарифы/лимиты), `handlers/premium.py` (инвойсы),
`scheduler.py` (авто-повторения слов), таблицы `plans` и `usage_counters` в SQLite.

## 🖥 Параметры сервера (Debian + Docker)

**Вариант A — Groq API (рекомендуется):** LLM считается у них бесплатно, сервер нужен только для бота.
- VPS: **2 vCPU / 2 GB RAM / 40 GB SSD** (с запасом на faster-whisper локально) — от ~300–500 ₽/мес
- Если голос офлайн не нужен (Whisper API/не включён): хватит **1 vCPU / 1 GB RAM** (~200 ₽/мес)

**Вариант B — Ollama локально:** модель 7B (qwen2.5:7b-instruct-q4_K_M ≈ 4.7 GB) считает на сервере.
- Минимум: **4 vCPU / 8 GB RAM / 80 GB NVMe** — ~1500–2500 ₽/мес, ответ ~3–8 сек
- Комфортно: **8 vCPU / 16 GB RAM** или GPU-сервер (например, Selectel/Yandex Cloud с T4/A10) — быстрее и можно модель 13B+
- STT faster-whisper `base.en` добавляет ~1 GB RAM; `small.en` — ~2 GB

Подключение к Ollama из контейнера бота — в `docker-compose.yml` (профиль `ollama`):
```bash
docker compose --profile ollama up -d
docker compose run --rm ollama-loader pull qwen2.5:7b-instruct-q4_K_M
# в .env: OPENAI_API_KEY=ollama, OPENAI_BASE_URL=http://ollama:11434/v1, OPENAI_MODEL=qwen2.5:7b-instruct-q4_K_M
```

## 🚀 Боевой запуск: минимальная связка «из РФ, почти бесплатно»

Проверенная конфигурация по умолчанию — всё в коде уже готово, менять ничего не нужно:

| Компонент | Решение | Цена | Настройка |
|---|---|---|---|
| Сервер | VPS Debian 12, **2 vCPU / 2 GB / 40 GB SSD** (Timeweb/Selectel/REG.ru) | ~400 ₽/мес | один раз: `bash deploy.sh` |
| LLM-диалог | **Groq** (Llama 3.3 70B) | 0 ₽ | `.env`: `GROQ_API_KEY=gsk_...` |
| Озвучка (TTS) | **Yandex SpeechKit**, тестовый период | 0 ₽ | `.env`: `YANDEX_SPEECHKIT_API_KEY`, `FOLDER_ID` |
| Распознавание (STT) | **faster-whisper base** локально в контейнере бота | 0 ₽ | ничего — уже в requirements.txt |

Шаги запуска:
```bash
# 1. Купите VPS с Debian 12 в РФ, подключитесь по SSH как root
# 2. Одна команда:
curl -fsSL https://raw.githubusercontent.com/USERNAME/english-telegram-bot/main/deploy.sh | bash
#    (или скопируйте проект: scp -r . root@IP:/opt/english-bot)
# 3. Заполните /opt/english-bot/.env: BOT_TOKEN + GROQ_API_KEY + SPEECHKIT-ключи
# 4. bash deploy.sh   # пересоберёт и запустит контейнеры
docker compose logs -f bot   # проверка; модель whisper (~150 MB) скачается при первом голосовом
```

Масштабирование без изменения кода (только `.env`):
- Кончился бесплатный пакет SpeechKit → пополните биллинг Yandex Cloud (TTS начнёт работать платно ~100 ₽/10k символов).
- Whisper на CPU стал тормозить или кончилась RAM → зарегистрируйтесь в Select AI (Selectel), добавьте `SPEECH_API_KEY` + `SPEECH_BASE_URL` — код сам переключится на API, faster-whisper останется запасным.
- Выросли лимиты Groq → платный тариф Groq ($0.59/1M токенов) или `OPENAI_BASE_URL` на Select AI/YandexGPT.
- Много одновременных чатов → апгрейд VPS до 4 vCPU/4 GB (бот лёгкий, узкое место — только локальный whisper).

## 📦 Запуск в LXC-контейнере БЕЗ Docker (Kali хост + классический LXC)

Публичный IP и облачный VPS не обязательны: бот на long polling можно держать
в LXC-контейнере на домашнем или выделенном сервере. Вариант ниже рассчитан на
**классический LXC** (`lxc-create` / `lxc-start` / `lxc-attach`, пакет `lxc`
в Kali) — без Docker и без LXD. Контейнер: Debian 12 (bookworm), бот работает
как systemd-сервис на Python venv внутри контейнера.

Два шага на хосте Kali (из папки проекта, от root):

```bash
sudo ./deploy-lxc-nodocker-classic.sh create   # lxc-create -t debian -r bookworm,
                                               # лимиты 2 vCPU / 3 GB RAM, старт CT
sudo ./deploy-lxc-nodocker-classic.sh attach   # копирует проект в /opt/english-bot
                                               # и запускает install-bot.sh внутри CT:
                                               # apt + venv + pip, затем скачивает ВСЕ
                                               # модели (см. ниже), ставит systemd-юниты
# Впишите ключи и запустите бота:
sudo lxc-attach -n english-bot -- nano /opt/english-bot/.env       # BOT_TOKEN, GROQ_API_KEY
sudo lxc-attach -n english-bot -- systemctl restart english-bot
sudo lxc-attach -n english-bot -- journalctl -u english-bot -f     # логи
```

Что автоматически скачивает `install-bot.sh` при установке (~6 ГБ, шаг [1/4]…[4/4]):
- **faster-whisper `base`** (~150 MB) — распознавание голосовых (STT), офлайн;
- **Piper voice `en_US-lessac-medium`** (~60 MB) — озвучка ответов (TTS), офлайн,
  без Yandex SpeechKit; путь сам прописывается в `PIPER_MODEL_PATH`;
- **Ollama + модель `qwen2.5:7b-instruct-q4_K_M`** (~4.7 GB) — локальный резерв LLM,
  systemd-юнит `ollama.service`, `OLLAMA_ENABLED=on` дописывается в `.env`;
- проверку доступности `api.telegram.org` из контейнера.

Failover диалога: Groq → (лимиты/OFF) Ollama → (недоступен) офлайн rule-based движок.
При HTTP 429/quota Groq уходит в кулдаун 15 мин (`LLM_COOLDOWN_SEC`), запросы идут в
Ollama; после восстановления цепочка возвращается к Groq автоматически.

Полезные команды классического LXC:
- `sudo lxc-ls -f` — список контейнеров и их состояние;
- `sudo lxc-attach -n english-bot` — интерактивная оболочка внутри CT;
- `sudo lxc-info -n english-bot` — IP/статус/использование ресурсов;
- `sudo lxc-stop -n english-bot` / `lxc-start -n english-bot` — останов/старт;
- обновление кода: `sudo ./deploy-lxc-nodocker-classic.sh attach` (перезальёт
  проект; сервис перезапустите вручную);
- удаление: `sudo lxc-stop -n english-bot && sudo lxc-destroy -n english-bot -f`.

Ресурсы контейнера: **2 CPU / 3 GB RAM (+2 GB swap)** — быстрее всего работает
связка Groq+whisper+Piper; если хотите использовать Ollama-резерв в бою, лучше
**4 CPU / 8 GB RAM** (модель 7B q4 ~5 GB RAM, генерация на CPU ~3–8 сек). Диск —
dir-backend, квот нет: нужно ~10 ГБ свободно на разделе `/var` (Debian CT ~1 ГБ +
модели ~6 ГБ + БД/кэш). Для гарантии можно создать отдельный LV:
`lvcreate -L 15G -n botvg` и смонтировать в rootfs.
Сеть — NAT через `lxcbr0`: боту нужны только исходящие соединения к
Telegram API/Groq/HuggingFace/Ollama.com, входящие порты не открываем. Автозапуск
CT при старте хоста включён (`lxc.start.auto = 1` + `systemctl enable lxc`).

Примечания для Kali-хоста:
- Если AppArmor мешает старту systemd внутри CT:
  `ln -s /etc/apparmor.d/usr.sbin.lxcfs 2>/dev/null; systemctl restart apparmor`
  либо в конфиге CT добавьте `lxc.apparmor.profile = unconfined`.
- На SELinux-ядрах (не Kali по умолчанию) может потребоваться
  `lxc.mount.auto = cgroup:mixed`.

Варианты для других окружений сохранены: `deploy-lxc-nodocker.sh` (LXD:
`lxc launch/exec`) и `deploy-lxc.sh` (Proxmox `pct` + Docker).
Альтернатива без systemd — `systemd.service` + ручной запуск venv (см. выше).

⚠️ Домашний сервер: нужен стабильный интернет «из дома наружу» (исходящих
соединений достаточно, входящие порты не открываем). При падении провайдера/света
бот недоступен — для продакшена надёжнее VPS или второй резервный запуск.
