# Dockerfile — самооптимизирующийся ML-роутер
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8073
EXPOSE 8073
CMD ["node", "server.js"]
