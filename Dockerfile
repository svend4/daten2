# Dockerfile — Vision (анализ изображений + поиск по фото)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8088
EXPOSE 8088
CMD ["node", "server.js"]
