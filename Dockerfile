# Dockerfile — слой наблюдаемости (observability + бенчмарк)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8074
EXPOSE 8074
CMD ["node", "server.js"]
