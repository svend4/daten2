# Dockerfile — автономный управляющий (autonomous manager)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8077
EXPOSE 8077
CMD ["node", "server.js"]
