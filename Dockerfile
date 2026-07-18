# Dockerfile for Django Flower Shop
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application
COPY . .

# Статику собираем на этапе сборки (не нужен runtime-env)
RUN python manage.py collectstatic --noinput || true
RUN chmod +x docker-entrypoint.sh

EXPOSE 10000

# Миграции + администратор (из ADMIN_*) выполняются при старте, когда доступен runtime-env
CMD ["./docker-entrypoint.sh"]
