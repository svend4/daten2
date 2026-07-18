# Dockerfile — дистилляция учитель→ученик (distillation)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8089
EXPOSE 8089
CMD ["node", "server.js"]
