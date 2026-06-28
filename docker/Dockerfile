# ---- Stage 1: build frontend ----
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: python runtime ----
FROM python:3.11-slim AS runtime
WORKDIR /app

# 系统依赖（最小）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/

# 前端构建产物 → backend 通过 NFM_FRONTEND_DIST 找到
ENV NFM_FRONTEND_DIST=/app/frontend/dist
COPY --from=frontend /fe/dist /app/frontend/dist

ENV NFM_DATA_DIR=/data
ENV NFM_HOST=0.0.0.0
ENV NFM_PORT=8765
VOLUME ["/data"]
EXPOSE 8765

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
