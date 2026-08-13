# Multi-stage build: React SPA → static assets, then Python API serving them.
# One container = one origin (no CORS, no separate hosting).

# ---- stage 1: build the frontend -------------------------------------------
FROM node:22-alpine AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- stage 2: python app ---------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# The built SPA — api/app.py serves it from web/dist.
COPY --from=web /build/dist ./web/dist

EXPOSE 8000
# HF Spaces (Docker Space) exposes $PORT on newer runtimes; default to 8000.
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
