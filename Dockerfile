# Dockerfile — семантический поиск (AI search)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8072
EXPOSE 8072
CMD ["node", "server.js"]
