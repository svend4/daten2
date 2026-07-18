# Dockerfile — chaos-харнесс
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8096
EXPOSE 8096
CMD ["node", "server.js"]
