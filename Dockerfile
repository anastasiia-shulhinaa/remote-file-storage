# Production image: FastAPI backend + the built React/Vite web client (one service).
# The web client is static files served by FastAPI; it is still only a REST client of the API.

# --- stage 1: build the web client ------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- stage 2: backend ----------------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=web /web/dist web/dist
WORKDIR /app/backend
EXPOSE 8000
# Render provides $PORT; locally it defaults to 8000. Secrets come from the environment, never the image.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
