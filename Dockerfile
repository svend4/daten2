# Dockerfile — файрвол для ИИ-агентов (agent firewall)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8076
EXPOSE 8076
CMD ["node", "server.js"]
