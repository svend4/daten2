# Dockerfile — полиглот-бенчмарк (перф-отчёт по 7 стекам)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8100
EXPOSE 8100
CMD ["node", "server.js"]
