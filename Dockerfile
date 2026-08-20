# Novel2Vid V1.0 Docker
FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY main.py .
COPY app/ app/
COPY comfyui_workflows/ comfyui_workflows/
COPY static/ static/

# 输出和临时目录
RUN mkdir -p output

EXPOSE 8190

ENV COMFYUI_URL=http://comfyui:8188
ENV COMFYUI_MODELS_DIR=/models

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8190"]
