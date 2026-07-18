# Dockerfile — shadow/canary через роутер
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8094
EXPOSE 8094
CMD ["node", "server.js"]
