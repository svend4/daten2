# Dockerfile — control-plane (портал)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8099
EXPOSE 8099
CMD ["node", "server.js"]
