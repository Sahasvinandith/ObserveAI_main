# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — web-frontend service (Nginx)
#
# NOTE: This service is OPTIONAL. The ai-backend (FastAPI) already serves the
# built React frontend from web/frontend/dist at the root URL (/). You only
# need this container if you want to decouple static asset serving from the
# Python process (e.g., to put a CDN or load balancer in front).
#
# Build stages:
#   1. node — installs npm dependencies and runs `vite build`
#   2. nginx — copies the static dist into a minimal Nginx image
#
# The Nginx config proxies /api/* and /ws/* to the ai-backend service,
# and serves all other routes from the React SPA.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /frontend

# Install dependencies first (cache layer)
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci --prefer-offline

# Copy source and build
COPY web/frontend/ ./
RUN npm run build

# ── Stage 2: Serve with Nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

LABEL maintainer="ObserveAI"
LABEL description="Static frontend — Nginx serving the built React app"

# Remove default Nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our custom Nginx config
# Path is relative to the build context (project root)
COPY containerized/services/web-frontend/nginx.conf /etc/nginx/conf.d/observeai.conf

# Copy built React app
COPY --from=builder /frontend/dist /usr/share/nginx/html

# Health check via Nginx stub_status (returns 200 for the root page)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:80/ >/dev/null 2>&1 || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
