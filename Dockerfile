# Dockerfile — цифровой двойник магазина (digital twin)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8075
EXPOSE 8075
CMD ["node", "server.js"]
