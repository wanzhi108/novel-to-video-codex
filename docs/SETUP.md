# 环境搭建指南

## 1. Python 环境

### 1.1 LuminaForge 桌面应用

```bash
# 推荐使用 Python 3.11+
python -m venv venv
venv/Scripts/activate    # Windows
# pip install -r requirements.txt
```

依赖（`requirements.txt`）：
- fastapi==0.115.6
- uvicorn==0.34.0
- httpx==0.28.1
- python-multipart==0.0.20
- aiofiles==24.1.0
- websockets>=12.0
- edge-tts>=6.1.0

### 1.2 CosyVoice2 环境（独立 venv）

```bash
cd D:/CosyVoice2
python -m venv cosy_env
cosy_env/Scripts/activate
pip install torch==2.7.0+cu128  # CUDA 12.8
pip install transformers==4.51.3  # 必须精确版本！
pip install tokenizers==0.21.1
pip install modelscope==1.20.0
pip install numpy  # 必须 2.x，勿降到 1.26.4
# 其余按 CosyVoice2 官方 requirements.txt
```

### 1.3 story2 管线脚本

story2 脚本不需要额外 venv，使用系统 Python 或 WorkBuddy managed Python 即可。
依赖：`requests`（ComfyUI API 调用）、`Pillow`（图片处理）。

## 2. ComfyUI 安装

### 2.1 安装 ComfyUI

```bash
# 推荐使用 ComfyUI-WorkFisher-V2 或官方 ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI.git
```

### 2.2 模型下载

| 模型 | 放置路径 | 大小 |
|------|----------|------|
| LTX 2.3 22B fp8 | `models/diffusion_models/` | ~23GB |
| Gemma 3 12B (text encoder) | `models/text_encoders/` | ~6GB |
| VAE | `models/vae/` | ~200MB |

### 2.3 ComfyUI 自定义节点

story2 管线需要以下自定义节点：
- **ComfyUI-VideoHelperSuite** (VHS_VideoCombine) — 视频合成输出
- **ComfyUI-LTXVideo** — LTX I2V 节点

### 2.4 启动命令（低显存模式）

```bat
:: comfyui/restart_comfyui.bat 的核心命令：
D:\ComfyUI-WorkFisher-V2\python\python.exe ^
  D:\ComfyUI-WorkFisher-V2\ComfyUI\main.py ^
  --lowvram --async-offload 2 ^
  --port 8188 --listen 127.0.0.1
```

> **必须** `--lowvram --async-offload 2`。普通模式提交 LTX 22B 会直接 OOM 崩进程。

## 3. FFmpeg

```bash
# 确认安装
ffmpeg -version    # 需要 6.0+，推荐 8.x
ffprobe -version

# Windows: 下载 https://www.gyan.dev/ffmpeg/builds/ 解压后加入 PATH
```

## 4. 字体

字幕烧录需要 **NotoSansSC** 字体（已包含在 `resources/fonts/`）。

story2 管线通过 `fontsdir` 参数注入 FFmpeg，无需系统安装。

## 5. 前端构建（可选，如需修改 UI）

```bash
cd web/
npm install
npm run build    # 产物输出到 web/dist/
```

如果只修改后端逻辑，`web/dist/` 已包含预构建前端，无需重新构建。

## 6. 环境变量配置

```bash
# 复制模板
cp .env.example .env

# 编辑 .env
DEEPSEEK_API_KEY=sk-your-key-here
COMFYUI_URL=http://127.0.0.1:8188
COMFYUI_MODELS_DIR=D:/ComfyUI-WorkFisher-V2/ComfyUI/models
```

## 7. 验证安装

```bash
# 1. 验证 ComfyUI
curl http://127.0.0.1:8188/system_stats
# 应返回 JSON，含 devices.gpu_vram_total

# 2. 验证 CosyVoice2
curl http://127.0.0.1:50000/
# 应返回 200

# 3. 验证 FFmpeg
ffmpeg -version | head -1

# 4. 验证 LuminaForge（如使用桌面应用）
python scripts/launcher.py
# 浏览器访问 http://localhost:8190
```

## 8. 硬件最低要求

| 组件 | 最低 | 推荐 | 说明 |
|------|------|------|------|
| GPU VRAM | 8GB | 12GB+ | LTX 22B fp8 靠 CPU/RAM 卸载跑在 8GB |
| 系统 RAM | 16GB | 32GB+ | 16GB 是真实速度瓶颈（权重 23GB > RAM，换页） |
| 磁盘 | 60GB | 120GB+ | 模型 + ComfyUI + CosyVoice2 合计 ~100GB |
| CPU | 8 核 | 16 核+ | async-offload 时 CPU 负载高 |
