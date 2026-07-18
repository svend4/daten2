# Dockerfile — green/FinOps-роутер
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8091
EXPOSE 8091
CMD ["node", "server.js"]
