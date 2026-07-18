#!/bin/sh
set -e

# Схема + сид (миграции), затем — администратор из ADMIN_* (если задан ADMIN_PASSWORD)
python manage.py migrate --noinput
python manage.py ensure_admin || true

exec gunicorn --bind "0.0.0.0:${PORT:-10000}" flower_shop.wsgi:application
