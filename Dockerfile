# Dockerfile — рынок агентов (agent-to-agent negotiation)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8078
EXPOSE 8078
CMD ["node", "server.js"]
