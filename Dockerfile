# Dockerfile — реальные интеграции (payment/embeddings адаптеры)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8101
EXPOSE 8101
CMD ["node", "server.js"]
