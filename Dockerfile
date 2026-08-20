# ---- 前端构建 ----
FROM node:20-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- 运行环境 ----
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ scripts/
COPY app/ app/
COPY comfyui/ comfyui/
COPY static/ static/
COPY --from=web-build /web/dist web/dist/

RUN mkdir -p output

EXPOSE 8190

ENV COMFYUI_URL=http://comfyui:8188
ENV COMFYUI_MODELS_DIR=/models

CMD ["python", "scripts/main.py"]