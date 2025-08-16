FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Railway сам пробросит PORT в контейнер
ENV PORT=${PORT}
EXPOSE ${PORT}

# Запуск через gunicorn (1 воркер, чтобы не терять user_state в памяти)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:${PORT}", "--workers", "1", "--threads", "4", "--timeout", "60"]

