# Dockerfile for React + Flask API Flower Shop
# Multi-stage build

# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend with static files
FROM python:3.12-slim
WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy backend
COPY backend/ .

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./static

# Set permissions for SQLite
RUN chmod 666 flowers.db

EXPOSE 10000

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "api:app"]
