# Local, self-contained Skillscope: builds the index from the fictional samples in data/samples
# (no network, no keys) and serves the static site with nginx as a non-root user.
# Usage: docker compose up --build   ->   http://localhost:8080

# ---- 1. Pipeline: collect (sample API), analyze and index -------------------------------------
FROM python:3.14.8-slim-trixie AS data
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY pipeline/ pipeline/
COPY collector/ collector/
COPY analyzer/ analyzer/
COPY indexer/ indexer/
COPY config/ config/
COPY data/samples/ data/samples/
RUN uv run --no-sync python -m pipeline build --offline --out /app/site

# ---- 2. Front: type-check, bundle with SRI and scan the result for credentials ---------------
FROM node:26.11.1-trixie-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
COPY --from=data /app/site /app/site
RUN npm run build && npm run scan:bundle

# ---- 3. Runtime: static files only, unprivileged nginx --------------------------------------
FROM nginxinc/nginx-unprivileged:1.30.5-alpine3.24 AS runtime
COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY docker/nginx/security-headers.conf /etc/nginx/security-headers.conf
COPY --from=web /app/site /usr/share/nginx/html
USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
