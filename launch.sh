#!/bin/bash
# Novel2Vid V1.0 一键启动脚本 (Linux/macOS)

set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     Novel2Vid V1.0 一键启动脚本          ║"
echo "║     小说转视频 AI 生成器                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装 Python 3.11+"
    exit 1
fi

# 检查 pip 依赖
echo "[检查] Python 依赖..."
if ! python3 -c "import fastapi" &> /dev/null; then
    echo "[安装] 正在安装 Python 依赖..."
    pip install -r requirements.txt
fi

# 检查 ComfyUI
echo "[检查] ComfyUI 连接..."
if ! curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
    echo "[警告] ComfyUI 未启动 (http://127.0.0.1:8188)"
    echo "  图片和视频生成功能将不可用"
    echo "  请先启动 ComfyUI"
    read -p "是否继续启动（仅 Web 界面可用）？[y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

# 检查 API Key
if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "[提示] DEEPSEEK_API_KEY 未设置"
    echo "  请在浏览器中打开 http://localhost:8190 后在界面输入"
    echo "  或设置: export DEEPSEEK_API_KEY=sk-xxx"
fi

# 启动服务器
echo ""
echo "[启动] Novel2Vid 服务器..."
echo "  浏览器访问: http://localhost:8190"
echo "  按 Ctrl+C 停止服务器"
echo ""

python3 main.py
