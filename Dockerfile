# Dockerfile — событийная шина (event bus)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8097
EXPOSE 8097
CMD ["node", "server.js"]
