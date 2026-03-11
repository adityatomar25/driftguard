# ── DriftGuard Frontend ───────────────────────────────────────
# Multi-stage: build React app, then serve with nginx
# Build:  docker build -t driftguard-frontend frontend/
# Run:    docker run -p 3000:80 driftguard-frontend

# --- stage 1: build ---
FROM node:18-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit

COPY . .
RUN npm run build

# --- stage 2: serve with nginx ---
FROM nginx:1.25-alpine

LABEL org.opencontainers.image.title="DriftGuard Dashboard" \
      org.opencontainers.image.source="https://github.com/adityatomar25/driftguard"

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost/ || exit 1
