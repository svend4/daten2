# Dockerfile for Django Flower Shop
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application
COPY . .

# Collect static files and migrate
RUN python manage.py collectstatic --noinput || true
RUN python manage.py migrate --noinput || true

EXPOSE 10000

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "flower_shop.wsgi:application"]
