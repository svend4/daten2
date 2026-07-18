# Dockerfile — контракт codegen + CDC (Pact)
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY . .
ENV PORT=8095
EXPOSE 8095
CMD ["node", "server.js"]
