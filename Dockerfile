# Dockerfile — ИИ-управляющий (AI manager)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8071
EXPOSE 8071
CMD ["node", "server.js"]
