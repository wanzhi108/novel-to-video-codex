"""
统一配置管理 - 所有环境变量、路径、阈值集中管理
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 自动加载项目根目录 .env 文件
load_dotenv(Path(__file__).parent.parent / ".env")

# ─── ComfyUI 连接 ──────────────────────────────────────────
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
# v9.6: 智能检测 ComfyUI models 目录，优先级: 环境变量 > URL 推断 > 默认值
_default_models = os.environ.get("COMFYUI_MODELS_DIR", "")
if not _default_models:
    if "8188" in COMFYUI_URL:
        _default_models = "D:/ComfyUI-WorkFisher-V2/ComfyUI/models"
    else:
        _default_models = str(Path(__file__).parent.parent / "ComfyUI" / "models")
COMFYUI_MODELS_DIR = Path(_default_models)

# ─── DeepSeek LLM ──────────────────────────────────────────
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"  # 或 deepseek-reasoner

# ─── TTS ────────────────────────────────────────────────────
TTS_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_DEFAULT_RATE = "+5%"
TTS_DEFAULT_VOLUME = "+10%"
TTS_NARRATOR_VOICE = "zh-CN-YunxiNeural"  # 旁白默认男声
# CosyVoice 2 本地 TTS（v11 新增，可选部署）
COSYVOICE_URL = "http://localhost:50000"
COSYVOICE_ENDPOINT = "/generate"          # API 端点
COSYVOICE_TIMEOUT = 60                     # 请求超时(秒)

# ─── 输出尺寸 ───────────────────────────────────────────────
# 竖屏 9:16 — 红果漫剧标准（与 main.py 保持一致）
IMG_WIDTH = 1080
IMG_HEIGHT = 1920
IMG_HIRES_SCALE = 1.5  # Hires.fix 放大倍率

# Wan2.1 480P 竖屏
WAN21_WIDTH = 480
WAN21_HEIGHT = 832
WAN21_FRAMES = 49  # 8GB VRAM 优化
WAN21_FPS = 16
WAN21_STEPS = 10
WAN21_BLOCKS_TO_SWAP = 40

# ─── 模型校验阈值 ───────────────────────────────────────────
MIN_SAFETENSORS_SIZE = 1_000_000_000  # 1GB
KNOWN_MODEL_SIZES = {
    "v1-5-pruned-emaonly.safetensors": 3_900_000_000,
    "sd1.5": 3_900_000_000,
    "DreamShaper_8_pruned.safetensors": 1_500_000_000,
    "sd_xl": 6_000_000_000,
    "animagine-xl-4.0.safetensors": 6_000_000_000,
    "realisticVision": 4_100_000_000,
    "ltx-2.3": 25_000_000_000,
    # SDXL 写实模型预期大小（FP16 baked VAE 约 6.6GB）
    "RealVisXL_V4.0.safetensors": 6_000_000_000,
    "realvisxlV40.safetensors": 6_000_000_000,
    "JuggernautXL_v9.safetensors": 6_000_000_000,
}

# ─── 路径 ────────────────────────────────────────────────────
WORKFLOW_DIR = Path(__file__).parent.parent / "comfyui_workflows"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
STATIC_DIR = Path(__file__).parent.parent / "static"

OUTPUT_DIR.mkdir(exist_ok=True)

# ─── 服务质量配置 ────────────────────────────────────────────
COMFYUI_TIMEOUT_IMAGE = 900     # 图片生成超时(秒)
COMFYUI_TIMEOUT_VIDEO = 1800    # 视频生成超时(秒)
COMFYUI_POLL_INTERVAL = 2       # 轮询间隔(秒)
WAN21_MAX_RETRIES = 2           # Wan2.1 最大重试次数
RETRY_BASE_DELAY = 5            # 重试基础延迟(秒)

# ─── QA 测试配置 ────────────────────────────────────────────
QA_MAX_AUTO_FIXES = 3           # 自动修复最大尝试次数
QA_MIN_VIDEO_DURATION = 0.5     # 最小视频时长(秒)
QA_MIN_VIDEO_SIZE = 5000        # 最小视频文件大小(bytes)
