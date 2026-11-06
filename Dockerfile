# Образ для деплоя бота (работает и на сервере в РФ, т.к. polling — исходящие соединения)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Кэш моделей faster-whisper (base ~150 MB) переживает пересборку образа
ENV HF_HOME=/app/models-cache
VOLUME /app/models-cache

CMD ["python", "main.py"]
