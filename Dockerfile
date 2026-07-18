# Dockerfile — RAG + память (rag-memory)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8079
EXPOSE 8079
CMD ["node", "server.js"]
