# Dockerfile for Node.js Express + SQLite Flower Shop
FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm install

# Copy application
COPY . .

# Генерируем БД из канонических schema.sql + seed.sql
RUN node init_db.js

EXPOSE 10000

ENV PORT=10000

CMD ["node", "server.js"]
