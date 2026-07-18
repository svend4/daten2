# Dockerfile — разговорная витрина (AI storefront)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8070
EXPOSE 8070
CMD ["node", "server.js"]
