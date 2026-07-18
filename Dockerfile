# Dockerfile — авто-эвалы и LLM-as-judge (evals)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8090
EXPOSE 8090
CMD ["node", "server.js"]
