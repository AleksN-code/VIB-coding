FROM python:3.12-slim

# Логи Python одразу виводяться в docker logs, без буферизації
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /bot

# Спершу лише залежності — цей шар кешується, поки requirements.txt не зміниться
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо тільки код бота (.env в образ не потрапляє — токен передає docker-compose)
COPY app/ ./app/

# Запуск не від root
RUN useradd --create-home botuser
USER botuser

CMD ["python", "-m", "app.main"]
