# Dockerfile — property-based тесты инвариантов контракта
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8098
EXPOSE 8098
CMD ["node", "server.js"]
