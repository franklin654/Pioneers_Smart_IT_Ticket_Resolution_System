# --- Stage 1: build the React app ---
FROM node:20-alpine AS build

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci --prefer-offline

COPY frontend/ .
RUN npm run build

# --- Stage 2: serve via nginx ---
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/api/v1/health/live || exit 1
