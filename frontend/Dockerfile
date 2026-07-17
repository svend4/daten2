FROM node:20-alpine
WORKDIR /app
# vite — devDependency, поэтому ставим все зависимости (не --omit=dev)
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm","run","dev"]
