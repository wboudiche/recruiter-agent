# syntax=docker/dockerfile:1.7

# ---- Stage 1: build ----
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY tsconfig*.json vite.config.ts tailwind.config.ts postcss.config.js index.html ./
COPY public ./public
COPY src ./src
COPY test ./test

# Empty VITE_API_URL makes the app issue same-origin `/api/...` requests
# which nginx proxies to the backend service.
ENV VITE_API_URL=""
RUN npm run build

# ---- Stage 2: serve ----
FROM nginx:1.27-alpine AS serve

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
