"""
小说转视频 - 有声小说流水线 v8.7
Novel → Paragraphs → Image Prompts → Images → Videos + Subtitles + TTS Audio
改进：智能分角色配音 / 三者同步 / QA自测 / SRT字幕 / Edge-TTS配音 / 段落同步 / 多风格管线
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import asyncio, json, os, uuid, time, random, copy, re, shutil, subprocess, logging
from pathlib import Path
import httpx, websockets
import edge_tts, sys
import gc  # v8.7.1: 移到顶部，避免循环内重复导入
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range

# 源码模式以仓库根为项目根；打包模式以 _MEIPASS 为只读资源根。
# 同时把仓库根和 scripts/ 加入 sys.path，保证 python scripts/main.py
# 也能导入 app/*、storage、video_engine、cloud_video 等模块。
PROJECT_ROOT = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Windows 控制台 UTF-8 编码修复（防止 print emoji 时 GBK 编码崩溃）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # 非关键：仅影响控制台输出编码，不影响功能

# 导入模块化组件
from app.config import DEEPSEEK_API_KEY as DEEPSEEK_DEFAULT_KEY
from app.config import COMFYUI_URL, COMFYUI_MODELS_DIR, OUTPUT_DIR, WORKFLOW_DIR
from app.config import MIN_SAFETENSORS_SIZE, KNOWN_MODEL_SIZES
from app.models import GenerateRequest
from app.models import Character, Scene, JobState

# v12.0: SQLite 存储引擎（替换 JSON 文件存储）
import storage as db_storage
# v12.0: 统一视频生成调度引擎
import video_engine

logger = logging.getLogger("novel2vid")

app = FastAPI(title="有声小说转视频 v4.0")

# ─── 禁用浏览器缓存 (防止前端更新后浏览器仍用旧版) ─────────
@app.middleware("http")
async def no_cache_middleware(request, call_next):
    response = await call_next(request)
    # 对 HTML 和 JS 文件禁用缓存
    path = request.url.path
    if path.endswith(('.html', '.js', '.css')) or path == '/':
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ─── 配置 ───────────────────────────────────────────────
# v9.10: 不再重复定义 COMFYUI_URL，统一使用 app.config 导入的值
# 如需覆盖，设置环境变量 COMFYUI_URL 即可，app.config 加载 .env 时生效
COMFYUI_WS_URL = COMFYUI_URL.replace("http", "ws").replace("https", "wss")
# v9.6: 智能检测 ComfyUI models 目录
#   1. 环境变量 COMFYUI_MODELS_DIR
#   2. 从 COMFYUI_URL 推断（如 http://127.0.0.1:8188 → 尝试 ../models 相对路径）
#   3. 默认回退路径
_default_models = os.environ.get("COMFYUI_MODELS_DIR", "")
if not _default_models:
    # 默认使用仓库旁 ComfyUI/models；可用 COMFYUI_MODELS_DIR 覆盖
    _default_models = str(PROJECT_ROOT / "ComfyUI" / "models")
COMFYUI_MODELS_DIR = Path(_default_models)
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_DEFAULT_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# ─── 已知模型合理大小（字节），用于检测损坏文件 ──────────
# 如果模型文件小于这个大小，很可能是下载中断/损坏
KNOWN_MODEL_SIZES = {
    # SD 1.5 系列 (~4GB)
    "v1-5-pruned-emaonly.safetensors": 3_900_000_000,  # ~3.9GB
    "sd1.5": 3_900_000_000,
    # DreamShaper 8 (~2GB pruned)
    "DreamShaper_8_pruned.safetensors": 1_500_000_000,  # ~2GB pruned FP16
    # SDXL 系列 (~6-7GB)
    "sd_xl": 6_000_000_000,
    "animagine-xl-4.0.safetensors": 6_000_000_000,
    "RealVisXL_V4.0.safetensors": 6_000_000_000,  # v8.7: 写实风格SDXL
    "realisticVision": 4_100_000_000,  # ~4GB (RealisticVision SD1.5)
    # LTX-Video 系列
    "ltx-2.3": 25_000_000_000,  # ~28GB
    # 通用阈值：小于1GB 的 .safetensors 几乎肯定是损坏的
}
MIN_SAFETENSORS_SIZE = 1_000_000_000  # 1GB，低于此值认为损坏
# 打包模式：工作流在 _MEIPASS（资源目录），输出到 exe 同级目录（持久化）
if getattr(sys, "frozen", False):
    WORKFLOW_DIR = PROJECT_ROOT / "comfyui"
    OUTPUT_DIR = Path(sys.executable).parent / "output"
else:
    WORKFLOW_DIR = PROJECT_ROOT / "comfyui"
    OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 竖屏 9:16 尺寸 - 红果漫剧标准 1080×1920
# v6.2: 保持高分辨率输出质量，用批处理优化速度而非降低分辨率
IMG_WIDTH = 1080
IMG_HEIGHT = 1920
VID_WIDTH = 672     # LTX-Video 2.3 推理分辨率（保持，确保质量）
VID_HEIGHT = 1152    # LTX-Video 2.3 推理分辨率（保持，确保质量）

# ─── 风格词工具函数 ─────────────────────────────────────
def _get_style_image_suffix(style: str = "cinematic") -> str:
    """根据风格返回图像提示词后缀。"""
    if style == "realistic":
        return "photorealistic, cinematic film still, realistic textures, 35mm film grain, 9:16 vertical"
    if style == "anime":
        return "anime art style, vibrant colors, clean line art, cel shading, 9:16 vertical"
    if style == "ink":
        return "chinese ink wash painting, xianxia illustration, wuxia fantasy art, 9:16 vertical"
    if style == "folk_horror":
        return ("dark chinese folk horror, realistic cinematic film still, muted earthy colors, "
                "traditional chinese paper craft, eerie supernatural atmosphere, "
                "sinister fog, dim candlelight, rural qing dynasty village, "
                "no anime, no cartoon, no western architecture, 9:16 vertical")
    # cinematic / default
    return "cinematic film still, photorealistic, dramatic lighting, shallow depth of field, 9:16 vertical"

def _get_style_video_suffix(style: str = "cinematic") -> str:
    """根据风格返回视频提示词后缀。"""
    if style == "realistic":
        return "cinematic live action, photorealistic, 35mm film look, smooth camera movement, 9:16 vertical"
    if style == "anime":
        return "anime style, vibrant colors, clean line art, smooth animation, 9:16 vertical"
    if style == "ink":
        return "chinese ink wash painting, xianxia fantasy illustration, flowing ink animation, 9:16 vertical"
    if style == "folk_horror":
        return ("dark chinese folk horror live action, realistic cinematic motion, "
                "eerie supernatural atmosphere, muted earthy colors, "
                "subtle camera movement, slow push in, 9:16 vertical")
    return "cinematic film look, photorealistic, dramatic lighting, smooth camera movement, 9:16 vertical"

# ─── 内存存储 ────────────────────────────────────────────
jobs: dict = {}  # job_id → JobState，将在 JobStorage 定义后初始化
ws_clients: dict = {}  # job_id → list[WebSocket] 用于推送进度
_background_tasks: set = set()  # v8.7.1: 后台任务跟踪，防止异常静默丢失
_ws_locks: dict = {}  # job_id → asyncio.Lock 保护并发访问
JOB_PORTRAIT_MAP: dict = {}  # v12.2: job_id → {character_name: uploaded_image_url} IP-Adapter 定妆照锚定


def _spawn_background_task(coro, name: str = "unknown"):
    """v8.7.1: 安全启动后台任务，记录异常"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(lambda t: logger.error(
        f"[Background] {name} 失败: {t.exception()}"
    ) if t.exception() else None)
    return task


# ─── 数据模型 ────────────────────────────────────────────
class JobStorage:
    """v12.0: SQLite 持久化存储 — 替换 JSON 文件存储
    保持与旧接口兼容，内部委托给 storage.py 的 SQLite 引擎。
    """
    STORAGE_DIR = OUTPUT_DIR / "jobs"  # 保留旧路径引用（兼容）

    @staticmethod
    async def save(job: JobState):
        """异步保存 job 到 SQLite"""
        await db_storage.sync_save(job)

    @staticmethod
    async def load_all() -> dict[str, JobState]:
        """从 SQLite 加载所有 job"""
        return await db_storage.sync_load_all()

    @staticmethod
    async def delete(job_id: str):
        """从 SQLite 删除 job"""
        await db_storage.sync_delete(job_id)

    @staticmethod
    async def list_jobs() -> list[dict]:
        """返回所有 job 摘要列表（SQL 查询，无需加载完整数据）"""
        return await db_storage.sync_list_jobs()

    @staticmethod
    async def export_job(job_id: str) -> Optional[dict]:
        """v12.1: 导出任务为字典"""
        return await db_storage.sync_export_job(job_id)

    @staticmethod
    async def import_job(data: dict) -> Optional[JobState]:
        """v12.1: 从字典导入任务"""
        return await db_storage.sync_import_job(data)

    @staticmethod
    async def archive_old_jobs(days: int = 30) -> list[str]:
        """v12.1: 归档指定天数未更新的任务"""
        return await db_storage.sync_archive_old_jobs(days)

    @staticmethod
    async def list_archived() -> list[dict]:
        """v12.1: 列出已归档任务"""
        return await db_storage.sync_list_archived()

    @staticmethod
    async def restore_archived(job_id: str) -> Optional[JobState]:
        """v12.1: 从归档恢复任务"""
        return await db_storage.sync_restore_archived(job_id)

# ─── 初始化内存存储（启动时从 SQLite 加载）──────────────────
jobs: dict = {}  # job_id → JobState，在 startup 事件中从 SQLite 加载

# ─── DeepSeek API 调用 ────────────────────────────────────
async def call_deepseek(api_key: str, system_prompt: str, user_prompt: str,
                        model: str = "deepseek-chat", max_tokens: int = 8192,
                        temperature: float = 0.7) -> str:
    """调用 DeepSeek API，含自动重试（指数退避）+ 截断检测自动扩容
    temperature 建议值：分析提取类=0.3, 创意生成类=0.7, 平衡类=0.5"""
    if not api_key or not api_key.strip():
        raise ValueError("DeepSeek API Key 未填写，请在上传步骤中填入有效的 API Key")

    current_max_tokens = max_tokens
    max_token_cap = 65536  # DeepSeek 最大输出上限

    for truncation_round in range(3):  # 最多扩容 2 次
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": current_max_tokens
        }

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(DEEPSEEK_URL, json=payload, headers=headers)
                    if resp.status_code == 401:
                        raise ValueError("DeepSeek API Key 无效或已过期，请检查 API Key 是否正确")
                    if resp.status_code == 402:
                        raise ValueError("DeepSeek 账户余额不足，请充值后重试")
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        print(f"[DeepSeek] 429 限频，第 {attempt+1} 次重试，等待 {wait}s", flush=True)
                        if attempt < 2:
                            await asyncio.sleep(wait)
                            continue
                        raise ValueError("DeepSeek API 请求频率超限（多次重试失败），请稍后重试")
                    # v9.5: 显式处理 "input length too long" 400 错误
                    if resp.status_code == 400:
                        try:
                            error_data = resp.json()
                            error_msg = error_data.get("error", {}).get("message", "")
                        except Exception:
                            error_msg = resp.text
                        if "input length too long" in error_msg.lower():
                            raise ValueError(
                                f"DeepSeek 输入太长（400）: 总 prompt 超过模型上下文限制。"
                                f"当前 system={len(system_prompt)}chars + user={len(user_prompt)}chars。"
                                f"建议：缩短原文或精简角色/环境分析。\n错误详情: {error_msg[:300]}"
                            )
                        raise ValueError(f"DeepSeek API 400 错误: {error_msg[:300]}")
                    if resp.status_code >= 500:
                        wait = 2 ** attempt
                        print(f"[DeepSeek] HTTP {resp.status_code}，第 {attempt+1} 次重试，等待 {wait}s", flush=True)
                        if attempt < 2:
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    finish_reason = choice.get("finish_reason", "stop")

                    # ——— 截断检测：finish_reason == "length" 表示输出因 token 限制被截断 ———
                    if finish_reason == "length" and truncation_round < 2:
                        new_tokens = min(current_max_tokens * 2, max_token_cap)
                        if new_tokens > current_max_tokens:
                            print(f"[DeepSeek] 输出被截断 (max_tokens={current_max_tokens})，"
                                  f"扩容至 {new_tokens} 后重试", flush=True)
                            current_max_tokens = new_tokens
                            break  # 跳出重试循环，进入下一轮扩容
                        else:
                            print(f"[DeepSeek] 输出被截断但已达上限 ({max_token_cap})，"
                                  f"返回不完整结果", flush=True)
                    return content
            except httpx.TimeoutException:
                wait = 2 ** attempt
                print(f"[DeepSeek] 超时，第 {attempt+1} 次重试，等待 {wait}s", flush=True)
                if attempt < 2:
                    await asyncio.sleep(wait)
                    continue
            except httpx.ConnectError:
                wait = 2 ** attempt
                print(f"[DeepSeek] 连接失败，第 {attempt+1} 次重试，等待 {wait}s", flush=True)
                if attempt < 2:
                    await asyncio.sleep(wait)
                    continue
            except ValueError:
                raise  # 不重试客户端错误（401/402）
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"[DeepSeek] 异常: {str(e)[:100]}，第 {attempt+1} 次重试，等待 {wait}s", flush=True)
                    await asyncio.sleep(wait)
                    continue
            # 重试次数耗尽，如果还有扩容机会则继续，否则报错
            if truncation_round >= 2:
                raise ValueError(f"DeepSeek API 调用失败（多轮重试无效）")

        # 本轮扩容等待后继续外层循环
        if truncation_round < 2:
            await asyncio.sleep(1)
            continue

    raise ValueError(f"DeepSeek API 调用失败（输出持续被截断，已达 token 上限 {max_token_cap}）")

# ─── 内容安全预检（红果4月7日审核新规）───────────────────
CONTENT_SAFETY_SYSTEM = """你是红果短剧平台内容审核专家，严格遵守2026年4月7日新版审核标准。
你需要逐项检查以下内容是否违规，返回JSON格式结果：

审核维度（5项，每项pass=true表示通过）：
1. values_check: 价值观审查 - 不能有拜金主义/躺平主义/仇恨煽动/阶级对立/违法犯罪美化/历史虚无主义
2. visual_check: 画风审查 - 不能有恐怖血腥/猎奇惊悚/画面刺眼不适/过度暴力/性暗示
3. taste_check: 品味审查 - 不能有低俗内容/粗口脏话/歧视性语言/侮辱性内容
4. copyright_check: 版权审查 - 不能有AI魔改知名IP/无授权肖像/真人明星相似/抄袭知名作品
5. political_check: 政治审查 - 不能有政治敏感内容/分裂言论/攻击现行制度/涉政隐喻

返回格式（只返回JSON）:
{"pass": true/false, "issues": ["问题描述"], "risk_level": "low/medium/high", "detail": {"values_check": true, "visual_check": true, "taste_check": true, "copyright_check": true, "political_check": true}}"""

async def content_safety_check(api_key: str, text: str) -> dict:
    """内容安全预检 — 红果4月7日审核标准
    
    返回: {"pass": bool, "issues": [str], "risk_level": str, "detail": dict}
    如果 DeepSeek API 不可用，默认放行（不做阻塞）
    """
    if not api_key or not text:
        return {"pass": True, "issues": [], "risk_level": "low", "detail": {}}
    
    # 控制检查文本长度（太多token浪费）
    check_text = text[:4000]
    
    try:
        result = await call_deepseek(
            api_key,
            CONTENT_SAFETY_SYSTEM,
            f"请审核以下小说内容是否符合红果平台审核标准：\n\n{check_text}",
            max_tokens=1024,
            temperature=0.3  # 内容审核需要确定性输出
        )
        safety = extract_json_object(result) or {}
        if not safety:
            return {"pass": True, "issues": [], "risk_level": "low", "detail": {}}
        
        return {
            "pass": safety.get("pass", True),
            "issues": safety.get("issues", []),
            "risk_level": safety.get("risk_level", "low"),
            "detail": safety.get("detail", {})
        }
    except Exception as e:
        print(f"[SafetyCheck] 审核调用失败（不阻塞流程）: {e}", flush=True)
        return {"pass": True, "issues": [f"审核系统暂不可用: {str(e)[:80]}"], "risk_level": "low", "detail": {}}

# ─── ComfyUI API 客户端 ────────────────────────────────────
class ComfyUIClient:
    def __init__(self, base_url: str = COMFYUI_URL):
        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws").replace("https", "wss")
        self._last_comfyui_error = ""
        self._last_comfyui_node = ""
        self._last_comfyui_node_id = ""

    async def get_checkpoints(self) -> list[str]:
        """从ComfyUI API获取可用checkpoint列表，并过滤掉损坏文件"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/object_info/CheckpointLoaderSimple")
                resp.raise_for_status()
                data = resp.json()
                cfg = data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"]
                if isinstance(cfg, list) and len(cfg) > 0:
                    if isinstance(cfg[0], list):
                        checkpoints = cfg[0]
                    else:
                        checkpoints = cfg
                else:
                    return []
        except Exception as e:
            self._last_comfyui_error = f"get_checkpoints: {e}"
            logger.warning(f"[ComfyUI] 获取checkpoints列表失败: {e}")
            return []

    def _validate_checkpoint_file(self, filename: str) -> bool:
        """验证checkpoint文件完整性：大小检查 + SHA256边车文件校验"""
        ckpt_dir = COMFYUI_MODELS_DIR / "checkpoints"
        filepath = ckpt_dir / filename
        
        # 文件不存在（可能是子目录或其他存储方式）→ 放行，交给ComfyUI处理
        if not filepath.exists():
            return True
        
        try:
            size = filepath.stat().st_size
        except OSError:
            return True  # 读取失败，放行
        
        # 空文件占位符 → 过滤
        if size == 0:
            logger.warning(f"[模型校验] 跳过空文件: {filename}")
            return False
        
        # 小于最小阈值 → 几乎肯定是损坏的
        if size < MIN_SAFETENSORS_SIZE:
            logger.warning(f"[模型校验] 跳过疑似损坏文件 ({size/1e9:.1f}GB): {filename}")
            return False
        
        # 检查已知模型的期望大小（允许15%偏差）
        for key, expected_size in KNOWN_MODEL_SIZES.items():
            if key.lower() in filename.lower():
                min_size = expected_size * 0.85
                if size < min_size:
                    logger.warning(
                        f"[模型校验] 跳过损坏文件: {filename} "
                        f"(实际{size/1e9:.1f}GB < 预期≥{min_size/1e9:.1f}GB)"
                    )
                    return False
                break
        
        # SHA256 边车文件校验（可选：仅在 .sha256 文件存在时启用）
        sha256_path = filepath.with_suffix(filepath.suffix + ".sha256")
        if sha256_path.exists():
            try:
                expected_hash = sha256_path.read_text().strip().split()[0].lower()
                if len(expected_hash) >= 64:
                    import hashlib
                    hasher = hashlib.sha256()
                    with open(filepath, "rb") as f:
                        while chunk := f.read(8 * 1024 * 1024):  # 8MB chunks
                            hasher.update(chunk)
                    actual_hash = hasher.hexdigest()
                    if actual_hash != expected_hash:
                        logger.warning(f"[模型校验] SHA256 不匹配: {filename}")
                        return False
            except Exception:
                pass  # 哈希校验失败不阻塞，回退到大小校验
        
        return True

    async def normalize_checkpoint_name(self, name: str) -> str:
        """v9.6: 自动补全 checkpoint 扩展名 + 验证名称在 ComfyUI 可用列表中
        
        问题: 前端或用户可能传入不含 .safetensors 的 checkpoint 名（如 "RealVisXL_V4.0"），
        导致 ComfyUI 400 验证失败。
        
        策略: 从 ComfyUI /object_info 拉取可用列表，模糊匹配后返回规范名称。
        无匹配时原样返回（让 submit_workflow 报更清晰的错误）。
        """
        if not name:
            return name
        
        # 如果已有 .safetensors 或 .ckpt 扩展名，直接验证
        if name.endswith(('.safetensors', '.ckpt', '.pt')):
            return name
        
        # 从 ComfyUI 拉取可用 checkpoint 列表（带缓存）
        try:
            available = await self.get_checkpoints()
        except Exception:
            print(f"[CheckpointNorm] 无法获取 ComfyUI checkpoint 列表，原样返回: {name}", flush=True)
            return name
        
        if not available:
            print(f"[CheckpointNorm] ComfyUI 返回空列表，原样返回: {name}", flush=True)
            return name
        
        # 精确匹配：name + .safetensors
        with_ext = name + ".safetensors"
        if with_ext in available:
            print(f"[CheckpointNorm] 自动补全: {name} → {with_ext}", flush=True)
            return with_ext
        
        # 精确匹配：name + .ckpt
        with_ckpt = name + ".ckpt"
        if with_ckpt in available:
            print(f"[CheckpointNorm] 自动补全: {name} → {with_ckpt}", flush=True)
            return with_ckpt
        
        # 前缀匹配（处理带子目录路径的情况，如 "wanvideo/Wan2_1_VAE"）
        for avail in available:
            if avail.endswith("/" + with_ext) or avail.endswith("\\" + with_ext):
                print(f"[CheckpointNorm] 路径匹配: {name} → {avail}", flush=True)
                return avail
        
        # 模糊匹配（忽略大小写）
        name_lower = name.lower()
        for avail in available:
            avail_lower = avail.lower().replace("\\", "/")
            if avail_lower.endswith("/" + name_lower + ".safetensors") or \
               avail_lower.endswith("/" + name_lower + ".ckpt"):
                print(f"[CheckpointNorm] 模糊匹配: {name} → {avail}", flush=True)
                return avail
        
        # 无匹配：输出警告，原样返回
        available_sample = ", ".join(available[:5])
        print(f"[CheckpointNorm] ⚠️ 无法匹配: {name} (可用: {available_sample}...)", flush=True)
        return name

    @staticmethod
    def find_output_file(outputs: dict, prefer_types: list = None) -> tuple:
        """递归搜索 ComfyUI outputs 中的文件。
        
        ComfyUI 不同节点使用不同的输出键名：
        - SaveImage → "images"
        - VHS_VideoCombine → "gifs" (即使输出是 .mp4)
        - PreviewImage 等 → "images"
        
        本函数递归搜索所有嵌套层级，按 prefer_types 优先级返回。
        
        Returns:
            (filename, subfolder, file_type) 或 (None, "", "")
        """
        if prefer_types is None:
            prefer_types = ["gifs", "videos", "images"]
        
        def _search(data: dict, depth: int = 0) -> list[tuple]:
            """递归搜索，返回所有找到的 (filename, subfolder, type, depth)"""
            results = []
            if depth > 10 or not isinstance(data, dict):
                return results
            for key, val in data.items():
                if key in ("images", "gifs", "videos") and isinstance(val, list) and val:
                    for item in val:
                        if isinstance(item, dict) and "filename" in item:
                            results.append((item["filename"], item.get("subfolder", ""), key, depth))
                elif isinstance(val, dict):
                    results.extend(_search(val, depth + 1))
                elif isinstance(val, list):
                    for v in val:
                        if isinstance(v, dict):
                            results.extend(_search(v, depth + 1))
            return results
        
        all_results = _search(outputs)
        if not all_results:
            # 最后兜底：尝试直接遍历 outputs 顶层
            for node_id, node_out in outputs.items():
                if isinstance(node_out, dict):
                    for key in prefer_types:
                        if key in node_out and node_out[key]:
                            info = node_out[key][0]
                            if isinstance(info, dict) and "filename" in info:
                                return info["filename"], info.get("subfolder", ""), key
            return None, "", ""
        
        # 按 prefer_types 优先级 + 深度（浅层优先）排序
        type_order = {t: i for i, t in enumerate(prefer_types)}
        all_results.sort(key=lambda x: (type_order.get(x[2], 99), x[3]))
        best = all_results[0]
        return best[0], best[1], best[2]

    async def get_models(self) -> dict:
        """获取所有可用模型列表 (checkpoints + vae + loras)"""
        checkpoints = await self.get_checkpoints()
        vae_list = await self.get_vae_list()
        loras: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/object_info/LoraLoader")
                resp.raise_for_status()
                data = resp.json()
                cfg = data["LoraLoader"]["input"]["required"]["lora_name"]
                if isinstance(cfg, list) and len(cfg) > 0:
                    loras = cfg[0] if isinstance(cfg[0], list) else cfg
        except Exception as e:
            logger.warning(f"[ComfyUI] 获取模型列表失败: {str(e)[:100]}")
        return {"checkpoints": checkpoints, "vae": vae_list, "loras": loras}

    async def get_vae_list(self) -> list[str]:
        """获取可用VAE列表"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/object_info/VAELoader")
                resp.raise_for_status()
                data = resp.json()
                cfg = data["VAELoader"]["input"]["required"]["vae_name"]
                if isinstance(cfg, list) and len(cfg) > 0:
                    if isinstance(cfg[0], list):
                        return cfg[0]
                    return cfg
                return []
        except Exception as e:
            logger.warning(f"[ComfyUI] 获取VAE列表失败: {e}")
            return []

    async def interrupt(self):
        """中断当前ComfyUI任务"""
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{self.base_url}/interrupt")
            return resp.status_code == 200

    async def get_queue(self) -> dict:
        """获取队列状态"""
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{self.base_url}/queue")
            resp.raise_for_status()
            return resp.json()

    async def submit_workflow(self, workflow: dict) -> str:
        """提交工作流，返回 prompt_id
        
        v9.6: 增强 400 错误日志化 — 解析 ComfyUI 返回的 invalid prompt 详情。
        v9.7: 增加调试日志 — 输出工作流摘要。
        """
        payload = json.dumps({"prompt": workflow}, ensure_ascii=False).encode("utf-8")
        # v9.7 调试: 输出工作流节点摘要
        checkpoint_name = "?"
        for nid, ndata in workflow.items():
            if ndata.get("class_type") == "CheckpointLoaderSimple":
                checkpoint_name = ndata.get("inputs", {}).get("ckpt_name", "?")
                break
        dims = "?"
        for nid, ndata in workflow.items():
            if ndata.get("class_type") == "EmptyLatentImage":
                w = ndata.get("inputs", {}).get("width", "?")
                h = ndata.get("inputs", {}).get("height", "?")
                dims = f"{w}×{h}"
                break
        node_count = len(workflow)
        print(f"[ComfyUI] 提交工作流: {node_count}节点, checkpoint={checkpoint_name}, 尺寸={dims}", flush=True)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/prompt",
                content=payload,
                headers={"Content-Type": "application/json"}
            )
            # v9.6: 400 错误日志化 — 解析 ComfyUI 返回的验证详情
            if resp.status_code == 400:
                try:
                    error_data = resp.json()
                except Exception:
                    error_data = {"error": resp.text}
                
                # 提取关键调试信息
                node_count = len(workflow)
                checkpoint_nodes = []
                for nid, ndata in workflow.items():
                    if ndata.get("class_type") == "CheckpointLoaderSimple":
                        ckpt = ndata.get("inputs", {}).get("ckpt_name", "?")
                        checkpoint_nodes.append(f"node#{nid}.ckpt_name={ckpt}")
                    elif "checkpoint" in str(ndata.get("inputs", {})).lower():
                        for k, v in ndata.get("inputs", {}).items():
                            if "checkpoint" in k.lower() or "ckpt" in k.lower():
                                checkpoint_nodes.append(f"node#{nid}.{k}={v}")
                
                detail_msg = str(error_data.get("error", error_data))[:300]
                ckpt_info = "; ".join(checkpoint_nodes[:5]) if checkpoint_nodes else "无 checkpoint 节点"
                raise RuntimeError(
                    f"ComfyUI 400: 工作流验证失败。"
                    f"工作流节点数={node_count}, checkpoint信息=[{ckpt_info}]. "
                    f"ComfyUI响应: {detail_msg}"
                )
            resp.raise_for_status()
            return resp.json()["prompt_id"]

    async def wait_for_result_ws(self, prompt_id: str, job_id: str = "", scene_id: int = 0,
                                  timeout: int = 1200) -> dict:
        """等待 ComfyUI 任务完成，带进度推送和自动重试。
        
        使用 HTTP 轮询 history API + 可选 queue API 获取剩余任务数。
        支持指数退避重试（网络临时故障）。
        """
        start = time.time()
        self._last_comfyui_error = ""
        self._last_comfyui_node = ""
        self._last_comfyui_node_id = ""
        last_progress_push = 0.0  # 进度推送节流
        
        print(f"[INFO] 等待任务完成: prompt_id={prompt_id[:20]}..., timeout={timeout}s", flush=True)
        
        async with httpx.AsyncClient(timeout=10) as client:
            while time.time() - start < timeout:
                try:
                    # 同时获取 history（任务状态）和 queue（队列位置）
                    resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                    if resp.status_code == 200:
                        data = resp.json()
                        if prompt_id in data:
                            entry = data[prompt_id]
                            status = entry.get("status", {})
                            
                            # 检查是否完成
                            if status.get("completed", False):
                                print(f"[INFO] [OK] 任务完成: {prompt_id[:20]}...", flush=True)
                                if job_id:
                                    await self._push_progress(job_id, scene_id, {
                                        "comfyui_progress": 1.0,
                                        "comfyui_status": "completed"
                                    })
                                return entry
                            
                            # 检查是否有错误
                            if status.get("status_str") == "error":
                                msgs = status.get("messages", [])
                                for m in msgs:
                                    if m[0] == "execution_error":
                                        err = m[1]
                                        self._last_comfyui_error = err.get('exception_message', '未知错误')
                                        self._last_comfyui_node = err.get('node_type', '?')
                                        self._last_comfyui_node_id = err.get('node_id', '?')
                                # v9.7: 增强错误信息 — 附加 ComfyUI 系统状态
                                extra_info = ""
                                try:
                                    async with httpx.AsyncClient(timeout=5) as c:
                                        r2 = await c.get(f"{self.base_url}/system_stats")
                                        if r2.status_code == 200:
                                            ds = r2.json().get("devices", [{}])
                                            for d in ds:
                                                if d.get("type") == "cuda" or "cuda" in d.get("name", ""):
                                                    vram_total = d.get("vram_total", 0)
                                                    vram_free = d.get("vram_free", 0)
                                                    if vram_total > 0:
                                                        extra_info = (
                                                            f" | VRAM空闲={vram_free/(1024**2):.0f}MB"
                                                            f"/总计={vram_total/(1024**2):.0f}MB"
                                                        )
                                                        break
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    f"ComfyUI 节点 [{self._last_comfyui_node_id}] {self._last_comfyui_node} 执行失败: "
                                    f"{self._last_comfyui_error[:300]}{extra_info}"
                                )
                            
                            # 推送进度（节流：最多每秒一次）
                            if job_id and (time.time() - last_progress_push) > 1.0:
                                last_progress_push = time.time()
                                try:
                                    # 尝试从 queue API 获取排队位置
                                    q_resp = await client.get(f"{self.base_url}/queue")
                                    if q_resp.status_code == 200:
                                        q = q_resp.json()
                                        running = q.get("queue_running", [])
                                        pending = q.get("queue_pending", [])
                                        total_ahead = len(pending) + (0 if running and running[0][1] == prompt_id else len(running))
                                        await self._push_progress(job_id, scene_id, {
                                            "comfyui_progress": min(0.95, 1.0 / (1 + total_ahead)),
                                            "comfyui_status": "running",
                                            "comfyui_queue_ahead": total_ahead
                                        })
                                except Exception:
                                    pass  # queue 查询失败不影响主流程
                
                except Exception as e:
                    if "ComfyUI" in str(e):
                        raise
                    # 其他错误（如网络错误），继续轮询
                    print(f"[WARN] 轮询出错，继续尝试: {e}", flush=True)
                
                # 等待 2 秒后再次轮询
                await asyncio.sleep(2)
            
            # 超时
            raise TimeoutError(f"ComfyUI 工作流超时 ({timeout}s): {prompt_id}")
    
    async def _push_progress(self, job_id: str, scene_id: int, progress_data: dict):
        """推送 ComfyUI 内部进度到前端（通过 broadcast_progress）"""
        try:
            await broadcast_progress(job_id, {
                "type": "comfyui_progress",
                "scene_id": scene_id,
                **progress_data
            })
        except Exception:
            pass  # 进度推送失败不影响主流程

    async def _wait_for_result_poll(self, prompt_id: str, timeout: int = 600) -> dict:
        """回退轮询方式"""
        start = time.time()
        async with httpx.AsyncClient(timeout=30) as client:
            while time.time() - start < timeout:
                resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    if prompt_id in data:
                        entry = data[prompt_id]
                        status = entry.get("status", {})
                        if status.get("completed", False) or status.get("status_str") == "success":
                            return entry
                        if status.get("status_str") == "error":
                            msgs = status.get("messages", [])
                            err_detail = ""
                            for m in msgs:
                                if m[0] == "execution_error":
                                    err = m[1]
                                    err_detail = f"节点 [{err.get('node_id', '?')}] {err.get('node_type', '?')}: {err.get('exception_message', '')[:300]}"
                            raise RuntimeError(f"ComfyUI 执行失败: {err_detail}")
                await asyncio.sleep(2)
        raise TimeoutError(f"Workflow {prompt_id} timed out after {timeout}s")

    async def upload_image(self, image_path: str, overwrite: bool = True) -> str:
        filename = Path(image_path).name
        async with httpx.AsyncClient(timeout=30) as client:
            with open(image_path, "rb") as f:
                resp = await client.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (filename, f, "image/png")},
                    data={"overwrite": str(overwrite).lower()}
                )
            resp.raise_for_status()
            return resp.json().get("name", filename)

    async def download_output(self, filename: str, subfolder: str = "",
                              output_type: str = "output", save_dir: Path = OUTPUT_DIR) -> str:
        async with httpx.AsyncClient(timeout=900) as client:
            resp = await client.get(
                f"{self.base_url}/view",
                params={"filename": filename, "subfolder": subfolder, "type": output_type}
            )
            resp.raise_for_status()
            save_path = save_dir / filename
            save_path.write_bytes(resp.content)
            return str(save_path)

comfyui = ComfyUIClient()

# ─── WebSocket 进度广播 ──────────────────────────────────
async def broadcast_progress(job_id: str, data: dict):
    """向所有监听该 job 的 WebSocket 客户端推送进度 (v8.7: 加锁保护并发)"""
    if job_id not in ws_clients:
        return
    # 获取或创建该 job_id 的锁
    if job_id not in _ws_locks:
        _ws_locks[job_id] = asyncio.Lock()
    async with _ws_locks[job_id]:
        dead = []
        clients = list(ws_clients[job_id])
        for ws in clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in ws_clients.get(job_id, []):
                ws_clients[job_id].remove(ws)

@app.websocket("/ws/progress/{job_id}")
async def ws_progress(websocket: WebSocket, job_id: str):
    """前端 WebSocket 接入点，用于接收实时进度 (v8.7: 加锁保护并发)"""
    await websocket.accept()
    if job_id not in _ws_locks:
        _ws_locks[job_id] = asyncio.Lock()
    async with _ws_locks[job_id]:
        if job_id not in ws_clients:
            ws_clients[job_id] = []
        ws_clients[job_id].append(websocket)
    try:
        while True:
            await websocket.receive_text()  # 保持连接
    except WebSocketDisconnect:
        async with _ws_locks.get(job_id, asyncio.Lock()):
            if job_id in ws_clients and websocket in ws_clients[job_id]:
                ws_clients[job_id].remove(websocket)

# ─── 工作流模板处理 ────────────────────────────────────────
def load_workflow(name: str) -> dict:
    with open(WORKFLOW_DIR / f"{name}.json", "r", encoding="utf-8") as f:
        return json.load(f)

def fill_workflow(template: dict, replacements: dict) -> dict:
    """将模板中的占位符替换为实际值，支持字符串和数字类型。

    模板中占位符格式为 "{{KEY}}"（带引号，使模板是合法 JSON）。
    替换时根据值的类型决定是否需要引号：
    - 字符串/其他类型：保留引号，替换为 "value"
    - 数字类型：去掉引号，替换为 1234

    v9.10 修复: 按 key 长度降序排序，避免短 key 作为长 key 的子串被误替换
    （如 "WIDTH" 先于 "HIRES_WIDTH" 替换会导致 "{{HIRES_WIDTH}}" 变成 "{{HIRES_1080}}" 无法匹配）。
    """
    workflow = copy.deepcopy(template)
    json_str = json.dumps(workflow, ensure_ascii=False)
    # 按 key 长度降序：确保 HIRES_WIDTH 先于 WIDTH 替换，避免子串误匹配
    sorted_items = sorted(replacements.items(), key=lambda kv: -len(kv[0]))
    for key, val in sorted_items:
        # 占位符在 JSON 字符串中形如："{{KEY}}"（含 JSON 双引号）
        placeholder = '"{{' + key + '}}"'
        if isinstance(val, (int, float)):
            # 数字类型：去掉引号，直接替换为数字
            json_str = json_str.replace(placeholder, str(val))
        else:
            # 字符串类型：保留引号，只替换内容
            json_str = json_str.replace(placeholder, json.dumps(str(val)))
    return json.loads(json_str)

# ─── FFmpeg 工具 ──────────────────────────────────────────
def find_ffmpeg() -> str:
    """查找 ffmpeg 可执行文件"""
    # 0. v12.1: 显式环境变量（最优先，规避后台进程 PATH/家目录解析差异导致找不到 ffmpeg）
    for _env_key in ("FFMPEG_PATH", "FFMPEG_BIN"):
        _ef = os.environ.get(_env_key, "")
        if _ef and Path(_ef).exists():
            return _ef
    # 1. 环境变量（PATH 搜索）
    p = shutil.which("ffmpeg")
    if p:
        return p
    # 2. ComfyUI 自带的 ffmpeg（从环境变量或常见安装目录查找）
    comfyui_base = os.environ.get("COMFYUI_PATH", "")
    if comfyui_base:
        comfyui_ffmpeg = Path(comfyui_base) / "ffmpeg" / "ffmpeg.exe" if sys.platform == "win32" else Path(comfyui_base) / "ffmpeg" / "ffmpeg"
        if comfyui_ffmpeg.exists():
            return str(comfyui_ffmpeg)
    # 3. 常见路径（v9.6: 扩展搜索范围，添加 PATH 搜索）
    common_paths = ["C:/ffmpeg/bin/ffmpeg.exe", "D:/ffmpeg/bin/ffmpeg.exe"]
    # 也尝试在 PATH 中查找
    try:
        import subprocess
        result = subprocess.run(["where", "ffmpeg"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            paths = result.stdout.strip().split("\n")
            common_paths = paths + common_paths
    except Exception:
        pass
    for path in common_paths:
        if Path(path).exists():
            return path
    # 4. v12.1: 通配符搜索（WinGet 包 / ComfyUI 自带 / Program Files）
    #    规避「后端进程 PATH 不含 ffmpeg」导致 find_ffmpeg 返回空、Ken Burns 静默失效、
    #    进而回退到 22B 视频模型在 8GB 显存下 OOM 的问题。
    try:
        # WinGet 安装的 Gyan.FFmpeg（通配搜索，不依赖具体版本号）
        wg = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        if wg.exists():
            for p in wg.rglob("ffmpeg.exe"):
                if Path(str(p)).exists():
                    return str(p)
        # ComfyUI 自带 ffmpeg
        for base in [os.environ.get("COMFYUI_PATH", ""), str(Path.home() / "ComfyUI"), "C:/ComfyUI"]:
            if base:
                f = Path(base) / "ffmpeg" / "ffmpeg.exe"
                if f.exists():
                    return str(f)
    except Exception:
        pass
    return ""

# ─── Edge-TTS 配音 ──────────────────────────────────────────
# 推荐的中文声音列表
RECOMMENDED_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "gender": "女", "style": "温柔自然", "recommended": True},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓依", "gender": "女", "style": "活泼年轻"},
    {"id": "zh-CN-YunjianNeural", "name": "云健", "gender": "男", "style": "沉稳大气", "recommended": True},
    {"id": "zh-CN-YunxiNeural", "name": "云希", "gender": "男", "style": "阳光活力"},
    {"id": "zh-CN-YunxiaNeural", "name": "云夏", "gender": "男", "style": "少年清朗"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬", "gender": "男", "style": "新闻播报"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北", "gender": "女", "style": "东北口音"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮", "gender": "女", "style": "陕西口音"},
    {"id": "zh-HK-HiuGaaiNeural", "name": "曉佳", "gender": "女", "style": "粤语"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻", "gender": "女", "style": "台湾腔"},
]

# ─── TTS 情感参数映射（v9.9: 扩展情绪类型 + intensity 强度控制）──
_TTS_MOOD_PARAMS = {
    "紧张":  {"rate": "+8%",   "pitch": "+2Hz"},   # 加快语速，音调略升
    "恐惧":  {"rate": "+5%",   "pitch": "-2Hz"},   # 语速略快，音调压低（颤抖感）
    "愤怒":  {"rate": "+10%",  "pitch": "+3Hz"},   # 语速加快，音调升高
    "悲伤":  {"rate": "-10%",  "pitch": "-3Hz"},   # 语速减慢，音调低沉
    "喜悦":  {"rate": "+6%",   "pitch": "+2Hz"},   # 语速略快，音调上扬
    "压抑":  {"rate": "-8%",   "pitch": "-2Hz"},   # 语速放缓，音调压低
    "壮阔":  {"rate": "-3%",   "pitch": "+1Hz"},   # 语速略慢（大气），音调稳重
    "热血":  {"rate": "+12%",  "pitch": "+3Hz"},   # 快速有力，音调高昂
    "释然":  {"rate": "-5%",   "pitch": "-1Hz"},   # 放缓释放，音调略低
    "孤独":  {"rate": "-12%",  "pitch": "-3Hz"},   # 最慢，最低沉
    "惆怅":  {"rate": "-7%",   "pitch": "-2Hz"},   # 缓慢忧郁
    "温馨":  {"rate": "-5%",   "pitch": "+0Hz"},   # 温柔缓和，音调自然
    "神秘":  {"rate": "-5%",   "pitch": "-1Hz"},   # 缓慢神秘
    "悸动":  {"rate": "+3%",   "pitch": "+1Hz"},   # 略快，心跳感
    # v9.9 新增：喜剧/日常情绪
    "幽默":  {"rate": "+4%",   "pitch": "+1Hz"},   # 略快，音调上扬（轻松诙谐）
    "无奈":  {"rate": "-6%",   "pitch": "-2Hz"},   # 放缓，音调低沉（叹气感）
    "得意":  {"rate": "+5%",   "pitch": "+3Hz"},   # 略快，音调明显上扬（炫耀感）
    "惊讶":  {"rate": "+8%",   "pitch": "+4Hz"},   # 快速，音调骤升
    "困惑":  {"rate": "-4%",   "pitch": "-1Hz"},   # 略慢，音调微降（犹豫感）
    "平静":  {"rate": "+0%",   "pitch": "+0Hz"},   # 默认中性
}

def _is_cosyvoice_available() -> bool:
    """检查 CosyVoice 2 是否在 localhost:50000 运行"""
    try:
        import builtins
        return builtins.__dict__.get('COSYVOICE_AVAILABLE', False)
    except Exception as e:
        logger.debug(f"[CosyVoice] 可用性检查失败: {e}")
        return False


async def _generate_tts_cosyvoice(text: str, output_path: str, voice: str = "", mood: str = "",
                                   speed: float = 1.0, intensity: int = 5) -> float:
    """CosyVoice 2 本地 TTS — 电影级中文配音, 需单独部署服务 (端口 50000)
    要求: CosyVoice 2 已通过一键安装包部署并启动 WebUI
    
    v12.0 增强:
    - speed 参数: 0.5-2.0 语速控制
    - intensity 参数: 情感强度 1-10，映射到 CosyVoice 的 emotion_weight
    - 更完整的情感标签映射
    
    API: POST http://localhost:50000/generate
    """
    import aiohttp
    
    # 情感标签映射（v12.0 扩展）
    mood_tags = {
        "紧张": ("[tense] ", ""), "温馨": ("[gentle] ", ""), "悲伤": ("[sad] ", ""),
        "壮阔": ("[powerful] ", ""), "神秘": ("[whisper] ", ""), 
        "热血": ("[passionate] ", ""), "恐惧": ("[fearful] ", ""),
        "喜悦": ("[happy] ", ""), "惆怅": ("[melancholic] ", ""),
        "愤怒": ("[angry] ", ""), "压抑": ("[suppressed] ", ""),
        "释然": ("[calm] ", ""), "宁静": ("[soft] ", ""),
        "诡异": ("[eerie] ", ""), "孤独": ("[lonely] ", ""),
        "幽默": ("[amused] ", ""), "无奈": ("[resigned] ", ""),
        "得意": ("[proud] ", ""), "惊讶": ("[surprised] ", ""),
        "困惑": ("[confused] ", ""), "平静": ("[neutral] ", ""),
    }
    
    prefix, suffix = mood_tags.get(mood, ("", ""))
    
    # 根据 intensity 调整情感强度（CosyVoice 支持 emotion_weight 0.0-2.0）
    emotion_weight = 0.5 + (intensity / 10.0) * 1.0  # 0.6 ~ 1.5
    
    text_with_mood = f"{prefix}{text}{suffix}"
    
    payload = {
        "text": text_with_mood,
        "voice": voice or "default",
        "speed": speed,
        "emotion_weight": emotion_weight,
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:50000/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=90)
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CosyVoice HTTP {resp.status}")
            
            content_type = resp.headers.get("Content-Type", "")
            if "audio" in content_type:
                audio_data = await resp.read()
                with open(output_path, "wb") as f:
                    f.write(audio_data)
            else:
                result = await resp.json()
                audio_url = result.get("audio_url", "") or result.get("audio_path", "")
                if audio_url:
                    local_audio_path = audio_url.replace("http://localhost:50000/", "")
                    import shutil
                    shutil.copy(local_audio_path, output_path)
                else:
                    raise RuntimeError("CosyVoice 未返回音频数据")
    
    duration = await get_audio_duration(output_path)
    return duration


async def _generate_silence_audio(output_path: str, duration: float) -> str:
    """v12.0: 生成指定时长的静默音频文件（TTS 全部失败时的最终降级）"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        # 连 FFmpeg 都没有，写空文件
        Path(output_path).write_bytes(b"")
        return output_path
    
    try:
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(duration),
            "-q:a", "9",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.communicate(), timeout=30)
    except Exception:
        Path(output_path).write_bytes(b"")
    
    return output_path


async def generate_tts(text: str, output_path: str, voice: str = "zh-CN-XiaoxiaoNeural",
                       rate: str = "+0%", volume: str = "+0%",
                       engine: str = "edge",
                       mood: str = "",
                       intensity: int = 5,
                       is_narration: bool = False) -> float:
    """生成语音文件，返回音频时长(秒)
    
    engine 参数:
      - "edge"    : Edge-TTS（默认，免费，支持 zh/en 100+ 声音）
      - "kokoro"  : Kokoro TTS（本地，高质量，需安装 kokoro-onnx）
      - "cosyvoice": CosyVoice 2（本地，电影级中文配音，需单独部署 localhost:50000）
    
    mood 参数（v6.1）: 场景情绪，自动调整 rate/pitch 实现情感配音
    intensity 参数（v9.9）: 情绪强度 1-10，影响 prosody 调整幅度
    is_narration 参数（v9.9）: 旁白对白差异化 — 旁白情绪减弱，对白情绪增强
    """
    # v9.9: 情感化配音 — mood 始终生效，叠加到用户 rate 上
    mood_rate = rate
    mood_pitch = "+0Hz"
    if mood and mood in _TTS_MOOD_PARAMS:
        mp = _TTS_MOOD_PARAMS[mood]
        # 根据强度调整幅度：intensity 5 = 标准，10 = 1.5倍，1 = 0.3倍
        strength = 0.3 + (intensity / 10.0) * 0.7  # 0.37 ~ 1.0
        # 旁白情绪减弱（×0.5），对白情绪保持
        if is_narration:
            strength *= 0.5

        # 解析并缩放 rate
        base_rate_str = mp["rate"]
        try:
            sign = 1 if base_rate_str.startswith("+") else -1
            val = int(base_rate_str[1:].rstrip("%"))
            scaled = int(val * strength)
            # 叠加到用户 rate
            user_val = int(rate[1:].rstrip("%")) if rate and rate != "+0%" else 0
            user_sign = 1 if rate.startswith("+") else -1
            combined = user_sign * user_val + sign * scaled
            mood_rate = f"{'+' if combined >= 0 else '-'}{abs(combined)}%"
        except Exception:
            mood_rate = rate if rate != "+0%" else mp["rate"]

        # 解析并缩放 pitch
        base_pitch_str = mp["pitch"]
        try:
            psign = 1 if base_pitch_str.startswith("+") else -1
            pval = int(base_pitch_str[1:].rstrip("Hz"))
            pscaled = int(pval * strength)
            mood_pitch = f"{'+' if pscaled >= 0 else '-'}{abs(pscaled)}Hz"
        except Exception:
            mood_pitch = base_pitch_str
    
    if engine == "cosyvoice":
        try:
            # v11: 自动将 Edge-TTS voice_id 翻译为 CosyVoice2 speaker 名
            cv_voice = _translate_voice_for_cosyvoice(voice)
            # v12.0: 传入 speed 和 intensity 参数
            # 将 rate "+5%" 转换为 speed 1.05
            cv_speed = 1.0
            try:
                if rate and rate != "+0%":
                    rate_val = float(rate.replace("+", "").replace("-", "").rstrip("%")) / 100.0
                    cv_speed = 1.0 + (rate_val if rate.startswith("+") else -rate_val)
                    cv_speed = max(0.5, min(2.0, cv_speed))
            except Exception:
                cv_speed = 1.0
            
            return await _generate_tts_cosyvoice(text, output_path, cv_voice, mood,
                                                   speed=cv_speed, intensity=intensity)
        except Exception as e:
            # v9.11: 增强诊断 — str(ConnectionRefusedError) 常为空，改用类型+repr，并给出可操作提示
            etype = type(e).__name__
            emsg = str(e) or repr(e)
            hint = ""
            if any(k in etype for k in ("Connect", "Timeout", "ClientConnector", "ClientOS")):
                hint = " | 提示: CosyVoice2 服务(端口 50000)未启动或不可达，请先启动 CosyVoice WebUI"
            elif etype == "ModuleNotFoundError" or "aiohttp" in emsg:
                hint = " | 提示: 缺少依赖 aiohttp，请执行 pip install aiohttp"
            print(f"[WARN] CosyVoice TTS 失败 [{etype}] {emsg[:80]}{hint}，回退到 Edge-TTS", flush=True)
            engine = "edge"
    
    if engine == "kokoro":
        try:
            # Kokoro TTS（高质量本地 TTS）
            # 安装: pip install kokoro-onnx
            import kokoro_onnx
            # Kokoro 声音映射：中文声音
            kokoro_voice_map = {
                "zh-CN-XiaoxiaoNeural": "af_sky",     # 女声
                "zh-CN-YunjianNeural": "am_adam",     # 男声
                "zh-CN-XiaoyiNeural": "af_bella",     # 年轻女声
                "zh-CN-YunyangNeural": "am_michael",  # 成熟男声
            }
            kokoro_voice = kokoro_voice_map.get(voice, "af_sky")
            kokoro = kokoro_onnx.Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
            # Kokoro 主要支持英文，中文回退到 edge-tts
            if voice.startswith("zh"):
                raise ValueError("Kokoro 不支持中文，回退到 Edge-TTS")
            samples, sr = kokoro.create(text, voice=kokoro_voice, speed=1.0, lang="en-us")
            import soundfile as sf
            sf.write(output_path.replace(".mp3", ".wav"), samples, sr)
            # 转换为 mp3
            ffmpeg = find_ffmpeg()
            if ffmpeg and Path(output_path.replace(".mp3", ".wav")).exists():
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg, "-y", "-i", output_path.replace(".mp3", ".wav"), output_path,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as e:
            print(f"[WARN] Kokoro TTS 失败 ({str(e)[:60]})，回退到 Edge-TTS", flush=True)
            engine = "edge"

    if engine == "edge":
        # Edge-TTS（高质量免费在线 TTS，支持中文）
        # v6.1: 情感化配音 — 根据场景情绪动态调整语速和音调
        # v12.0: 增加 2 次重试 + 静默降级
        last_err = None
        for attempt in range(2):
            try:
                communicate = edge_tts.Communicate(
                    text, voice, 
                    rate=mood_rate, 
                    pitch=mood_pitch,
                    volume=volume
                )
                await communicate.save(output_path)
                # 验证文件有效
                if Path(output_path).exists() and Path(output_path).stat().st_size > 100:
                    break
                else:
                    raise RuntimeError("Edge-TTS 输出文件为空")
            except Exception as e:
                last_err = e
                print(f"[WARN] Edge-TTS 第{attempt+1}次失败: {str(e)[:80]}", flush=True)
                if attempt == 0:
                    await asyncio.sleep(1)  # 重试前等待
        else:
            # v12.0: 所有 TTS 引擎均失败 → 生成静默音频
            print(f"[ERROR] 所有 TTS 引擎失败，生成静默音频: {str(last_err)[:100]}", flush=True)
            estimated_duration = max(len(text) * 0.15, 2.0)  # 估算时长
            await _generate_silence_audio(output_path, estimated_duration)
            duration = await get_audio_duration(output_path)
            return duration

    # 用 ffprobe 获取音频时长
    duration = await get_audio_duration(output_path)
    return duration

async def get_audio_duration(audio_path: str) -> float:
    """用 ffprobe 获取音频时长"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return 0.0
    ffprobe = ffmpeg.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
    if not Path(ffprobe).exists():
        # 尝试直接用 ffprobe
        import shutil as sh
        ffprobe = sh.which("ffprobe") or ffprobe

    try:
        cmd = [
            ffprobe, "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0 and stdout:
            return float(stdout.decode().strip())
    except Exception as e:
        logger.warning(f"[Audio] ffprobe 获取时长失败 ({audio_path}): {e}")
    return 0.0

async def combine_audio_video(video_path: str, audio_path: str, output_path: str,
                               audio_duration: float = 0.0) -> str:
    """用 ffmpeg 将配音和视频合并。保持视频完整时长，音频不够则静默补齐"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(audio_path).exists():
        # 没有 ffmpeg 或音频，直接复制原视频
        shutil.copy2(video_path, output_path)
        return output_path

    # 获取视频时长
    video_duration = await get_audio_duration(video_path)

    cmd = [
        ffmpeg, "-y",
        "-i", video_path,      # 视频输入
        "-i", audio_path,       # 音频输入
    ]

    if audio_duration > 0 and video_duration > 0 and audio_duration > video_duration * 1.05:
        # [v2 全面修复] 音频明显比视频长：循环视频片段填充音频时长，
        # 而非极端慢放（慢放会把 4s 片段拉成 100s 冻帧 = 单图感）。
        # -stream_loop -1 无限循环视频，-t 截断到音频时长，配音完整保留。
        loop_cmd = [
            ffmpeg, "-y",
            "-stream_loop", "-1", "-i", video_path,
            "-i", audio_path,
            "-t", str(audio_duration),
            "-filter_complex", "[1:a]aresample=48000[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *loop_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            shutil.copy2(video_path, output_path)
        return output_path
    else:
        # 视频够长或音频略短：保持视频完整时长，音频不够的部分静默
        cmd.extend([
            "-filter_complex",
            "[1:a]apad,aresample=48000[a]",
            "-map", "0:v", "-map", "[a]",
            "-t", str(video_duration),
        ])

    cmd.extend([
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        output_path
    ])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

    if proc.returncode != 0:
        # 合并失败，直接复制原视频
        shutil.copy2(video_path, output_path)

    return output_path

# ─── FFmpeg 字幕烧录 ──────────────────────────────────────

def _find_chinese_font() -> str:
    """找到系统中可用的中文字体文件路径"""
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑（首选，Windows 标准中文字体）
        "C:/Windows/Fonts/simhei.ttf",      # 黑体
        "C:/Windows/Fonts/simsunb.ttf",     # 宋体
        "C:/Windows/Fonts/simfang.ttf",     # 仿宋
        "C:/Windows/Fonts/STXIHEI.TTF",     # 华文细黑
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux WQY
        "/System/Library/Fonts/PingFang.ttc",               # macOS PingFang
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return ""


def _auto_select_checkpoint_by_style(job: JobState) -> None:
    """根据 job.style 自动切换图像/视频模型，让风格与文本题材一致。
    仅在用户使用默认 anime 模型或风格明确要求写实/水墨时生效。
    使用 KNOWN_MODEL_SIZES 严格校验完整性，避免加载损坏/未下载完的模型。
    """
    style = getattr(job, 'style', 'cinematic')

    def _is_complete(name: str, min_size: int = MIN_SAFETENSORS_SIZE) -> bool:
        """检查模型文件是否完整：存在 + 大小 >= 已知预期值 或 至少 >= min_size"""
        p = COMFYUI_MODELS_DIR / "checkpoints" / name
        if not p.exists():
            return False
        size = p.stat().st_size
        # 优先用 KNOWN_MODEL_SIZES 中的预期大小（85% 阈值，容忍不同版本）
        expected = KNOWN_MODEL_SIZES.get(name, 0)
        if expected > 0:
            if size < expected * 0.85:
                print(f"[Auto] 模型 {name} 不完整: {size/1e9:.2f}GB < 预期 {expected/1e9:.2f}GB 的85%，跳过", flush=True)
                return False
            return True
        return size >= min_size

    # 写实 / 电影级：优先尝试写实 SDXL 模型
    if style in ("realistic", "cinematic"):
        realistic_candidates = [
            "RealVisXL_V4.0.safetensors",
            "JuggernautXL_v9.safetensors",
            "dreamshaper_8.safetensors",
            "leosamsMoonfilm_009.safetensors",
            "sd_xl_base_1.0.safetensors",
        ]
        current = job.img_checkpoint
        # 只在用户仍使用默认 anime 模型时才自动切换，避免覆盖用户显式选择
        if "animagine" in current.lower() or current == "":
            for name in realistic_candidates:
                if _is_complete(name):
                    job.img_checkpoint = name
                    print(f"[Auto] 风格={style}, 自动切换到写实模型: {name}", flush=True)
                    break
            else:
                # 所有写实候选都不完整，保留 animagine-xl 但提示
                print(f"[Auto] 风格={style}, 但无完整写实模型可用，保留 {current}", flush=True)

    # 水墨 / 古风：优先尝试国风模型
    elif style == "ink":
        ink_candidates = [
            "guofeng3XL_v2.safetensors",
            "chineseInkXL_v1.safetensors",
        ]
        current = job.img_checkpoint
        if "animagine" in current.lower() or current == "":
            for name in ink_candidates:
                if _is_complete(name):
                    job.img_checkpoint = name
                    print(f"[Auto] 风格={style}, 自动切换到水墨模型: {name}", flush=True)
                    break

    # 中式民俗恐怖：优先写实模型
    elif style == "folk_horror":
        folk_candidates = [
            "RealVisXL_V4.0.safetensors",
            "JuggernautXL_v9.safetensors",
            "leosamsMoonfilm_009.safetensors",
            "sd_xl_base_1.0.safetensors",
        ]
        current = job.img_checkpoint
        if "animagine" in current.lower() or current == "":
            for name in folk_candidates:
                if _is_complete(name):
                    job.img_checkpoint = name
                    print(f"[Auto] 风格={style}, 自动切换到写实模型: {name}", flush=True)
                    break

async def burn_subtitles(video_path: str, subtitle_text: str, output_path: str,
                          font_size: int = 22, margin_bottom: int = 40) -> str:
    """用 ffmpeg 烧录字幕到视频底部（支持中文）"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(video_path, output_path)
        return output_path

    # 清理字幕文本（去除 ffmpeg drawtext 的特殊字符）
    clean_text = subtitle_text.replace("'", "").replace(":", "").replace("\n", " ")
    # 去掉引号等标点但保留中文
    clean_text = clean_text.replace('"', "").replace('"', "").replace('"', "")
    clean_text = clean_text.replace("'", "").replace("'", "")
    # 截取合理长度（中文20字/行）
    if len(clean_text) > 30:
        clean_text = clean_text[:28] + "..."

    # 转义 ffmpeg filter 中的特殊字符
    def escape_filter(s: str) -> str:
        s = s.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        s = s.replace("[", "\\[").replace("]", "\\]").replace(",", "\\,")
        return s

    clean_text_escaped = escape_filter(clean_text)

    # 查找中文字体
    font_path = _find_chinese_font()

    box_h = font_size + 24
    box_y = f"ih-{margin_bottom + box_h}"

    if font_path:
        # 有中文字体：用 fontfile 指定
        font_path_escaped = font_path.replace("\\", "/").replace(":", "\\:")
        drawtext = (
            f"drawtext=fontfile='{font_path_escaped}'"
            f":text='{clean_text_escaped}'"
            f":fontcolor=white:fontsize={font_size}"
            f":x=(w-text_w)/2:y=h-{margin_bottom}-text_h"
            f":borderw=2:bordercolor=black@0.8"
            f":box=1:boxcolor=black@0.55:boxborderw=6"
        )
    else:
        # 没有字体文件：用 SRT 内嵌字幕方式（跨平台降级）
        srt_path = Path(output_path).parent / f"_sub_{uuid.uuid4().hex[:6]}.srt"
        srt_path.write_text(
            f"1\n00:00:00,000 --> 00:59:59,000\n{clean_text}\n\n",
            encoding="utf-8-sig"
        )
        escaped_srt = str(srt_path).replace(":", "\\:").replace("'", "\\'")
        drawtext = f"subtitles='{escaped_srt}'"

    filter_str = (
        f"drawbox=x=0:y={box_y}:w=iw:h={box_h}:color=black@0.6:t=fill,"
        + drawtext
    )

    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-crf", "22", "-preset", "ultrafast",
        "-c:a", "copy",
        output_path
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")[:200]
            print(f"[WARN] 字幕烧录失败 ({err_msg})，直接复制视频", flush=True)
            shutil.copy2(video_path, output_path)
    except Exception as e:
        print(f"[WARN] 字幕烧录异常: {e}", flush=True)
        shutil.copy2(video_path, output_path)

    # 清理临时字幕文件
    tmp_srt = Path(output_path).parent / f"_sub_{{}}.srt"
    for f in Path(output_path).parent.glob("_sub_*.srt"):
        f.unlink(missing_ok=True)

    return output_path

async def merge_videos(video_paths: list[str], output_path: str) -> str:
    """用 ffmpeg 将多个视频合并为一个

    v9.8: 容错改进 — FFmpeg 有时在输出完成后仍返回非 0 退出码
    （如音频流警告），此时检查输出文件是否完整可用，若可用则视为成功。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法合并视频。请安装 ffmpeg 并添加到 PATH。")

    # 创建 concat 文件列表
    concat_file = Path(output_path).parent / f"concat_{uuid.uuid4().hex[:6]}.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for vp in video_paths:
            # ffmpeg concat 需要转义特殊字符
            safe_path = str(vp).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        # v9.8: 强制 yuv420p + High profile，确保 Windows 默认播放器兼容
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-crf", "20", "-preset", "medium",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

    # 清理临时文件
    concat_file.unlink(missing_ok=True)

    if proc.returncode != 0:
        # v9.8: FFmpeg 可能在输出完成后仍返回非 0（音频流警告等）
        # 检查输出文件是否实际存在且有效
        out_path = Path(output_path)
        if out_path.exists() and out_path.stat().st_size > 10000:
            print(f"[Merge] FFmpeg 返回码非 0 但输出文件有效 ({out_path.stat().st_size//1024}KB)，视为成功", flush=True)
            return output_path
        err_msg = stderr.decode("utf-8", errors="ignore")[-500:]
        raise RuntimeError(f"视频合并失败: {err_msg}")

    return output_path

# ─── v6.2: 转场效果多样化（FFmpeg xfade）─────────────────────────────

# 转场类型与场景情绪匹配表
_TRANSITION_MOOD_MAP = {
    "恐惧": ["fadeblack", "smoothdown"],
    "紧张": ["dip", "circlecrop"],
    "神秘": ["radial", "circleopen"],
    "压抑": ["fadeblack", "wiperight"],
    "壮阔": ["slideup", "wipeleft"],
    "热血": ["circlecrop", "dip"],
    "悲伤": ["fade", "smoothdown"],
    "喜悦": ["circleopen", "radial"],
    "幽默": ["circleopen", "slideleft", "wiperight"],
    "无奈": ["fade", "smoothdown"],
    "得意": ["circleopen", "radial"],
    "default": ["fade", "dip", "circlecrop", "slideleft", "wiperight", "smoothup", "radial", "fadeblack"],
}

# v9.9: 情绪突变时的分隔转场（情绪差异大时使用）
_TRANSITION_BREAK = {"fadeblack", "fadewhite", "dip"}

# v9.9: 情绪连贯时的平滑转场
_TRANSITION_SMOOTH = {"fade", "smoothup", "smoothdown", "slideleft", "slideright"}


def _select_transition(mood: str, index: int, prev_mood: str = "") -> str:
    """v9.9: 根据场景情绪和相邻场景情绪差异选择转场类型

    - 相邻情绪相似 → 平滑转场（fade/slide）
    - 相邻情绪突变 → 分隔转场（fadeblack/dip）
    """
    candidates = _TRANSITION_MOOD_MAP.get(mood, _TRANSITION_MOOD_MAP["default"])

    # 如果有前一场景情绪，且情绪差异大，用分隔转场
    if prev_mood and prev_mood != mood:
        # 情绪从负面到正面或反之，用 fadeblack 分隔
        negative = {"恐惧", "悲伤", "压抑", "紧张", "孤独", "惆怅"}
        positive = {"喜悦", "温馨", "壮阔", "热血", "得意"}
        if (prev_mood in negative and mood in positive) or \
           (prev_mood in positive and mood in negative):
            return "fadeblack"
        # 情绪类型不同但不是对立，用 dip
        if prev_mood not in candidates:
            return "dip"

    return candidates[index % len(candidates)]


async def merge_videos_with_transitions(
    video_paths: list[str],
    output_path: str,
    transition_duration: float = 0.5,
    transition_types: list[str] = None,
    scene_moods: list[str] = None,
    subtitle_path: Optional[str] = None,
) -> str:
    """
    v6.2: 使用 xfade 实现多样化转场
    - transition_types: 转场类型列表（长度 = len(video_paths) - 1）
    - scene_moods: 场景情绪列表（用于自动匹配转场类型）
    - subtitle_path: 烧录的 ASS/SRT 字幕路径（红果漫剧要求 hardsub）
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法合并视频。请安装 ffmpeg 并添加到 PATH。")
    
    if len(video_paths) < 2:
        if video_paths:
            shutil.copy2(video_paths[0], output_path)
        return output_path

    # v9.9: 提高阈值到 20，让更多场景能用 xfade 转场
    # 超过 20 个时用简单 concat（xfade filtergraph 太复杂会溢出）
    if len(video_paths) > 20:
        return await merge_videos(video_paths, output_path)
    
    # ── 确定转场类型（v9.9: 传入相邻场景情绪差异）──
    if transition_types is None:
        transition_types = []
        for i in range(len(video_paths) - 1):
            mood = scene_moods[i] if scene_moods and i < len(scene_moods) else "default"
            prev = scene_moods[i-1] if scene_moods and i > 0 and i-1 < len(scene_moods) else ""
            transition_types.append(_select_transition(mood, i, prev_mood=prev))
    
    # ── 获取每个视频的时长 ──
    durations = []
    for vp in video_paths:
        dur = await get_audio_duration(vp)
        if dur <= 0:
            dur = 5.0  # 默认5秒
        durations.append(dur)
    
    # ── 构建 xfade filtergraph ──
    # 示例 (3个视频):
    # [0:v][1:v]xfade=transition=fade:duration=0.5:offset=4.5[xfade0];
    # [xfade0][2:v]xfade=transition=slideleft:duration=0.5:offset=9.0[outv]
    
    # 命令在下方 _build_xfade_cmd 中按转场类型惰性构建（安全转场回退用），此处不再预构建。
    # ── 执行（带「安全转场」回退）──
    def _build_xfade_cmd(ttypes):
        """按给定转场类型构建 xfade 合并命令（抽离以便失败时回退到安全转场）"""
        fp = []
        for i in range(len(video_paths) - 1):
            offset = max(sum(durations[:i+1]) - transition_duration * (i + 1), 0.0)
            in_label = "[0:v]" if i == 0 else f"[xfade{i-1}]"
            out_label = "[outv]" if i == len(video_paths) - 2 else f"[xfade{i}]"
            fp.append(f"{in_label}[{i+1}:v]xfade=transition={ttypes[i]}:duration={transition_duration}:offset={offset:.2f}{out_label}")
        fp.append("".join([f"[{i}:a]" for i in range(len(video_paths))]) + f"concat=n={len(video_paths)}:v=0:a=1[outa]")
        # 字幕烧录（如有）
        if fp and fp[-1].endswith("[outv]"):
            fp[-1] = fp[-1].replace("[outv]", "[outv_pre]")
        if subtitle_path and os.path.exists(subtitle_path):
            sub_escaped = subtitle_path.replace("\\", "/").replace(":", "\\:")
            for idx in range(len(fp) - 1, -1, -1):
                if "[outv]" in fp[idx]:
                    fp[idx] = fp[idx].replace("[outv]", "[outv_pre]")
                    break
            fp.append(f"[outv_pre]ass={sub_escaped}[outv]")
        else:
            for idx in range(len(fp) - 1, -1, -1):
                if "[outv_pre]" in fp[idx]:
                    fp[idx] = fp[idx].replace("[outv_pre]", "[outv]")
                    break
        ins = []
        for vp in video_paths:
            ins.extend(["-i", vp])
        return [ffmpeg, "-y", *ins, "-filter_complex", ";".join(fp),
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-r", "30", "-crf", "18", "-preset", "medium",
                "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                output_path]

    async def _run_xfade(ttypes):
        c = _build_xfade_cmd(ttypes)
        print(f"[XFade] 使用 {len(ttypes)} 个转场效果: {ttypes}", flush=True)
        proc = await asyncio.create_subprocess_exec(*c, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        return proc.returncode, stderr.decode(errors="ignore")

    # 某些 FFmpeg 构建未实现 dip / fadeblack 等转场（报 "Not yet implemented
    # in FFmpeg"），会导致 xfade 整体失败。这里先按选定转场尝试；失败则统一
    # 回退到最通用、必然受支持的 'fade' 重试一次，仍失败才退化到无转场拼接。
    try:
        rc, err = await _run_xfade(transition_types)
        if rc != 0:
            safe = ["fade"] * max(len(video_paths) - 1, 0)
            if list(transition_types) != safe:
                print(f"[XFade] 选定转场失败，回退安全转场(fade)重试: {err[:200]}", flush=True)
                rc2, err2 = await _run_xfade(safe)
                if rc2 == 0:
                    print(f"[XFade] 安全转场合并完成: {output_path}", flush=True)
                    return output_path
                err = err2
            print(f"[XFade] xfade 失败，回退简单合并: {err[:200]}", flush=True)
            return await merge_videos(video_paths, output_path)
        print(f"[XFade] 转场合并完成: {output_path}", flush=True)
        return output_path
    except Exception as e:
        print(f"[XFade] 转场异常: {str(e)[:200]}，回退简单合并", flush=True)
        return await merge_videos(video_paths, output_path)

async def upscale_video(input_path: str, output_path: str, target_width: int = 1080, target_height: int = 1920) -> str:
    """用 ffmpeg lanczos 将视频缩放到目标分辨率，并强制输出30fps (红果漫剧标准)"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return input_path
    
    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-vf", f"scale={target_width}:{target_height}:flags=lanczos,fps=30",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        str(output_path)
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            return output_path
        else:
            print(f"[Upscale] ffmpeg 超分失败，保留原始视频: {stderr.decode()[:200]}")
            return input_path
    except asyncio.TimeoutError:
        proc.kill()
        return input_path

# ─── P2-⑨: 口型同步（MuseTalk / SadTalker / Echomimic）──────────────────────────
def _resolve_tool_dir(env_key: str, default_name: str) -> str:
    """解析外部工具目录：环境变量 > 仓库 tools/ > 用户目录 ai-tools/"""
    env_dir = os.environ.get(env_key, "").strip()
    if env_dir:
        return env_dir
    for cand in (PROJECT_ROOT / "tools" / default_name,
                 Path.home() / "ai-tools" / default_name):
        if cand.exists():
            return str(cand)
    return str(PROJECT_ROOT / "tools" / default_name)

_LIPSYNC_TOOLS = {
    "musetalk": {
        "weight_path": _resolve_tool_dir("MUSETALK_DIR", "MuseTalk"),
        "script": "python -m scripts.inference --inference_config {cfg} --result_dir {output_dir} --version v15",
    },
    "sadtalker": {
        "weight_path": _resolve_tool_dir("SADTALKER_DIR", "SadTalker"),
        "script": "python inference.py --driven_audio {audio} --source_image {face} --result_dir {output_dir} --enhancer gfpgan",
    },
}

# ComfyUI 自带 Python（已含 torch/CUDA/insightface/librosa 等，复用其环境跑 MuseTalk/SadTalker）
COMFYUI_PYTHON = os.environ.get("COMFYUI_PYTHON", "")
if not COMFYUI_PYTHON:
    for _cand in (PROJECT_ROOT / "ComfyUI" / "python" / "python.exe",
                  Path.home() / "ComfyUI" / "python" / "python.exe"):
        if _cand.exists():
            COMFYUI_PYTHON = str(_cand)
            break

# MuseTalk 专属 venv（Python 3.12 + torch 2.7.0+cu128 适配 RTX 5070 Blackwell sm_120，
# + mmcv-lite 2.2.0 + mmpose/mmengine 纯 Python 版，启动期 stub 屏蔽 mmcv CUDA ext + 强制
# torch.load(weights_only=False) + numpy 2.4.1 以兼容 numba）。与 ComfyUI 的 torch 隔离。
# 注意：torch 2.2.2+cu121 在 sm_120 上无法运行 CUDA kernel，切勿回退。
MUSE_TALK_PYTHON = os.environ.get("MUSETALK_PYTHON", "")
if not MUSE_TALK_PYTHON:
    MUSE_TALK_PYTHON = str(Path(_LIPSYNC_TOOLS["musetalk"]["weight_path"]) / "venv" / "Scripts" / "python.exe")


async def _detect_lipsync_tool() -> Optional[str]:
    """检测可用的口型同步工具（按优先级）"""
    # 1. 检查环境变量强制指定
    forced = os.environ.get("LIPSYNC_TOOL", "").lower()
    if forced in _LIPSYNC_TOOLS:
        if Path(_LIPSYNC_TOOLS[forced]["weight_path"]).exists():
            return forced

    # 2. 按优先级自动检测
    for tool in ["musetalk", "sadtalker"]:
        if Path(_LIPSYNC_TOOLS[tool]["weight_path"]).exists():
            if tool == "musetalk" and not Path(MUSE_TALK_PYTHON).exists():
                # MuseTalk 专属 venv 尚未构建，跳过（配音+字幕照常）
                continue
            return tool

    return None


async def _apply_lip_sync(scene, scene_dir: Path, video_path: str, job) -> str:
    """P2-⑨: 用配音音频驱动角色口型
    1. 优先尝试 MuseTalk（轻量、效果好）
    2. 备选 SadTalker
    3. 都没有则跳过（兜底）
    """
    if not video_path or not Path(video_path).exists():
        return video_path

    # 找该场景的配音音频
    audio_path = None
    # v12.2 修正：配音主输出名是 scene_{id}.mp3（见 _single_voice_dubbing 行7871），
    # 旧候选列表只找 _audio.wav/_dub.mp3/_audio.mp3 全都不匹配，导致口型同步拿不到
    # 真实配音，只能靠“从视频抽音频”兜底（抽到的是 BGM/合成轨，不是人声）。
    # 这里把 scene_{id}.mp3/.wav 放最前，优先用真实配音。
    candidates = [
        scene_dir / f"scene_{scene.id:03d}.mp3",
        scene_dir / f"scene_{scene.id:03d}.wav",
        scene_dir / f"scene_{scene.id:03d}_audio.wav",
        scene_dir / f"scene_{scene.id:03d}_dub.mp3",
        scene_dir / f"scene_{scene.id:03d}_audio.mp3",
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 1000:
            audio_path = str(c)
            break

    if not audio_path:
        # 尝试从视频中提取音频
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            audio_path = str(scene_dir / f"scene_{scene.id:03d}_extracted.wav")
            try:
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg, "-y", "-i", video_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    audio_path,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await asyncio.wait_for(proc.communicate(), timeout=60)
                if not Path(audio_path).exists() or Path(audio_path).stat().st_size < 1000:
                    audio_path = None
            except Exception:
                audio_path = None

    if not audio_path:
        return video_path

    # 检测可用工具
    tool = await _detect_lipsync_tool()
    if not tool:
        # 没装口型同步工具，跳过（不报错）
        return video_path

    weight_path = _LIPSYNC_TOOLS[tool]["weight_path"]
    # v12.2 修正（关键）：MuseTalk 的 scripts/inference.py 内部用 os.system 调「裸 ffmpeg」，
    # 且 --ffmpeg_path 形同虚设（脚本根本没读取该参数）。后台进程（服务/启动器）的 PATH
    # 往往不含 ffmpeg，导致帧抽取/视频合成静默失败 → 不产出 mp4 → 口型同步被降级跳过。
    # 解决办法：把 find_ffmpeg() 找到的 ffmpeg 所在目录前置注入子进程 PATH。
    _ff = find_ffmpeg()
    _ff_dir = str(Path(_ff).parent) if _ff else ""
    _path_prefix = f'set "PATH={_ff_dir};%PATH%" && ' if _ff_dir else ""

    if tool == "musetalk":
        # v12.2 修正：原 `python -m musetalk.inference --video/--audio/--output` 是失效写法
        # （包内无 inference 模块；真实入口 scripts/inference.py 走 config yaml + task_id）。
        # 改为：写一份单任务 config，调用 `python -m scripts.inference`，输出到确定路径。
        cfg_path = scene_dir / f"lipsync_cfg_{scene.id:03d}.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("task1:\n")
            f.write(f'  video_path: "{video_path}"\n')
            f.write(f'  audio_path: "{audio_path}"\n')
            f.write(f'  result_name: "scene_{scene.id:03d}_lipsync.mp4"\n')
        result_dir = scene_dir / "lipsync_out"
        output_path = result_dir / "v15" / f"scene_{scene.id:03d}_lipsync.mp4"
        cmd_str = (
            f'{_path_prefix}cd /d "{weight_path}" && '
            f'"{MUSE_TALK_PYTHON}" -m scripts.inference '
            f'--inference_config "{cfg_path}" '
            f'--result_dir "{result_dir}" '
            f'--version v15 --batch_size 4 --use_float16'
        )
    else:
        # SadTalker
        output_path = scene_dir / f"scene_{scene.id:03d}_lipsync.mp4"
        cmd_str = (
            f'cd /d "{weight_path}" && '
            f'"{COMFYUI_PYTHON}" inference.py '
            f'--driven_audio "{audio_path}" '
            f'--source_image "{scene_dir}/scene_{scene.id:03d}_img.png" '
            f'--result_dir "{scene_dir}" '
            f'--enhancer gfpgan'
        )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        # v12.2 修正：MuseTalk v15 在 RTX 5070 上约 6.5s/帧（mmcv CUDA ext 被 stub），
        # 190 帧场景实测需 ~1235s，原 900s 必超时。提到 1800s 留出余量。
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)

        # 成功判定：优先精确路径；否则在 result_dir 下回退搜索最大 mp4
        # （兼容不同 MuseTalk 小版本把结果写到嵌套子目录的情况）。
        produced = None
        if Path(output_path).exists() and Path(output_path).stat().st_size > Path(video_path).stat().st_size * 0.5:
            produced = output_path
        else:
            try:
                cands = [
                    p for p in Path(result_dir).rglob("*.mp4")
                    if p.stat().st_size > Path(video_path).stat().st_size * 0.5
                ]
                if cands:
                    produced = max(cands, key=lambda x: x.stat().st_size)
            except Exception:
                pass

        if produced is not None:
            print(f"[LipSync] P2-⑨ 口型同步完成: {tool} → {produced}", flush=True)
            return str(produced)
        else:
            serr = stderr.decode()[:500] if stderr else ""
            print(f"[LipSync] {tool} 未产出有效视频(精确路径存在={Path(output_path).exists()}); stderr={serr}", flush=True)
    except Exception as e:
        print(f"[LipSync] {tool} 执行失败: {e}", flush=True)

    return video_path



_ENDING_CARD_DURATION = 3.0  # 3 秒尾卡


async def _append_ending_card(
    video_path: str,
    output_path: str,
    title: str = "",
    series_name: str = "",
    next_episode_hint: str = "下集更精彩",
) -> str:
    """P1-⑧: 追加 3 秒片尾引导卡
    - 黑色背景 + 粗体白字标题
    - "上滑看全集" / "点赞+关注" / "下一集预告"
    - BGM 淡出
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(video_path).exists():
        if Path(video_path).exists():
            shutil.copy2(video_path, output_path)
        return output_path

    fontfile = "C:/Windows/Fonts/msyhbd.ttc"
    if not Path(fontfile).exists():
        fontfile = "C:/Windows/Fonts/msyh.ttc"
    if not Path(fontfile).exists():
        fontfile = "/System/Library/Fonts/PingFang.ttc"
    fontfile_esc = fontfile.replace("\\", "/").replace(":", "\\:")

    # 标题
    title_display = (title or "精彩短剧")[:12]
    series_display = (series_name or "墨影流光 · 短剧场")[:24]

    # 三行文字：主标题、副标题、上滑引导
    text_lines = [
        # (y_pos_pct, fontsize, text, color)
        ("0.30", 72, title_display, "white"),
        ("0.50", 40, series_display, "white@0.85"),
        ("0.72", 48, "↑ 上滑看全集", "yellow"),
        ("0.82", 32, "点赞 + 关注 · 不迷路", "white@0.75"),
    ]

    drawtext_chain = []
    for yp, fs, txt, color in text_lines:
        safe_txt = txt.replace("'", "\\'")
        drawtext_chain.append(
            f"drawtext=fontfile='{fontfile_esc}':"
            f"text='{safe_txt}':fontcolor={color}:fontsize={fs}:"
            f"x=(w-text_w)/2:y=h*{yp}-text_h/2:"
            f"box=1:boxcolor=black@0.4:boxborderw=15"
        )
    drawtext_filter = ",".join(drawtext_chain)

    # 用 ffmpeg concat 拼接：原视频 + 3秒黑屏带文字
    ending_path = output_path + ".ending_tmp.mp4"
    cmd_ending = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={_ENDING_CARD_DURATION}",
        "-vf", drawtext_filter,
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-crf", "18",
        "-an",  # 尾卡无音轨
        ending_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_ending,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
    except Exception as e:
        print(f"[Ending] 尾卡生成失败: {e}", flush=True)
        shutil.copy2(video_path, output_path)
        return output_path

    if not Path(ending_path).exists() or Path(ending_path).stat().st_size < 1000:
        shutil.copy2(video_path, output_path)
        return output_path

    # 拼接原视频 + 尾卡（视频流 concat，音频从原视频保留）
    concat_list = output_path + ".concat.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        f.write(f"file '{Path(video_path).as_posix()}'\n")
        f.write(f"file '{Path(ending_path).as_posix()}'\n")

    cmd_concat = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-crf", "18", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_concat,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=180)
    except Exception as e:
        print(f"[Ending] 尾卡拼接失败: {e}", flush=True)
        shutil.copy2(video_path, output_path)
        return output_path

    # 清理临时
    for p in [ending_path, concat_list]:
        Path(p).unlink(missing_ok=True)

    if Path(output_path).exists() and Path(output_path).stat().st_size > Path(video_path).stat().st_size * 0.9:
        print(f"[Ending] P1-⑧ 尾卡已追加: {output_path} (+{_ENDING_CARD_DURATION}s)", flush=True)
        return output_path
    else:
        shutil.copy2(video_path, output_path)
        return output_path


def _build_series_filename(title: str, genre: str = "", episode: int = 1) -> str:
    """P1-⑧: 系列化命名：题材_系列名_第N集_日期"""
    from datetime import datetime
    today = datetime.now().strftime("%m%d")
    # 题材归类
    genre_tag = ""
    if genre:
        genre_map = {
            "甜宠": "甜", "霸总": "霸", "穿越": "穿", "古风": "古",
            "言情": "言", "都市": "都", "职场": "职", "校园": "校",
            "悬疑": "悬", "复仇": "仇", "重生": "重", "逆袭": "逆",
            "亲情": "亲", "玄幻": "玄", "仙侠": "仙",
        }
        genre_tag = genre_map.get(genre, "")

    # 清理标题中的非法字符
    clean_title = "".join(c for c in (title or "未命名") if c not in r'\/:*?"<>|')
    clean_title = clean_title.strip()[:20]

    parts = []
    if genre_tag:
        parts.append(genre_tag)
    parts.append(clean_title)
    parts.append(f"第{episode}集")
    parts.append(today)
    return "_".join(parts)


async def add_bgm_to_video(video_path: str, bgm_path: str, output_path: str, bgm_volume: float = 0.25) -> str:
    """将背景音乐混入视频，支持淡入淡出和循环"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(bgm_path).exists():
        shutil.copy2(video_path, output_path)
        return output_path

    vid_duration = await get_audio_duration(video_path)
    fade_out_start = max(vid_duration - 3, 0)
    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-stream_loop", "-1", "-i", bgm_path,
        "-filter_complex",
        f"[1:a]volume={bgm_volume},afade=t=in:ss=0:d=2,afade=t=out:st={fade_out_start:.1f}:d=3[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    if proc.returncode != 0:
        shutil.copy2(video_path, output_path)
    return output_path

# ─── v6.0: 自动配乐系统 ──────────────────────────────────
# 优先使用 bgm/ 目录中预生成的高品质BGM，回退到简单正弦波合成

# 情绪 → BGM文件名映射（v2: _Name格式, v1: lowercase格式）
_BGM_MOOD_FILE_MAP = {
    "神秘": "Mysterious",      "悬疑": "Mysterious",
    "恐惧": "Horror_Scary",    "恐怖": "Horror_Scary",
    "温馨": "Warm_Happy",      "温暖": "Warm_Happy",
    "喜悦": "Happy_Upbeat",    "欢乐": "Happy_Upbeat",
    "悲伤": "Sad_Emotional",   "难过": "Sad_Emotional",
    "壮阔": "Epic_Cinematic",  "史诗": "Epic_Cinematic",
    "紧张": "Tense_Suspense",  "焦灼": "Tense_Suspense",
    "热血": "Action_Epic",     "战斗": "Action_Epic", "燃": "Action_Epic",
    "压抑": "Sad_Emotional",   "孤独": "Sad_Emotional",
    "惆怅": "Sad_Emotional",   "悸动": "Warm_Happy",
    "释然": "Warm_Happy",
}

# 回退：正弦波合成映射（用于 bgm/ 中没有对应文件时）
_BGM_MOOD_MAP = {
    "神秘":  {"base_freq": 220, "pattern": "minor_slow",   "tempo": 0.6},
    "恐惧":  {"base_freq": 196, "pattern": "minor_pulse",  "tempo": 0.4},
    "压抑":  {"base_freq": 185, "pattern": "drone",        "tempo": 0.3},
    "紧张":  {"base_freq": 246, "pattern": "staccato",     "tempo": 0.8},
    "温馨":  {"base_freq": 261, "pattern": "major_slow",   "tempo": 0.5},
    "喜悦":  {"base_freq": 293, "pattern": "major_fast",   "tempo": 0.9},
    "悲伤":  {"base_freq": 210, "pattern": "minor_slow",   "tempo": 0.4},
    "壮阔":  {"base_freq": 174, "pattern": "major_epic",   "tempo": 0.7},
    "热血":  {"base_freq": 330, "pattern": "staccato",     "tempo": 1.0},
    "孤独":  {"base_freq": 220, "pattern": "drone",        "tempo": 0.3},
    "惆怅":  {"base_freq": 232, "pattern": "minor_slow",   "tempo": 0.5},
    "悸动":  {"base_freq": 277, "pattern": "major_slow",   "tempo": 0.6},
}


def _find_mood_bgm_file(mood: str) -> str | None:
    """在 bgm/ 目录中查找匹配情绪的BGM文件，返回完整路径或 None"""
    bgm_dir = PROJECT_ROOT / "bgm"
    if not bgm_dir.exists():
        return None
    
    # 精确匹配
    bgm_name = _BGM_MOOD_FILE_MAP.get(mood)
    if bgm_name:
        p = bgm_dir / f"{bgm_name}.mp3"
        if p.exists() and p.stat().st_size > 10000:
            return str(p)
    
    # 模糊匹配：检查文件名是否包含情绪关键词
    for mp3 in sorted(bgm_dir.glob("*.mp3")):
        if mp3.stat().st_size < 10000:
            continue
        stem = mp3.stem.lower()
        if mood in stem or (bgm_name and bgm_name in stem):
            return str(mp3)
    
    return None


async def _generate_scene_bgm(scene_mood: str, duration: float, output_path: str) -> bool:
    """为单个场景生成氛围背景音（使用 ffmpeg 正弦波合成，v6.0保留为回退方案）
    返回是否成功生成。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False

    preset = _BGM_MOOD_MAP.get(scene_mood, _BGM_MOOD_MAP.get("神秘"))
    freq = preset["base_freq"]
    tempo = preset["tempo"]
    pattern = preset["pattern"]

    if "minor" in pattern:
        freqs = [freq, freq * 1.189, freq * 1.498]
    elif "major" in pattern:
        freqs = [freq, freq * 1.260, freq * 1.498]
    elif pattern == "drone":
        freqs = [freq * 0.5, freq]
    else:
        freqs = [freq, freq * 1.334]

    dur = max(duration + 2, 10.0)

    filter_parts = []
    for i, f in enumerate(freqs):
        vol = 0.12 / len(freqs)
        if i == 0:
            vol = 0.18 / len(freqs)
        filter_parts.append(f"sine=frequency={f:.1f}:duration={dur:.1f},volume={vol:.3f}[s{i}]")

    if len(filter_parts) > 1:
        mix_inputs = "".join(f"[s{i}]" for i in range(len(filter_parts)))
        mix_filter = f"amix=inputs={len(filter_parts)}:duration=longest[bgm_raw]"
        filter_str = ";".join(filter_parts) + ";" + mix_filter
        aout = "[bgm_raw]"
    else:
        filter_str = filter_parts[0].replace(f"[s0]", "[bgm_raw]")
        aout = "[bgm_raw]"

    fade_d = min(2.0, dur * 0.15)
    fade_out_st = max(dur - fade_d, 0)
    full_filter = (
        filter_str + ";"
        + f"{aout}afade=t=in:ss=0:d={fade_d:.1f},"
        + f"afade=t=out:st={fade_out_st:.1f}:d={fade_d:.1f}[out]"
    )

    cmd = [
        ffmpeg, "-y",
        "-filter_complex", full_filter,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "64k",
        output_path
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return proc.returncode == 0 and Path(output_path).exists() and Path(output_path).stat().st_size > 100
    except Exception as e:
        logger.warning(f"[SFX] 音效生成失败 ({output_path}): {e}")
        return False


async def add_scene_bgm(video_path: str, output_path: str, mood: str,
                         bgm_volume: float = 0.20, scene_setting: str = "") -> str:
    """v6.0→v12.0: 为单场景视频添加情绪BGM + 环境音（三轨混音）"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(video_path, output_path)
        return output_path

    vid_duration = await get_audio_duration(video_path) or 5.0

    # v12.0: 自动选择环境音
    ambient_file = _select_ambient_sound(scene_setting, mood)
    if ambient_file:
        print(f"[Audio] v12.0 场景环境音: {Path(ambient_file).name} (设定: {scene_setting[:20]}, 情绪: {mood})", flush=True)

    # v6.0: 优先使用 bgm/ 目录中预生成的和弦BGM
    bgm_file = _find_mood_bgm_file(mood)
    if bgm_file and Path(bgm_file).exists():
        # v12.0: 三轨混音（对白 + 环境音 + BGM）
        if ambient_file:
            result = await mix_audio_3track(video_path, bgm_file, output_path,
                                             ambient_path=ambient_file,
                                             bgm_volume=bgm_volume, ambient_volume=0.12)
        else:
            result = await mix_audio_high_quality(video_path, bgm_file, output_path, bgm_volume)
        if Path(output_path).exists() and Path(output_path).stat().st_size > Path(video_path).stat().st_size * 0.8:
            print(f"[BGM] 使用预生成BGM: {Path(bgm_file).name} (情绪: {mood})", flush=True)
            return result
    
    # 回退：正弦波合成
    bgm_tmp = output_path + "_bgm_tmp.mp3"
    success = await _generate_scene_bgm(mood, vid_duration, bgm_tmp)
    if not success:
        shutil.copy2(video_path, output_path)
        return output_path
 
    # 回退：正弦波合成 - v12.0: 也使用三轨混音
    if ambient_file:
        result = await mix_audio_3track(video_path, bgm_tmp, output_path,
                                         ambient_path=ambient_file,
                                         bgm_volume=bgm_volume, ambient_volume=0.12)
    else:
        result = await mix_audio_high_quality(video_path, bgm_tmp, output_path, bgm_volume)
    Path(bgm_tmp).unlink(missing_ok=True)
    return result


# ─── v6.0: SFX 音效系统 ──────────────────────────────────

_SFX_SCENE_RULES = {
    "setting": {
        "山": ["wind", "forest"], "雨": ["rain"], "夜": ["night"],
        "镇": ["market"], "市": ["market"], "林": ["forest"],
        "街": ["market"], "岸": ["wind"], "海": ["wind"],
        "雾": ["wind"], "晨": ["wind"], "院": ["door"],
        "铺": ["door"], "台": ["riser"], "戏": ["riser"],
    },
    "mood": {
        "恐惧": ["riser", "boom"], "紧张": ["heartbeat", "riser"],
        "神秘": ["wind", "bell"],  "压抑": ["heartbeat"],
        "壮阔": ["boom", "whoosh"], "热血": ["whoosh"],
        "悬疑": ["heartbeat", "riser"], "惊悚": ["heartbeat", "boom"],
    },
    "description_keywords": {
        "开门": ["door"], "敲门": ["door"], "关门": ["door"],
        "走路": ["step"], "脚步": ["step"], "奔跑": ["step"],
        "打": ["hit"], "击": ["hit"], "碎": ["hit"],
        "轰": ["boom"], "爆炸": ["boom"],
        "风吹": ["wind"], "风": ["wind"],
    }
}


def _match_sfx_for_scene(scene) -> list[str]:
    """根据场景描述匹配音效列表，返回音效文件名列表（无扩展名）"""
    matched = []
    
    # 1. 匹配场景地点
    if scene.setting:
        for keyword, sfx_list in _SFX_SCENE_RULES["setting"].items():
            if keyword in scene.setting:
                for sfx in sfx_list:
                    if sfx not in matched:
                        matched.append(sfx)
    
    # 2. 匹配情绪
    if scene.mood:
        for keyword, sfx_list in _SFX_SCENE_RULES["mood"].items():
            if keyword in scene.mood:
                for sfx in sfx_list:
                    if sfx not in matched:
                        matched.append(sfx)
    
    # 3. 匹配描述关键词
    if scene.description:
        for keyword, sfx_list in _SFX_SCENE_RULES["description_keywords"].items():
            if keyword in scene.description:
                for sfx in sfx_list:
                    if sfx not in matched:
                        matched.append(sfx)
    
    return matched


# ─── v8.7 程序化 SFX 音效生成 ──────────────────────────────

_PROGRAMMATIC_SFX = {
    "wind":     lambda duration_ms: _gen_noise(duration_ms, lowpass=400),
    "rain":     lambda duration_ms: _gen_noise(duration_ms, lowpass=800),
    "forest":   lambda duration_ms: _gen_mixed(duration_ms, [
        (lambda d: _gen_noise(d, lowpass=300), 0.6),
        (lambda d: _gen_tone(d, 600, 0.3), 0.4),
    ]),
    "night":    lambda duration_ms: _gen_mixed(duration_ms, [
        (lambda d: _gen_noise(d, lowpass=200), 0.7),
        (lambda d: _gen_tone(d, 40, 0.15), 0.3),
    ]),
    "market":   lambda duration_ms: _gen_noise(duration_ms, lowpass=1200) + 3,
    "bell":     lambda duration_ms: _gen_envelope_tone(duration_ms, 800, attack=50, decay=1800, volume=-6),
    "door":     lambda duration_ms: _gen_envelope_tone(duration_ms, 200, attack=10, decay=400, volume=-3),
    "hit":      lambda duration_ms: _gen_envelope_tone(duration_ms, 150, attack=5, decay=300, volume=0),
    "step":     lambda duration_ms: _gen_pulse_tone(duration_ms, 80, interval=400, volume=-12),
    "heartbeat":lambda duration_ms: _gen_pulse_tone(duration_ms, 60, interval=700, volume=-6),
    "riser":    lambda duration_ms: _gen_riser(duration_ms),
    "boom":     lambda duration_ms: _gen_envelope_tone(duration_ms, 60, attack=10, decay=1200, volume=0),
    "whoosh":   lambda duration_ms: _gen_riser(duration_ms, start=200, end=3000),
}

def _gen_noise(duration_ms: int, lowpass: int = 1000, volume: float = -12):
    """生成白噪声 → 低通滤波"""
    from pydub import AudioSegment
    audio = AudioSegment.silent(duration=0)
    try:
        import numpy as np
        sr = 44100
        samples = int(sr * duration_ms / 1000)
        noise = np.random.normal(0, 0.3, samples).astype(np.float32)
        # 简易低通 (移动平均)
        if lowpass > 0 and samples > lowpass * 2:
            window = int(sr / (lowpass * 2))
            noise = np.convolve(noise, np.ones(window)/window, mode='same')
        noise = np.clip(noise * 32767, -32767, 32767).astype(np.int16)
        audio = AudioSegment(noise.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    except ImportError:
        audio = AudioSegment.silent(duration=duration_ms)
    return audio + volume

def _gen_tone(duration_ms: int, freq: int = 440, volume: float = -12):
    """生成纯正弦波"""
    from pydub import AudioSegment
    try:
        import numpy as np
        sr = 44100
        samples = int(sr * duration_ms / 1000)
        t = np.arange(samples) / sr
        tone = np.sin(2 * np.pi * freq * t).astype(np.float32)
        tone = (tone * 32767 * 0.5).astype(np.int16)
        audio = AudioSegment(tone.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    except ImportError:
        audio = AudioSegment.silent(duration=duration_ms)
    return audio + volume

def _gen_envelope_tone(duration_ms: int, freq: int, attack: int = 50, decay: int = 500, volume: float = -6):
    """带包络的音（attack → decay → silence）"""
    from pydub import AudioSegment
    try:
        import numpy as np
        sr = 44100
        samples = int(sr * duration_ms / 1000)
        t = np.arange(samples) / sr
        tone = np.sin(2 * np.pi * freq * t).astype(np.float32)
        env = np.ones(samples) * 0.001
        a_samples = int(sr * attack / 1000)
        d_samples = int(sr * decay / 1000)
        env[:a_samples] = np.linspace(0, 1, a_samples)
        if a_samples + d_samples < samples:
            env[a_samples:a_samples + d_samples] = np.linspace(1, 0.001, d_samples)
        tone = (tone * env * 32767).astype(np.int16)
        audio = AudioSegment(tone.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    except ImportError:
        audio = AudioSegment.silent(duration=duration_ms)
    return audio + volume

def _gen_pulse_tone(duration_ms: int, freq: int, interval: int = 500, volume: float = -12):
    """生成脉冲式音（短促重复）"""
    from pydub import AudioSegment
    try:
        import numpy as np
        sr = 44100
        total = int(sr * duration_ms / 1000)
        pulse = int(sr * 0.05)
        gap = int(sr * interval / 1000)
        audio_arr = np.zeros(total, dtype=np.float32)
        pos = 0
        while pos + pulse < total:
            audio_arr[pos:pos+pulse] = np.sin(2*np.pi*freq*np.arange(pulse)/sr) * 0.5
            pos += gap
        audio_arr = (audio_arr * 32767).astype(np.int16)
        audio = AudioSegment(audio_arr.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    except ImportError:
        audio = AudioSegment.silent(duration=duration_ms)
    return audio + volume

def _gen_riser(duration_ms: int, start: int = 200, end: int = 2000, volume: float = -8):
    """生成频率扫升（riser）"""
    from pydub import AudioSegment
    try:
        import numpy as np
        sr = 44100
        samples = int(sr * duration_ms / 1000)
        t = np.arange(samples) / sr
        freqs = np.linspace(start, end, samples)
        phase = 2 * np.pi * np.cumsum(freqs) / sr
        tone = np.sin(phase).astype(np.float32)
        tone *= np.linspace(0, 1, samples)
        tone = (tone * 32767 * 0.6).astype(np.int16)
        audio = AudioSegment(tone.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    except ImportError:
        audio = AudioSegment.silent(duration=duration_ms)
    return audio + volume

def _gen_mixed(duration_ms: int, generators: list):
    """混合多个生成器输出"""
    from pydub import AudioSegment
    mixed = AudioSegment.silent(duration=duration_ms, frame_rate=44100)
    for gen_fn, vol in generators:
        mixed = mixed.overlay(gen_fn(duration_ms) + int(vol * 10))
    return mixed


async def _generate_procedural_sfx(name: str) -> str:
    """v8.7: 程序化合成 SFX 音效文件，返回临时 wav 路径"""
    gen = _PROGRAMMATIC_SFX.get(name)
    if not gen:
        return ""
    from pydub import AudioSegment
    try:
        duration_ms = 5000  # 默认5秒
        audio = gen(duration_ms)
        if len(audio) < 10:
            return ""
        sfx_dir = PROJECT_ROOT / "sfx" / "_generated"
        sfx_dir.mkdir(parents=True, exist_ok=True)
        wav_path = sfx_dir / f"{name}.wav"
        audio.export(str(wav_path), format="wav")
        if wav_path.stat().st_size > 500:
            return str(wav_path)
    except Exception as e:
        print(f"[SFX-Gen] 生成 {name} 失败: {str(e)[:60]}", flush=True)
    return ""


async def add_scene_sfx(video_path: str, scene, output_path: str, sfx_volume: float = 0.25) -> str:
    """v6.0: 根据场景描述自动匹配并叠加环境音效"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(video_path, output_path)
        return output_path
    
    sfx_names = _match_sfx_for_scene(scene)
    if not sfx_names:
        shutil.copy2(video_path, output_path)
        return output_path
    
    sfx_dir = PROJECT_ROOT / "sfx"
    sfx_paths = []  # v8.7.1: 初始化列表
    
    # v8.7: 程序化生成缺失的 SFX (sfx/ 目录为空时自动合成)
    for name in list(sfx_names):
        found = False
        for subdir in ["ambient", "action", "transition"]:
            p = sfx_dir / subdir / f"{name}.mp3"
            if p.exists() and p.stat().st_size > 500:
                found = True
                sfx_paths.append(str(p))
                break
        if not found:
            proc_path = await _generate_procedural_sfx(name)
            if proc_path:
                sfx_paths.append(proc_path)
    
    if not sfx_paths:
        shutil.copy2(video_path, output_path)
        return output_path
    
    vid_duration = await get_audio_duration(video_path) or 5.0
    
    # 构建 ffmpeg 混合命令
    inputs = ["-i", video_path]
    sfx_labels = []
    for i, sfx_p in enumerate(sfx_paths):
        inputs.extend(["-stream_loop", "-1", "-i", sfx_p])
        sfx_labels.append(f"[{i+1}:a]")
    
    # 混合所有音效
    amix_count = 1 + len(sfx_paths)
    sfx_mix = "".join(sfx_labels)
    filter_complex = (
        f"{sfx_mix}amix=inputs={amix_count}:duration=first:dropout_transition=0,"
        f"volume={sfx_volume}[outa]"
    )
    
    cmd = [
        ffmpeg, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[outa]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", str(vid_duration),
        output_path
    ]
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode == 0 and Path(output_path).exists():
            sfx_info = ", ".join([Path(p).stem for p in sfx_paths])
            print(f"[SFX] 场景 {scene.id}: 叠加音效 [{sfx_info}]", flush=True)
            return output_path
        else:
            print(f"[SFX] 场景 {scene.id}: 音效混合失败", flush=True)
            shutil.copy2(video_path, output_path)
            return output_path
    except Exception as e:
        print(f"[SFX] 场景 {scene.id}: 异常 ({str(e)[:60]})", flush=True)
        shutil.copy2(video_path, output_path)
        return output_path


def split_paragraphs(text: str, max_chars: int = 120) -> list[str]:
    raw = [p.strip() for p in re.split(r'\n{1,}', text) if p.strip()]
    result = []
    for para in raw:
        if not para:
            continue
        if len(para) < 5:
            continue
        if len(para) > max_chars:
            sentences = re.split(r'(?<=[。！？…])', para)
            chunk = ""
            for sent in sentences:
                if len(chunk) + len(sent) <= max_chars:
                    chunk += sent
                else:
                    if chunk.strip():
                        result.append(chunk.strip())
                    chunk = sent
            if chunk.strip():
                result.append(chunk.strip())
        else:
            result.append(para)
    return result


# ─── v7.0 IP-Adapter 角色定妆照生成 ─────────────────────
async def _generate_character_portrait(job, character, save_dir: Path) -> Optional[str]:
    """为指定角色生成一张高质量正面定妆照，用作 IP-Adapter 的参考图像。
    返回本地文件路径，失败返回 None。
    """
    try:
        from app.config import DEEPSEEK_API_KEY
    except ImportError:
        return None
    
    if not DEEPSEEK_API_KEY and not job.deepseek_key:
        # 没有 DeepSeek, 直接用 kling_prompt
        portrait_prompt = character.kling_prompt
        if not portrait_prompt:
            return None
    else:
        # 有 DeepSeek: 优化定妆照 prompt
        api_key = job.deepseek_key or DEEPSEEK_API_KEY
        portrait_prompt = character.kling_prompt or ""
        
        # 如果有 kling_prompt 直接使用，否则用角色属性构建
        if not portrait_prompt:
            parts = []
            if character.gender:
                parts.append(f"gender: {character.gender}")
            if character.age_range:
                parts.append(f"age: {character.age_range}")
            if character.appearance:
                parts.append(f"appearance: {character.appearance}")
            if character.clothing:
                parts.append(f"clothing: {character.clothing}")
            if character.body_type:
                parts.append(f"body type: {character.body_type}")
            
            if not parts:
                return None
            
            # DeepSeek 生成专业定妆照 prompt
            base_prompt = f"角色名: {character.name}\n" + "\n".join(parts)
            style_hint = "写实电影风格" if (job and getattr(job, 'style', 'cinematic') in ('cinematic', 'realistic')) else "动漫风格"
            try:
                rewrite_system = f"""你是专业角色定妆照设计师。将角色信息转为高质量英文prompt。
格式: solo portrait, [character description], front facing, looking at camera with neutral expression, 
clear facial features, symmetrical composition, soft studio lighting, {style_hint},
professional photography, best quality, 8k.
只输出prompt文本，不加解释。"""
                result = await call_deepseek(
                    api_key, rewrite_system, base_prompt,
                    max_tokens=256, temperature=0.3
                )
                portrait_prompt = result.strip().strip('"').strip("'").strip()
            except Exception as e:
                logger.warning(f"[Portrait] 角色正脸prompt生成失败: {str(e)[:100]}")
                return None
    
    if not portrait_prompt or len(portrait_prompt) < 20:
        return None
    
    print(f"[Portrait] 为 {character.name} 生成定妆照: {portrait_prompt[:80]}...", flush=True)
    
    # 使用纯净 txt2img 工作流 (不使用 IP-Adapter, 避免循环依赖)
    txt2img_template = load_workflow("txt2img")
    portrait_seed = abs(hash(character.name + job.id)) % (2**31)
    
    portrait_workflow = fill_workflow(txt2img_template, {
        "POSITIVE_PROMPT": f"masterpiece, best quality, {portrait_prompt}",
        "NEGATIVE_PROMPT": "(worst quality:1.5), (low quality:1.5), blurry, deformed, watermark, text, multiple people, group",
        "SEED": portrait_seed,
        "WIDTH": IMG_WIDTH,
        "HEIGHT": IMG_HEIGHT,
        "CHECKPOINT": job.img_checkpoint,
    })
    
    prompt_id = await comfyui.submit_workflow(portrait_workflow)
    result = await comfyui.wait_for_result_ws(prompt_id, job_id=job.id, timeout=600)
    
    outputs = result.get("outputs", {})
    portrait_filename = None
    portrait_subfolder = ""
    for node_id, node_out in outputs.items():
        if "images" in node_out:
            img_info = node_out["images"][0]
            portrait_filename = img_info["filename"]
            portrait_subfolder = img_info.get("subfolder", "")
            break
    
    if not portrait_filename:
        return None
    
    local_path = await comfyui.download_output(portrait_filename, portrait_subfolder, save_dir=save_dir)
    if local_path and Path(local_path).exists():
        size_kb = Path(local_path).stat().st_size / 1024
        print(f"[Portrait] {character.name} 定妆照已保存: {local_path} ({size_kb:.0f}KB)", flush=True)
        return str(local_path)
    return None


async def _build_character_material_library(job: JobState, scene: Scene, scene_dir: Path):
    """
    v12.0: 角色素材库自动构建 — 场景首帧成功后自动裁剪角色参考图

    流程:
    1. 检查场景图片是否已生成
    2. 为每个出场角色检查是否已有素材库
    3. 如有可灵 API Key: 调用 generate_character_set 生成 3 角度参考图
    4. 如无可灵: 使用 ComfyUI img2img 从场景图裁剪角色面部作为参考
    5. 将素材库路径存入 character.material_library_path（动态属性）

    参数:
        job: 任务状态
        scene: 当前场景
        scene_dir: 场景输出目录
    """
    if not scene.image_path or not Path(scene.image_path).exists():
        return

    if not job.characters:
        return

    # 解析场景中出场的角色
    scene_char_names = []
    if scene.characters:
        # scene.characters 是逗号分隔的角色名
        scene_char_names = [n.strip() for n in scene.characters.split(",") if n.strip()]
    if not scene_char_names:
        return

    # 素材库根目录
    matlib_dir = OUTPUT_DIR / job.id / "character_matlib"
    matlib_dir.mkdir(parents=True, exist_ok=True)

    for char in job.characters:
        if char.name not in scene_char_names:
            continue

        # 检查是否已有素材库（跳过已生成的）
        existing_path = getattr(char, 'material_library_path', '') or ''
        if existing_path and Path(existing_path).exists():
            continue

        char_dir = matlib_dir / char.name
        char_dir.mkdir(parents=True, exist_ok=True)

        # 方案 A: 有可灵 API Key → 生成多角度参考图
        if job.kling_api_key:
            try:
                from kling_client import KlingImageClient
                kling = KlingImageClient(api_key=job.kling_api_key)

                # 构建角色描述
                desc = char.kling_prompt or char.appearance or ""
                if char.clothing:
                    desc += f", wearing {char.clothing}"
                if char.body_type:
                    desc += f", {char.body_type}"

                if not desc or len(desc) < 10:
                    continue

                print(f"[MatLib] 为角色 {char.name} 生成多角度参考图...", flush=True)
                result = await kling.generate_character_set(
                    character_description=desc,
                    save_dir=str(char_dir),
                    character_name=char.name,
                    n_angles=3,
                )

                if result["status"] == "succeed" and result.get("paths"):
                    char_dir_str = str(char_dir)
                    # 动态设置属性（兼容 Pydantic 模型）
                    setattr(char, 'material_library_path', char_dir_str)
                    print(f"[MatLib] 角色 {char.name} 素材库已创建: {len(result['paths'])} 张参考图", flush=True)
                    continue
            except Exception as e:
                print(f"[MatLib] 可灵生成失败: {str(e)[:100]}", flush=True)

        # 方案 B: 无可灵 → 从场景图裁剪面部作为参考（使用 ComfyUI 或简单裁剪）
        try:
            from PIL import Image
            img = Image.open(scene.image_path)
            w, h = img.size
            # 简单裁剪: 上半部分中心区域作为面部参考
            # 竖屏 1080x1920 → 面部通常在上 1/3
            face_crop = img.crop((w // 4, h // 8, w * 3 // 4, h * 3 // 8))
            face_path = char_dir / f"{char.name}_face_crop.png"
            face_crop.save(face_path)
            setattr(char, 'material_library_path', str(char_dir))
            print(f"[MatLib] 角色 {char.name} 从场景图裁剪参考图: {face_path}", flush=True)
        except Exception as e:
            print(f"[MatLib] 裁剪失败: {str(e)[:80]}", flush=True)


def _get_character_clothing_desc(job: JobState, scene: Scene) -> str:
    """
    v12.0: 获取本场景出场角色的着装描述，注入到 image_prompt 中确保衣物一致性

    返回: 英文着装描述字符串，如 "wearing red dress, black coat"
    """
    if not job.characters or not scene.characters:
        return ""

    scene_char_names = [n.strip() for n in scene.characters.split(",") if n.strip()]
    if not scene_char_names:
        return ""

    clothing_parts = []

    # 优先从 character_analysis 获取（15维详细信息）
    if job.character_analysis and isinstance(job.character_analysis.get('characters'), list):
        for c in job.character_analysis['characters']:
            if c.get('name', '') in scene_char_names:
                typical_clothing = c.get('typical_clothing', '')
                if typical_clothing and typical_clothing != '未提及':
                    clothing_parts.append(f"wearing {typical_clothing}")

    # 补充从 characters 获取
    if not clothing_parts:
        for char in job.characters:
            if char.name in scene_char_names and char.clothing:
                clothing_parts.append(f"wearing {char.clothing}")

    return ", ".join(clothing_parts)
    """
    构建全局角色外貌固定描述表，用于确保跨所有场景角色外貌一致。
    v6.2: 优先使用 character_analysis（15维详细信息），其次使用 characters（v6.0），最后从分镜汇总
    """
    lines = []
    
    # 优先：使用 v6.2 character_analysis（15维详细信息）
    if job.character_analysis and isinstance(job.character_analysis.get('characters'), list):
        for c in job.character_analysis['characters']:
            name = c.get('name', '未知角色')
            # 拼接外貌描述（15维中选择最重要的用于 AI 绘画）
            parts = []
            if c.get('physical_description'):
                parts.append(c['physical_description'])
            if c.get('face_detail'):
                parts.append(c['face_detail'])
            if c.get('hair_style'):
                parts.append(c['hair_style'])
            if c.get('eye_detail'):
                parts.append(c['eye_detail'])
            if c.get('skin_tone'):
                parts.append(c['skin_tone'])
            if c.get('typical_clothing'):
                parts.append(f"wearing {c['typical_clothing']}")
            if c.get('special_marks'):
                parts.append(c['special_marks'])
            desc = ', '.join([p for p in parts if p and p != '未提及'])
            if desc:
                lines.append(desc)
        if lines:
            return ', '.join(lines)
    
    # 其次：使用 v6.0 characters
    if job.characters:
        for c in job.characters:
            kling_prompt = getattr(c, 'kling_prompt', '')
            appearance = getattr(c, 'appearance', '')
            clothing = getattr(c, 'clothing', '')
            body_type = getattr(c, 'body_type', '')
            
            if kling_prompt:
                desc = kling_prompt.strip()
            else:
                parts = []
                if appearance:
                    parts.append(appearance)
                if body_type:
                    parts.append(body_type)
                if clothing:
                    parts.append(f"wearing {clothing}")
                desc = ', '.join(parts)
            if desc:
                lines.append(desc)
        if lines:
            return ', '.join(lines)
    
    # 备选：从分镜的 characters 字段汇总（去重）
    char_mentions: dict = {}
    for scene in job.scenes:
        if scene.characters and scene.characters.strip() not in ("无", ""):
            for segment in scene.characters.split(";"):
                segment = segment.strip()
                if "：" in segment or ":" in segment:
                    sep = "：" if "：" in segment else ":"
                    name = segment.split(sep)[0].strip()
                    if name not in char_mentions:
                        char_mentions[name] = segment
    
    if char_matches := _extract_char_english_from_scene_chars(char_mentions.values()):
        return ', '.join(char_matches)

    return ""


def _build_global_character_desc(job) -> str:
    """聚合所有角色的外貌描述，作为提示词生成时的全局上下文锚点。

    数据来源优先级：
      1. job.character_analysis（15 维详细角色分析）
      2. job.characters（v6.0 角色对象）
    若两者皆无，返回空字符串。
    """
    lines = []

    # 优先：character_analysis（15 维详细信息）
    if getattr(job, "character_analysis", None) and isinstance(job.character_analysis.get("characters"), list):
        for c in job.character_analysis["characters"]:
            name = c.get("name", "未知角色")
            parts = []
            for key in ("physical_description", "face_detail", "hair_style", "eye_detail", "typical_clothing", "special_marks"):
                val = c.get(key)
                if val and val != "未提及":
                    parts.append(val if key != "typical_clothing" else f"wearing {val}")
            desc = ", ".join(parts)
            if desc:
                lines.append(f"{name}: {desc}")

    # 其次：v6.0 characters 对象
    if not lines and getattr(job, "characters", None):
        for c in job.characters:
            name = getattr(c, "name", "")
            kling_prompt = getattr(c, "kling_prompt", "")
            appearance = getattr(c, "appearance", "")
            clothing = getattr(c, "clothing", "")
            body_type = getattr(c, "body_type", "")
            if kling_prompt:
                lines.append(f"{name}: {kling_prompt.strip()}")
            else:
                parts = []
                for val in (appearance, body_type):
                    if val and val != "未提及":
                        parts.append(val)
                if clothing and clothing != "未提及":
                    parts.append(f"wearing {clothing}")
                desc = ", ".join(parts)
                if desc:
                    lines.append(f"{name}: {desc}")

    return "\n".join(lines)


def _build_scene_character_desc(job, scene) -> str:
    """v9.9: 只构建当前场景出场角色的外貌描述，防止跨场景角色污染。

    从 scene.characters 字段解析出场角色名，然后从 job.characters /
    character_analysis 中提取对应角色的外貌，忽略未出场角色。
    """
    # 解析当前场景出场的角色名
    appearing_names = set()
    if scene.characters and scene.characters.strip() not in ("无", ""):
        for segment in scene.characters.split(";"):
            segment = segment.strip()
            if "：" in segment or ":" in segment:
                sep = "：" if "：" in segment else ":"
                name = segment.split(sep)[0].strip()
                if name:
                    appearing_names.add(name)
            elif segment:
                appearing_names.add(segment)

    if not appearing_names:
        # 无明确出场角色，返回全局描述作为兜底
        return _build_global_character_desc(job)

    lines = []

    # 优先：character_analysis（15维详细信息）
    if job.character_analysis and isinstance(job.character_analysis.get('characters'), list):
        for c in job.character_analysis['characters']:
            name = c.get('name', '未知角色')
            if name not in appearing_names:
                continue
            parts = []
            if c.get('physical_description') and c['physical_description'] != '未提及':
                parts.append(c['physical_description'])
            if c.get('face_detail') and c['face_detail'] != '未提及':
                parts.append(c['face_detail'])
            if c.get('hair_style') and c['hair_style'] != '未提及':
                parts.append(c['hair_style'])
            if c.get('eye_detail') and c['eye_detail'] != '未提及':
                parts.append(c['eye_detail'])
            if c.get('typical_clothing') and c['typical_clothing'] != '未提及':
                parts.append(f"wearing {c['typical_clothing']}")
            if c.get('special_marks') and c['special_marks'] != '未提及':
                parts.append(c['special_marks'])
            desc = ', '.join(parts)
            if desc:
                lines.append(f"{name}: {desc}")

    # 其次：v6.0 characters
    if not lines and job.characters:
        for c in job.characters:
            name = getattr(c, 'name', '')
            if name not in appearing_names:
                continue
            kling_prompt = getattr(c, 'kling_prompt', '')
            appearance = getattr(c, 'appearance', '')
            clothing = getattr(c, 'clothing', '')
            body_type = getattr(c, 'body_type', '')
            if kling_prompt:
                lines.append(f"{name}: {kling_prompt.strip()}")
            else:
                parts = []
                for val in [appearance, body_type]:
                    if val and val != '未提及':
                        parts.append(val)
                if clothing and clothing != '未提及':
                    parts.append(f"wearing {clothing}")
                desc = ', '.join(parts)
                if desc:
                    lines.append(f"{name}: {desc}")

    if lines:
        return '\n'.join(lines)

    # 兜底：从分镜 characters 字段提取
    if scene.characters:
        return scene.characters

    return _build_global_character_desc(job)


def _extract_char_english_from_scene_chars(raw_char_list) -> list[str]:
    """从分镜 characters 字段的原始文本中提取英文外貌关键词。"""
    results = []
    for raw in raw_char_list:
        # 提取 [] 内的外貌特征片段
        import re as _re
        brackets = _re.findall(r'\[([^\]]+)\]', raw)
        if brackets:
            en_parts = []
            for b in brackets:
                translated = _translate_to_english_keywords(b)
                if translated:
                    en_parts.append(translated)
            if en_parts:
                results.append(", ".join(en_parts))
    return results


# ─── v9.10: 参数化运镜体系（蒸馏即梦4.0 21种运镜）──
# 每种镜头 = 类型 + 速度 + 焦段 + 机位 + 运动描述
_CAMERA_PRESETS = {
    # ── 推拉类（Dolly Push/Pull）──
    "轨道慢推": {
        "type": "dolly_push", "speed": "0.8m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "slow dolly push in, camera moving steadily forward at 0.8m/s, 50mm focal length, background gradually blurring, subject coming into sharp focus",
    },
    "低机位前推": {
        "type": "dolly_push", "speed": "0.8m/s", "focal": "35mm",
        "height": "0.3m", "angle": "0°",
        "desc": "low angle dolly push in, camera at 0.3m height moving forward at 0.8m/s, 35mm focal length, imposing upward perspective, dramatic tension",
    },
    "高机位后拉": {
        "type": "dolly_pull", "speed": "1.0m/s", "focal": "20mm",
        "height": "3.0m", "angle": "0°",
        "desc": "high angle dolly pull back, camera at 3m height pulling back at 1.0m/s, 20mm wide focal length, revealing entire scene from above",
    },
    "急速推镜": {
        "type": "dolly_push", "speed": "3.5m/s", "focal": "85mm",
        "height": "1.2m", "angle": "0°",
        "desc": "rapid dolly push in, camera accelerating to 3.5m/s, 85mm telephoto, focus snapping to subject core, intense visual pressure",
    },
    "特写切远景快拉": {
        "type": "dolly_pull", "speed": "4.5m/s", "focal": "16mm",
        "height": "1.5m", "angle": "0°",
        "desc": "extreme pull from close-up to wide shot, camera pulling back at 4.5m/s, 16mm ultra wide, dramatic spatial contrast reveal",
    },

    # ── 变焦类（Zoom）──
    "变焦推镜": {
        "type": "zoom_in", "speed": "1.5x/s", "focal": "24mm→85mm",
        "height": "1.5m", "angle": "0°",
        "desc": "zoom in from 24mm to 85mm, fixed camera position, focal length smoothly increasing, subject magnified without camera movement",
    },
    "变焦拉镜": {
        "type": "zoom_out", "speed": "1.5x/s", "focal": "85mm→24mm",
        "height": "1.5m", "angle": "0°",
        "desc": "zoom out from 85mm to 24mm, fixed camera position, focal length smoothly decreasing, background expanding to reveal context",
    },

    # ── 摇镜类（Pan）──
    "左摇镜": {
        "type": "pan_left", "speed": "10°/s", "focal": "35mm",
        "height": "1.5m", "angle": "90°",
        "desc": "horizontal pan left at 10°/s, sweeping 90°, 35mm focal length, smooth horizontal tracking, environment revealing frame by frame",
    },
    "右摇镜": {
        "type": "pan_right", "speed": "10°/s", "focal": "35mm",
        "height": "1.5m", "angle": "90°",
        "desc": "horizontal pan right at 10°/s, sweeping 90°, 35mm focal length, smooth horizontal tracking",
    },

    # ── 俯仰类（Tilt）──
    "仰拍旋摇": {
        "type": "tilt_up", "speed": "20°/s", "focal": "50mm",
        "height": "0.3m", "angle": "-75°→0°",
        "desc": "low angle tilt up from -75°, rotating at 20°/s, 50mm focal length, dramatic upward reveal, subject appearing towering and powerful",
    },
    "俯拍旋摇": {
        "type": "tilt_down", "speed": "20°/s", "focal": "24mm",
        "height": "3.0m", "angle": "75°→0°",
        "desc": "high angle tilt down from 75°, rotating at 20°/s, 24mm wide focal length, full environmental coverage from above",
    },

    # ── 环绕类（Orbit）──
    "左环摇": {
        "type": "orbit_left", "speed": "15°/s", "focal": "50mm",
        "height": "1.2m", "angle": "360°",
        "desc": "left orbit around subject at 15°/s, 360° rotation, 50mm focal length, camera at 1.2m height, subject remaining centered throughout",
    },
    "右环摇": {
        "type": "orbit_right", "speed": "15°/s", "focal": "50mm",
        "height": "1.2m", "angle": "360°",
        "desc": "right orbit around subject at 15°/s, 360° rotation, 50mm focal length, smooth circular tracking",
    },
    "旋转前推": {
        "type": "orbit_push", "speed": "20°/s+0.8m/s", "focal": "50mm",
        "height": "1.5m", "angle": "360°",
        "desc": "360° rotation at 20°/s combined with forward dolly at 0.8m/s, spiral approach, electronic stabilization",
    },

    # ── 跟拍与升降类（Tracking/Elevation）──
    "跟焦跟拍": {
        "type": "tracking", "speed": "1.0m/s", "focal": "85mm",
        "height": "1.5m", "angle": "0°",
        "desc": "smooth tracking follow shot, camera locked on subject at 1.0m/s, 85mm focal length, continuous autofocus, no jitter",
    },
    "高速跟拍": {
        "type": "tracking", "speed": "5.0m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "high speed tracking shot at 5.0m/s, electronic stabilization, slight motion blur, dynamic action following",
    },
    "垂直升镜": {
        "type": "elevation_up", "speed": "0.6m/s", "focal": "35mm→24mm",
        "height": "1.5m→5.0m", "angle": "0°",
        "desc": "vertical elevation from close-up to full view, camera rising at 0.6m/s from 1.5m to 5m, focal length widening from 35mm to 24mm",
    },

    # ── 分段式（Segmented）──
    "阶梯推镜": {
        "type": "segmented_push", "speed": "0.7m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "segmented dolly push in 3 stages at 0.7m/s each, 0.5s pause between stages, focal length subtly adjusting, rhythmic tension building",
    },
    "阶梯拉镜": {
        "type": "segmented_pull", "speed": "0.9m/s", "focal": "50mm",
        "height": "1.5m", "angle": "0°",
        "desc": "segmented dolly pull back in 3 stages at 0.9m/s each, 0.5s pause between stages, environment revealing in layers",
    },

    # ── 斜角动感类（Dutch Angle）──
    "斜角拉镜": {
        "type": "dutch_pull", "speed": "1.2m/s", "focal": "28mm",
        "height": "1.5m", "angle": "15° tilt",
        "desc": "dutch angle pull back at 1.2m/s, camera tilted 15°, 28mm wide focal length, dynamic unease, enhanced motion feel",
    },
    "斜角推镜": {
        "type": "dutch_push", "speed": "1.0m/s", "focal": "40mm",
        "height": "1.5m", "angle": "15° tilt",
        "desc": "dutch angle push in at 1.0m/s, camera tilted 15°, 40mm focal length, visual tension, dramatic approach",
    },
}

# 向后兼容：保留旧的中文→英文简化映射（用于 prompt 解析和兼容）
_CAMERA_MAP_SIMPLE = {
    "固定镜头": "static shot, locked camera, no movement",
    "缓慢推镜": "slow push in, dolly zoom, gradually approaching subject",
    "缓慢拉镜": "slow pull back, dolly out, revealing wider context",
    "横摇": "smooth panning shot, horizontal tracking movement",
    "竖摇": "tilt shot, vertical camera movement",
    "特写": "extreme close-up shot, detail focus, shallow depth of field",
    "近景": "medium close-up, intimate framing",
    "中景": "medium shot, balanced composition",
    "全景": "wide establishing shot, full environmental context",
    "跟拍": "tracking shot, smooth camera follow, motion parallax",
    "俯拍": "high angle shot, bird's eye perspective",
    "仰拍": "low angle hero shot, dramatic upward perspective",
}


# ─── v7.0 Ken Burns 视频动画 ───────────────────────────────
# ─── v7.2 云端文生视频 ──────────────────────────────────────
CLOUD_VIDEO_SCRIPT = PROJECT_ROOT / "scripts" / "cloud_video.py"

async def _generate_cloud_t2v(scene, scene_dir: Path) -> str:
    """调用云端文生视频 API, 返回本地 mp4 路径或空字符串
    
    使用 cloud_video.py 桥接层调用 buddy-cloud.py。
    自动处理并发限制 (429) 重试。
    """
    import json as _json
    if not CLOUD_VIDEO_SCRIPT.exists():
        print(f"[CloudT2V] cloud_video.py 未找到", flush=True)
        return ""
    
    parts = []
    if scene.image_prompt:
        parts.append(scene.image_prompt[:300])
    elif scene.description:
        parts.append(scene.description[:200])
    camera = getattr(scene, 'camera', '') or ''
    if camera:
        parts.append(f"镜头运动: {camera}")
    mood = getattr(scene, 'mood', '') or ''
    if mood:
        mood_en = {"紧张": "tense", "温馨": "warm cozy", "悲伤": "sad melancholic",
                   "壮阔": "epic grand", "神秘": "mysterious eerie", "热血": "passionate",
                   "恐惧": "fearful terrifying", "喜悦": "joyful", "宁静": "calm peaceful",
                   "诡异": "eerie supernatural", "压抑": "oppressive dark"}.get(mood, mood)
        parts.append(f"{mood_en} atmosphere")
    prompt = "，".join(p for p in parts if p)
    if len(prompt) < 20:
        return ""
    
    output_path = str(scene_dir / f"scene_{scene.id:03d}_cloud.mp4")
    
    try:
        import subprocess as _sp
        # 传递当前环境变量（含 .env 中的 CLOUD_VIDEO_TOKEN）
        env = os.environ.copy()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(CLOUD_VIDEO_SCRIPT), prompt, output_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        
        if proc.returncode == 0 and Path(output_path).exists():
            size = Path(output_path).stat().st_size
            if size > 10000:
                print(f"[CloudT2V] 场景 {scene.id}: 完成 ({size/1024:.0f}KB)", flush=True)
                return output_path
        
        # 读取 stderr 获取详细错误
        err_text = stderr.decode()[:300] if stderr else ""
        out_text = stdout.decode()[:300] if stdout else ""
        # 尝试从 stdout 解析 JSON 错误
        err_msg = err_text
        if not err_msg and out_text:
            try:
                err_json = _json.loads(out_text)
                err_msg = err_json.get("message", out_text[:150])
            except:
                err_msg = out_text[:150]
        print(f"[CloudT2V] 场景 {scene.id}: 失败 ({err_msg[:200]})", flush=True)
        return ""
    except asyncio.TimeoutError:
        print(f"[CloudT2V] 场景 {scene.id}: 超时 (600s)", flush=True)
        return ""
    except Exception as e:
        print(f"[CloudT2V] 场景 {scene.id}: 异常 ({str(e)[:100]})", flush=True)
        return ""


# ─── v7.2 漫剧伪声字特效 ──────────────────────────────────
async def _add_manga_fx(video_path: str, scene, scene_dir: Path) -> str:
    """给视频添加漫剧风格伪声字 + 说话角色字幕
    红果漫剧标志性特征: "轰" "啊?!" "砰" 等文字弹幕, 带缩放弹入+淡出
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return video_path
    
    output_path = str(scene_dir / f"scene_{scene.id:03d}_fx.mp4")
    mood = getattr(scene, 'mood', '') or ''
    subtitle = getattr(scene, 'subtitle_text', '') or ''
    characters = getattr(scene, 'characters', '') or ''
    
    # 查找中文字体
    font_path = _find_chinese_font()
    font_param = ""
    if font_path:
        font_escaped = font_path.replace("\\", "/").replace(":", "\\:")
        font_param = f"fontfile='{font_escaped}':"
    
    # 情绪 → 伪声字映射
    # v8.2: 伪声字（"！""？！"等）是红果漫剧元素，不适合写实/叙事/恐怖风视频
    # 全部清空，避免在叙事场景中出现无关叠加文字
    fx_map = {}
    
    sfx_text = fx_map.get(mood, "")
    
    # 构建 FFmpeg filter chain
    filters = []
    
    # 1. 伪声字特效: 屏幕中央大号字体, 缩放弹入 + 淡出
    if sfx_text:
        sfx_filter = (
            f"drawtext={font_param}"
            f"text='{sfx_text}':"
            f"fontsize=80:fontcolor=red@0.9:borderw=3:bordercolor=black@0.7:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-100:"
            f"enable='between(t,0.1,2.5)'"
        )
        filters.append(sfx_filter)
    
    # 2. 角色标签: 左上角显示说话角色名
    if characters:
        char_name = characters.split(",")[0].strip()[:4]
        char_filter = (
            f"drawtext={font_param}"
            f"text='[{char_name}]':"
            f"fontsize=28:fontcolor=white@0.85:borderw=2:bordercolor=black@0.5:"
            f"x=20:y=30:"
            f"enable='between(t,0.1,8)'"
        )
        filters.append(char_filter)
    
    # 3. 字幕: 底部居中, 半透明黑底
    if subtitle and len(subtitle) > 1:
        safe_text = subtitle.replace("'", "'\\''").replace(":", "\\:").replace("%", "\\%")
        sub_filter = (
            f"drawtext={font_param}"
            f"text='{safe_text[:80]}':"
            f"fontsize=24:fontcolor=white@0.9:borderw=1:bordercolor=black:"
            f"x=(w-text_w)/2:y=h-th-60:"
            f"box=1:boxcolor=black@0.4:boxborderw=8:"
            f"enable='between(t,0.2,8)'"
        )
        filters.append(sub_filter)
    
    if not filters:
        return video_path
    
    filter_str = ",".join(filters)
    
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-i", video_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-c:a", "copy",
        output_path,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await asyncio.wait_for(proc.communicate(), timeout=60)
    
    if Path(output_path).exists() and Path(output_path).stat().st_size > 1000:
        return output_path
    return video_path


async def _generate_ken_burns_video(image_path: str, scene, scene_dir: Path, job_id: str) -> str:
    """用 FFmpeg zoompan 生成 Ken Burns 风格的推拉摇移动画。
    100%稳定, 无 AI 漂移, 适合对话/静态场景。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return ""
    
    output_path = str(scene_dir / f"scene_{scene.id:03d}_kb.mp4")
    intensity = getattr(scene, 'emotional_intensity', 5)
    camera = getattr(scene, 'camera', '') or ''
    mood = getattr(scene, 'mood', '') or ''
    
    # 根据镜头和情绪确定动画参数
    # 帧数: 跟 duration 联动，避免前 5s 有动作后 N-5s 静止
    try:
        dur = float(getattr(scene, 'duration', '5s').rstrip('s')) if isinstance(getattr(scene, 'duration', None), str) else float(getattr(scene, 'duration', 5) or 5)
    except Exception:
        dur = 5.0
    fps = 24
    frames = max(48, int(dur * fps))  # 至少 2 秒，避免太短
    width, height = 1080, 1920
    
    # 动画类型
    if '拉' in camera or '远景' in camera:
        # 拉远 (zoom out) - 加大幅度让用户能感知
        zoom_start = 1.35
        zoom_end = 1.0
    elif '推' in camera or '近景' in camera or '特写' in camera:
        # 推进 (zoom in) - 加大到 18%/12% 让用户看到
        zoom_start = 1.0
        zoom_end = 1.22 if intensity >= 7 else 1.15
    elif '跟' in camera or '移' in camera or '摇' in camera:
        # 横移 (pan)
        zoom_val = 1.1
        pan_coeff = 1.0 - 1.0 / zoom_val  # 横移幅度 (x 可移动范围占比)
        # 修正 v12.1: 原代码将字符串 pan_dir("left"/"right") 直接拼入 ffmpeg 表达式,
        #   导致 x='...*(left*0.5+0.5)...' 语法非法 -> ffmpeg 报错 -> 0 字节视频。
        #   改为数值方向系数, 并约束 x 落在合法区间 [0, iw*pan_coeff] 内。
        if '右' in camera:
            x_expr = f"iw*{pan_coeff:.4f}*on/({frames}-1)"
        else:  # 默认向左横移
            x_expr = f"iw*{pan_coeff:.4f}*(1-on/({frames}-1))"
        filter_str = (
            f"zoompan=z={zoom_val}:d={frames}:"
            f"x='{x_expr}':"
            f"y='ih/2-(ih/{zoom_val}/2)':"
            f"s={width}x{height}:fps={fps}"
        )
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-loop", "1", "-i", image_path,
            "-filter_complex", filter_str,
            "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", output_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        return output_path if Path(output_path).exists() else ""
    
    elif '俯' in camera:
        # 俯拍下拉
        zoom_val = 1.1
        filter_str = (
            f"zoompan=z='if(eq(on,0),{zoom_val},{zoom_val})':d={frames}:"
            f"x='iw/2-(iw/{zoom_val}/2)':"
            f"y='if(eq(on,0),0,on/{frames}*10)':"
            f"s={width}x{height}:fps=24"
        )
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-loop", "1", "-i", image_path,
            "-filter_complex", filter_str,
            "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", output_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        return output_path if Path(output_path).exists() else ""
    
    elif '仰' in camera:
        # 仰拍上推
        zoom_val = 1.1
        filter_str = (
            f"zoompan=z='if(eq(on,0),{zoom_val},{zoom_val})':d={frames}:"
            f"x='iw/2-(iw/{zoom_val}/2)':"
            f"y='ih/{zoom_val}-ih/2+on/{frames}*10':"
            f"s={width}x{height}:fps=24"
        )
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-loop", "1", "-i", image_path,
            "-filter_complex", filter_str,
            "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", output_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        return output_path if Path(output_path).exists() else ""
    
    else:
        # 默认: 明显推镜 (zoom in) — 修复原 1.03-1.12 用户看不出来的问题
        if intensity >= 7:
            zoom_end = 1.20  # 高情绪强推
        elif intensity <= 3:
            zoom_end = 1.12  # 低情绪也要能看出
        else:
            zoom_end = 1.15  # 中等

        filter_str = (
            f"zoompan=z='min(zoom+{((zoom_end-1.0)/frames)*2:.6f},{zoom_end})':"
            f"d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={width}x{height}:fps=24"
        )
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-loop", "1", "-i", image_path,
            "-filter_complex", filter_str,
            "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", output_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        return output_path if Path(output_path).exists() else ""

    # ── v12.1 修复: '拉'/'推' 分支只设置了 zoom_start/zoom_end 却未构建 filter 也未返回,
    #    会隐式返回 None 导致 ken_burns 静默失败并回退 LTX。此处统一构建 zoompan 并生成。
    if zoom_end < zoom_start:
        # 拉远 (zoom out): 从 zoom_start 递减到 zoom_end
        step = (zoom_start - zoom_end) / frames * 2
        filter_str = (
            f"zoompan=z='if(eq(on,0),{zoom_start:.3f},max(zoom-{step:.6f},{zoom_end:.3f}))':"
            f"d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={width}x{height}:fps=24"
        )
    else:
        # 推进 (zoom in): 从 zoom_start 递增到 zoom_end
        step = (zoom_end - zoom_start) / frames * 2
        filter_str = (
            f"zoompan=z='if(eq(on,0),{zoom_start:.3f},min(zoom+{step:.6f},{zoom_end:.3f}))':"
            f"d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={width}x{height}:fps=24"
        )
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-loop", "1", "-i", image_path,
        "-filter_complex", filter_str,
        "-t", str(dur), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", output_path,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await asyncio.wait_for(proc.communicate(), timeout=60)
    return output_path if Path(output_path).exists() else ""



# ─── v9.10: 场景感知自动镜头选择 ──────────────────────────
# 根据场景的情绪、强度、画面内容自动推荐最佳运镜

# 情绪→推荐运镜映射（即梦蒸馏）
_MOOD_CAMERA_MAP = {
    "紧张":  ["急速推镜", "低机位前推", "斜角推镜"],
    "恐惧":  ["急速推镜", "斜角拉镜", "阶梯推镜"],
    "愤怒":  ["急速推镜", "低机位前推", "旋转前推"],
    "悲伤":  ["缓慢拉镜", "阶梯拉镜", "垂直升镜"],
    "喜悦":  ["轨道慢推", "左环摇", "右环摇"],
    "压抑":  ["阶梯推镜", "斜角拉镜", "俯拍旋摇"],
    "壮阔":  ["高机位后拉", "俯拍旋摇", "垂直升镜"],
    "热血":  ["旋转前推", "急速推镜", "高速跟拍"],
    "释然":  ["缓慢拉镜", "垂直升镜", "变焦拉镜"],
    "孤独":  ["阶梯拉镜", "高机位后拉", "斜角拉镜"],
    "惆怅":  ["缓慢拉镜", "变焦拉镜", "阶梯拉镜"],
    "温馨":  ["轨道慢推", "跟焦跟拍", "变焦推镜"],
    "神秘":  ["左摇镜", "右摇镜", "仰拍旋摇"],
    "悸动":  ["变焦推镜", "阶梯推镜", "低机位前推"],
    "幽默":  ["跟焦跟拍", "轨道慢推", "左环摇"],
    "无奈":  ["缓慢拉镜", "变焦拉镜", "俯拍旋摇"],
    "得意":  ["仰拍旋摇", "低机位前推", "左环摇"],
    "惊讶":  ["急速推镜", "特写切远景快拉", "变焦推镜"],
    "困惑":  ["左摇镜", "阶梯推镜", "变焦推镜"],
    "平静":  ["轨道慢推", "跟焦跟拍", "固定镜头"],
}

# 强度→镜头距离映射
_INTENSITY_DISTANCE_MAP = {
    1: "全景",    # 情绪极低：远距离建立场景
    2: "全景",
    3: "中景",    # 情绪低：中等距离
    4: "中景",
    5: "中景",    # 情绪中等：平衡
    6: "近景",    # 情绪偏高：拉近
    7: "近景",
    8: "特写",    # 情绪高：极近
    9: "特写",
    10: "特写",   # 情绪爆表：极特写
}

# 景别→焦距&机位
_DISTANCE_PARAMS = {
    "全景": {"focal": "20mm", "height": "3.0m"},
    "中景": {"focal": "50mm", "height": "1.5m"},
    "近景": {"focal": "85mm", "height": "1.2m"},
    "特写": {"focal": "135mm", "height": "1.0m"},
}


def _auto_select_camera(scene, job=None) -> dict:
    """v9.10: 根据场景上下文自动选择最佳运镜（即梦蒸馏）

    选择逻辑：
    1. 如果 scene.camera 已设置且有效，使用用户指定的
    2. 否则根据 mood + intensity + description 自动推荐
    3. 返回带参数的运镜描述
    """
    camera_cn = getattr(scene, 'camera', '') or ''
    mood = getattr(scene, 'mood', '') or ''
    intensity = getattr(scene, 'emotional_intensity', 5) or 5
    description = getattr(scene, 'description', '') or ''

    # 用户指定了镜头 → 优先使用
    if camera_cn:
        # 尝试匹配预设
        for preset_name in _CAMERA_PRESETS:
            if preset_name in camera_cn:
                return _CAMERA_PRESETS[preset_name]
        # 复合镜头：逐词匹配
        cam_parts = []
        for part in camera_cn.replace("·", ".").split("."):
            part = part.strip()
            for preset_name in _CAMERA_PRESETS:
                if preset_name == part or preset_name in part:
                    cam_parts.append(preset_name)
        if cam_parts:
            return _CAMERA_PRESETS[cam_parts[0]]
        # 无法匹配 → 返回简单描述
        simple = _CAMERA_MAP_SIMPLE.get(camera_cn, "slow push in, cinematic camera movement")
        return {"type": "custom", "desc": simple}

    # 自动推荐
    candidates = _MOOD_CAMERA_MAP.get(mood, ["轨道慢推", "跟焦跟拍"])

    # 根据 intensity 从候选中选择
    if intensity >= 7:
        pick = candidates[0]  # 最剧烈的
    elif intensity >= 4:
        pick = candidates[1] if len(candidates) > 1 else candidates[0]
    else:
        pick = candidates[-1] if len(candidates) > 1 else candidates[0]

    if pick in _CAMERA_PRESETS:
        return _CAMERA_PRESETS[pick]

    # 根据画面描述中的关键词推测
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in ['推', '近', 'push', 'close']):
        pick = "轨道慢推"
    elif any(kw in desc_lower for kw in ['拉', '远', 'pull', 'wide', '全景']):
        pick = "高机位后拉"
    elif any(kw in desc_lower for kw in ['环', '转', 'orbit', 'rotate', '围绕']):
        pick = "左环摇"
    elif any(kw in desc_lower for kw in ['跟', '追', 'track', 'follow']):
        pick = "跟焦跟拍"

    return _CAMERA_PRESETS.get(pick, _CAMERA_PRESETS["轨道慢推"])


# ─── P0-③: 多样化运镜调度器 ──────────────────────────
# 6 种景别 + 8 种运镜类型，强制相邻场景不重复
_SHOT_SIZES = ["全景", "中景", "近景", "特写", "中景", "全景"]  # 平衡节奏
_MOVEMENT_TYPES = ["push", "pull", "pan", "tilt", "orbit", "track", "zoom", "static"]


def _diversify_cameras_for_scenes(scenes: list) -> None:
    """P0-③: 批量给所有场景分配镜头，强制：
    1. 相邻场景景别不重复（避免节奏雷同）
    2. 同类型运镜连续不超过 2 次
    3. 开篇用全景建立场景，收尾用近景/特写做情绪落点
    """
    if not scenes:
        return

    # 景别节奏：开篇全景，结尾近景/特写
    n = len(scenes)
    rhythm = []
    if n <= 4:
        # 短剧：全景→中景→近景→特写 渐入式
        rhythm = ["全景", "中景", "近景", "特写"][:n]
    else:
        # 长剧：螺旋上升 + 情绪落点
        for i in range(n):
            # 7 段节奏循环
            r = ["全景", "中景", "近景", "中景", "特写", "近景", "中景"]
            rhythm.append(r[i % len(r)])

    # 强制收尾用近景/特写
    if n >= 2:
        rhythm[-1] = "近景" if n % 2 == 0 else "特写"

    prev_shot = None
    prev_movement = None
    for i, scene in enumerate(scenes):
        # 1) 确定景别
        target_shot = rhythm[i] if i < len(rhythm) else "中景"
        # 强制不重复
        if target_shot == prev_shot:
            # 在 4 种里换
            alts = [s for s in ["全景", "中景", "近景", "特写"] if s != prev_shot]
            target_shot = alts[i % len(alts)]
        prev_shot = target_shot
        scene.shot_size = target_shot

        # 2) 确定运镜（基于 mood + intensity + shot_size）
        mood = getattr(scene, "mood", "") or ""
        intensity = getattr(scene, "emotional_intensity", 5) or 5
        candidates = _MOOD_CAMERA_MAP.get(mood, ["轨道慢推", "跟焦跟拍", "固定镜头"])

        # 选一个跟 prev_movement 不同的
        chosen = None
        for cand in candidates:
            movement = _CAMERA_PRESETS.get(cand, {}).get("type", "")
            if movement != prev_movement:
                chosen = cand
                break
        if not chosen:
            chosen = candidates[0]

        prev_movement = _CAMERA_PRESETS.get(chosen, {}).get("type", "")
        scene.camera = chosen

        # 3) 写入 description 后缀（确保 ComfyUI 看到）
        cam_desc = _CAMERA_PRESETS.get(chosen, {}).get("desc", "")
        dist_params = _DISTANCE_PARAMS.get(target_shot, {"focal": "50mm", "height": "1.5m"})

        # 构造完整镜头指令附加到 description
        camera_directive = f"[{target_shot}|{chosen}]"
        if hasattr(scene, "description") and scene.description:
            # 避免重复
            if camera_directive not in scene.description:
                scene.description = f"{scene.description} {camera_directive}"
        else:
            scene.description = camera_directive

    print(f"[Camera] P0-③ 多样化运镜调度完成: {len(scenes)} 场景，"
          f"景别节奏={[s.shot_size for s in scenes]}", flush=True)


# ─── P2-⑫: 红果金币/广告位自动定位 ──────────────────────────
_COIN_INSERTION_THRESHOLD = 7  # intensity >= 7 视为高潮/冲突点


def _mark_coin_insertion_points(scenes: list) -> list[dict]:
    """P2-⑫: 自动检测高潮/冲突场景，标记为红果金币/广告插入点
    返回 [{"scene_id": int, "intensity": int, "time_pos": float, "type": str}, ...]
    """
    if not scenes:
        return []

    insertion_points = []
    cumulative = 0.0

    for scene in scenes:
        intensity = getattr(scene, "emotional_intensity", 5) or 5
        dur_str = getattr(scene, "duration", "5s") or "5s"
        try:
            dur = float(str(dur_str).rstrip("s").strip() or 5.0)
        except (ValueError, TypeError):
            dur = 5.0

        if intensity >= _COIN_INSERTION_THRESHOLD:
            insertion_points.append({
                "scene_id": scene.id,
                "intensity": intensity,
                "time_pos": cumulative,
                "duration": dur,
                "type": "coin_reward" if intensity >= 8 else "hook_climax",
            })
            scene._coin_point = True  # 标记

        cumulative += dur

    if insertion_points:
        print(f"[Coin] P2-⑫ 标记 {len(insertion_points)} 个高潮点（intensity≥{_COIN_INSERTION_THRESHOLD}）", flush=True)
        for p in insertion_points[:5]:
            print(f"  - 场景{p['scene_id']} @ {p['time_pos']:.1f}s intensity={p['intensity']} type={p['type']}", flush=True)
    else:
        print(f"[Coin] P2-⑫ 未检测到高潮点（intensity<{_COIN_INSERTION_THRESHOLD}）", flush=True)

    return insertion_points


async def _insert_coin_card(
    video_path: str,
    output_path: str,
    insertion_time: float = 5.0,
    duration: float = 3.0,
) -> str:
    """P2-⑫: 在指定时间点插入 3 秒金币/广告位引导卡
    - 渐变红色背景
    - "点击下方领取" + 金币图标 emoji 🪙
    - 完成后自动消失
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(video_path).exists():
        if Path(video_path).exists():
            shutil.copy2(video_path, output_path)
        return output_path

    fontfile = "C:/Windows/Fonts/msyhbd.ttc"
    if not Path(fontfile).exists():
        fontfile = "C:/Windows/Fonts/msyh.ttc"
    fontfile_esc = fontfile.replace("\\", "/").replace(":", "\\:")

    # 渐变红色背景 + 文字
    drawtext_chain = [
        f"drawtext=fontfile='{fontfile_esc}':text='🪙 点击下方领取':"
        f"fontcolor=yellow:fontsize=64:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-40:"
        f"box=1:boxcolor=red@0.6:boxborderw=30",
        f"drawtext=fontfile='{fontfile_esc}':text='看视频领金币 · 不容错过':"
        f"fontcolor=white:fontsize=32:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+50"
    ]
    drawtext_filter = ",".join(drawtext_chain)

    # 生成 3 秒红色引导卡
    coin_path = output_path + ".coin_tmp.mp4"
    cmd_coin = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=0xcc0000:s=1080x1920:d={duration}",
        "-vf", drawtext_filter,
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-crf", "18", "-an",
        coin_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_coin,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
    except Exception as e:
        print(f"[Coin] 引导卡生成失败: {e}", flush=True)
        shutil.copy2(video_path, output_path)
        return output_path

    if not Path(coin_path).exists():
        shutil.copy2(video_path, output_path)
        return output_path

    # 拼接：[原视频前段] + [引导卡] + [原视频后段]
    # 先切分原视频
    part1 = output_path + ".p1.mp4"
    part2 = output_path + ".p2.mp4"
    try:
        # 前段
        proc1 = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-i", video_path, "-t", str(insertion_time),
            "-c:v", "libx264", "-preset", "ultrafast", part1,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc1.communicate(), timeout=120)
        # 后段
        proc2 = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-ss", str(insertion_time), "-i", video_path,
            "-c:v", "libx264", "-preset", "ultrafast", part2,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc2.communicate(), timeout=120)
    except Exception as e:
        print(f"[Coin] 切分视频失败: {e}", flush=True)
        for p in [part1, part2, coin_path]:
            Path(p).unlink(missing_ok=True)
        shutil.copy2(video_path, output_path)
        return output_path

    # concat 三段
    concat_list = output_path + ".concat.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for seg in [part1, coin_path, part2]:
            f.write(f"file '{Path(seg).as_posix()}'\n")

    cmd_concat = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-crf", "18", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_concat,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
    except Exception as e:
        print(f"[Coin] concat 失败: {e}", flush=True)

    # 清理
    for p in [part1, part2, coin_path, concat_list]:
        Path(p).unlink(missing_ok=True)

    if Path(output_path).exists() and Path(output_path).stat().st_size > Path(video_path).stat().st_size * 0.9:
        print(f"[Coin] P2-⑫ 引导卡已插入 @ {insertion_time:.1f}s: {output_path}", flush=True)
        return output_path
    else:
        shutil.copy2(video_path, output_path)
        return output_path



_EXPRESSION_BY_MOOD = {
    "紧张": "furrowed brows, tense jaw, slight frown, alert expression",
    "恐惧": "wide eyes, slightly open mouth, raised brows, fearful look",
    "愤怒": "angry brows, clenched jaw, narrowed eyes, intense glare",
    "悲伤": "drooping mouth corners, soft eyes, downturned brows, melancholic",
    "喜悦": "slight smile, bright eyes, relaxed brows, joyful expression",
    "温馨": "gentle smile, soft eyes, relaxed face, warm expression",
    "释然": "subtle smile, soft relaxed face, calm eyes",
    "热血": "determined expression, intense eyes, slight grin, focused",
    "压抑": "subtle pain in eyes, slight frown, closed lips",
    "壮阔": "awe-struck expression, slightly open mouth, wide eyes",
    "神秘": "half-smile, slight squint, knowing look, mysterious",
    "悸动": "blushing cheeks, soft gaze, slight smile, fluttering eyes",
    "幽默": "playful smile, raised eyebrow, smirk, amused",
    "无奈": "sigh expression, half-smile, soft eyes, resigned",
    "得意": "smug grin, raised chin, confident smile",
    "惊讶": "wide open eyes, raised brows, slightly open mouth",
    "困惑": "puzzled expression, tilted head, raised brow",
    "平静": "neutral calm expression, relaxed face, soft gaze",
    "孤独": "distant gaze, melancholic eyes, isolated expression",
    "惆怅": "distant gaze, slightly downturned mouth, wistful",
    "亲密": "loving gaze, soft smile, tender expression, gentle",
}


def _inject_expression_to_prompt(scene) -> None:
    """P2-⑪: 根据 mood 注入面部表情控制词到 description
    注：与 _diversify_cameras_for_scenes 写的 [景别|运镜] 不冲突，追加到末尾
    """
    mood = getattr(scene, "mood", "") or ""
    expression = _EXPRESSION_BY_MOOD.get(mood)
    if not expression:
        return

    # 检查是否已注入
    if "[EXP:" in (getattr(scene, "description", "") or ""):
        return

    tag = f"[EXP:{mood}→{expression[:40]}]"
    desc = getattr(scene, "description", "") or ""
    if tag not in desc:
        scene.description = f"{desc} {tag}".strip()

    # 同时给 camera_prompt 也注入
    cam_prompt = getattr(scene, "camera_prompt", "") or ""
    if cam_prompt and expression not in cam_prompt:
        scene.camera_prompt = f"{cam_prompt}, {expression}"



_POV_KEYWORDS = {
    "我看到", "我听见", "我感到", "我意识到", "我猛然",
    "眼前", "视野", "视线", "映入眼帘", "出现在我", "我低头", "我抬头",
    "我转身", "我扭头", "我看着", "我望着", "我盯着", "我握紧",
    "我攥紧", "我心跳", "我呼吸", "我心里", "我眼中",
    "I saw", "I heard", "I felt", "my view", "my eyes", "I looked",
    "before me", "I turned", "I realized",
}
_POV_PREFERRED_CAMERAS = ["特写", "近景", "跟焦跟拍", "轨道慢推", "低机位前推"]


def _detect_pov_scenes(scenes: list) -> None:
    """P2-⑩: 检测 POV 主观镜头
    - 场景描述含第一人称视角关键词 → 标记 pov=True
    - 强制使用 POV 推荐的运镜（前推/特写/跟拍）
    - 在 description 后追加 [POV] 标记给 ComfyUI
    """
    if not scenes:
        return

    count = 0
    for scene in scenes:
        desc = getattr(scene, "description", "") or ""
        subtitle = getattr(scene, "subtitle_text", "") or ""
        full_text = desc + " " + subtitle

        is_pov = any(kw in full_text for kw in _POV_KEYWORDS)

        if is_pov:
            scene.pov = True
            count += 1

            # 强制用 POV 推荐运镜
            current_cam = getattr(scene, "camera", "") or ""
            if current_cam not in _POV_PREFERRED_CAMERAS:
                # 改成"跟焦跟拍"（最通用的 POV 镜头）
                scene.camera = "跟焦跟拍"
                if scene.description and "[POV]" not in scene.description:
                    scene.description = f"[POV] {scene.description}"
                elif not scene.description:
                    scene.description = "[POV]"

    print(f"[POV] P2-⑩ POV 主观镜头识别: {count}/{len(scenes)} 个场景", flush=True)



_HOOK_TEMPLATES = [
    "close-up of character's shocked face",
    "character reaching for something urgently",
    "tense dialogue in progress, mid-conversation",
    "dramatic confrontation, eye contact with rival",
    "mysterious object in foreground, character in background",
    "split second before action begins",
    "tears falling / 眼泪滑落",
    "hand grabbing wrist aggressively",
    "sword pointing at throat",
    "door bursting open",
]

_REVERSAL_KEYWORDS = {
    "突然": 1, "但是": 1, "然而": 1, "却": 0.5, "不料": 1, "竟": 1,
    "原来": 1, "只见": 0.5, "没想到": 1, "可": 0.5, "谁知": 1, "岂料": 1,
    "suddenly": 1, "but": 0.5, "however": 1, "unexpectedly": 1, "yet": 0.5,
}


def _apply_opening_hook(scenes: list) -> None:
    """P1-⑤: 第一个场景强制用冲突/动作/对白开头，禁止环境建立。
    改写第一个 scene 的 description 和 prompt，注入"开篇钩子"模板。
    """
    if not scenes:
        return

    first = scenes[0]
    desc = getattr(first, "description", "") or ""

    # 检测首句是否冲突型（前 30 字内含"突然/但是/却/原来/suddenly"等）
    first_30 = desc[:30]
    is_hook = any(kw in first_30 for kw in _REVERSAL_KEYWORDS.keys())

    if is_hook:
        return  # 已经是冲突型开头，跳过

    # 选择一个钩子模板
    import random
    hook = random.choice(_HOOK_TEMPLATES)

    # 改写 description
    if desc:
        first.description = f"[OPENING HOOK: {hook}] {desc}"
    else:
        first.description = f"[OPENING HOOK: {hook}]"

    print(f"[Hook] P1-⑤ 第一个场景已注入开篇钩子: {hook}", flush=True)


def _check_reversal_points(scenes: list) -> None:
    """P1-⑥: 检查每 8-15 秒是否包含反转/疑问/冲突点。
    如果连续 8s 场景无反转关键词，自动标记该场景需要补一个微反转。
    """
    if not scenes:
        return

    # 累加时长
    cumulative = 0.0
    last_reversal_pos = 0.0
    issues = []

    for i, scene in enumerate(scenes):
        dur_str = getattr(scene, "duration", "5s") or "5s"
        try:
            dur = float(str(dur_str).rstrip("s").strip() or 5.0)
        except (ValueError, TypeError):
            dur = 5.0

        desc = (getattr(scene, "description", "") or "") + \
               (getattr(scene, "subtitle_text", "") or "")

        # 计算该场景反转强度
        reversal_score = sum(_REVERSAL_KEYWORDS.get(kw, 0)
                             for kw in _REVERSAL_KEYWORDS
                             if kw in desc)

        gap = cumulative - last_reversal_pos
        if gap >= 8.0 and reversal_score < 0.5:
            issues.append((i, cumulative, gap, scene))
            scene._needs_reversal = True  # 标记

        if reversal_score >= 0.5:
            last_reversal_pos = cumulative

        cumulative += dur

    if issues:
        print(f"[Reversal] P1-⑥ 发现 {len(issues)} 个场景缺乏反转点（8s+）: "
              f"{[i+1 for i, _, _, _ in issues[:5]]}", flush=True)
        # 自动注入微反转
        for i, t, gap, scene in issues:
            micro_hook = random.choice([
                "突然，", "就在这时，", "不料，", "可是，", "没想到，",
            ])
            if not scene.description.startswith(micro_hook):
                scene.description = f"{micro_hook}{scene.description or ''}"
            scene._needs_reversal = False
    else:
        print(f"[Reversal] P1-⑥ 全部场景反转点合格 ✓", flush=True)


def _compute_dynamic_durations(scenes: list) -> None:
    """P1-⑦: 动态场景时长：情绪→时长映射
    - 紧张/恐惧/愤怒/热血: 6-8s（拉长压迫感）
    - 喜悦/温馨/释然: 3-4s（轻盈）
    - 悲伤/压抑/惆怅: 4-5s（中等）
    - 高潮（intensity>=8）: 7-8s
    - 过渡（intensity<=3）: 1.5-2.5s
    - 对白场景: 默认 4s
    """
    import random
    if not scenes:
        return

    _DURATION_BY_MOOD = {
        "紧张": (6, 8), "恐惧": (6, 8), "愤怒": (6, 8), "热血": (5, 7),
        "喜悦": (3, 4), "温馨": (3, 5), "释然": (3, 4), "幽默": (2, 4),
        "悲伤": (4, 5), "压抑": (4, 6), "惆怅": (4, 5), "孤独": (4, 6),
        "壮阔": (5, 7), "神秘": (4, 6), "悸动": (3, 5), "无奈": (3, 4),
        "惊讶": (3, 4), "困惑": (3, 4), "平静": (3, 5), "得意": (4, 5),
    }

    for scene in scenes:
        mood = getattr(scene, "mood", "") or "平静"
        intensity = getattr(scene, "emotional_intensity", 5) or 5

        # 优先按情绪
        if mood in _DURATION_BY_MOOD:
            lo, hi = _DURATION_BY_MOOD[mood]
        else:
            lo, hi = (3, 5)

        # intensity 极端值覆盖
        if intensity >= 8:
            lo, hi = max(lo, 6), max(hi, 8)
        elif intensity <= 3:
            lo, hi = min(lo, 2.5), min(hi, 3.5)

        # 边界保护
        lo = max(1.0, lo)
        hi = max(lo, min(10.0, hi))

        scene.duration = f"{random.uniform(lo, hi):.1f}s"

    print(f"[Duration] P1-⑦ 动态时长已应用: "
          f"{[s.duration for s in scenes[:8]]}", flush=True)


def _build_camera_prompt(camera_cn: str) -> str:
    """v9.10: 参数化运镜prompt生成（即梦蒸馏）

    升级为参数化描述：速度/焦段/机位/角度等工程参数
    """
    if not camera_cn:
        return "slow push in, camera dolly 0.8m/s, 50mm focal length, 1.5m height, cinematic camera movement"

    # 尝试精确匹配预设
    if camera_cn in _CAMERA_PRESETS:
        return _CAMERA_PRESETS[camera_cn]["desc"]

    # 复合镜头：拆分匹配
    for part in camera_cn.replace("·", ".").split("."):
        part = part.strip()
        if part in _CAMERA_PRESETS:
            return _CAMERA_PRESETS[part]["desc"]

    # 向后兼容：简单映射
    for cn, en in _CAMERA_MAP_SIMPLE.items():
        if cn in camera_cn:
            return en

    return "slow push in, camera dolly 0.8m/s, 50mm focal length, cinematic camera movement"


def _generate_camera_motion(scene, job=None) -> str:
    """v9.10: 完整的镜头运动生成（即梦蒸馏最高层接口）

    结合自动选择 + 参数化描述，返回最终 video prompt 中使用的镜头运动文本。
    """
    camera = _auto_select_camera(scene, job)
    desc = camera.get("desc", "slow push in, cinematic camera movement")

    # 根据 intensity 添加景深控制
    intensity = getattr(scene, 'emotional_intensity', 5) or 5
    if intensity >= 7:
        desc += ", shallow depth of field, background heavily blurred, subject isolation"
    elif intensity <= 3:
        desc += ", deep depth of field, everything in focus, wide context"

    # 添加节奏注释
    if intensity >= 8:
        desc += ", rapid camera rhythm, fast cuts pace"
    elif intensity <= 3:
        desc += ", slow meditative pace, lingering camera"

    return desc


# ─── v8.3 提示词清理 + 多镜头系统 ──────────────────────────────

_ANIME_POLLUTION = [
    "anime style", "manhwa art style", "webtoon art style", "manga style",
    "cel shading", "clean crisp line art", "clean line art",
    "vibrant saturated colors", "vibrant colors",
    "digital illustration", "commercial anime quality",
    "trending on pixiv", "trending on artstation",
    "(perfect face:1.1)", "(perfect hands:1.2)",
]

_CINEMATIC_REPLACEMENT = [
    "cinematic realism, photorealistic rendering, atmospheric cinematography",
    "film grain, natural color grading, professional movie lighting",
]

def _prompt_has_human_subject(prompt: str) -> bool:
    """v12.1-fix-2: 检测 image_prompt 是否明确描述人物/人脸/肖像。
    用于避免 scene.characters 为空（如强制 Ken Burns 路由）时，系统仍向反向提示词
    注入 (face:1.5)/(person:1.6) 等强人物禁止项，与正向提示词冲突导致画面花屏。
    """
    if not prompt:
        return False
    prompt_lower = prompt.lower()
    human_indicators = [
        "portrait", "face", "facial", "man", "woman", "person", "people",
        "human", "elderly", "old man", "old woman", "lighthouse keeper",
        "特写", "人脸", "肖像", "老人", "男人", "女人", "人物"
    ]
    return any(h in prompt_lower for h in human_indicators)

def _clean_image_prompt(prompt: str, scene=None, job=None) -> str:
    """v8.7: 清理 image_prompt 风格污染 + 场景类型感知增强
    - 移除 anime/manhwa 污染词
    - 根据场景是否有角色，强制添加/禁止人物描述
    - 确保纯环境场景不出现人物
    - v9.8: 增加 folk_horror 风格专属清理"""
    import re
    if not prompt:
        return prompt
    cleaned = prompt
    style = getattr(job, 'style', 'cinematic') or 'cinematic'

    # v9.9: 只在非 anime 风格时移除 anime 污染词；anime 风格下保留
    if style != "anime":
        for term in _ANIME_POLLUTION:
            cleaned = cleaned.replace(term, "")

    # v9.8: folk_horror 风格下清理与中式恐怖冲突的标签
    if style == "folk_horror":
        folk_conflicts = [
            "wuxia fantasy art", "wuxia period drama aesthetic", "xianxia",
            "pixiv", "artstation", "bright colors", "cheerful atmosphere",
            "vibrant", "pastel", "kawaii", "chibi", "cartoon",
            "anime", "manhwa", "manga", "western architecture",
            "art nouveau", "gothic cathedral", "european style",
            "skull", "skeleton", "cranium", "giant skull",
        ]
        for term in folk_conflicts:
            cleaned = re.sub(re.escape(term), "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r',\s*,', ',', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    cleaned = cleaned.strip().strip(',').strip()
    # v8.6: 移除短prompt保护（Bug5修复），总执行清理避免anime泄漏
    
    # v8.7: 动态获取角色名列表
    all_char_names = _get_character_names(job)
    
    # v8.5: 场景类型感知 — 无人物场景强制禁止人物
    has_characters = False
    if scene:
        chars = getattr(scene, 'characters', '') or ''
        speaking = getattr(scene, 'speaking_characters', []) or []
        # Bug1修复: 多种"无角色"格式统一检测
        no_char_markers = ["无", "无角色", "本镜未出场", "未出场", "环境开场"]
        has_chars_str = bool(chars) and not any(m in chars for m in no_char_markers)
        has_speaking = bool(speaking) and any(s.strip() and s.strip() != "无" for s in speaking)
        # v8.7: 从all_char_names动态提取中文名检测
        _chinese_names = [n for n in all_char_names if len(n) <= 4 and any('\u4e00' <= c <= '\u9fff' for c in n)]
        has_named = any(name in str(speaking) for name in _chinese_names)
        has_characters = has_chars_str or has_speaking or has_named

    # v12.1-fix-2: 即使 scene.characters 为空（常用于强制 Ken Burns 路由），
    # 若 image_prompt 本身明确描述人物/人脸/肖像，也不注入 no_human 约束，
    # 否则会出现"画人脸 + 禁止人脸"的矛盾提示词，导致画面花屏。
    if not has_characters and _prompt_has_human_subject(cleaned):
        has_characters = True
        print(f"[PromptClean] 场景含人物描述词，忽略空 characters 标记，不注入 no_human: {scene.id if scene else '?'}", flush=True)

    if not has_characters:
        # 纯环境场景：禁止人物出现
        no_human = "no humans, no people, no person, no face, no portrait, empty scene, focus on environment and atmosphere only"
        # 移除 prompt 中可能的角色描述（如人名、外貌词）
        for name in all_char_names:
            cleaned = cleaned.replace(name, '')
        cleaned = f"{no_human}, {cleaned}"
        # 清理后追加重申
        cleaned += ", absolutely no human presence, pure environmental photography"
    
    if "cinematic" not in cleaned.lower():
        cleaned += ", cinematic composition, filmic atmosphere"
    return cleaned


# v8.5: 基础角色名列表（用于清理无角色场景prompt的通用描述词）
_BASE_CHARACTER_NAMES = [
    # 通用外观描述（这些是风格描述，需要保留）
    "young man", "black hair", "amber eyes", "fair skin",
    "wearing an apron", "holding a bamboo", "holding bamboo",
    "wearing dark", "wearing robe", "wearing long",
]

def _get_character_names(job=None):
    """v8.7: 动态获取角色名列表 — 合并基础通用词和job中的角色名"""
    names = list(_BASE_CHARACTER_NAMES)
    if job and hasattr(job, 'characters') and job.characters:
        for c in job.characters:
            if c.name and c.name not in names:
                names.append(c.name)
    return names


def _get_scene_environment(scene, job) -> dict | None:
    """v9.4: 根据场景 setting 匹配 job.environment_analysis 中的环境信息。
    
    统一的环境匹配工具函数，消除 _build_fallback_image_prompt、
    _extract_vmix_tags 等多处重复的循环匹配代码。
    
    返回匹配的 environment dict，无匹配时返回 None。
    """
    if not job or not job.environment_analysis:
        return None
    envs = job.environment_analysis.get('environments', [])
    if not envs:
        return None
    scene_setting = (getattr(scene, 'setting', '') or '').strip()
    if not scene_setting:
        return None
    for env in envs:
        env_name = (env.get('name', '') or '').strip()
        if env_name and (env_name in scene_setting or scene_setting in env_name):
            return env
    return None


async def _build_fallback_image_prompt(scene, global_character_desc: str = "", job=None) -> str:
    """
    v7.1 Seedream蒸馏 — 图像提示词生成逻辑
    模仿即梦(Seedream)的 LLM 改写流程: 中文场景 → DeepSeek → 专业英文prompt
    
    三步策略:
    1. DeepSeek 改写整个场景为英文prompt (即梦同款LLM翻译)
    2. 失败则回退到 400词条逐词翻译
    3. VMix 结构化标签始终前置
    
    顺序设计原理：
    - SD/SDXL 对前置 token 权重更高
    - [color][lighting][composition] 第一优先级  
    - 场景环境 + 动作内容 第二优先级
    - 角色外貌 第三优先级
    """
    parts = []
    
    # v7.0: VMix 结构化美学前缀 (最高优先级)
    vmix_tags = _extract_vmix_tags(scene, job)
    if vmix_tags:
        parts.append(vmix_tags)
    
    # v7.1: 即梦蒸馏 — DeepSeek 改写中文场景为完整英文prompt
    scene_desc_en = ""
    if scene.description and job:
        # v9.4: 注入环境分析中的 atmosphere 和 key_props 到 DeepSeek 改写上下文
        env_atmo = ""
        env_props = ""
        env_match = _get_scene_environment(scene, job)
        if env_match:
            env_atmo = env_match.get('atmosphere', '') or ''
            env_props = env_match.get('key_props', '') or ''
        
        scene_ctx = {
            "setting": scene.setting or "",
            "mood": scene.mood or "",
            "camera": scene.camera or "",
            "characters": scene.characters or "",
            "atmosphere": env_atmo,          # v9.4: 环境级氛围（与场景 mood 互补）
            "key_props": env_props,          # v9.4: 标志性物体
        }
        scene_desc_en = await _deepseek_prompt_rewrite(scene.description, scene_ctx)
        if scene_desc_en and len(scene_desc_en) > 30:
            parts.append(scene_desc_en)
    
    # v6.2: 如果传入 job，自动获取角色一致性描述
    if job is not None:
        auto_char_desc = _build_global_character_desc(job)
        if auto_char_desc:
            global_character_desc = auto_char_desc
        
        # v9.4: 环境一致性描述 — 注入原名 + 新增 weather/time_period/scale/key_props
        env_match = _get_scene_environment(scene, job)
        if env_match:
            env_parts = []
            # description
            env_desc = env_match.get('description', '')
            if env_desc:
                translated = _translate_to_english_keywords(env_desc[:200])
                if translated:
                    env_parts.append(translated)
            # atmosphere (中文氛围词，让 DeepSeek 或后续处理整合)
            env_atmosphere = env_match.get('atmosphere', '')
            if env_atmosphere:
                env_parts.append(env_atmosphere)
            # v9.4: 时间段
            env_time = env_match.get('time_period', '')
            TIME_EN = {
                "dawn": "dawn, golden sunrise, early morning light",
                "morning": "morning, bright daylight",
                "noon": "noon, harsh midday sun, strong shadows",
                "afternoon": "afternoon, warm golden hour approaching",
                "dusk": "dusk, twilight, dramatic sunset sky",
                "night": "night scene, dark, moonlit",
            }
            if env_time and env_time in TIME_EN:
                env_parts.append(TIME_EN[env_time])
            # v9.4: 天气
            env_weather = env_match.get('weather', '')
            if env_weather and env_weather.strip() not in ('', 'N/A', '未提及', '无'):
                env_parts.append(env_weather.strip())
            # v9.4: 空间尺度
            env_scale = env_match.get('scale', '')
            SCALE_EN = {
                "epic": "epic scale, grand vast architecture",
                "large": "large spacious environment",
                "medium": "medium scale",
                "small": "small confined space",
                "intimate": "intimate close quarters",
            }
            if env_scale and env_scale in SCALE_EN:
                env_parts.append(SCALE_EN[env_scale])
            # v9.4: 标志性道具
            env_props = env_match.get('key_props', '')
            if env_props and env_props.strip() not in ('', '无', 'N/A', '未提及'):
                env_parts.append(env_props.strip())
            
            if env_parts:
                parts.append(", ".join([p for p in env_parts if p]))
    
    # DeepSeek改写未成功, 回退到逐词翻译
    if not scene_desc_en or len(scene_desc_en) < 30:
        if scene.setting:
            setting_en = _translate_to_english_keywords(scene.setting)
            if setting_en:
                parts.append(setting_en)
        if scene.description:
            desc_en = _translate_to_english_keywords(scene.description)
            if desc_en:
                parts.append(desc_en)

    # Layer 3: 本场景角色外貌
    scene_char = _parse_scene_character(scene, global_character_desc)
    if scene_char:
        parts.append(scene_char)

    # v12.0: 角色着装一致性 — 强制注入出场角色的着装描述
    if job is not None:
        clothing_desc = _get_character_clothing_desc(job, scene)
        if clothing_desc:
            parts.append(clothing_desc)

    # Layer 4: 情绪氛围
    mood_map = {
        "紧张": "tense atmosphere, dramatic lighting",
        "温馨": "warm cozy atmosphere, soft golden lighting",
        "悲伤": "melancholic sorrowful mood, desaturated colors",
        "壮阔": "epic grand scenery, majestic scale",
        "神秘": "mysterious atmosphere, fog and shadows",
        "热血": "passionate energetic motion blur, dynamic angle",
        "恐惧": "fearful terrifying atmosphere, dark ominous tones",
        "喜悦": "joyful happy warm bright colors",
        "惆怅": "wistful melancholic mood, soft fading light",
        "愤怒": "angry intense red tones, high contrast",
        "压抑": "oppressive dark confined space, low key lighting",
        "释然": "relieved peaceful morning light, open composition",
        "宁静": "peaceful serene calm ambient",
        "诡异": "eerie uncanny unsettling atmosphere",
    }
    if scene.mood:
        parts.append(mood_map.get(scene.mood, f"{scene.mood} mood, cinematic atmosphere"))

    # ═══ Layer 5: 镜头语言 ═══
    camera_map = {
        "特写": "extreme close-up, face filling frame, shallow depth of field",
        "超特写": "macro detail shot, extreme close-up on object or eyes",
        "近景": "medium close-up, chest up, intimate framing",
        "中景": "medium shot, waist up, balanced composition",
        "全景": "full body shot, wide environmental context",
        "远景": "wide establishing shot, figure small in environment, scale",
        "俯拍": "high angle bird's eye view, looking down",
        "仰拍": "low angle hero shot, looking up, dramatic perspective",
        "跟随镜头": "tracking shot following subject, motion blur background",
        "慢推": "slow dolly push in, gradually closing distance",
        "慢拉": "slow dolly pull back, revealing context",
        "过肩镜头": "over the shoulder shot, depth and layering",
        "主观视角": "POV first person view, immersive",
    }
    parts.append(camera_map.get(scene.camera, "cinematic medium shot"))

    # ═══ Layer 6: 光线设计 ═══
    intensity = getattr(scene, 'emotional_intensity', 5)
    if intensity >= 8:
        parts.append("dramatic chiaroscuro lighting, high contrast")
    elif intensity >= 6:
        parts.append("cinematic directional lighting, volumetric")
    elif intensity <= 3:
        parts.append("soft diffused gentle lighting, even illumination")
    else:
        parts.append("natural cinematic lighting, atmospheric")

    # ═══ Layer 7: 质量+风格（根据 job.style 动态选择，不再硬编码 anime）═══
    quality = "masterpiece, best quality, highly detailed"
    style = getattr(job, 'style', 'cinematic') if job else 'cinematic'
    style_suffix = _get_style_image_suffix(style)
    parts.append(f"{quality}, {style_suffix}")

    return ", ".join([p for p in parts if p])


def _parse_scene_character(scene, global_desc: str) -> str:
    """
    从本场景的 characters 字段提取出场角色的英文外貌描述。
    优先使用场景级具体外貌（含动作/表情），其次用全局角色表兜底。
    """
    import re as _re

    # 优先：从本场景的 characters 字段提取具体外貌+动作
    raw_chars = getattr(scene, 'characters', '') or ''
    if raw_chars and raw_chars not in ('无', '', 'None'):
        brackets = _re.findall(r'\[([^\]]+)\]', raw_chars)
        if brackets:
            en_parts = []
            for b in brackets:
                translated = _translate_to_english_keywords(b)
                if translated:
                    en_parts.append(translated)
            if en_parts:
                return ", ".join(en_parts)

    # 兜底：使用全局角色描述（已纯英文化）
    if global_desc and global_desc.strip():
        return global_desc.strip()

    return ""


def _translate_to_english_keywords(chinese_text: str) -> str:
    """
    将中文描述快速转为英文关键词。
    使用简单字典匹配 +启发式规则，不依赖外部API。
    返回空字符串表示无法翻译。
    """
    import re as _re

    # 常见视觉关键词映射（v5.5 扩充至120+词条，覆盖传统中国/恐怖/现代等多种题材）
    # v6.3 扩充：从 200+ 词条扩展到 400+ 词条
    # 新增：红果漫剧高频术语
    visual_dict = {
        # ═══ 角色外貌（精细分类）═══
        "双瞳": "dual-colored heterochromia eyes, left and right eye different colors",
        "凤眼": "phoenix eyes, upturned almond eyes, elegant eye shape",
        "桃花眼": "peach blossom eyes, alluring bedroom eyes, seductive gaze",
        "丹凤眼": "slanted phoenix eyes, sharp narrow eyes",
        "杏眼": "almond shaped eyes, large round doe eyes",
        "虎牙": "sharp canine tooth, cute fang peeking from lips",
        "梨涡": "dimples when smiling, cheek dimples",
        "酒窝": "deep dimples, charming smile creases",
        "薄唇": "thin lips, narrow mouth line",
        "朱唇": "vermillion red lips, painted crimson lips",
        "剑眉": "sword-like sharp eyebrows, angular brows",
        "柳眉": "willow leaf shaped eyebrows, gentle curved brows",
        "鹅蛋脸": "oval face shape, perfect egg-shaped face",
        "瓜子脸": "heart shaped face, delicate v-line jaw",
        "国字脸": "square jaw face, strong angular face",
        "苍白": "deathly pale complexion, ashen pallor",
        "红润": "rosy healthy complexion, flushed cheeks",
        "青筋": "veins bulging, visible blue veins on temple or hands",
        "汗珠": "beads of sweat, sweat dripping down face",
        "泪痕": "tear streaks on cheeks, dried tear tracks",
        "泪光": "glistening tears in eyes, eyes shimmering with tears",
        "红眼": "reddened eyes, bloodshot eyes from crying or rage",
        "红眶": "red rimmed eyes, puffy eyelids",
        "黑眼圈": "dark circles under eyes, exhausted hollow eyes",
        "白头发": "silver white hair, aged white hair",
        "花白头发": "salt and pepper gray hair, graying streaks",
        "寸头": "buzz cut short hair, military crop haircut",
        "丸子头": "top knot bun hairstyle, high bun updo",
        "麻花辫": "braided hair, twin braids, woven plait",
        "披肩发": "shoulder length loose hair, cascading over shoulders",
        "刘海": "bangs covering forehead, fringe hairstyle",
        "散发": "disheveled loose flowing hair, wild unbound hair",
        "散发披肩": "long flowing unbound hair cascading over shoulders",
        "束发": "hair tied up, hair bound in high ponytail or bun",
        "玉冠": "jade hair crown, ornate jade headpiece",
        "发簪": "decorative hairpin, ornate hair stick",
        "金钗": "golden hairpin accessory, gold ornamental hair clasp",
        "丝带": "silk ribbon in hair, flowing ribbon hair tie",
        "斗笠": "conical bamboo hat, traditional wide brim hat",
        "面纱": "translucent face veil, mysterious face covering",
        "面具": "ornate mask covering face, mysterious half mask",
        "青铜面具": "ancient bronze mask, eerie metallic face covering",
        # 角色特征
        "清秀": "delicate refined features, elegant gentle appearance",
        "俊美": "strikingly handsome, dashing beautiful features",
        "冷峻": "cold stern appearance, severe icy demeanor",
        "沧桑": "weathered aged appearance, world-worn face",
        "儒雅": "scholarly refined elegant appearance, cultured gentleman",
        "枭雄": "ruthless warlord presence, ambitious overlord aura",
        "书生气": "bookish scholarly demeanor, intellectual appearance",
        "江湖气": "wandering martial artist aura, street-smart warrior vibe",
        # 服装细节
        "劲装": "form-fitting martial arts combat uniform",
        "战甲": "ornate battle armor, engraved metal armor plates",
        "甲胄": "full body armor, heavy plate mail armor",
        "护腕": "leather bracers wrist guards, armored vambraces",
        "披风": "flowing cape billowing, dramatic sweeping cloak",
        "斗篷": "hooded cloak, dark enveloping cloak",
        "大氅": "grand ceremonial overcoat, majestic outer robe",
        "铠袖": "armored sleeves, metal plated arm guards",
        "腰封": "ornate waist sash, embroidered waist cincher",
        "束腰": "waist cinched tight, corseted narrow waist",
        "玉佩": "jade pendant hanging from waist, ornate jade accessory",
        "令牌": "command token at waist, authority badge",
        "香囊": "fragrant sachet pouch, delicate embroidered perfume bag",
        "折扇": "folding fan in hand, elegant paper fan prop",
        "长剑": "long sword, straight double-edged blade",
        "短刀": "short blade dagger, concealed knife",
        "软剑": "flexible whip sword, chain sword, urumi blade",
        "唐刀": "tang dynasty straight sword, single edged curved tang blade",
        "枪": "spear with red tassel, long pole weapon",
        # 现代装
        "西装": "tailored business suit, sharp formal suit",
        "高定西装": "bespoke haute couture suit, luxury tailored suit",
        "衬衫": "crisp white dress shirt, button down shirt",
        "休闲装": "casual streetwear outfit, relaxed modern clothing",
        "运动服": "athletic sportswear, sleek workout outfit",
        "校服": "school uniform, neat student attire",
        "工装": "utility workwear jumpsuit, practical worker uniform",
        "礼服": "evening formal gown, elegant cocktail dress",
        "婚纱": "wedding dress, flowing white bridal gown",
        "旗袍": "traditional chinese qipao dress, figure-hugging cheongsam",
        "汉服": "traditional hanfu clothing, flowing historical chinese robes",
        "JK制服": "japanese schoolgirl sailor uniform, pleated skirt outfit",
        # 环境场景（扩充）
        "宫殿": "grand palace interior, imperial hall, magnificent court",
        "大殿": "great hall, vast imperial throne room, soaring ceiling",
        "地牢": "dark dungeon cell, underground prison chamber",
        "密室": "hidden secret chamber, concealed underground room",
        "书房": "traditional study room, scholar's private library",
        "练功房": "training hall, martial arts practice chamber",
        "悬崖": "precipice edge, sheer cliff drop, vertigo-inducing height",
        "瀑布": "thundering waterfall cascade, misty water curtain",
        "竹林": "dense bamboo forest grove, emerald bamboo thicket",
        "雪地": "vast snow-covered field, pristine white snowscape",
        "沙漠": "endless desert dunes, scorching barren wasteland",
        "战场": "war-torn battlefield, chaos and destruction",
        "废墟": "collapsed ruins rubble, shattered destroyed remains",
        "码头": "wooden dock pier, harbor waterfront",
        "船舱": "wooden ship cabin interior, cramped boat quarters",
        "花海": "endless sea of blooming flowers, vibrant flower field",
        "枫林": "crimson maple forest, autumn red leaves canopy",
        "客栈": "traditional inn interior, rustic tavern lodging",
        "茶楼": "tea house pavilion, elegant multi-story tea establishment",
        "酒楼": "bustling restaurant tavern, lively dining hall",
        "当铺": "old pawn shop, dim cluttered antique broker storefront",
        "绣楼": "young lady's boudoir pavilion, upstairs embroidery chamber",
        "闺房": "maiden's private boudoir chamber, delicate feminine room",
        # 现代场景
        "咖啡厅": "cozy cafe interior, warm coffee shop atmosphere",
        "办公室": "modern corporate office, sleek glass walled workspace",
        "会议室": "boardroom, long conference table, glass walled",
        "医院": "sterile hospital room, white medical environment",
        "教室": "bright classroom interior, rows of wooden desks",
        "书店": "cozy bookstore interior, towering bookshelves",
        "天台": "rooftop terrace, open-air rooftop with city view",
        "地下车库": "underground parking garage, dim concrete parking lot",
        "电梯间": "cramped elevator interior, mirrored elevator walls",
        # 天气/光线（精细分类）
        "暴雨": "torrential downpour, sheets of driving rain",
        "细雨": "light drizzling rain, gentle misty rain",
        "狂风": "howling gale force wind, violently whipping wind",
        "微风": "gentle breeze, soft rustling wind",
        "闪电": "lightning bolt streaking across sky, electric flash",
        "雷鸣": "thunder rumbling, storm crackling electricity",
        "彩虹": "vibrant rainbow arc across sky, prismatic light",
        "朝阳": "golden morning sunrise, dawn first light",
        "夕阳": "crimson sunset glow, warm golden hour sunset",
        "星空": "starry night sky, vast milky way galaxy",
        "极光": "aurora borealis dancing in sky, ethereal green lights",
        "血月": "blood red moon, ominous crimson lunar eclipse",
        "逆光": "dramatic backlight, subject silhouetted against bright background",
        "侧光": "side lighting, strong directional light creating depth",
        "底光": "underlighting, eerie light from below casting upward shadows",
        "顶光": "overhead lighting, harsh light from above",
        "柔光": "soft diffused gentle light, dreamy ethereal glow",
        "硬光": "harsh crisp directional light, sharp defined shadows",
        # 情绪/表情（精细分类）
        "冷笑": "cold sneer, contemptuous smirk, mocking smile",
        "苦笑": "bitter wry smile, resigned helpless smile",
        "邪笑": "sinister wicked grin, evil twisted smile",
        "狞笑": "savage cruel grin, menacing predatory smile",
        "傻笑": "goofy foolish grin, dazed silly smile",
        "泪中带笑": "smiling through tears, bittersweet tearful smile",
        "双目通红": "bloodshot crimson eyes, eyes burning red with emotion",
        "瞳孔收缩": "pupils constricting sharply, eyes narrowing to slits",
        "瞳孔放大": "pupils dilating wide, eyes widening in shock",
        "眼神一暗": "eyes darkening, gaze turning cold and dangerous",
        "眼神一亮": "eyes lighting up, sudden sparkle of hope in eyes",
        "目光如刀": "gaze sharp as blade, piercing cutting stare",
        "目光如炬": "eyes burning with intensity, fierce blazing gaze",
        "倒吸一口凉气": "gasping sharply, sharp intake of breath, stunned",
        "屏住呼吸": "holding breath, breath caught in throat",
        "咬牙切齿": "gritting teeth, jaw clenched tight with fury",
        "浑身发抖": "entire body trembling, shaking uncontrollably",
        "腿软": "legs giving way, knees buckling weak",
        "踉跄": "staggering unsteady, stumbling almost falling",
        "瘫坐": "collapsing to seated position, slumping down helpless",
        "崩溃": "breaking down completely, emotional collapse despair",
        "绝望": "utter despair, hopeless crushed expression",
        "倔强": "stubborn defiant expression, refusing to yield",
        "隐忍": "suppressed restrained emotion, biting back tears",
        "动容": "visibly moved touched, emotional expression softening",
        # 动作（精细分类）
        "拔剑": "drawing sword from sheath, blade sliding out",
        "收剑": "sheathing sword, blade sliding back into scabbard",
        "出鞘": "unsheathing weapon, blade gleaming as drawn",
        "横剑": "holding sword horizontally across body, defensive stance",
        "指剑": "pointing sword tip forward, blade aimed threateningly",
        "劈砍": "slashing downward with force, powerful sweeping cut",
        "格挡": "parrying blocking attack, blade clashing defense",
        "后跃": "leaping backward, evading with agile backflip",
        "俯冲": "diving downward, plunging descending rapidly",
        "虚影": "afterimage blur, phantom afterimage from speed",
        "残影": "residual blur trail, motion ghost afterimage",
        "瞬移": "instant teleportation, blinking from one spot to another",
        "飞身": "leaping flying through air, airborne soaring",
        "飘落": "drifting floating gently down, descending gracefully",
        "坠落": "plummeting falling, tumbling downward rapidly",
        "踉跄后退": "staggering backward reeling, stumbling retreat",
        "猛地站起": "suddenly standing up, springing to feet",
        "猛然回头": "whipping head around sharply, snapping to look back",
        "缓缓转头": "slowly turning head, deliberate measured movement",
        "扯住衣角": "clutching grabbing corner of clothing, tugging hem",
        "手指微颤": "fingers trembling slightly, subtle finger quiver",
        "双腿一软": "legs buckling collapsing, knees giving way",
        # 氛围/特效
        "杀意": "killing intent aura, murderous bloodlust presence",
        "杀气": "deadly murderous aura, oppressive killing pressure",
        "威压": "overwhelming oppressive presence, crushing authoritative aura",
        "灵气": "spiritual energy aura, ethereal mystical glow",
        "黑气": "dark malevolent energy, ominous black miasma",
        "金光": "radiant golden divine light, holy golden radiance",
        "白光": "pure white blinding light, divine white radiance",
        "血雾": "crimson blood mist spray, atomized blood particles",
        "火花": "sparks flying, embers scattering, fiery sparks",
        "冰晶": "crystalline ice shards, frozen crystal fragments",
        "花瓣飞舞": "flower petals dancing swirling in air, petal storm",
        "落叶纷飞": "autumn leaves swirling falling, rustling leaf cascade",
        # 构图术语
        "三分法": "rule of thirds composition, balanced thirds framing",
        "黄金分割": "golden ratio composition, phi grid framing",
        "对称构图": "symmetrical composition, mirror balanced framing",
        "对角线": "diagonal composition, dynamic angled framing",
        "画框构图": "frame within a frame composition, framing foreground object",
        "留白": "negative space composition, intentional empty space",
        "引导线": "leading lines converging, directional lines guiding eye",
        # 人物相关
        "年轻女子": "young adult woman", "中年男子": "middle-aged man",
        "少女": "teenage girl", "女子": "young woman", "女人": "woman",
        "男人": "man", "少年": "boy", "老妇人": "elderly woman",
        "老人": "elderly person", "孩子": "child", "女孩": "girl", "男孩": "boy",
        "长发": "long flowing hair", "短发": "short hair", "黑发": "black hair",
        "白发": "white silver hair", "马尾": "ponytail hairstyle", "束发": "hair tied back",
        "白衣": "wearing white clothing", "灰衣": "wearing grey outfit",
        "红衣": "wearing red garment", "黑衣": "wearing black attire",
        "古装": "traditional Chinese costume", "汉服": "traditional hanfu robe",
        "长袍": "wearing long flowing robe", "现代装": "modern casual clothing",
        "围裙": "wearing apron, work apron", "短褐": "wearing short coarse hemp garment",
        "深蓝色": "deep blue colored", "灰蓝色": "grey blue colored",
        # 传统中国恐怖题材
        "纸扎铺": "traditional joss paper shop, funeral paper crafts store",
        "纸人": "paper effigy, joss paper human figure",
        "竹篾": "bamboo strips, bamboo splints framework",
        "浆糊": "flour paste, starch glue on surface",
        "香炉": "incense burner, smoking incense sticks",
        "供桌": "altar table, offering table",
        "油灯": "oil lamp, flickering flame, warm glow",
        "香": "incense sticks burning, wisps of smoke",
        "铜铃": "bronze bell, metal bell", "灯笼": "paper lantern, red lantern",
        "纸马": "paper horse effigy", "旗幡": "banner flags, fluttering cloth",
        "门板": "wooden door panels, shop front shutters",
        "石板路": "cobblestone road, stone paved path",
        "屋檐": "traditional Chinese roof eaves, curved eaves",
        "傩戏": "Chinese Nuo ritual drama, exorcism performance",
        "傩戏台": "Nuo drama stage, traditional ritual platform",
        "毛笔": "ink brush, calligraphy brush", "朱砂": "red cinnabar ink, vermilion pigment",
        "暗红色": "dark crimson red, blood red",
        "青瓷": "celadon ceramic, pale green porcelain",
        "裁纸刀": "paper cutting knife, utility blade",
        "工坊": "workshop interior, artisan workshop",
        "后院": "back courtyard, rear yard",
        "雾": "mist fog haze", "雾气": "drifting mist fog",
        "山雾": "mountain mist, valley fog",
        "纸灰": "paper ash dust, burnt paper residue",
        "幽绿色": "eerie ghostly green glow",
        # 场景相关
        "海边": "by the sea, ocean shore", "山间": "in mountains, mountain path",
        "房间": "interior room", "酒店房间": "hotel room interior",
        "酒店大堂": "luxury hotel lobby", "街道": "street, road",
        "庭院": "courtyard", "电梯": "elevator interior",
        "雨中": "in the rain, raining", "夜晚": "at night, night time",
        "黄昏": "at dusk, sunset glow, golden hour", "清晨": "early morning, dawn",
        "雾中": "shrouded in mist, foggy environment",
        "店铺": "shop interior, store", "床边": "beside bed, bedroom",
        "门口": "at doorway, door frame", "舞台": "on stage, theater stage",
        "窗前": "by the window", "走廊": "corridor hallway",
        "破庙": "abandoned temple ruins", "镇子": "small town, rural village",
        "古镇": "ancient town, historic village",
        "沅江": "river scenery, riverside, water reflection",
        "木架": "wooden rack shelf, timber frame",
        "柜台": "shop counter, wooden counter desk",
        # 动作/状态
        "站着": "standing upright", "坐着": "sitting down",
        "躺着": "lying down resting", "跪着": "kneeling on ground",
        "转身": "turning around, body rotating", "跑": "running fast",
        "走": "walking slowly", "冲": "dashing rushing sprinting",
        "推开": "pushing open, door swinging open",
        "接过": "taking receiving in hand", "递来": "handing over extending",
        "发抖": "trembling shaking shivering", "回头": "looking back over shoulder",
        "低头": "head bowed down, looking down", "抬头": "looking up, face tilted up",
        "哭泣": "crying, tears streaming down face",
        "微笑": "gentle smile, slight smile", "发颤": "trembling slightly, quivering",
        "皱眉": "furrowed brows, frowning",
        "侧耳听": "listening carefully, head tilted, attentive",
        "探出": "peeking out, leaning out from",
        "蜷缩": "huddled curled up, crouching",
        "惊讶": "surprised expression, wide eyes, mouth open",
        "愤怒": "angry expression, furrowed brows, clenched fists",
        "害怕": "fearful expression, trembling, eyes wide with terror",
        "警觉": "alert watchful expression, tense posture",
        "茫然": "blank vacant expression, lost gaze",
        "手持": "holding in hand, gripping", "看着": "gazing at, looking at, staring",
        "穿上": "putting on wearing clothing", "脱下": "taking off removing",
        "点": "dabbing dotting touching with brush tip",
        "画": "drawing painting brush stroke",
        "捻": "rubbing between fingers, feeling texture",
        # 物品
        "竹条": "bamboo strip, thin bamboo slat",
        "手机": "mobile phone smartphone",
        "房卡": "hotel key card", "外套": "coat jacket",
        "桌子": "wooden table", "椅子": "wooden chair", "床": "wooden bed",
        "门": "wooden door", "窗户": "latticed window", "墙": "stone wall, aged wall",
        "水珠": "water droplets", "旋转门": "revolving glass door",
        "座钟": "antique pendulum clock, grandfather clock",
        "火盆": "brazier fire pit, burning embers",
        "被褥": "bedding futon, folded blankets",
        "血": "blood, bloodstain, crimson liquid",
        "碎布": "torn fabric scraps, shredded cloth",
        # 光线/氛围（扩充分类）
        "月光": "moonlight illuminating, silver moon glow",
        "阳光": "sunlight streaming, golden sun rays",
        "阴影": "deep shadows, dark shadow areas",
        "昏暗": "dimly lit, dark gloomy",
        "明亮": "brightly lit, well illuminated",
        "水汽": "misty moisture haze, humid air",
        "暖气": "warm indoor heating glow",
        "浓雾": "thick dense fog, low visibility",
        "风雨": "wind and rain storm, stormy weather",
        "青烟": "wispy blue smoke, curling smoke tendrils",
        "剪影": "silhouette, backlit figure outline",
        "余韵": "lingering after-effect, fading trace",
        "暗淡": "dim fading light, subdued illumination",
        "灰白": "grey white, pale ashen",
        "暗黄": "dark yellow ochre, muted gold",
        "灰蓝": "grey blue, slate blue tones",
        "暖黄": "warm yellow amber, golden warmth",
        "冷暗": "cold dark, cool shadow tones",
        "昏暗光": "dim light, low key lighting",
        "饱和": "saturated vivid colors",
        "低饱和": "desaturated muted tones, low saturation",
        "高对比": "high contrast, stark light and shadow",
        # 构图/镜头
        "前景": "foreground element, in foreground",
        "中景": "midground, middle distance",
        "背景": "background, distant backdrop",
        "远景": "wide establishing shot, panoramic view",
        "特写": "extreme close-up detail shot",
        "俯拍": "birds eye view, looking down from above",
        "仰拍": "low angle shot, looking up",
        "主光源": "key light source, main illumination",
        "色温": "color temperature lighting",
        "窗棂": "window lattice, mullioned window frame",
        "水平线": "horizon line, horizontal composition",
        "纵深感": "depth of field, layered depth",
    }

    result = chinese_text
    # 逐个替换已知关键词
    for cn, en in sorted(visual_dict.items(), key=lambda x: -len(x[0])):  # 先替换长的
        result = result.replace(cn, en)

    # 清理：移除剩余的中文字符（只保留英文+标点+数字）
    cleaned = _re.sub(r'[^\x00-\x7F\s,.:;\'"-]', '', result)
    cleaned = _re.sub(r'\s+', ' ', cleaned).strip()

    # 如果清理后内容太少，返回空字符串（避免无意义片段）
    # v9.10: 返回空时附加兜底标记，调用方检测后使用通用描述
    if len(cleaned) < 10:
        return ""
    return cleaned


# ─── v7.0 Seedream 蒸馏: 中文场景 → 专业英文提示词改写 ──
async def _deepseek_prompt_rewrite(chinese_desc: str, scene_context: dict = None) -> str:
    """使用 DeepSeek 将中文场景描述改写为即梦风格的专业英文提示词。
    替代 _translate_to_english_keywords() 的逐词翻译, 理解语境和风格。
    scene_context: {"setting": "...", "mood": "...", "camera": "...", "characters": "..."}
    """
    from app.config import DEEPSEEK_API_KEY
    
    if not DEEPSEEK_API_KEY:
        return ""
    
    # 构建用户消息
    parts = [f"场景描述: {chinese_desc}"]
    if scene_context:
        ctx = scene_context
        if ctx.get("setting"):
            parts.append(f"环境: {ctx['setting']}")
        if ctx.get("mood"):
            parts.append(f"情绪: {ctx['mood']}")
        if ctx.get("atmosphere"):              # v9.4: 环境级空间氛围
            parts.append(f"空间氛围: {ctx['atmosphere']}")
        if ctx.get("camera"):
            parts.append(f"镜头: {ctx['camera']}")
        if ctx.get("characters"):
            parts.append(f"角色: {ctx['characters']}")
        if ctx.get("key_props"):               # v9.4: 标志性道具
            parts.append(f"关键道具: {ctx['key_props']}")
    user_msg = "\n".join(parts)
    
    try:
        result = await call_deepseek(
            DEEPSEEK_API_KEY,
            SEEDREAM_REWRITE_SYSTEM,
            user_msg,
            max_tokens=512,
            temperature=0.3  # 低温度保证翻译稳定, 不添加额外创意
        )
        # 清理结果
        lines = result.strip().split("\n")
        prompt = lines[0] if lines else result
        # 去掉可能残留的 JSON/引号
        prompt = prompt.strip('"').strip("'").strip()
        if len(prompt) < 30:
            return ""
        return prompt
    except Exception as e:
        print(f"[Seedream] Prompt rewrite failed: {str(e)[:80]}", flush=True)
        return ""


# ─── v7.0 Seedream 蒸馏: VMix 美学标签提取 ──────────────
def _extract_vmix_tags(scene, job=None) -> str:
    """从分镜和环境分析中提取 VMix 结构化美学标签。
    返回 Danbooru 风格的前缀字符串, 例如:
    [color: warm amber] [lighting: rim light] [composition: rule of thirds] [scale: epic scale]
    Animagine XL 原生理解 Danbooru 标签格式, 前置权重最高。
    v9.4: 新增 scale 标签，使用统一的环境匹配工具函数。
    """
    tags = []
    
    # 统一环境匹配（消除重复循环）
    env_match = _get_scene_environment(scene, job) if job else None
    
    # 1. 色板: 从环境分析或情绪推断
    env_color = env_match.get('color_scheme', '') if env_match else ""
    
    # 根据情绪强度推断色板
    intensity = getattr(scene, 'emotional_intensity', 5)
    mood = getattr(scene, 'mood', '') or ''
    
    if env_color:
        # 反向查找 VMix 色板英文名
        for eng, cn in VMIX_TAGS["palette"].items():
            if cn in env_color or env_color in cn:
                tags.append(f"color: {eng}")
                break
        if not any("color:" in t for t in tags):
            tags.append(f"color: warm amber")
    elif intensity >= 7:
        tags.append(f"color: {'crimson red' if '怒' in mood or '恐惧' in mood else 'golden hour' if '壮' in mood or '热血' in mood else 'fiery orange'}")
    elif intensity <= 3:
        tags.append(f"color: {'pastel pink' if '温馨' in mood or '喜悦' in mood else 'moonlit silver' if '宁静' in mood or '悲伤' in mood else 'icy blue'}")
    else:
        tags.append(f"color: {'jade green' if '古' in getattr(scene, 'setting', '') or '山' in getattr(scene, 'setting', '') else 'warm amber'}")

    # 2. 光线: 从环境分析提取
    env_lighting = env_match.get('lighting', '') if env_match else ""
    
    if env_lighting:
        for eng, cn in VMIX_TAGS["lighting"].items():
            if cn in env_lighting or env_lighting in cn:
                tags.append(f"lighting: {eng}")
                break
    
    if not any("lighting:" in t for t in tags):
        if intensity >= 7:
            tags.append("lighting: dramatic chiaroscuro")
        elif intensity <= 3:
            tags.append("lighting: soft diffused")
        else:
            tags.append("lighting: cinematic volumetric")
    
    # 3. 构图: 从镜头语言推断
    camera = getattr(scene, 'camera', '') or ''
    if '特写' in camera or '近景' in camera:
        tags.append("composition: close-up portrait")
    elif '远景' in camera or '全景' in camera:
        tags.append("composition: wide establishing shot")
    elif '俯' in camera:
        tags.append("composition: bird's eye view")
    elif '仰' in camera:
        tags.append("composition: low angle hero")
    elif '过肩' in camera:
        tags.append("composition: over the shoulder")
    else:
        tags.append("composition: rule of thirds")
    
    # v9.4: 4. 尺度 — 从环境分析提取
    env_scale = env_match.get('scale', '') if env_match else ""
    if env_scale:
        for eng, cn in VMIX_TAGS.get("scale", {}).items():
            if cn in env_scale or env_scale in cn:
                tags.append(f"scale: {eng}")
                break
    
    return ", ".join(tags)


# ─── v7.0 Seedream 蒸馏: 多维图文对齐评分 ──────────────
async def _prompt_quality_score(prompt_en: str) -> float:
    """v8.7: 用 DeepSeek 评估图像提示词质量 (1-10分)。
    返回归一化分数 (0.0-1.0)。
    注意: DeepSeek 是纯文本模型，无法直接评估图文对齐。
    这里评估的是 prompt 本身的描述质量（细节丰富度、词汇精确度等），
    作为图文对齐度的代理指标。
    """
    from app.config import DEEPSEEK_API_KEY
    
    if not DEEPSEEK_API_KEY or not prompt_en:
        return 0.5  # 无信息时返回中性分
    
    try:
        user_msg = f"""请评估以下 AI 图像生成提示词的视觉描述质量 (1-10分):
提示词: {prompt_en[:500]}

评分标准:
- 是否包含具体的人物外貌描述 (头发颜色 眼睛 服装)
- 是否有明确的场景环境
- 是否有光线/色彩/构图指示
- 是否使用了专业 Danbooru 标签风格
- 词汇丰富度和精确度

只返回一个数字 (1-10), 不返回其他内容。"""
        
        result = await call_deepseek(
            DEEPSEEK_API_KEY,
            "你是一个专业的 AI 图像提示词质量评估器。只返回 1-10 的数字评分。",
            user_msg,
            max_tokens=16,
            temperature=0.1
        )
        
        # 提取数字
        import re as _re
        match = _re.search(r'(\d+(?:\.\d+)?)', result.strip())
        if match:
            score = float(match.group(1))
            return min(max(score / 10.0, 0.0), 1.0)
        return 0.5
    except Exception as e:
        logger.warning(f"[PromptQuality] 评分失败: {str(e)[:80]}")
        return 0.5


# ─── 好莱坞级分镜系统 v5.0 ─────────────────────────────
# 说明：以下三个 SYSTEM PROMPT 共同构成好莱坞级别的分镜生成体系：
#   1. STORY_STRUCTURE_SYSTEM  — 故事结构预分析（三幕式+情绪弧线）
#   2. STORYBOARD_SYSTEM       — 好莱坞级分镜生成（核心）
#   3. PROMPT_SYSTEM           — 商业级英文提示词生成（匹配好莱坞分镜标准）

# ─── 故事结构预分析 Prompt ──────────────────────────────────
STORY_STRUCTURE_SYSTEM = """你是一位好莱坞级别的剧本分析师和故事结构专家，曾参与多部商业大片的剧本开发。
你的任务：在分镜生成之前，先对小说文本进行专业的故事结构分析，为后续分镜设计提供战略级的叙事蓝图。

## 分析维度（必须全部覆盖）

### 一、三幕式结构定位（Three-Act Structure）
将原文精确划分为：
- **第一幕（铺垫/Setup）**：引入世界、角色、核心冲突。结束于「激励事件（Inciting Incident）」——
  打破主角平静生活的事件，约全文 20%-25% 处。
- **第二幕（对抗/Confrontation）**：主角面对障碍、成长、失败、再度奋起。中间点（Midpoint）约 50% 处，
  高潮前的最大挫折（All Is Lost）约 75% 处。
- **第三幕（解决/Resolution）**：最终决战/高潮，所有线索汇聚，冲突解决，新常态建立。

### 二、核心情绪弧线（Emotional Beat Map）
标注全文的情绪波形（用曲线图思维）：
- 开篇基调（宁静/紧张/神秘/欢快…）
- 第一次情绪转折（在激励事件处）
- 情绪低谷（All Is Lost 时刻）
- 最终高潮的情绪峰值
- 结尾余韵

### 三、关键视觉主题（Visual Themes）
提取 2-4 个贯穿全文的视觉母题（Visual Motifs），例如：
- 色彩母题：某角色出现时总是伴随金色光线 / 悲伤场景总是阴雨
- 物体母题：某件道具反复出现，承载情感记忆
- 构图母题：主角的孤独感通过大量远景+居中小人物体现

### 四、角色关系图谱（Character Web）
- 每个主要角色的核心欲望（Want）和深层需求（Need）
- 角色之间的关系性质（盟友/敌对/暧昧/父子…）
- 角色在故事中的弧线（从 A 状态成长为 B 状态）

### 五、场景节奏建议（Pacing Guide）
- 开篇：建议节奏（慢热/快节奏/中速）
- 动作场面：建议镜头切换频率（快速剪切/长镜头）
- 情感场面：建议镜头停留时长（长镜头沉淀/快速切换累积情绪）

## 返回格式（严格 JSON）
```json
{
  "three_act": {
    "act1_range": "约第1段～第X段（前20%-25%）",
    "act2_range": "约第X+1段～第Y段（中间50%）",
    "act3_range": "约第Y+1段～结尾（后25%）",
    "inciting_incident": "激励事件的具体描述（打破平静的事件）",
    "midpoint": "中间点的具体描述（转折点）",
    "all_is_lost": "最大挫折的具体描述（最低谷）",
    "climax": "高潮的具体描述（最终对决/解决）"
  },
  "emotional_arc": [
    {"position": "开头", "mood": "情绪基调", "intensity": 1-10},
    {"position": "激励事件", "mood": "...", "intensity": ...},
    {"position": "中间点", "mood": "...", "intensity": ...},
    {"position": "最低谷", "mood": "...", "intensity": ...},
    {"position": "高潮", "mood": "...", "intensity": ...},
    {"position": "结尾", "mood": "...", "intensity": ...}
  ],
  "visual_motifs": [
    {"motif": "母题描述", "description": "在分镜中如何体现这个视觉母题"}
  ],
  "character_arcs": [
    {"name": "角色名", "want": "角色想要的", "need": "角色需要的", "arc": "从…成长为…"}
  ],
  "pacing_notes": {
    "opening": "开篇节奏建议",
    "action_scenes": "动作场面镜头节奏建议",
    "emotional_scenes": "情感场面镜头停留建议",
    "ending": "结尾节奏建议"
  },
  "color_script": {
    "act1_palette": "第一幕主色调（含心理暗示）",
    "act2_palette": "第二幕主色调",
    "act3_palette": "第三幕主色调",
    "key_transitions": "关键色彩转换点及叙事目的"
  }
}
```

## 强制规则
1. 只返回 JSON 对象，不添加任何其他文字
2. 分析必须基于原文实际内容，不能虚构情节
3. 情绪强度用 1-10 数值，便于分镜生成时参考"""

# ─── v6.3: 角色预分析 Prompt（融合v6.2 15维度 + v4.0声音/Kling字段） ──
CHARACTER_ANALYSIS_SYSTEM = """你是一位好莱坞级角色设计师兼AI绘画提示词工程师。从小说文本中以导演和画师的双重视角，提取所有角色并构建完整的视觉档案+声音档案。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第一部分：核心原则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
你的输出将同时驱动三个系统：
 • AI绘画 → 需要精确外貌描述（头发/眼睛/肤色/服装/特殊标记）
 • AI视频 → 需要角色全身+动作+表情连续性描述
 • AI配音 → 需要年龄段+性格推断（用于声音匹配）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第二部分：分析维度（18项，必须全覆盖）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【身份维度】
1. name: 角色名字（中文原名）
2. role: 身份定位（主角/反派/重要配角/次要角色/路人）
3. importance_level: 重要级别（primary/main antagonist/secondary/minor）

【年龄与声音维度】
4. gender: 性别（男/女）
5. age_appearance: 目测年龄描述（如"约25岁的青年""看起来40岁左右的中年男子"）
6. age_range: 年龄段（儿童/少年/青年/中年/老年）─ 用于TTS声音匹配
7. speaking_style: 说话风格描述（如"语速平缓、低沉有力""语调高昂、节奏紧凑""软糯拖音"）─ 用于TTS声音匹配

【外貌维度 - 精细化分拆】
8. physical_description: 整体身材描述（身高cm+体型+体态，如"身高约180cm，身材修长精瘦，站姿挺拔如松"）
9. face_detail: 面部特征（脸型+五官风格+气质，如"剑眉星目，鼻梁挺直，薄唇紧抿，面部线条锋利"）
10. hair_style: 发型发色（长度+颜色+质感+造型，如"黑色短发微卷，额前碎发，发尾略翘"）
11. eye_detail: 眼睛特征（颜色+形状+眼神+特殊习惯，如"深棕色凤眼，眼尾微挑，习惯性微眯"）
12. skin_tone: 肤色（白皙/偏白/小麦色/古铜色/黝黑 + 质感描述）
13. typical_clothing: 标志性服装（款型+颜色+材质+配饰，如"黑色修身短打劲装，银丝束带，右肩暗纹护甲"）
14. body_type: 身体特征摘要（身高+体型，简短版供快速匹配，如"修长精瘦，站姿挺拔"）

【性格与表情维度】
15. personality: 性格特征描述（3-5个关键词，如"冷酷外表下藏着温柔/寡言/行事果断"）
16. typical_expression: 常见表情/神态（如"常带审视的目光，思考时眉心微蹙，愤怒时下颌绷紧"）

【特殊标志与关系】
17. special_marks: 特殊标志（疤痕/胎记/纹身/饰品/标志性配件等）
18. relationships: 与其他角色的关系（如"张三的恋人/李四的宿敌"）

【AI绘画专用 - Kling Prompt】
19. kling_prompt: 英文正面角色脸描述（用于AI文生图，格式："portrait of a [gender] [age_range], [hair], [eyes], [skin tone], [facial features], wearing [clothing], front view, looking at camera, high detail face, photorealistic"）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第三部分：返回格式（严格 JSON）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
只返回 JSON 对象，第一个字符必须是 {，最后一个字符必须是 }：

{
  "characters": [
    {
      "name": "林逸",
      "role": "主角",
      "importance_level": "primary",
      "gender": "男",
      "age_appearance": "约25岁的青年",
      "age_range": "青年",
      "speaking_style": "语速平缓、低沉有力，情绪激动时略微加速",
      "physical_description": "身高约180cm，身材修长精瘦，站姿挺拔如松，肩宽腰窄",
      "face_detail": "剑眉星目，鼻梁挺直，薄唇微抿，面部线条锋利，下颌角分明",
      "hair_style": "黑色短发微卷，额前几缕碎发，发尾略翘，偶尔会随手拨开",
      "eye_detail": "深棕色凤眼，眼尾微挑，目光锐利，审视他人时习惯性微眯",
      "skin_tone": "偏白，因常年修炼少有日晒",
      "typical_clothing": "黑色修身短打劲装，腰间银丝束带，右肩有暗纹护甲，袖口收紧",
      "body_type": "修长精瘦，肩宽腰窄，姿态挺拔",
      "personality": "冷酷外表下藏着温柔，寡言，行事果断，极度护短",
      "typical_expression": "常带审视的目光，思考时眉心微蹙，愤怒时下颌绷紧",
      "special_marks": "左手背有火焰形胎记，战斗时微微发光",
      "relationships": "李四的生死之交，王五的宿敌，赵六的暗恋对象",
      "kling_prompt": "portrait of a young man, short tousled black hair, sharp phoenix eyes, fair skin, angular face with defined jaw, wearing black martial arts uniform with silver sash, flame-shaped birthmark on left hand, front view, high detail face, photorealistic"
    }
  ],
  "total_count": 1,
  "note": "基于文本分析覆盖原文所有出场人物"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第四部分：强制规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 只返回 JSON 对象，禁止任何其他文字
2. 所有信息必须 100% 来自原文，不能虚构（未提及的标注"未提及"）
3. primary + main antagonist 共不超过 3 个，secondary 不限
4. 如果角色初次出场信息不完整，如实标注，待后续章节补充
5. typical_clothing 取角色最标志性的一套服装
6. kling_prompt 必须是英文，适合 AI 文生图（SD/Flux/Kling 通用格式）
7. age_range 和 speaking_style 对 TTS 声音匹配至关重要，必须根据原文推断
8. body_type 是 physical_description 的精简版，便于程序快速读取"""

# ─── v6.2: 环境预分析 Prompt ──────────────────────────────
ENVIRONMENT_ANALYSIS_SYSTEM = """你是一位专业的影视场景设计师，擅长从小说文本中提取所有场景空间的详细视觉信息。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第一部分：你的任务
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
从给定的小说文本中，提取所有场景/环境的详细视觉信息。
你的分析将直接驱动 AI 绘画的场景一致性和空间连贯性。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第二部分：分析维度（必须覆盖）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

对每个场景/环境，按以下维度提取：

1. name: 场景名称（如"青云宗大殿""废弃的城西工厂3号车间""竹林小径"）
2. location_type: 场景类型（interior=室内/exterior=室外/mixed=室内外混合/abstract=抽象空间）
3. description: 场景详细描述（5-8句话的空间视觉描绘，含：空间尺度、建筑风格、材质质感、关键特征）
4. time_period: 该场景最常出现的时间段（dawn=清晨/morning=上午/noon=正午/afternoon=下午/dusk=黄昏/night=夜晚/variable=多变）
5. lighting: 光源描述（主光源位置+性质+色温，如"穹顶天窗透下的自然光，正午时垂直照射中央，形成丁达尔效应"）
6. color_scheme: 主色调方案（如"金+象牙白为主，青色琉璃点缀""暗灰+锈红为主，黄色安全灯惨淡照明"）
7. atmosphere: 空间氛围（如"庄严肃穆""阴森压抑""温馨舒适""空旷荒凉"）
8. key_props: 关键道具/标志物（如"中央十丈高祖师像""破旧的红色集装箱""窗前枯松盆景"）
9. scale: 空间尺度（epic=恢弘大场景/large=大型空间/medium=中型空间/small=小空间/intimate=亲密空间）
10. weather: 该场景的典型天气（如果原文有描述。如"always raining""sunny""foggy morning"）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第三部分：返回格式（严格 JSON 对象）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
只返回 JSON 对象，第一个字符必须是 {，最后一个字符必须是 }：

{
  "environments": [
    {
      "name": "青云宗大殿",
      "location_type": "interior",
      "description": "高耸的穹顶绘满星辰图，三十六根汉白玉立柱环绕四周，每根柱上雕有历代宗主的法相。正中央是一尊十丈高的开派祖师像，祖师右手执剑指天，左手捏法诀。地面是整块青玉打磨而成，光可鉴人，正中刻有巨大的太极图案。入口处两侧有青铜香炉，袅袅青烟升起。穹顶最高处有一圆形天窗，自然光垂直射入，在祖师像身上形成神圣的光柱。",
      "time_period": "variable",
      "lighting": "穹顶天窗透下的自然光形成主光源（正午时最亮），三十六根立柱上的夜明珠提供辅助冷光，青铜香炉的微火提供暖色点缀光",
      "color_scheme": "金（祖师像）+ 象牙白（汉白玉柱）+ 青玉色（地面）+ 夜明珠冷白+香炉暖橙",
      "atmosphere": "庄严肃穆，压迫感中带着神圣",
      "key_props": "十丈祖师像、星图穹顶、汉白玉立柱、青玉太极地面、青铜香炉",
      "scale": "epic",
      "weather": "N/A（室内）"
    }
  ],
  "total_count": 1,
  "environmental_theme": "本文的环境主题词：古典仙侠/庄严神圣（用2-4个词概括所有场景的共性）",
  "note": "基于文本分析，以上场景覆盖了原文所有明确出现的空间"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第四部分：强制规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 只返回 JSON 对象，禁止任何其他文字
2. description 必须足够详细，能直接用于 AI 绘画的 prompt
3. 每个场景的 lighting/color_scheme 必须具体，不能用"温馨灯光""普通色调"等模糊描述
4. 如果原文对某个环境的描述非常少，基于常识合理推断但标注为推断
5. 环境数量通常3-8个（短篇小说），长篇可更多但不超过15个
6. 相似但有区别的场景分开列出（如"大殿-白天"和"大殿-夜晚"分开）"""

# ─── 好莱坞级分镜生成 Prompt（核心）────────────────────────
STORYBOARD_SYSTEM = """你是一位好莱坞级别的商业漫剧导演兼分镜师，曾主导多部 Netflix 级别竖屏漫剧的视觉开发。
你深谙好莱坞叙事语法、专业镜头语言和商业漫剧的视觉节奏。你的分镜不仅能准确讲述故事，
更能通过专业的视听语言让观众产生深层次的情感共鸣。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第零部分：红果漫剧商业节奏铁律（最高优先级）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

你必须遵守红果漫剧的"短剧黄金法则"：

【铁律1：3秒钩子（Hook）】
- 第一个分镜（开幕）必须在3秒内给出强钩子：
  · 信息钩子：揭示关键矛盾/悬念（"穿越成了废柴王妃？""系统提示：你将在3分钟后死亡"）
  · 视觉钩子：冲击性画面（刀光闪过/血迹/坠落/对峙特写）
  · 情绪钩子：极端情绪状态（愤怒、恐惧、震惊、绝望）
- 第一个分镜的 description 必须以"强钩子"画面开始
- 禁止慢热开幕！禁止风景定场开幕！

【铁律2：10秒爆点（Turning Point）】
- 前2-3个分镜（约10秒）内必须出现剧情转折/冲突升级：
  · "系统的第一个任务""反派突然出现""隐藏身份被揭穿"等
- 每10秒必须给观众一个"继续看下去"的理由

【铁律3：30秒第一反转（First Reversal）】
- 前6-8个分镜（约30秒）内必须有第一次反转：
  · 身份反转（"原来他是..."）
  · 局势反转（"看似赢定了，结果..."）
  · 信息反转（"被告知的真相实际上是谎言"）
- 反转必须出乎意料但在逻辑之中

【铁律4：每3个分镜一个爽点/悬念的节奏密度】
- 不能有连续2个以上的纯叙事分镜
- 每隔1-2个叙事分镜，必须插入1个冲突/悬念/反转/情绪高点分镜
- storytelling_rhythm 字段必须准确标注：info_drop / conflict / reversal / cliffhanger / emotional_peak

【铁律5：集末钩子（Cliffhanger）】
- 最后一个分镜必须有钩子，让观众必须看下一集
- 具体形式：悬念问题/新角色出现/突发危机/未说出口的秘密

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第一部分：好莱坞叙事原则（你必须遵守）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【原则1：展示，不要告诉（Show, Don't Tell）】
- 绝对不要用画面"展示"心理描写的文字本身
- 正确做法：将抽象情绪转化为具象的视觉元素
  例：原文"他感到深深的孤独" → 画面：远景，角色独自坐在长椅上，前景有栏杆投影横切画面

【原则2：视线匹配（Eyeline Match）与180度规则】
- 对话场景中，两个角色的对切镜头必须保持相同的银幕方向
- 角色A看向画面右侧，角色B必须看向画面左侧（不能两个人都看向同一侧）
- 在 description 中注明角色的视线方向（looking right / looking left / looking down / eyes locked on...）

【原则3：构图服务于叙事（Composition Serves Story）】
- 角色在画面中的位置反映其权力关系：
  · 强势角色：画面下方（稳固感）/ 占据画面更多空间 / 仰拍
  · 弱势角色：画面上方（不稳固感）/ 占据画面较少空间 / 俯拍
  · 平等对话：两人高度相近，画面平衡
- 孤独感：角色居中但很小，大量留白 / 远景
- 压迫感：低角度仰拍 + 广角镜头畸变
- 亲密感：特写 + 浅景深（背景虚化）

【原则4：镜头运动必须有动机（Motivated Camera Movement）】
- 慢推（Slow Push In）：揭示角色内心 / 加强情感浓度 / 聚焦关键细节
- 慢拉（Slow Pull Back）：揭示环境规模 / 表达孤独或离别 / 场景收尾
- 跟随镜头（Tracking）：跟随角色行动，增强代入感
- 横摇（Pan）：建立空间关系 / 在两个角色之间建立联系
- 绝对禁止无意义的多余镜头运动

【原则5：光线必须动机化（Motivated Lighting）】
- 每个场景必须有明确的主光源（Key Light），并在 setting 字段中说明其位置和性质
  · 室内日景：窗外自然光从一侧打入，形成明暗分割
  · 室内夜景：台灯/烛光作为主光源，形成暖色局部光+冷色环境光对比
  · 室外：太阳/月亮方向明确，阴影方向一致
- 使用三点布光概念（Key / Fill / Back）来设计画面层次

【原则6：色彩脚本（Color Script）服务于情绪弧线】
- 每个分镜的色调必须与当前情绪弧线位置匹配
- 在 description 中明确写出主色调和辅助色调
- 色温（Color Temperature）：暖色（橙/红/黄）= 亲密/安全/激情；冷色（蓝/青/紫）= 疏离/危险/忧郁

【原则7：景别选择服务于情绪强度】
- 超特写（Extreme Close-Up）：眼球/嘴唇/手部细节 → 极度紧张/亲密/恐怖
- 特写（Close-Up）：面部充满画面 → 情感高峰/关键决定
- 近景（Medium Close-Up）：头部+肩部 → 对话/情感表达
- 中景（Medium Shot）：腰部以上 → 动作+对话混合
- 全景（Full Shot）：全身+部分环境 → 建立动作/空间关系
- 远景（Wide Shot）：角色在环境中很小 → 孤独/规模/环境叙事
- 超远景（Extreme Wide）：角色几乎不可见 → 存在主义孤独/史诗感

【原则8：纵深构图（Deep Composition）而非平面构图】
- 好的画面有三层：前景（Foreground）/ 中景（Midground）/ 背景（Background）
- 在 description 中明确写出三层分别有什么
- 利用前景物体做画框（Frame within Frame），引导视线聚焦主体

【原则9：视觉节奏（Visual Rhythm）= 剪辑节奏】
- 动作场面：短镜头（2-3秒）+ 快速切换 + 大量手持晃动感
- 情感场面：长镜头（5-8秒）+ 缓慢推拉 + 稳定构图
- 对话场面：中景建立 → 特写交替（Shot-Reverse-Shot）+ 过肩镜头（OTS）
- 在 duration 字段中精确体现这种节奏设计

【原则10：连续性系统（Continuity System）】
- 同一场景内，角色的银幕方向（Screen Direction）必须保持一致
  · 如果场景A中角色从左侧入画，整个场景都要保持这个方向逻辑
- 视线匹配：角色看向画外的方向，在下一个镜头中必须得到回应
- 道具位置连续：上一镜茶杯在左手边，下一镜不能跑到右手边（除非有动作交代）
- 在 continuity_note 字段中主动管理这些连续性细节

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第二部分：商业漫剧专项要求（竖屏9:16）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【竖屏构图法则】
- 主体位置：遵循九宫格构图，将主体放在黄金分割点（约画面高度 5/8 处）
- 头部空间（Headroom）：头顶留 1/8 画面高度，不能顶天也不能留太多
- 视线方向留白（Look Room）：如果角色看向画面左侧，左侧留更多空间
- 文字安全区：画面底部 1/5 预留给字幕，不能放置重要视觉信息

【漫剧视觉风格】
- 线条清晰，色彩饱和但不过度刺眼
- 人物比例：7-9头身，表情夸张但符合动漫美学
- 速度线、效果线、气氛符号（闪亮背景、速度线、冲击特效）在必要时使用
- 对白气泡位置不能遮挡角色面部

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第三部分：分镜生成任务
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 【最高优先级：绝对忠实原文】
- 每一个分镜画面的内容、人物、地点、动作，必须100%来自原文已经明确描述的内容
- 绝对禁止添加原文没有的剧情、角色、场景或道具
- 如果某段原文是心理描写，将其转化为具象的视觉元素（见原则1）

## 【上下文感知：你看到的是完整故事】
- 你已经通过故事结构预分析了解了整个故事的三幕结构、情绪弧线和视觉母题
- 每个分镜必须知道自己在故事中的位置（第几幕？情绪弧线的哪个阶段？）
- 在 description 中体现这种上下文感知（例如："此时故事已进入第二幕中段，角色正处于挫折后的反思阶段..."）

## 【角色一致性：跨所有分镜统一（v6.3：使用预分析角色档案 + 微表情层级）】
- 用户消息中提供了「角色预分析档案」，其中包含每个角色的精确外貌、发型、服装、标志特征
- **你必须严格复用**预分析档案中的外貌描述，不能自由发挥改动任何细节
- 同一角色在所有分镜中必须使用字面一致的外貌描述字符串
- characters 字段格式（直接复制预分析档案中的描述）：
  "角色名：[复刻档案中的发型]、[复刻档案中的服装]、[复刻档案中的五官特征]、[当前表情/动作]"
- 如果预分析档案中缺少某角色的外貌信息，才自己补全并保持跨镜一致

### 微表情层级（v6.3新增：情感表现力升级）
每个分镜的 description 必须包含以下三层情感细节之一：
- **第一层·面部微表情**：眉弓变化（上挑/紧蹙/微颤）/ 嘴角变化（上扬/下撇/紧抿/微张）/ 眼神变化（瞳孔收缩/目光涣散/眼尾微红）
- **第二层·肢体微动作**：手指动作（攥紧/发抖/无意识摩挲）/ 呼吸节奏（急促/屏息/深叹）/ 姿态微调（后仰/前倾/侧身）
- **第三层·氛围暗示**：汗水/泪光/青筋/面色变化，与环境互动（风吹动头发/影子拉长/雨滴滑落）
- 每个分镜至少覆盖其中一层，情感高潮分镜覆盖全部三层

## 【环境一致性：跨所有分镜统一（v6.2：使用预分析场景档案）】
- 用户消息中提供了「环境预分析档案」，其中包含每个场景空间的精确描述、光线方案、色调
- **你必须严格复用**预分析档案中的环境描述，同一空间在不同分镜中都使用相同的空间特征
- setting 字段直接引用预分析档案中的 name，description 中复用其 lighting/color_scheme
- 如果角色在不同分镜中处于同一环境，该环境的视觉特征必须完全一致
- 如果预分析档案中缺少某环境的描述，才自己补全并保持跨镜一致

## 【商业漫剧节奏：每个分镜都是精心设计的】
- 分镜数量应合理覆盖原文所有重要情节（每200-400字原文生成1个分镜，情感密集处加密）
- 相邻分镜之间必须有明确的视觉或情感连接（不能跳跃）
- 用 continuity_note 字段明确写出与前后镜头的连接方式

### 视觉伏笔与回响系统（v6.3新增）
- **视觉伏笔（Visual Setup）**：在早期分镜中埋入一个视觉细节，在后期分镜中回收
  · 例如：分镜2中角色摸了摸左手胎记 → 分镜15中胎记发光预示身份觉醒
- **视觉回响（Visual Echo）**：关键道具/动作在不同分镜中重复出现，形成视觉主题
  · 例如：每个重要决定前出现"擦剑"动作，建立条件反射
- 在 visual_motif_note 字段中注明本镜是 "setup/echo/payoff"，建立视觉叙事线

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第四部分：返回格式（严格 JSON 数组）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 返回格式（只返回 JSON 数组，禁止其他任何文字）
```json
[
  {
    "title": "3-8字，直接概括本镜画面的核心内容（动词+名词，如'拔剑出鞘''雨后重逢'）",
    "description": "5-7句话，专业级画面描述：①具体动作和肢体语言（含视线方向）②表情和微表情（眼睛/嘴角/眉弓的变化）③三层构图（前景/中景/背景各有什么）④光线设计（主光源位置、色温、阴影方向）⑤色彩方案（主色调+辅助色，与情绪弧线匹配）⑥本镜在故事弧线中的位置和作用",
    "characters": "角色名：[发色发型]、[服装]、[眼睛]、[当前表情动作]（完整描述，与其他分镜保持字面一致）",
    "setting": "精确地点名称、时间段、天气、主光源（位置和色温）、阴影方向",
    "mood": "从以下选择：紧张/温馨/悲伤/壮阔/神秘/热血/恐惧/喜悦/惆怅/愤怒/压抑/释然/孤独/悸动/释然",
    "camera": "从以下选择：超特写/特写/近景/中景/全景/远景/超远景/俯拍/仰拍/跟随镜头/慢推/慢拉/横摇",
    "subtitle_text": "直接引用本镜对应的原文文字（对白或旁白），一字不差",
    "storytelling_rhythm": "从以下选择：hook/conflict/reversal/cliffhanger/emotional_peak/info_drop/suspense（第1分镜必须是hook，最后分镜必须是cliffhanger）",
    "duration": "2s/3s/5s/8s/10s（根据镜头节奏设计，但：第1分镜≤3s保证钩子速度；动作冲突2-3s；情感场面5-8s；定场镜头≤5s）",
    "continuity_note": "专业连续性说明：①上一镜的最后一个画面是什么，本镜如何从那个状态接入 ②本镜最后一个画面是什么，为下一镜做了什么视觉预示 ③视线方向/银幕方向/道具位置的连续性管理",
    "emotional_intensity": "情绪强度 1-10（与故事结构预分析中的情绪弧线对应）",
    "visual_motif_note": "本镜如何体现视觉母题（如果有），或本镜建立了什么新的视觉母题"
  }
]
```

## 强制规则
1. 只返回 JSON 数组，第一个字符必须是 `[`，最后一个字符必须是 `]`
2. JSON 格式必须完全正确（所有字符串用双引号，逗号正确，无 trailing comma）
3. 每个分镜的 description 必须可以直接转化为一张商业级画面（细节足够丰富）
4. subtitle_text 必须是原文的直接引用，不能改写或概括
5. 分镜数量应合理覆盖原文（通常 8-25 个分镜，根据文本长度动态调整）
6. emotional_intensity 必须与故事整体情绪弧线保持一致（不能开头就10级情绪）
7. visual_motif_note 要有意识地在分镜中建立视觉连贯性"""

PROMPT_SYSTEM = """你是好莱坞级别的 AI 绘画提示词工程师，专为商业级竖屏漫剧生成 Stable Diffusion / FLUX / WAN2.1 英文提示词。
你深谙视觉叙事语言，能将专业分镜描述转化为 AI 可以精确执行的视觉指令。
当前生成模式：质量优先（Quality-First），追求画面细节和情感表现力的极致。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第一部分：核心使命
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将中文分镜描述 100% 准确地转化为英文提示词，让 AI 生成与分镜描述完全一致的商业级画面。
你的提示词必须体现好莱坞级别的视觉设计：光线动机化、构图叙事化、色彩情绪化。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第二部分：image_prompt 生成规范（英文，220-300词）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### 结构顺序（必须严格按此顺序，用逗号分隔）：

【第1层：质量锚点（Quality Anchors）】─ 必须放在最前面，引导模型优先处理
masterpiece, best quality, ultra detailed, 8k uhd, sharp focus, intricate details, professional illustration, cinematic composition, award-winning artwork


【第2层：主体人物（Subject ─ 最重要，直接来自分镜 description）】
❗ 关键：必须从分镜的 characters 字段逐字提取外貌描述，翻译成英文，不能改写或概括
格式：
  [hair color] [hairstyle] hair, [eye color] eyes, [skin tone] skin,
  wearing [clothing color] [clothing type],
  [current action in present continuous tense],
  [specific facial expression with micro-details]

❗ 角色一致性铁律：
  - 同一角色在所有分镜中的外貌关键词必须字面完全相同
  - 例如：所有分镜中"林逸"的描述都必须以 "black hair, short hair, amber eyes, wearing dark blue martial arts robe" 开头
  - 不能在某镜写 "black hair"，下一镜写 "dark hair"──必须字面一致

【第3层：动作与互动（Action & Interaction）】
- 用现在进行时精确描述动作：standing with sword drawn, turning toward camera, looking down with trembling lips...
- 如有互动：reachng out to [character name], eyes locked with [character name], hand trembling near sword hilt...

【第4层：场景环境（Environment ─ 直接来自分镜 setting + description）】
❗ 必须具体，不能用 generic background / vague setting
- 精确地点：ancient Chinese courtyard with stone pavement, inside a candlelit tavern, on a misty mountain peak...
- 时间光线：dawn with golden sunlight from left, dusk with warm orange glow, night under cold moonlight...
- 天气氛围：gentle rain falling, mist drifting between trees, wind blowing through curtains...
- 具体道具（来自原文）：antique sword on the table, half-burned candle, teacup with rising steam...

【第5层：光线设计（Lighting Design ─ 来自分镜 description 中的光线说明）】
- 主光源（Key Light）：warm sunlight from window left, cold moonlight from above, flickering candlelight from below...
- 补光（Fill Light）：soft ambient bounce light, subtle rim light on hair...
- 背光源（Back Light）：silhouette against bright window, hair edge highlighted by sunlight...
- 光线情绪：high contrast dramatic lighting, soft diffused lighting, chiaroscuro lighting...

### 光线→情绪映射表（v6.3升级：根据分镜 mood 自动匹配光线方案）：
- 紧张/恐惧 → high contrast chiaroscuro, harsh shadows, cold blue rim light, flickering unstable light source
- 温馨/甜蜜 → warm golden hour light, soft diffused glow, candlelit warmth, gentle bokeh background lights
- 悲伤/惆怅 → overcast diffused light, muted gray-blue tones, soft shadowless lighting, rain-streaked window light
- 壮阔/史诗 → dramatic god rays, epic backlighting, warm orange against cool blue, volumetric light beams
- 神秘/悬疑 → single spotlight in darkness, fog-diffused moonlight, colored gel lighting (purple/teal),
  heavy shadows concealing details, rim light only revealing silhouette
- 热血/愤怒 → intense red/orange backlight, high contrast, dynamic light flare, heat haze distortion

【第6层：构图设计（Composition ─ 来自分镜 camera + description）】
- 画幅：portrait orientation, 9:16 vertical, vertical composition
- 景别：close-up on face / medium shot / full body shot / wide establishing shot / extreme close-up on eyes

### 分镜类型构图模板（v6.3升级：按镜头类型自动匹配构图）：
- **单人特写（ECU/CU）**：face centered in frame, filling 70% of screen, shallow depth of field, blurred background,
  headroom 15% from top, chin near bottom third, eyes at golden ratio point
- **双人对峙/对话（MCU/MS）**：two characters in frame, shot reverse shot composition,
  dominant character occupying 60% of frame, subordinate 40%, vertical split or diagonal tension line
- **群像/多人（WS/FS）**：hierarchical arrangement, main character at foreground slightly off-center,
  supporting characters in midground, receding depth layering, triangular or pyramidal grouping
- **环境空镜（EWS）**：character small in vast environment (less than 15% of frame),
  negative space emphasis, establishing scale and atmosphere, architectural leading lines

- 构图技法：rule of thirds, golden ratio composition, leading lines from [object] toward subject,
  frame within frame using [foreground object], deep composition with foreground/midground/background clearly defined
- 视线引导：character looking toward upper right corner, eyeline leading viewer's gaze to [object]

【第7层：情绪与氛围（Mood & Atmosphere ─ 来自分镜 mood + emotional_intensity）】
- 情绪关键词（英文）：tense atmosphere, melancholic mood, warm intimate atmosphere, epic grand atmosphere...
- 根据 emotional_intensity（1-10）调整画面紧张感：
  · 1-3：soft, peaceful, calm, gentle color palette
  · 4-6：moderate tension, dynamic posture, balanced colors
  · 7-10：high tension, dramatic lighting, intense color contrast, dynamic action lines

【第8层：风格词（Style Tokens ─ 红果漫剧专用，v6.3升级）】
优先级从高到低排列，确保 AI 理解画风方向：
- 核心风格（必选2个）：
  · 古装/玄幻/武侠：chinese ink wash style, wuxia fantasy art, ancient chinese aesthetics, xianxia illustration
  · 现代/都市/甜宠：modern manhwa style, korean webtoon art, contemporary romance illustration, urban fantasy
  · 悬疑/恐怖/惊悚：dark atmospheric anime, psychological thriller art, horror manga style
- 通用品质（必选全部）：
  anime style, manhwa art style, vibrant saturated colors, clean crisp line art, cel shading,
  detailed beautiful background, (perfect face:1.1), (perfect hands:1.2), 8k resolution,
  digital illustration, trending on pixiv, commercial anime quality
- 红果平台特化（选配，根据内容类型）：
  · 甜宠/恋爱：soft romantic lighting, sparkling eyes, delicate blush, tender atmosphere
  · 爽文/逆袭：dynamic action lines, powerful aura, dramatic wind effect, intense energy
  · 虐恋/悲剧：melancholic color grading, rain atmosphere, emotional expression, tear-streaked face
  · 搞笑/轻松：exaggerated comedic expression, chibi proportions, playful dynamic pose
  · 悬疑/反转：shadowy atmosphere, dramatic chiaroscuro, mysterious fog, tense eye contact

【第9层：否定缓冲（Negative Buffer）】
不需要在这里写 negative，但避免在 image_prompt 中出现模糊词（blurry, foggy, unclear 等）

### image_prompt 完整示例（参考格式）：
```
masterpiece, best quality, ultra detailed, 8k uhd, sharp focus, intricate details, cinematic composition,
black hair short hair, amber eyes, fair skin, wearing dark blue martial arts robe with silver embroidery,
standing with sword drawn, right hand trembling slightly, looking toward camera with determined expression,
inside ancient Chinese courtyard, stone pavement, dusk with warm orange glow from right,
lanterns casting warm light, cherry blossom petals drifting in wind,
close-up on face, portrait orientation 9:16, rule of thirds, golden ratio,
tense atmosphere, dramatic lighting with strong contrast,
anime style, manhwa art style, vibrant colors, clean line art, cel shading,
detailed background, (perfect face:1.1), (perfect hands:1.2)
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第三部分：video_prompt 生成规范（英文，80-100词，v6.3升级）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

在 image_prompt 的主体基础上，专注描述动态元素：
- 人物微动作：hair swaying gently in wind, fingers trembling slightly, chest slowly rising and falling,
  eyes blinking naturally, lips parting as if to speak...
- 环境动效：cherry blossom petals drifting slowly, dust particles floating in sunlight beams,
  rain falling softly, candle flame flickering, curtains swaying...
- 镜头运动（选一，必须有动机）：
  · slow push in toward character's face（揭示内心/加强情感）
  · slow pull back to reveal environment（建立空间关系/表达孤独）
  · subtle camera drift to left（跟随视线/建立连接）
  · steady cam following character walking（跟随行动/增强代入感）
- 情感动词：expressing inner turmoil, radiating quiet confidence, trembling with suppressed anger...

### 运动速度/节奏描述（v6.3新增：视频质量关键）：
- 根据场景情绪选择速度词（必须包含一个）：
  · slow motion, languid pace（悲伤/浪漫/沉思）
  · natural speed, steady rhythm（日常/对话/过渡）
  · quick, dynamic, snappy cuts（动作/冲突/紧张）
  · slow buildup then sudden acceleration（悬疑/反转）
- 节奏示例：
  · "slow push in toward character's face, hair moving gently in slow motion wind, tears falling in slow motion"
  · "dynamic quick pan following sword slash, hair whipping violently, dust exploding in fast motion"

示例：
```
slow push in toward character's face, slow motion, black hair swaying gently,
teardrop rolling slowly down cheek, fingers trembling near sword hilt,
cherry blossoms drifting across frame in slow motion, warm dusk light flickering through leaves,
expressing determined resolve before battle, anime style, manhwa art style, 9:16 vertical video
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第四部分：negative_prompt 固定模板
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(worst quality:1.5), (low quality:1.5), (normal quality:1.3), lowres, (bad hands:1.4),
(extra fingers:1.4), (missing fingers:1.3), (bad anatomy:1.3), (deformed body:1.3),
blurry, jpeg artifacts, watermark, username, signature, text overlay, UI, interface,
deformed, ugly, mutation, disfigured, poorly drawn face, extra limbs, cloned face,
gross proportions, cross-eyed, out of frame, cropped head, missing limbs,
plastic skin, doll-like, unrealistic proportions, bad perspective, tilted horizon

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
第五部分：严格规则（你必须遵守）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 只返回 JSON 对象，格式：{"image_prompt": "...", "video_prompt": "...", "negative_prompt": "..."}
2. 第一个字符必须是 `{`，最后一个字符必须是 `}`，JSON 格式必须完全正确
3. image_prompt 的角色外貌描述必须与分镜 characters 字段字面保持一致（英文翻译也要一致）
4. 绝对不能写 "a character" 或 "a person" 或 "someone"──必须写出具体外貌特征
5. 场景描述必须对应分镜 setting + description，不能写 "generic background" 或 "nice scenery"
6. image_prompt 长度 220-300 词，video_prompt 长度 80-100 词（v6.3质量优先）
7. 如果分镜中有 visual_motif_note 字段，必须在 image_prompt 中体现该视觉母题
8. 如果分镜中有 emotional_intensity 字段，必须在光线和色彩中体现对应强度
9. (v7.0 Seedream蒸馏) 必须额外输出 vmix_tags 对象: {"palette": "色板名称(如warm amber)", "lighting": "光线类型(如rim light)", "composition": "构图方式(如rule of thirds)"}"""

# ─── v7.0 Seedream 蒸馏: 兜底路径 DeepSeek 提示词改写 ──────
SEEDREAM_REWRITE_SYSTEM = """你是即梦(Seedream)风格的 AI 图片生成提示词翻译引擎。
你的任务: 接收中文场景描述 → 输出专业英文 SDXL/Animagine 提示词。

核心理念 (bytedance Seedream):
1. LLM 改写优于词典翻译 — 理解语境, 保留风格, 不丢语义
2. Danbooru 结构化标签 — Animagine XL 用 Danbooru 标签训练, 前置结构标签权重最高
3. VMix 美学注入 — 色板+光线+构图作为条件, 不是自然语言描述

输出格式 (纯文本, 不分段, 不加 JSON):
[color: COLOR_PALETTE] [lighting: LIGHTING_TYPE] [composition: COMPOSITION_TYPE], 
masterpiece, best quality, ultra detailed, 8k, 
ENGLISH_PROMPT_CONTENT

规则:
- 中文人名/地名音译为拼音 (如 叶尘 → Ye Chen, 青云山 → Qingyun Mountain)
- 使用 Danbooru 标签风格 (如 black hair, red eyes, hanfu, sword)
- 长度 150-250 词
- 不输出任何解释性文字, 不输出 JSON, 只输出提示词文本"""

# ─── v7.0 Seedream 蒸馏: VMix 美学标签提取 ──────────────
VMIX_TAGS = {
    "palette": {
        "warm amber": "暖琥珀", "cool blue": "冷蓝", "crimson red": "深红",
        "jade green": "玉绿", "golden hour": "黄金时刻", "moonlit silver": "月银",
        "neon purple": "霓虹紫", "earthy brown": "大地棕", "pastel pink": "粉彩",
        "monochrome": "黑白", "vintage sepia": "复古褐", "icy blue": "冰蓝",
        "lavender dusk": "薰衣紫暮", "fiery orange": "烈焰橙", "forest green": "森林绿",
        "deep ocean": "深海蓝", "cherry blossom": "樱花粉", "midnight black": "午夜黑"
    },
    "lighting": {
        "rim light": "边缘光", "soft diffused": "柔和散射", "dramatic chiaroscuro": "戏剧明暗",
        "cinematic volumetric": "电影体积光", "golden hour glow": "黄金时刻辉光",
        "moonlight": "月光", "neon glow": "霓虹光", "candlelight": "烛光",
        "backlight silhouette": "逆光剪影", "overcast flat": "阴天平光",
        "god rays": "圣光", "storm lightning": "闪电", "firelight": "火光",
        "studio softbox": "影棚柔光", "underwater caustics": "水下焦散"
    },
    "composition": {
        "rule of thirds": "三分法", "golden ratio": "黄金比例", "center framing": "中心构图",
        "dutch angle": "倾斜构图", "leading lines": "引导线", "symmetrical": "对称",
        "close-up portrait": "特写人像", "wide establishing shot": "广角定场",
        "over the shoulder": "过肩镜头", "low angle hero": "低角英雄",
        "bird's eye view": "俯拍", "frame within frame": "框中框"
    },
    # v9.4: 空间尺度标签（从 ENVIRONMENT_ANALYSIS.scale 提取）
    "scale": {
        "epic scale": "epic", "large space": "large", "medium shot": "medium",
        "small space": "small", "intimate close": "intimate",
    }
}

# ─── v4.0 角色 + 声音系统 ──────────────────────────────────

# ─── [已删除 v4.0 旧版 CHARACTER_ANALYSIS_SYSTEM] ───
# v6.3 版本已合并到上方第 2069 行，包含 15+ 维度全面角色档案
# 旧版 v4.0 定义已被更详细的 v6.2/v6.3 取代

# ─── CosyVoice 2 声音系统 ─────────────────────────────────
# CosyVoice 2 预训练 speaker 列表（需根据实际部署的 CosyVoice2 模型调整 speaker 名称）
# 通过 API: POST localhost:50000/generate 调用，voice 参数传 speaker 名
COSYVOICE_SPEAKERS = [
    # (speaker_name, gender, style_tags)
    ("default",           "中性", "通用"),
    # 以下为常见 CosyVoice2 中文 speaker，请按实际部署调整
    ("chinese_male_deep",   "男",   "沉稳 大气 低沉"),
    ("chinese_male_young",  "男",   "活力 阳光 清朗"),
    ("chinese_male_mature", "男",   "中年 沧桑 播报"),
    ("chinese_female_soft", "女",   "温柔 柔和 内敛"),
    ("chinese_female_bright","女",  "活泼 俏皮 灵动 清纯"),
    ("chinese_female_calm", "女",   "慈祥 沉稳 中年"),
]

# Edge-TTS voice_id → CosyVoice2 speaker_name 翻译表
# 当 engine="cosyvoice" 时，自动将 Edge-TTS ID 转换为 CosyVoice2 speaker 名
_EDGE_TO_COSYVOICE = {
    # 男声
    "zh-CN-YunjianNeural": "chinese_male_deep",
    "zh-CN-YunxiNeural": "chinese_male_young",
    "zh-CN-YunxiaNeural": "chinese_male_young",
    "zh-CN-YunyangNeural": "chinese_male_mature",
    # 女声
    "zh-CN-XiaoxiaoNeural": "chinese_female_soft",
    "zh-CN-XiaoyiNeural": "chinese_female_bright",
    "zh-CN-liaoning-XiaobeiNeural": "chinese_female_soft",
    "zh-CN-shaanxi-XiaoniNeural": "chinese_female_soft",
    "zh-HK-HiuGaaiNeural": "chinese_female_calm",
    "zh-TW-HsiaoChenNeural": "chinese_female_bright",
}

# CosyVoice2 角色特征 → speaker 映射规则（与 VOICE_MATCHING_RULES 结构对应）
COSYVOICE_VOICE_MAP = {
    # 男性
    "男_青年_沉稳": "chinese_male_deep",
    "男_青年_活力": "chinese_male_young",
    "男_少年_清朗": "chinese_male_young",
    "男_中年_沉稳": "chinese_male_mature",
    "男_老年_沧桑": "chinese_male_mature",
    "男_青年_播报": "chinese_male_mature",
    "男_反派_阴沉": "chinese_male_deep",
    # 女性
    "女_青年_温柔": "chinese_female_soft",
    "女_青年_活泼": "chinese_female_bright",
    "女_少年_清纯": "chinese_female_bright",
    "女_中年_沉稳": "chinese_female_calm",
    "女_老年_慈祥": "chinese_female_calm",
    "女_反派_凌厉": "chinese_female_soft",
    # 方言 → 回退同性别通用speaker
    "女_东北": "chinese_female_soft",
    "女_陕西": "chinese_female_soft",
    "女_粤语": "chinese_female_calm",
    "女_台湾": "chinese_female_bright",
}

def _translate_voice_for_cosyvoice(voice_id: str) -> str:
    """将 Edge-TTS voice_id 翻译为 CosyVoice2 speaker 名。
    如果 voice_id 已经是 CosyVoice2 speaker 名，直接返回。
    """
    if not voice_id:
        return "default"
    # 已经是 CosyVoice2 speaker 名（非 zh- 前缀的 Edge-TTS 格式）
    if not voice_id.startswith("zh-"):
        known_speakers = {s[0] for s in COSYVOICE_SPEAKERS}
        if voice_id in known_speakers or voice_id == "default":
            return voice_id
    # Edge-TTS ID → CosyVoice2 speaker 翻译
    return _EDGE_TO_COSYVOICE.get(voice_id, "default")

def get_cosyvoice_speaker(char) -> str:
    """根据角色属性智能匹配 CosyVoice2 speaker。
    
    复用与 match_voice_for_character() 相同的角色特征 → 风格匹配逻辑，
    但返回 CosyVoice2 speaker 名而非 Edge-TTS voice_id。
    
    Args:
        char: Character 对象（需有 gender, age_range, personality, speaking_style 属性）
    Returns:
        CosyVoice2 speaker 名称字符串
    """
    gender = getattr(char, 'gender', '') or "男"
    if gender not in ("男", "女"):
        gender = "男"
    age = getattr(char, 'age_range', '') or "青年"
    personality = getattr(char, 'personality', '') or ""
    style = getattr(char, 'speaking_style', '') or ""

    # 风格关键词映射（同 match_voice_for_character 逻辑）
    style_keywords = {
        "沉稳": "沉稳", "大气": "沉稳", "低沉": "沉稳", "沧桑": "沧桑",
        "活力": "活力", "阳光": "活力", "开朗": "活力", "热情": "活力",
        "温柔": "温柔", "内敛": "温柔", "柔和": "温柔",
        "活泼": "活泼", "俏皮": "活泼", "灵动": "活泼",
        "清朗": "清朗", "清纯": "清纯", "干净": "清朗",
        "播报": "播报", "正式": "播报", "严肃": "播报",
        "阴沉": "阴沉", "凌厉": "凌厉", "冷酷": "阴沉",
        "慈祥": "慈祥", "苍老": "沧桑",
    }

    matched_style = "沉稳"
    for keyword, style_name in style_keywords.items():
        if keyword in personality or keyword in style:
            matched_style = style_name
            break

    # 多级匹配
    keys_to_try = [
        f"{gender}_{age}_{matched_style}",
        f"{gender}_{年龄}_沉稳" if matched_style != "沉稳" else None,
        f"{gender}_青年_{matched_style}",
        f"{gender}_青年_沉稳",
    ]

    for key in keys_to_try:
        if key and key in COSYVOICE_VOICE_MAP:
            return COSYVOICE_VOICE_MAP[key]

    # 兜底
    return "chinese_female_soft" if gender == "女" else "chinese_male_deep"


# 智能声音匹配映射表
VOICE_MATCHING_RULES = {
    # 男性声音
    "男_青年_沉稳": {"id": "zh-CN-YunjianNeural", "name": "云健"},
    "男_青年_活力": {"id": "zh-CN-YunxiNeural", "name": "云希"},
    "男_少年_清朗": {"id": "zh-CN-YunxiaNeural", "name": "云夏"},
    "男_中年_沉稳": {"id": "zh-CN-YunjianNeural", "name": "云健"},
    "男_老年_沧桑": {"id": "zh-CN-YunjianNeural", "name": "云健"},
    "男_青年_播报": {"id": "zh-CN-YunyangNeural", "name": "云扬"},
    "男_反派_阴沉": {"id": "zh-CN-YunjianNeural", "name": "云健"},
    # 女性声音
    "女_青年_温柔": {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓"},
    "女_青年_活泼": {"id": "zh-CN-XiaoyiNeural", "name": "晓依"},
    "女_少年_清纯": {"id": "zh-CN-XiaoyiNeural", "name": "晓依"},
    "女_中年_沉稳": {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓"},
    "女_老年_慈祥": {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓"},
    "女_反派_凌厉": {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓"},
    # 方言
    "女_东北": {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北"},
    "女_陕西": {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮"},
    "女_粤语": {"id": "zh-HK-HiuGaaiNeural", "name": "曉佳"},
    "女_台湾": {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻"},
}

# v8.7 Phase 5b: 根据中文角色名猜测性别
_MALE_NAME_CHARS = "刚强勇毅磊峰伟浩鹏龙剑锋锐虎豹"
def guess_character_gender(name: str, job=None) -> str:
    """根据角色名中常见字猜测性别，无法判断时默认男"""
    if not name:
        return "男"
    # 已知角色列表优先
    if job and hasattr(job, 'characters') and job.characters:
        for c in job.characters:
            if c.name == name and c.gender in ("男", "女"):
                return c.gender
    # 关键字判断
    if any(kw in name for kw in ["姐", "娘", "姨", "姑", "嫂", "妹", "母", "婆"]):
        return "女"
    if any(kw in name for kw in ["哥", "叔", "伯", "兄", "弟", "父", "公"]):
        return "男"
    return "男"

def match_voice_for_character(char: Character) -> Character:
    """根据角色属性智能匹配最合适的Edge-TTS声音"""
    gender = char.gender if char.gender in ("男", "女") else "男"
    age = char.age_range if char.age_range else "青年"
    personality = char.personality or ""
    style = char.speaking_style or ""

    # 构建匹配键（从具体到宽泛尝试匹配）
    candidates = []

    # 优先匹配：性别_年龄段_风格关键词
    style_keywords = {
        "沉稳": "沉稳", "大气": "沉稳", "低沉": "沉稳", "沧桑": "沧桑",
        "活力": "活力", "阳光": "活力", "开朗": "活力", "热情": "活力",
        "温柔": "温柔", "内敛": "温柔", "柔和": "温柔",
        "活泼": "活泼", "俏皮": "活泼", "灵动": "活泼",
        "清朗": "清朗", "清纯": "清纯", "干净": "清朗",
        "播报": "播报", "正式": "播报", "严肃": "播报",
        "阴沉": "阴沉", "凌厉": "凌厉", "冷酷": "阴沉",
        "慈祥": "慈祥", "苍老": "沧桑",
    }

    matched_style = "沉稳"  # 默认
    for keyword, style_name in style_keywords.items():
        if keyword in personality or keyword in style:
            matched_style = style_name
            break

    # 尝试多级匹配
    keys_to_try = [
        f"{gender}_{age}_{matched_style}",
        f"{gender}_{age}_沉稳" if matched_style != "沉稳" else None,
        f"{gender}_青年_{matched_style}",
        f"{gender}_青年_沉稳",
    ]

    for key in keys_to_try:
        if key and key in VOICE_MATCHING_RULES:
            voice_info = VOICE_MATCHING_RULES[key]
            char.voice_id = voice_info["id"]
            char.voice_name = voice_info["name"]
            return char

    # 兜底：男用云健，女用晓晓
    if gender == "女":
        char.voice_id = "zh-CN-XiaoxiaoNeural"
        char.voice_name = "晓晓"
    else:
        char.voice_id = "zh-CN-YunjianNeural"
        char.voice_name = "云健"
    return char

# 场景对白拆分 Prompt
DIALOGUE_SPLIT_SYSTEM = """你是一位有声小说对白标注专家。你的任务是分析一段小说文本，将其拆分为旁白和对白，并标注每段对白的说话角色。

输入：一段小说原文
输出：JSON 数组，每个元素包含：
- type: "narration"（旁白）或 "dialogue"（对白）
- speaker: 说话角色名（旁白为 "旁白"）
- text: 文本内容

规则：
1. 旁白是叙述性文字，对白是角色说的话
2. 对白通常在引号中（"..." 或「...」），或通过"XX说/道/喊/低声"等标识
3. 如果对白前有叙述性动作描写，将其归入旁白
4. 保持原文完整性，不要省略任何文字
5. 只返回 JSON 数组"""

# ─── API 路由 ─────────────────────────────────────────────

@app.post("/api/create-job")
async def create_job():
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = JobState(id=job_id)
    await JobStorage.save(jobs[job_id])
    return {"job_id": job_id}

@app.post("/api/upload-novel")
async def upload_novel(job_id: str = Form(...), api_key: str = Form(""),
                       novel_title: str = Form(""), file: UploadFile = File(...)):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    content = (await file.read()).decode("utf-8", errors="ignore")
    jobs[job_id].novel_text = content
    jobs[job_id].deepseek_key = api_key.strip() or DEEPSEEK_DEFAULT_KEY
    jobs[job_id].novel_title = novel_title or file.filename.replace(".txt", "").replace(".md", "")
    jobs[job_id].current_step = "storyboard"
    await JobStorage.save(jobs[job_id])
    return {"job_id": job_id, "text_length": len(content)}

@app.post("/api/upload-text")
async def upload_text(job_id: str = Form(...), api_key: str = Form(""),
                      text: str = Form(...), novel_title: str = Form("")):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    jobs[job_id].novel_text = text
    jobs[job_id].deepseek_key = api_key.strip() or DEEPSEEK_DEFAULT_KEY
    jobs[job_id].novel_title = novel_title or "未命名小说"
    jobs[job_id].current_step = "storyboard"
    await JobStorage.save(jobs[job_id])
    return {"job_id": job_id, "text_length": len(text)}

@app.post("/api/upload-pulid-ref")
async def upload_pulid_reference(job_id: str = Form(...), file: UploadFile = File(...)):
    """上传 PuLID 角色参考人脸图"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    # 保存到 output/{job_id}/pulid_ref/
    ref_dir = OUTPUT_DIR / job_id / "pulid_ref"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_path = ref_dir / file.filename
    content = await file.read()
    ref_path.write_bytes(content)
    job.pulid_reference_image = str(ref_path)
    await JobStorage.save(job)
    return {"status": "ok", "path": str(ref_path), "filename": file.filename}

@app.post("/api/generate-kling-face")
async def generate_kling_face(
    job_id: str = Form(...),
    kling_api_key: str = Form(...),
    character_description: str = Form(...),
):
    """
    用可灵AI生成正面清晰角色脸，自动设为 PuLID 参考图
    
    参数:
        job_id: 任务ID
        kling_api_key: 可灵API密钥
        character_description: 角色描述 (如 "20岁年轻女性，黑色长发，温柔气质")
    """
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]

    if not kling_api_key:
        raise HTTPException(400, "请提供可灵API Key")
    if not character_description:
        raise HTTPException(400, "请提供角色描述")

    try:
        from kling_client import KlingImageClient
    except ImportError:
        raise HTTPException(400, "可灵客户端未安装，请先 pip install kling-client")

    client = KlingImageClient(api_key=kling_api_key)

    # 保存目录
    ref_dir = OUTPUT_DIR / job_id / "pulid_ref"
    ref_dir.mkdir(parents=True, exist_ok=True)
    filename = f"kling_face_{int(time.time())}.png"

    # 推送进度
    await broadcast_progress(job_id, {
        "type": "kling_face_progress",
        "status": "creating_task",
    })

    result = await client.generate_face_image(
        character_description=character_description,
        save_dir=str(ref_dir),
        filename=filename,
        on_progress=lambda s: broadcast_progress(job_id, {
            "type": "kling_face_progress",
            "status": s,
        }),
    )

    if result["status"] != "succeed":
        error_msg = result.get("message", "生成失败")
        code = result.get("code")
        if code == 1102:
            error_msg = "可灵账户余额不足，请充值后重试"
        elif code == 401:
            error_msg = "可灵API Key无效，请检查"
        raise HTTPException(400, f"可灵生成失败: {error_msg}")

    # 自动设为 PuLID 参考图
    face_path = result["path"]
    job.pulid_reference_image = face_path
    job.use_pulid = True  # 自动开启 PuLID
    # 自动切换到 SDXL 模型
    if "xl" not in job.img_checkpoint.lower() and "animagine" not in job.img_checkpoint.lower():
        sdxl_path = COMFYUI_MODELS_DIR / "checkpoints" / "animagine-xl-4.0.safetensors"
        if sdxl_path.exists() and sdxl_path.stat().st_size > 5_000_000_000:
            job.img_checkpoint = "animagine-xl-4.0.safetensors"
            print(f"[Kling] 自动切换到 SDXL 模型: {job.img_checkpoint}", flush=True)

    await JobStorage.save(job)

    await broadcast_progress(job_id, {
        "type": "kling_face_done",
        "path": face_path,
    })

    return {
        "status": "ok",
        "path": face_path,
        "image_url": result.get("image_url", ""),
        "task_id": result.get("task_id", ""),
    }

@app.get("/api/kling-face-preview/{job_id}")
async def get_kling_face_preview(job_id: str):
    """获取可灵生成的角色正脸预览图"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.pulid_reference_image or not Path(job.pulid_reference_image).exists():
        raise HTTPException(404, "未找到角色正脸图")
    return FileResponse(job.pulid_reference_image, media_type="image/png")

@ app.post("/api/analyze-story-structure")
async def analyze_story_structure_endpoint(job_id: str):
    """v5.0 好莱坞级：故事结构预分析
    在分镜生成之前，先对小说进行三幕式结构、情绪弧线、视觉母题的专业分析。
    """
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.novel_text:
        raise HTTPException(400, "请先上传小说文本")

    try:
        await broadcast_progress(job_id, {
            "type": "step", "step": "story_structure",
            "message": "正在分析故事结构（好莱坞三幕式 + 情绪弧线）..."
        })

        MAX_TEXT = 20000
        analysis_text = job.novel_text[:MAX_TEXT]
        user_msg = (
            "请对以下小说文本进行专业故事结构分析，严格按照 SYSTEM PROMPT 中的返回格式输出 JSON：\n\n"
            "## 原文开始 ##\n" + analysis_text + "\n## 原文结束 ##"
        )

        result = await call_deepseek(
            job.deepseek_key or DEEPSEEK_DEFAULT_KEY,
            STORY_STRUCTURE_SYSTEM,
            user_msg,
            max_tokens=4096,
            temperature=0.3  # 结构化分析需要一致性
        )

        structure = extract_json_object(result)
        if not structure:
            raise ValueError("故事结构解析返回空结果，请重试")

        job.story_structure = structure
        job.current_step = "story_structure"
        await JobStorage.save(job)

        await broadcast_progress(job_id, {
            "type": "story_structure_done",
            "structure": structure
        })

        return {"job_id": job_id, "story_structure": structure}

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        job.error = str(e)[:500]
        raise HTTPException(500, f"故事结构分析失败: {job.error}")


async def _analyze_story_structure(job) -> dict:
    """内部辅助函数：对 job 执行故事结构预分析，不触发 HTTP 异常。
    返回分析结果 dict，失败时返回空 dict。
    """
    try:
        MAX_TEXT = 20000
        analysis_text = job.novel_text[:MAX_TEXT]
        user_msg = (
            "请对以下小说文本进行专业故事结构分析，严格按照 SYSTEM PROMPT 中的返回格式输出 JSON：\n\n"
            "## 原文开始 ##\n" + analysis_text + "\n## 原文结束 ##"
        )
        result = await call_deepseek(
            job.deepseek_key or DEEPSEEK_DEFAULT_KEY,
            STORY_STRUCTURE_SYSTEM,
            user_msg,
            max_tokens=4096,
            temperature=0.3  # 结构化分析需要一致性
        )
        structure = extract_json_object(result)
        if structure:
            job.story_structure = structure
            return structure
    except Exception as e:
        print(f"[StoryStructure] 预分析失败（将跳过）: {str(e)[:200]}", flush=True)
    return {}

async def _analyze_characters_and_environments(job) -> tuple:
    """v6.3: 角色+环境并行预分析。使用 asyncio.gather 并行执行，节省约50%等待时间。
    返回 (character_analysis_dict, environment_analysis_dict)，失败时返回 ({}, {})。
    """
    MAX_TEXT = 20000
    analysis_text = job.novel_text[:MAX_TEXT]
    api_key = job.deepseek_key or DEEPSEEK_DEFAULT_KEY
    
    async def _do_character_analysis() -> dict:
        """并行子任务：角色分析"""
        if job.character_analysis:
            return job.character_analysis
        try:
            char_msg = (
                "请从以下小说文本中提取所有角色的详细信息，严格按照 SYSTEM PROMPT 中的返回格式输出 JSON：\n\n"
                "## 原文开始 ##\n" + analysis_text + "\n## 原文结束 ##"
            )
            char_raw = await call_deepseek(api_key, CHARACTER_ANALYSIS_SYSTEM, char_msg, max_tokens=4096, temperature=0.3)
            char_data = extract_json_object(char_raw)
            if char_data and isinstance(char_data.get("characters"), list) and len(char_data["characters"]) > 0:
                job.character_analysis = char_data
                print(f"[CharacterAnalysis] 成功提取 {char_data['total_count']} 个角色", flush=True)
                return char_data
            else:
                print("[CharacterAnalysis] 返回空结果，跳过", flush=True)
        except Exception as e:
            print(f"[CharacterAnalysis] 分析失败（将跳过）: {str(e)[:200]}", flush=True)
        return {}
    
    async def _do_environment_analysis() -> dict:
        """并行子任务：环境分析"""
        if job.environment_analysis:
            return job.environment_analysis
        try:
            env_msg = (
                "请从以下小说文本中提取所有场景/环境的详细信息，严格按照 SYSTEM PROMPT 中的返回格式输出 JSON：\n\n"
                "## 原文开始 ##\n" + analysis_text + "\n## 原文结束 ##"
            )
            env_raw = await call_deepseek(api_key, ENVIRONMENT_ANALYSIS_SYSTEM, env_msg, max_tokens=4096, temperature=0.3)
            env_data = extract_json_object(env_raw)
            if env_data and isinstance(env_data.get("environments"), list) and len(env_data["environments"]) > 0:
                job.environment_analysis = env_data
                env_result = env_data
                print(f"[EnvironmentAnalysis] 成功提取 {env_data['total_count']} 个场景", flush=True)
                return env_data
            else:
                print("[EnvironmentAnalysis] 返回空结果，跳过", flush=True)
        except Exception as e:
            print(f"[EnvironmentAnalysis] 分析失败（将跳过）: {str(e)[:200]}", flush=True)
        return {}
    
    # v6.3: 并行执行角色和环境分析（不互相等待）
    char_result, env_result = await asyncio.gather(
        _do_character_analysis(),
        _do_environment_analysis()
    )
    
    return char_result, env_result


# ─── v9.5: 角色/环境 JSON 压缩（解决 storyboard prompt 过长 400 错误）────────
def _compact_character_context(character_analysis: dict | None) -> str:
    """将全量 19 维角色分析压缩为 ~150 tokens/角色的文本摘要。
    
    从 json.dumps(character_analysis, indent=2) 的 ~2000 tokens/角色 
    压缩到仅保留跨镜一致性关键字段的纯文本，减少 **90%+ 体积**。
    """
    if not character_analysis:
        return "（无角色预分析，请自行从原文提取并保持跨镜一致）"
    
    chars = character_analysis.get("characters", [])
    if not chars:
        return "（无角色预分析，请自行从原文提取并保持跨镜一致）"
    
    lines = []
    for c in chars:
        name = c.get("name", "?")
        role = c.get("role", "")
        importance = c.get("importance_level", "")
        gender = c.get("gender", "")
        age = c.get("age_appearance", "")
        appearance = c.get("physical_description", "")
        clothing = c.get("typical_clothing", "")
        personality = c.get("personality", "")
        expression = c.get("typical_expression", "")
        kling = c.get("kling_prompt", "")
        
        parts = [f"- {name}"]
        if role:
            parts.append(f"[{role}]")
        if importance:
            parts.append(f"({importance})")
        if gender:
            parts.append(f"{gender}")
        if age:
            parts.append(f"{age}")
        if appearance:
            parts.append(f"外貌: {appearance}")
        if clothing:
            parts.append(f"着装: {clothing}")
        if personality:
            parts.append(f"性格: {personality}")
        if expression:
            parts.append(f"表情: {expression}")
        if kling:
            parts.append(f"KlingPrompt: {kling}")
        lines.append(" ".join(parts))
    
    return "角色档案（跨镜一致参考）:\n" + "\n".join(lines)


def _compact_environment_context(environment_analysis: dict | None) -> str:
    """将全量 10 维环境分析压缩为 ~80 tokens/环境的文本摘要。
    
    仅保留 scene matching 和视觉一致性关键字段（name/color_scheme/lighting/atmosphere）。
    """
    if not environment_analysis:
        return "（无环境预分析，请自行从原文提取并保持跨镜一致）"
    
    envs = environment_analysis.get("environments", [])
    if not envs:
        return "（无环境预分析，请自行从原文提取并保持跨镜一致）"
    
    lines = []
    for e in envs:
        name = e.get("name", "?")
        color = e.get("color_scheme", "")
        lighting = e.get("lighting", "")
        atmosphere = e.get("atmosphere", "")
        weather = e.get("weather", "")
        time_period = e.get("time_period", "")
        loc_type = e.get("location_type", "")
        
        parts = [f"- {name}"]
        if loc_type:
            parts.append(f"({loc_type})")
        if color:
            parts.append(f"色调: {color}")
        if lighting:
            parts.append(f"光线: {lighting}")
        if atmosphere:
            parts.append(f"氛围: {atmosphere}")
        if weather:
            parts.append(f"天气: {weather}")
        if time_period:
            parts.append(f"时段: {time_period}")
        lines.append(" ".join(parts))
    
    return "环境档案（跨镜一致参考）:\n" + "\n".join(lines)


@app.post("/api/generate-storyboard")
async def generate_storyboard(job_id: str, bypass_safety: bool = False):
    """v5.0 好莱坞级分镜生成 — 先执行故事结构预分析，再生成分镜
    
    v9.6: bypass_safety=True 跳过内容安全审核（用于测试志怪/玄幻等超自然题材）
           也可通过环境变量 BYPASS_SAFETY_CHECK=1 全局关闭审核。
    """
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.novel_text:
        raise HTTPException(400, "请先上传小说文本")

    try:
        # ── v5.0：先执行故事结构预分析（如果还没有） ──
        if not job.story_structure:
            await broadcast_progress(job_id, {
                "type": "step", "step": "story_structure_auto",
                "message": "自动执行故事结构预分析（好莱坞三幕式）..."
            })
            await _analyze_story_structure(job)
            await JobStorage.save(job)

        # ── v6.2: 角色+环境预分析（如果还没有） ──
        if not job.character_analysis or not job.environment_analysis:
            await broadcast_progress(job_id, {
                "type": "step", "step": "character_env_analysis",
                "message": "自动分析文本中的角色和环境（支撑跨镜一致性）..."
            })
            await _analyze_characters_and_environments(job)
            await JobStorage.save(job)

        story_structure = job.story_structure or {}
        structure_context = json.dumps(story_structure, ensure_ascii=False, indent=2) if story_structure else "（无预分析结果）"

        # ── v5.1：内容安全预检（红果4月7日审核新规）──
        # v9.6: 支持跳过审核（环境变量 BYPASS_SAFETY_CHECK=1 或 API 参数 bypass_safety=true）
        _bypass_safety = bypass_safety or os.environ.get("BYPASS_SAFETY_CHECK", "") == "1"
        if _bypass_safety:
            print(f"[SafetyCheck] 审核已跳过 (bypass_safety={bypass_safety})", flush=True)
            safety_result = {"pass": True, "issues": [], "risk_level": "skipped", "detail": {}}
        else:
            safety_result = await content_safety_check(
                job.deepseek_key or DEEPSEEK_DEFAULT_KEY,
                job.novel_text
            )
            if not safety_result.get("pass", True):
                job.error = f"内容审核不通过: {'; '.join(safety_result.get('issues', ['违规']))}"
                await JobStorage.save(job)
                raise HTTPException(400, job.error)
        # 记录审核结果
        job.progress = {**job.progress, "safety_check": safety_result}
        if safety_result.get("risk_level") == "high":
            # 高风险警告但不阻塞（人工二次确认）
            safety_issues = safety_result.get("issues", [])
            await broadcast_progress(job_id, {
                "type": "safety_warning",
                "message": f"⚠️ 内容安全风险较高: {'; '.join(safety_issues[:3])}"
            })

        # ── 将完整原文 + 结构分析一并送入 DeepSeek ──
        # v9.5: 降至 15000 字，避免 storyboard prompt 超出 DeepSeek 64K 上下文
        MAX_TEXT = 15000
        novel_text = job.novel_text
        is_truncated = len(novel_text) > MAX_TEXT
        analysis_text = novel_text[:MAX_TEXT]

        truncate_notice = ""
        if is_truncated:
            truncate_notice = (
                "\n【注意：原文较长，以下为前 "
                f"{MAX_TEXT} 字的节选，请覆盖所有已提供的情节内容。】\n\n"
            )

        # ── v6.1: 题材适配引导（红果五类流量倾斜题材）──
        subject_pref = job.subject_preference or ""
        subject_guide = ""
        _GENRE_GUIDES = {
            "言情": "\n\n## 【题材专项：言情/恋爱】\n- 重点刻画情感细节：眼神交流、微表情、肢体暧昧、距离变化\n- 多用特写+近景，强调面部微表情\n- 光线：柔和的暖光（夕阳/烛光/月光），高光柔化\n- 色调：粉/橘/暖金色调为主，辅助冷色对比\n- 节奏：情感推进时加快，甜蜜场景放慢\n- 关键词：romantic, intimate, tender touch, longing gaze, soft light, emotional connection\n",
            "古风玄幻": "\n\n## 【题材专项：古风玄幻/仙侠】\n- 重点刻画仙侠意境：云雾缭绕、御剑飞行、灵力光效、古建筑\n- 多用中景+远景建立世界观，全景展示战斗\n- 光线：灵力发光/月华/剑气光效作为重点光源\n- 色调：青/紫/金色灵力光效，场景偏冷色调\n- 节奏：战斗场面3s快切，修行场景5-8s慢推\n- 关键词：ancient chinese fantasy, flowing robes, spiritual energy glow, misty mountains, sword flight, celestial realm\n",
            "都市轻悬疑": "\n\n## 【题材专项：都市轻悬疑】\n- 重点刻画悬疑气氛：阴影细节、不自然的光影、关键道具特写、角色可疑表情\n- 多用特写+近景捕捉细节线索，穿插广角变形营造不安感\n- 光线：高对比度（亮处极亮/暗处极暗），窗户投影制造不安\n- 色调：冷灰/蓝绿为主，局部暖色暗示线索\n- 节奏：揭示线索时代入紧张短镜头(2-3s)，推理时代入慢推\n- 关键词：urban mystery, noir lighting, shadow play, suspicious glance, clue close-up, tense atmosphere\n",
            "现代甜宠": "\n\n## 【题材专项：现代甜宠/霸总】\n- 重点刻画甜蜜互动：牵手/壁咚/公主抱/额头轻吻等浪漫动作\n- 多用中景+近景展示互动，辅以浅景深虚化背景\n- 光线：柔和暖光（室内暖灯/午后阳光），高光柔化制造梦幻感\n- 色调：温暖奶油色/蜜桃色为主，配合浅粉/白色\n- 节奏：甜蜜场景放慢(5-8s)，冲突场景加快\n- 关键词：modern romance, sweet interaction, luxury setting, soft focus, warm lighting, tender moment, wealthy lifestyle\n",
            "奇幻冒险": "\n\n## 【题材专项：奇幻冒险】\n- 重点刻画世界观奇观：魔法特效、异世界建筑、奇幻生物、战斗场面\n- 多用远景展示世界规模+特写展示魔法细节\n- 光线：多光源（魔法发光/异色太阳/元素光效）\n- 色调：高饱和、色彩丰富但不刺眼，不同区域不同色调\n- 节奏：战斗2-3s快切，探索5-8s横摇\n- 关键词：fantasy adventure, magical effects, epic scale, vibrant colors, otherworldly landscape, action-packed\n",
        }
        if subject_pref in _GENRE_GUIDES:
            subject_guide = _GENRE_GUIDES[subject_pref]
        # 自动检测题材（如果用户未指定）
        elif job.story_structure:
            genre_hints = job.story_structure.get("genre_hints", "")
            # 简单关键词匹配自动注入
            for genre_key in ["言情", "古风玄幻", "都市轻悬疑", "现代甜宠", "奇幻冒险"]:
                if genre_key in str(genre_hints) or genre_key in job.novel_title:
                    subject_guide = _GENRE_GUIDES[genre_key]
                    break

        user_prompt = f"""请将以下完整小说文本改编为商业漫剧的连续分镜脚本。

## 故事结构预分析结果（你必须参考这个来分析！）
以下是对同一文本的 Hollywood 级别故事结构分析，你的分镜设计必须与之对齐：
{structure_context}

## 角色预分析档案（v9.5：精简压缩，跨镜角色一致性强制参考！！！）
{_compact_character_context(job.character_analysis)}

## 环境预分析档案（v9.5：精简压缩，跨镜场景一致性强制参考！！！）
{_compact_environment_context(job.environment_analysis)}

## 分镜生成要求：
1. 分镜数量：根据文本长度合理划分（每200-400字大约1个分镜，情感密集处可加密）
2. 必须覆盖原文的所有重要情节，不能跳过
3. 分镜之间必须连贯，形成完整的故事弧线（参考上方预分析结果中的情绪弧线）
4. subtitle_text 必须直接引用对应的原文文字（一字不差）
5. 每个分镜的 emotional_intensity 必须与预分析中的情绪弧线对应（1-10数值）
6. 如果有视觉母题（visual_motifs），必须在 visual_motif_note 中体现
7. 每个分镜的 story_act 字段标明本镜属于第几幕（act1/act2/act3）
8. 每个分镜的 storytelling_rhythm 字段标明节奏类型（hook/conflict/reversal/cliffhanger/emotional_peak）
{truncate_notice}{subject_guide}
## 原文开始 ##
{analysis_text}
## 原文结束 ##"""

        result = await call_deepseek(
            job.deepseek_key or DEEPSEEK_DEFAULT_KEY,
            STORYBOARD_SYSTEM,
            user_prompt,
            max_tokens=16384,
            temperature=0.7  # 分镜创意生成
        )

        scenes_raw = extract_json_array(result)
        if not scenes_raw:
            raise ValueError("分镜解析返回空结果，请检查 DeepSeek API Key 或稍后重试")

        all_scenes: list[Scene] = []
        for scene_id, raw in enumerate(scenes_raw, 1):
            characters = raw.get("characters", "")
            if isinstance(characters, list):
                characters = "; ".join(characters) if characters else "无"

            subtitle_text = raw.get("subtitle_text", "")
            subtitle_display = subtitle_text if len(subtitle_text) <= 60 else subtitle_text[:57] + "..."

            # 情绪强度（与故事结构预分析对齐）
            emotional_intensity = raw.get("emotional_intensity", 5)
            try:
                emotional_intensity = int(emotional_intensity)
            except (ValueError, TypeError):
                emotional_intensity = 5

            all_scenes.append(Scene(
                id=scene_id,
                subtitle_text=subtitle_text,
                subtitle_display=subtitle_display,
                title=raw.get("title", f"场景 {scene_id}"),
                description=raw.get("description", ""),
                characters=characters,
                setting=raw.get("setting", ""),
                mood=raw.get("mood", ""),
                camera=raw.get("camera", ""),
                duration=raw.get("duration", "5s"),
                continuity_note=raw.get("continuity_note", ""),
                emotional_intensity=emotional_intensity,
                visual_motif_note=raw.get("visual_motif_note", ""),
                story_act=raw.get("story_act", ""),
                story_position=raw.get("story_position", ""),
                storytelling_rhythm=raw.get("storytelling_rhythm", ""),
            ))

        job.scenes = all_scenes
        job.current_step = "storyboard"
        job.error = ""  # v9.6: 分镜生成成功时清除旧错误
        await JobStorage.save(job)
        return {
            "job_id": job_id,
            "scenes_count": len(all_scenes),
            "scenes": [s.model_dump() for s in all_scenes],
            "story_structure": story_structure
        }

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        job.error = str(e)[:500]
        await JobStorage.save(job)  # v9.6: 确保错误持久化
        raise HTTPException(500, f"生成分镜失败: {job.error}")


@ app.post("/api/update-storyboard")
async def update_storyboard(job_id: str, scenes: list[dict]):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    # 同时更新选中的模型
    updated = []
    for i, s in enumerate(scenes):
        data = {k: v for k, v in s.items() if k in Scene.model_fields and k != 'id'}
        # v6.3: 归一化 emotional_intensity，防止 LLM 返回浮点数触发 pydantic 验证错误
        if 'emotional_intensity' in data and isinstance(data['emotional_intensity'], float):
            data['emotional_intensity'] = int(float(data['emotional_intensity']))
        # 归一化 characters 字段：前端可能传来 list 而非 str
        if 'characters' in data and isinstance(data['characters'], list):
            data['characters'] = ", ".join(data['characters']) if data['characters'] else ""
        scene = Scene(id=i+1, **data)
        updated.append(scene)
    job.scenes = updated
    await JobStorage.save(job)
    return {"job_id": job_id, "scenes_count": len(updated)}

@app.post("/api/update-settings")
async def update_settings(job_id: str, img_checkpoint: str = "", vid_checkpoint: str = "",
                           tts_enabled: bool = True, tts_voice: str = "",
                           tts_rate: str = "+0%", tts_volume: str = "+0%",
                           use_hires_fix: bool = True, use_ipadapter: bool = False,
                           ipadapter_model: str = "ip-adapter-plus-face_sdxl_vit-h.safetensors",
                           ipadapter_reference_image: str = "",
                           clip_vision_model: str = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
                           use_pulid: bool = False,
                           pulid_model: str = "ip-adapter_pulid_sdxl_fp16.safetensors",
                           pulid_reference_image: str = "",
                           kling_api_key: str = "",
                           kling_face_description: str = "",
                           use_wan21: bool = False,
                           wan21_model: str = "WanVideo\\Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors",
                           wan21_t5_encoder: str = "umt5-xxl-enc-bf16.safetensors",
                           wan21_vae: str = "wanvideo\\Wan2_1_VAE_bf16.safetensors",
                           wan21_clip_vision: str = "clip_vision_h.safetensors",
                           use_color_grading: bool = True,
                           use_fade_transition: bool = True,
                           use_ass_subtitles: bool = False):
    """更新生成设置（模型选择、TTS配音、质量升级等）"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    # v9.6: 自动规范化 checkpoint 名称（补全 .safetensors 扩展名）
    if img_checkpoint:
        job.img_checkpoint = await comfyui.normalize_checkpoint_name(img_checkpoint)
    if vid_checkpoint:
        job.vid_checkpoint = await comfyui.normalize_checkpoint_name(vid_checkpoint)
    job.tts_enabled = tts_enabled
    if tts_voice:
        job.tts_voice = tts_voice
    if tts_rate:
        job.tts_rate = tts_rate
    if tts_volume:
        job.tts_volume = tts_volume
    # Level 1: Hires.fix
    job.use_hires_fix = use_hires_fix
    # Level 2: IP-Adapter
    job.use_ipadapter = use_ipadapter
    job.ipadapter_model = ipadapter_model
    job.ipadapter_reference_image = ipadapter_reference_image
    job.clip_vision_model = clip_vision_model
    # Level 2b: PuLID (SDXL)
    job.use_pulid = use_pulid
    job.pulid_model = pulid_model
    job.pulid_reference_image = pulid_reference_image
    if kling_api_key:
        job.kling_api_key = kling_api_key
    if kling_face_description:
        job.kling_face_description = kling_face_description
    # Level 3: Wan2.1
    job.use_wan21 = use_wan21
    job.wan21_model = wan21_model
    job.wan21_t5_encoder = wan21_t5_encoder
    job.wan21_vae = wan21_vae
    job.wan21_clip_vision = wan21_clip_vision
    # Level 5: 后期合成
    job.use_color_grading = use_color_grading
    job.use_fade_transition = use_fade_transition
    job.use_ass_subtitles = use_ass_subtitles
    await JobStorage.save(job)
    return {"status": "ok"}


# ───────────────────────────────────────────────────────────
# v12.1: Launcher 启动配置（与 launcher.py 共享 launcher_config.json）
# 用于前端设置面板持久化 auto_cosyvoice 等启动项，launcher 下次启动时读取。
# ───────────────────────────────────────────────────────────
LAUNCHER_CONFIG_FILE = PROJECT_ROOT / "launcher_config.json"

def _read_launcher_config() -> dict:
    try:
        if LAUNCHER_CONFIG_FILE.exists():
            with open(LAUNCHER_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

@app.get("/api/launcher-config")
async def get_launcher_config():
    """读取 launcher 启动配置（前端设置面板用）。"""
    cfg = _read_launcher_config()
    # 与 launcher.py 默认值保持一致
    cfg.setdefault("auto_cosyvoice", True)
    cfg.setdefault("auto_comfyui", False)
    cfg.setdefault("auto_start_server", True)
    return {"status": "ok", "config": cfg}

@app.post("/api/launcher-config")
async def post_launcher_config(config: dict):
    """更新并持久化 launcher 启动配置（如 auto_cosyvoice）。"""
    try:
        existing = _read_launcher_config()
        # 仅合并已知启动项，避免写入无关字段
        known_keys = ("auto_cosyvoice", "auto_comfyui", "auto_start_server",
                      "comfyui_url", "port", "api_key", "quality", "model",
                      "ipadapter", "active_preset")
        for k in known_keys:
            if k in config:
                existing[k] = config[k]
        with open(LAUNCHER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        return {"status": "ok", "config": existing}
    except Exception as e:
        raise HTTPException(500, f"保存 launcher 配置失败: {e}")

@app.get("/api/tts-voices")
async def get_tts_voices():
    """获取可用的 TTS 声音列表"""
    return {"voices": RECOMMENDED_VOICES}

@app.post("/api/preview-tts")
async def preview_tts(text: str = "这是一段测试语音，用于预览声音效果。", 
                       voice: str = "zh-CN-XiaoxiaoNeural",
                       rate: str = "+0%", volume: str = "+0%"):
    """生成 TTS 预览音频"""
    preview_dir = OUTPUT_DIR / "_tts_preview"
    preview_dir.mkdir(exist_ok=True)
    preview_path = str(preview_dir / f"preview_{uuid.uuid4().hex[:6]}.mp3")
    try:
        duration = await generate_tts(text, preview_path, voice=voice, rate=rate, volume=volume)
        return {"status": "ok", "audio_path": preview_path, "duration": duration}
    except Exception as e:
        raise HTTPException(500, f"TTS 预览失败: {str(e)[:200]}")

@app.get("/api/tts-preview-audio")
async def get_tts_preview_audio(path: str):
    """获取 TTS 预览音频文件"""
    preview_dir = OUTPUT_DIR / "_tts_preview"
    safe_path = Path(path).resolve()
    if not str(safe_path).startswith(str(preview_dir.resolve())):
        raise HTTPException(403, "禁止访问该路径")
    if not safe_path.exists():
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(str(safe_path), media_type="audio/mpeg")

# ─── v4.0 智能配音 API ─────────────────────────────────────

@app.post("/api/analyze-characters")
async def analyze_characters(job_id: str):
    """用 DeepSeek 分析小说中的角色，提取属性并智能匹配声音"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.novel_text:
        raise HTTPException(400, "请先上传小说文本")

    try:
        await broadcast_progress(job_id, {
            "type": "character_analysis", "status": "analyzing"
        })

        # 用前15000字分析角色（足够覆盖主要角色出场）
        analysis_text = job.novel_text[:15000]

        result = await call_deepseek(
            job.deepseek_key,
            CHARACTER_ANALYSIS_SYSTEM,
            f"请分析以下小说文本中的角色，提取每个角色的属性：\n\n{analysis_text}",
            max_tokens=4096,
            temperature=0.3  # 角色提取需要一致性
        )

        chars_data = extract_json_object(result)
        chars_raw = chars_data.get("characters", []) if chars_data else []
        characters = []
        for raw in chars_raw:
            # v9.2 修复: 组合LLM细粒度字段 → Character对象的appearance
            # LLM输出: physical_description, face_detail, hair_style, eye_detail, skin_tone
            appearance_parts = []
            if raw.get("physical_description"):
                appearance_parts.append(raw["physical_description"])
            if raw.get("face_detail"):
                appearance_parts.append(raw["face_detail"])
            if raw.get("hair_style"):
                appearance_parts.append(raw["hair_style"])
            if raw.get("eye_detail"):
                appearance_parts.append(raw["eye_detail"])
            if raw.get("skin_tone"):
                appearance_parts.append(raw["skin_tone"])
            composed_appearance = ", ".join(appearance_parts) if appearance_parts else ""

            char = Character(
                name=raw.get("name", "未知角色"),
                gender=raw.get("gender", "未知"),
                age_range=raw.get("age_range", "青年"),
                personality=raw.get("personality", ""),
                speaking_style=raw.get("speaking_style", ""),
                role_type=raw.get("role", "配角"),           # LLM输出"role"不是"role_type"
                appearance=composed_appearance,               # 组合细粒度字段
                body_type=raw.get("body_type", ""),
                clothing=raw.get("typical_clothing", ""),     # LLM输出"typical_clothing"
                kling_prompt=raw.get("kling_prompt", ""),
            )
            # 智能匹配声音（Edge-TTS + CosyVoice2 双引擎）
            char = match_voice_for_character(char)
            char.cosyvoice_voice = get_cosyvoice_speaker(char)
            characters.append(char)

        job.characters = characters
        await JobStorage.save(job)

        await broadcast_progress(job_id, {
            "type": "character_analysis", "status": "done",
            "characters_count": len(characters)
        })

        return {
            "job_id": job_id,
            "characters": [c.model_dump() for c in characters],
            "characters_count": len(characters)
        }

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        job.error = str(e)[:500]
        raise HTTPException(500, f"角色分析失败: {job.error}")

@app.post("/api/update-character-voice")
async def update_character_voice(job_id: str, character_name: str, voice_id: str):
    """手动修改某个角色的声音"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    for char in job.characters:
        if char.name == character_name:
            char.voice_id = voice_id
            # 查找声音名称
            for v in RECOMMENDED_VOICES:
                if v["id"] == voice_id:
                    char.voice_name = v["name"]
                    break
            break
    await JobStorage.save(job)
    return {"status": "ok"}

@app.post("/api/split-dialogues")
async def split_dialogues(job_id: str):
    """对每个场景的文本进行旁白/对白拆分，标注说话角色"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.scenes:
        raise HTTPException(400, "请先生成分镜")

    try:
        char_map = {c.name: c for c in job.characters}
        BATCH = 10

        for batch_start in range(0, len(job.scenes), BATCH):
            batch = job.scenes[batch_start: batch_start + BATCH]
            batch_text = ""
            for scene in batch:
                batch_text += f"\n[场景{scene.id}] {scene.subtitle_text}\n"

            result = await call_deepseek(
                job.deepseek_key,
                DIALOGUE_SPLIT_SYSTEM,
                f"请将以下场景文本拆分为旁白和对白，标注说话角色：\n{batch_text}",
                max_tokens=4096,
                temperature=0.3  # 文本分类需要确定性
            )

            dialogues_raw = extract_json_array(result)

            # 将对白拆分结果映射回各场景
            idx = 0
            for scene in batch:
                scene_dialogues = []
                # 收集本场景的对白
                while idx < len(dialogues_raw):
                    d = dialogues_raw[idx]
                    scene_dialogues.append(d)
                    idx += 1
                    # 简单判断：如果下一个元素还是当前场景的就继续
                    # DeepSeek返回的JSON没有场景ID，需要通过文本匹配
                    if idx < len(dialogues_raw):
                        next_text = dialogues_raw[idx].get("text", "")
                        # 检查是否属于下一个场景
                        if batch_start + batch.index(scene) + 1 < len(job.scenes):
                            next_scene_text = job.scenes[batch_start + batch.index(scene) + 1].subtitle_text[:20]
                            if next_text[:20] == next_scene_text:
                                break
                    if len(scene_dialogues) >= 20:  # 安全限制
                        break

                # 提取说话角色列表
                speakers = list(set(
                    d["speaker"] for d in scene_dialogues
                    if d.get("type") == "dialogue" and d.get("speaker") != "旁白"
                ))
                scene.speaking_characters = speakers

        return {
            "job_id": job_id,
            "scenes": [s.model_dump() for s in job.scenes]
        }

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        job.error = str(e)[:500]
        raise HTTPException(500, f"对白拆分失败: {job.error}")

@app.post("/api/update-smart-dubbing")
async def update_smart_dubbing(job_id: str, smart_dubbing: bool = True,
                                narrator_voice: str = "zh-CN-YunjianNeural"):
    """更新智能配音设置"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    job.smart_dubbing = smart_dubbing
    job.narrator_voice = narrator_voice
    await JobStorage.save(job)
    return {"status": "ok"}

@app.post("/api/generate-prompts")
async def generate_prompts(job_id: str):
    job = _get_job(job_id)

    # 防御：DeepSeek key 缺失时给出清晰错误，避免生成流程神秘 500
    from app.config import DEEPSEEK_API_KEY as _ds_key
    if not _ds_key and not getattr(job, "deepseek_key", ""):
        raise HTTPException(
            status_code=400,
            detail="DeepSeek API Key 未配置，无法生成提示词。请在设置中填写 API Key 后重试。",
        )

    try:
        # 构建全局角色描述（确保跨场景角色一致）
        global_character_desc = _build_global_character_desc(job)

        # 逐个场景串行生成（不并发），每个场景传入前一场景的提示词作为角色外貌锚点
        async def _prompt_for_scene(scene: Scene, prev_prompt_hint: str = "") -> Scene:
            """为单个场景生成提示词（含全局角色信息和上一镜参考）"""
            # v9.9: 只提取当前场景出场角色的外貌，防止跨场景角色描述污染
            scene_character_desc = _build_scene_character_desc(job, scene)
            user_msg = f"""## 【本分镜出场角色外貌设定 —— 仅描述以下角色】
{scene_character_desc or '无特定角色'}
{prev_prompt_hint}

## 【当前分镜完整信息（好莱坞级字段）】
分镜编号：#{scene.id} / 共{len(job.scenes)}个分镜
所属故事幕次：{scene.story_act or '未标注'}
故事位置：{scene.story_position or '未标注'}
标题：{scene.title}
原文台词/旁白：{scene.subtitle_text}
画面描述：{scene.description}
出场角色：{scene.characters}
场景环境：{scene.setting}
情绪氛围：{scene.mood}
镜头类型：{scene.camera}
情绪强度（1-10，来自故事结构预分析）：{scene.emotional_intensity}
视觉母题说明：{scene.visual_motif_note or '无'}
连贯说明：{scene.continuity_note}

## 【Prompt 生成要求（好莱坞级）】
1. image_prompt 必须精确描述本分镜的角色外貌和场景
2. 【关键】只描述上方「本分镜出场角色」中列出的角色！绝对不要加入未出场角色的外貌特征或动作
3. 【关键】不要加入其他分镜才出现的道具、动作或情节（如绳子、拉车、刨地等不属于本镜的元素）
4. 根据 emotional_intensity 调整光线对比度和色彩饱和度（强度>7时用高对比/浓郁色彩，<4时用低对比/柔和色彩）
5. 如果 visual_motif_note 非空，在 image_prompt 中明确体现该视觉母题
6. 如果有上一个分镜的提示词参考，在保持本分镜独特性的同时，保证同一角色的外貌关键词完全相同
7. 生成竖屏（9:16）image_prompt、video_prompt 和 negative_prompt
8. (v7.0 Seedream蒸馏) image_prompt 必须以 Danbooru 结构化标签开头: [color: XXX] [lighting: XXX] [composition: XXX],
   然后接 quality anchors + 主体描述。必须输出 vmix_tags JSON 字段"""
            # v7.0: 提取 VMix 标签并在 prompt 前注入结构指导
            vmix_tags = _extract_vmix_tags(scene, job)
            vmix_hint = f"\n\n## 【VMix 美学指导 (v7.0 Seedream蒸馏)】\n请将以下结构标签作为 image_prompt 的第一句: {vmix_tags}"
            user_msg += vmix_hint
            try:
                result = await call_deepseek(
                    job.deepseek_key,
                    PROMPT_SYSTEM,
                    user_msg,
                    max_tokens=2560,
                    temperature=0.5  # 提示词生成：平衡创意与一致性（v6.3升级：更长提示词）
                )
                prompts = extract_json_object(result)
                scene.image_prompt = prompts.get("image_prompt", "")
                scene.video_prompt = prompts.get("video_prompt", "")
                scene.negative_prompt = prompts.get("negative_prompt",
                    "(worst quality:1.5), (low quality:1.5), (bad hands:1.4), blurry, deformed, watermark, text, signature")
                # v7.0: 保存 VMix 标签供后续使用
                scene.vmix_tags = prompts.get("vmix_tags", {})
            except Exception as e:
                print(f"[Prompt] Scene {scene.id} failed: {str(e)[:100]}")
                scene.image_prompt = await _build_fallback_image_prompt(scene, global_character_desc, job=job)
                # v5.7: 视频prompt也用翻译后的英文，不用中文description
                desc_en = _translate_to_english_keywords(scene.description) if scene.description else ""
                mood_map_vp = {"紧张":"tense","温馨":"warm cozy","悲伤":"melancholic","壮阔":"epic",
                    "神秘":"mysterious","热血":"passionate","恐惧":"fearful","喜悦":"joyful",
                    "惆怅":"wistful","愤怒":"intense","压抑":"oppressive","释然":"relieved",
                    "宁静":"peaceful","诡异":"eerie"}
                mood_en = mood_map_vp.get(scene.mood, "cinematic") if scene.mood else "cinematic"
                style_vp = _get_style_video_suffix(getattr(job, 'style', 'cinematic'))
                scene.video_prompt = f"{desc_en}, {mood_en} atmosphere, subtle camera motion, slow push in, {style_vp}" if desc_en else f"{mood_en} atmosphere scene, cinematic movement, slow push in, {style_vp}"
                scene.negative_prompt = "(worst quality:1.5), (low quality:1.5), (bad hands:1.4), blurry, deformed, watermark, text, signature"
                scene.vmix_tags = {}
            return scene

        # 串行生成（非并发），保持前后连贯性
        for idx, scene in enumerate(job.scenes):
            prev_hint = ""
            if idx > 0 and job.scenes[idx-1].image_prompt:
                # v9.9: 提取角色外貌锚点词（前80字符），不传递整段场景描述
                prev_prompt = job.scenes[idx-1].image_prompt
                # 跳过通用质量词，提取角色描述部分
                quality_prefixes = ["masterpiece, best quality", "ultra detailed", "8k uhd"]
                for qp in quality_prefixes:
                    prev_prompt = prev_prompt.replace(qp + ", ", "").replace(qp, "")
                char_anchor = prev_prompt[:150].rstrip(",").strip()
                prev_hint = f"\n【上一镜角色外貌锚点（必须字面保持一致）】：{char_anchor}"
            await _prompt_for_scene(scene, prev_hint)

        job.current_step = "prompts"
        await JobStorage.save(job)
        return {"job_id": job_id, "scenes": [s.model_dump() for s in job.scenes]}

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        job.error = str(e)[:500]
        raise HTTPException(500, f"生成提示词失败: {job.error}")

@app.post("/api/start-generation")
async def start_generation(job_id: str):
    job = _get_job(job_id)
    if not job.scenes:
        raise HTTPException(400, "请先生成分镜和提示词")

    job.cancel_flag = False
    job.current_step = "generating"
    job.progress = {"current": 0, "total": len(job.scenes), "phase": "starting"}
    await JobStorage.save(job)
    _spawn_background_task(run_generation(job_id), f"run_generation({job_id})")
    return {"job_id": job_id, "status": "started"}

@app.post("/api/cancel-generation")
async def cancel_generation(job_id: str):
    """中断当前生成任务"""
    job = _get_job(job_id)
    job.cancel_flag = True
    await JobStorage.save(job)
    try:
        await comfyui.interrupt()
    except Exception:
        pass  # ComfyUI 不可达时，取消标志已设置，后续循环会检查
    return {"status": "cancelled"}

@app.post("/api/retry-scene/{job_id}/{scene_id}")
async def retry_scene(job_id: str, scene_id: int):
    """重试单个失败的场景"""
    job = _get_job(job_id)
    scene = next((s for s in job.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(404, "Scene not found")

    # 重置状态
    scene.status = "pending"
    scene.error_msg = ""
    scene.comfyui_progress = 0.0
    scene.image_path = None
    scene.video_path = None
    scene.final_video_path = None
    scene.audio_path = None
    scene.audio_duration = 0.0

    # 在后台重试
    _spawn_background_task(run_single_scene(job_id, scene_id), f"retry_scene({job_id}/{scene_id})")
    return {"status": "retrying", "scene_id": scene_id}


@app.post("/api/remerge/{job_id}")
async def remerge_videos(job_id: str):
    """v9.8: 重新合并最终视频（无需重新生成场景）

    当最终视频合并失败时，可用此端点重新触发合并。
    前提：各场景的 final_video_path 文件仍然存在。
    """
    job = _get_job(job_id)
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_paths = []
    scene_moods = []
    for scene in job.scenes:
        vp = scene.final_video_path or scene.video_path
        if vp and Path(vp).exists() and Path(vp).stat().st_size > 10000:
            video_paths.append(vp)
            scene_moods.append(getattr(scene, 'mood', '') or '')

    if not video_paths:
        raise HTTPException(400, "没有可合并的场景视频文件，请重新生成")

    merged_path = str(job_dir / f"{job.novel_title or 'output'}_merged.mp4")
    _spawn_background_task(_do_remerge(job_id, video_paths, merged_path, scene_moods), f"remerge({job_id})")
    return {"status": "merging", "video_count": len(video_paths), "merged_path": merged_path}


async def _do_remerge(job_id: str, video_paths: list[str], merged_path: str,
                      scene_moods: list[str] = None):
    """后台执行重新合并"""
    job = _get_job(job_id)
    try:
        job.current_step = "merging"
        job.progress = {"phase": "merging", "total": len(video_paths)}
        await broadcast_progress(job_id, {"type": "merging", "status": "started"})

        # P0-①: 传入字幕路径以烧录（hardsub）
        subtitle_path = str(OUTPUT_DIR / job_id / "subtitle.ass")
        if not Path(subtitle_path).exists():
            subtitle_path = None

        if len(video_paths) > 1:
            await merge_videos_with_transitions(video_paths, merged_path,
                                                scene_moods=scene_moods,
                                                subtitle_path=subtitle_path)
        else:
            import shutil
            shutil.copy(video_paths[0], merged_path)

        job.merged_video_path = merged_path
        job.current_step = "done"
        job.progress["phase"] = "done"
        await broadcast_progress(job_id, {"type": "job_complete", "merged_video": merged_path})
        print(f"[ReMerge] 合并完成: {merged_path} ({Path(merged_path).stat().st_size//1024}KB)", flush=True)
    except Exception as e:
        print(f"[ReMerge] 合并失败: {e}", flush=True)
        # 检查文件是否实际已生成
        if Path(merged_path).exists() and Path(merged_path).stat().st_size > 10000:
            job.merged_video_path = merged_path
            job.current_step = "done"
            job.progress["phase"] = "done"
            await broadcast_progress(job_id, {"type": "job_complete", "merged_video": merged_path})
            print(f"[ReMerge] 报错但文件有效，使用该文件", flush=True)
        else:
            job.current_step = "error"
            job.progress["phase"] = "merge_error"
            job.progress["error"] = f"重新合并失败: {str(e)[:300]}"
            await broadcast_progress(job_id, {
                "type": "error",
                "message": f"重新合并失败: {str(e)[:300]}",
                "phase": "merge_error"
            })
    await JobStorage.save(job)


async def run_single_scene(job_id: str, scene_id: int):
    """重试单个场景"""
    job = _get_job(job_id)
    scene = next((s for s in job.scenes if s.id == scene_id), None)
    if not scene:
        return

    scene_dir = OUTPUT_DIR / job_id
    scene_dir.mkdir(exist_ok=True)

    txt2img_template = load_workflow("txt2img")
    img2vid_template = load_workflow("img2vid")

    try:
        await _generate_scene(job, scene, scene_dir, txt2img_template, img2vid_template)
        scene.status = "done"
    except Exception as e:
        scene.status = "error"
        scene.error_msg = str(e)[:300]
        await broadcast_progress(job_id, {
            "type": "scene_status",
            "scene_id": scene.id,
            "status": "error",
            "error": scene.error_msg,
        })
    await JobStorage.save(job)

async def _calculate_image_quality_score(image_path: str, prompt_en: str = "") -> float:
    """
    v6.2: 多维度图像质量评分
    v7.0 Seedream蒸馏: 增加 DeepSeek 图文对齐评分，三维加权
    返回综合得分（越高越好）:
    - 清晰度 (30%): 梯度方差（边缘清晰度）
    - 色彩丰富度 (20%): 直方图熵
    - 图文对齐 (30%): DeepSeek 语义评估
    - 角色一致性 (20%): 与提示词中角色描述的匹配度
    """
    from PIL import Image
    import numpy as np
    import math
    from pathlib import Path
    
    try:
        img = Image.open(image_path).convert("RGB")
        arr = np.array(img, dtype=np.float64)
        h, w, c = arr.shape
        
        # 1. 清晰度: 梯度方差（简化版拉普拉斯）
        gray = np.mean(arr, axis=2)
        grad_x = gray[:, 1:] - gray[:, :-1]
        grad_y = gray[1:, :] - gray[:-1, :]
        grad_var = np.var(grad_x) + np.var(grad_y)
        clarity_score = min(grad_var / 100.0, 1.0)
        
        # 2. 色彩丰富度: 直方图熵
        hist = img.histogram()
        total = sum(hist)
        entropy = 0.0
        for count in hist:
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        color_score = min(entropy / 8.0, 1.0)
        
        # 3. v8.7: 提示词质量评分 (DeepSeek 评估，作为图文对齐代理)
        prompt_quality = 0.5  # 默认中性分
        if prompt_en:
            prompt_quality = await _prompt_quality_score(prompt_en)
        
        # 4. v7.0: 角色一致性 — 基于 prompt 长度和关键词密度
        # 提示词越长越详细 → 越可能包含准确的角色描述
        consistency_score = min(len(prompt_en) / 800.0, 1.0) if prompt_en else 0.5
        
        # v8.7: 综合得分 (四维加权)
        final_score = (
            clarity_score * 0.3 +
            color_score * 0.2 +
            prompt_quality * 0.3 +
            consistency_score * 0.2
        )
        return final_score
        
    except Exception as e:
        print(f"[Quality] 评分失败: {e}", flush=True)
        # 回退: 有评分数据时用加权，否则用文件大小
        try:
            file_size = Path(image_path).stat().st_size
            size_score = min(file_size / (5 * 1024 * 1024), 1.0)  # 5MB满分
            final_score = clarity_score * 0.4 + color_score * 0.3 + size_score * 0.3
        except Exception:
            final_score = 0.3  # 最低回退分
        return final_score


async def _generate_scene(job: JobState, scene: Scene, scene_dir: Path,
                           txt2img_template: dict, img2vid_template: dict):
    """生成单个场景的图片和视频（v4.0 智能配音+三者同步）

    超时保护：整个场景生成最多30分钟，避免ComfyUI卡住时整个管道卡住
    注意：Wan2.1 I2V 在 lowvram 模式下 8GB 显存可能需要 10-15 分钟/场景
    """
    # [质量优先补丁 v3] 8GB 显存上 22B LTX 视频生成极慢(单场可达 60-90 分钟),
    # 原 30 分钟外层超时会在 LTX 跑完前杀掉场景,导致 10/13 场"生成超时"。
    # 放宽到 120 分钟(7200s)让 LTX 有充足时间跑完(用户明确"时间不重要,质量优先")。
    # 注: LTX 自身内层 wait_for_result_ws 超时=3600s,外层必须 > 它。
    try:
        timeout_sec = 7200.0 if getattr(job, 'use_multi_shot', False) else 7200.0
        return await asyncio.wait_for(
            _generate_scene_impl(job, scene, scene_dir, txt2img_template, img2vid_template),
            timeout=timeout_sec
        )
    except asyncio.TimeoutError:
        raise RuntimeError(f"场景 {scene.id} 生成超时（{int(timeout_sec/60)}分钟），可能是 ComfyUI 卡住或显存不足")


# ─── v9.7: 智能显存检测与配置自适应 ──────────────────────────
async def _get_comfyui_vram_info() -> tuple[int, int]:
    """从 ComfyUI /system_stats 获取 (空闲, 总) 显存（MB）。
    失败时返回 (-1, -1)，调用方应保守处理。
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{COMFYUI_URL}/system_stats")
            if resp.status_code != 200:
                return -1, -1
            data = resp.json()
            devices = data.get("devices", [])
            if not devices:
                return -1, -1
            # 取第一个 CUDA 设备
            dev = None
            for d in devices:
                if d.get("type") == "cuda" or "cuda" in d.get("name", ""):
                    dev = d
                    break
            if dev is None:
                dev = devices[0]
            vram_total = dev.get("vram_total", 0)
            vram_free = dev.get("vram_free", 0)
            if vram_total > 0:
                return int(vram_free / (1024 * 1024)), int(vram_total / (1024 * 1024))
            return -1, -1
    except Exception:
        return -1, -1


async def _get_comfyui_vram_mb() -> int:
    """向后兼容包装：仅返回空闲显存（MB）。失败返回 -1。"""
    free_mb, _ = await _get_comfyui_vram_info()
    return free_mb


def _auto_select_generation_config(free_vram_mb: int, job: JobState,
                                   total_vram_mb: int = -1) -> dict:
    """v9.11: 根据显存自动选择最优生成配置。

    关键修复: 分辨率档位按【总显存】(显卡真实能力) 判定，而非瞬时空闲值。
    空闲显存仅用于在显存紧张时降级 hires / IP-Adapter，避免 OOM。
    这样 12GB 卡即使已加载底模(空闲跌破 9GB)仍能稳定输出红果标准 1080×1920。

    返回 dict: {
        "img_width": int, "img_height": int,
        "hires": bool, "ipadapter": bool,
        "checkpoint": str, "checkpoint_forced": bool
    }
    """
    CKPT = "animagine-xl-4.0.safetensors"
    # 若未拿到总显存(旧调用/检测失败)，退回用空闲值判定，保持旧行为
    capability_mb = total_vram_mb if total_vram_mb > 0 else free_vram_mb

    # ── Tier 1: 总显存 >= 10GB → 红果标准 1080×1920 ──
    if capability_mb >= 10000:
        # 空闲充裕才开 hires；空闲紧张则关 hires 但仍保 1080×1920 全分辨率
        hires = free_vram_mb < 0 or free_vram_mb >= 6000
        return {
            "img_width": 1080, "img_height": 1920,
            "hires": hires, "ipadapter": True,
            "checkpoint": CKPT, "checkpoint_forced": True
        }
    # ── Tier 2: 总显存 6-10GB → 896×1536 (接近竖屏比例, 可后期 upscale 到 1080) ──
    elif capability_mb >= 6000:
        return {
            "img_width": 896, "img_height": 1536,
            "hires": False,
            "ipadapter": free_vram_mb < 0 or free_vram_mb >= 3500,
            "checkpoint": CKPT, "checkpoint_forced": True
        }
    # ── Tier 3: 总显存 4-6GB (如 8GB 卡实际可用) → 768×1152 ──
    elif capability_mb >= 3500:
        return {
            "img_width": 768, "img_height": 1152,
            "hires": False, "ipadapter": True,
            "checkpoint": CKPT, "checkpoint_forced": True
        }
    # ── Tier 4: <3.5GB → 保守 768×1152 ──
    else:
        return {
            "img_width": 768, "img_height": 1152,
            "hires": False, "ipadapter": True,
            "checkpoint": CKPT, "checkpoint_forced": True
        }


async def _generate_scene_impl(job: JobState, scene: Scene, scene_dir: Path,
                            txt2img_template: dict, img2vid_template: dict):
    """实际生成逻辑（由 _generate_scene 调用，带超时保护）
    v9.10 修复: 移除 global IMG_WIDTH/IMG_HEIGHT，改用局部变量避免跨场景污染。
    """
    # 使用局部变量而非修改全局 IMG_WIDTH/IMG_HEIGHT，避免污染后续场景
    img_w = IMG_WIDTH
    img_h = IMG_HEIGHT
    
    # v9.7: 智能显存检测 + 配置自适应
    # v9.11: 档位按总显存判定，空闲仅用于降级 hires/IP-Adapter
    free_vram, total_vram = await _get_comfyui_vram_info()
    config = {"ipadapter": True, "hires": True}  # 默认值（VRAM 检测失败时使用）
    if free_vram > 0:
        config = _auto_select_generation_config(free_vram, job, total_vram)
        img_w = config["img_width"]
        img_h = config["img_height"]
        
        # 显存不足时自动降级 IP-Adapter
        if not config["ipadapter"] and job.use_ipadapter:
            print(f"[VRAM] 显存仅 {free_vram}MB，自动关闭 IP-Adapter 节省 ~2.4GB", flush=True)
            job.use_ipadapter = False
            job.ipadapter_reference_image = ""
        
        # 自动切换更适合的 checkpoint
        if config.get("checkpoint_forced") and config["checkpoint"] != job.img_checkpoint:
            print(f"[VRAM] 自动切换 checkpoint: {job.img_checkpoint} → {config['checkpoint']} (显存 {free_vram}MB)", flush=True)
            job.img_checkpoint = config["checkpoint"]
        
        print(f"[VRAM] 空闲 {free_vram}MB → 分辨率 {img_w}×{img_h}, "
              f"Hires={config['hires']}, IP-Adapter={config['ipadapter']}, "
              f"Checkpoint={job.img_checkpoint}", flush=True)
    else:
        # ComfyUI 系统状态不可达，不做自动调整
        pass
    
    job_id = job.id
    char_map = {c.name: c for c in job.characters}
    
    # v6.2: 构建角色一致性描述（优先使用 character_analysis 15维）
    global_character_desc = _build_global_character_desc(job)
    if global_character_desc:
        print(f"[Consistency] 角色一致性描述已加载 ({len(global_character_desc)} chars)", flush=True)
    if job.environment_analysis and isinstance(job.environment_analysis.get('environments'), list):
        print(f"[Consistency] 环境分析结果已加载 ({len(job.environment_analysis['environments'])} 个场景)", flush=True)

    # ── 前置检查：验证 checkpoint 文件完整性（仅警告，不阻塞生成）──
    if not comfyui._validate_checkpoint_file(job.img_checkpoint):
        print(f"[WARN] 图片模型文件可能不完整: {job.img_checkpoint}，继续尝试生成", flush=True)
    if job.vid_checkpoint and not comfyui._validate_checkpoint_file(job.vid_checkpoint):
        print(f"[WARN] 视频模型文件可能不完整: {job.vid_checkpoint}，继续尝试生成", flush=True)

    # v12.2: 角色一致性锚定 —— 为所有有 kling_prompt 的角色生成定妆照并上传，建立 portrait_map
    # （替换原仅锚定主角的逻辑，支持多角色跨镜一致；定妆照→IP-Adapter 静帧→LTX I2V 保脸）
    if job.characters:
        _pmap = JOB_PORTRAIT_MAP.setdefault(job.id, {})
        for _c in job.characters:
            if _c.name in _pmap or not getattr(_c, 'kling_prompt', ''):
                continue
            print(f"[IP-Adapter] 为角色 {_c.name} 生成定妆照...", flush=True)
            _pp = await _generate_character_portrait(job, _c, scene_dir)
            if _pp:
                try:
                    _pmap[_c.name] = await comfyui.upload_image(_pp)
                except Exception as e:
                    print(f"[IP-Adapter] {_c.name} 上传失败: {e}", flush=True)
        if _pmap:
            job.use_ipadapter = True
            # 兼容旧字段：默认填充主角定妆照
            if not job.ipadapter_reference_image:
                _mc = next((c for c in job.characters if getattr(c, 'role_type', '') == "主角"), None) or next((c for c in job.characters), None)
                if _mc and _mc.name in _pmap:
                    job.ipadapter_reference_image = _pmap[_mc.name]
            print(f"[IP-Adapter] 已建立角色定妆照映射: {list(_pmap.keys())}", flush=True)


    # ── Step 1: 生成竖屏图片 ──
    # v8.1: T2V 模式跳过图片生成（文生视频不需要参考图，省时免污染）
    local_img = None
    if job.video_mode == "ltx_t2v":
        print(f"[T2V-Skip] 场景 {scene.id}: 跳过参考图生成（T2V 直出）", flush=True)
        local_img = "__T2V_SKIPPED__"  # 哨兵值，跳过图片生成
    else:
        await broadcast_progress(job_id, {
            "type": "scene_status",
            "scene_id": scene.id,
            "status": "generating_img",
        })

    scene.status = "generating_img"
    scene.error_msg = ""
    scene.comfyui_progress = 0.0
    if job.video_mode != "ltx_t2v":

        # 使用基于 job_id 的固定 seed，确保同一任务中所有场景的角色一致性
        seed = abs(hash(job_id)) % (2**31)
        # 场景 seed 在 job seed 基础上偏移，保持各场景略有差异
        scene_seed = (seed + scene.id * 1000) % (2**31)

        # 强化负向提示词（商业级）
        base_negative = ("(worst quality:1.4), (low quality:1.4), (bad hands:1.4), "
                         "(extra fingers:1.3), (missing fingers:1.3), bad anatomy, "
                         "watermark, text, signature, blurry, out of focus, ugly, disfigured")
        
        # v8.6: 无角色场景强制禁止人物 (Bug1修复: chars="无"也视为无角色)
        chars = getattr(scene, 'characters', '') or ''
        speaking = getattr(scene, 'speaking_characters', []) or []
        # v8.7: 无角色场景检测 — 与_clean_image_prompt保持一致，使用动态角色名
        no_char_markers = ["无", "无角色", "本镜未出场", "未出场", "环境开场"]
        all_char_names = _get_character_names(job)
        _chinese_names = [n for n in all_char_names if len(n) <= 4 and any('\u4e00' <= c <= '\u9fff' for c in n)]
        has_chars_str = bool(chars) and not any(m in chars for m in no_char_markers)
        has_speaking = bool(speaking) and any(s.strip() and s.strip() != "无" for s in speaking)
        has_named = any(name in str(speaking) for name in _chinese_names)
        has_characters = has_chars_str or has_speaking or has_named

        # v12.1-fix-2: image_prompt 明确描述人物/人脸/肖像时，即使 characters 为空
        # 也不视为无角色场景，避免向反向提示词注入强人物禁止项导致画面花屏。
        if not has_characters and _prompt_has_human_subject(getattr(scene, 'image_prompt', '') or ''):
            has_characters = True
            print(f"[PromptClean] 场景含人物描述词，忽略空 characters 标记，不注入人物反向提示词: 场景 {scene.id}", flush=True)

        is_no_character = not has_characters
        if is_no_character:
            no_human_neg = ", (person:1.6), (man:1.6), (woman:1.6), (human:1.6), (face:1.5), (portrait:1.5), (people:1.5), anime, cartoon, cgi"
            base_negative += no_human_neg
        
        # Bug4修复: 无论DeepSeek生成什么，v8.6禁止项都强制合并
        scene_neg = scene.negative_prompt or ""
        if scene_neg and "worst quality" not in scene_neg:
            negative_prompt = base_negative + ", " + scene_neg
        else:
            negative_prompt = scene_neg if scene_neg else base_negative
        # 确保人物禁止项始终存在（即使DeepSeek版本被选用）
        if is_no_character and "person" not in negative_prompt:
            negative_prompt += no_human_neg

        # 强化正向提示词（加入质量增强词）
        positive_base = "masterpiece, best quality, ultra detailed, 8k, "
        # 注意：不再加 "portrait of" 前缀，避免风景/物品场景被强制生成成人像
        positive_prompt = scene.image_prompt or await _build_fallback_image_prompt(scene, _build_global_character_desc(job), job=job)
        if not positive_prompt.startswith("masterpiece"):
            positive_prompt = positive_base + positive_prompt
        # v8.5: 清理风格污染 + 场景类型感知（禁止无角色场景出现人物）
        positive_prompt = _clean_image_prompt(positive_prompt, scene, job)

        # v9.8: 追加风格后缀（对 DeepSeek 生成的 prompt 同样生效）
        style = getattr(job, 'style', 'cinematic') or 'cinematic'
        style_suffix = _get_style_image_suffix(style)
        if style_suffix and style_suffix.lower() not in positive_prompt.lower():
            positive_prompt = f"{positive_prompt}, {style_suffix}"

        # 根据风格追加反向提示词（抑制错误风格 + 志怪恐怖元素误用）
        if style == "folk_horror":
            folk_neg = (", anime, cartoon, 3d render, cgi, western architecture, "
                        "art nouveau, gothic cathedral, european style, bright pastel colors, cheerful, "
                        "skull, skeleton, bones, cranium, giant skull, human skull, cracked skull")
            if folk_neg not in negative_prompt:
                negative_prompt += folk_neg

        # v12.2: 本场角色定妆照锚定（多角色一致性）—— 选本场出场角色的定妆照作为 IP-Adapter 参考
        if JOB_PORTRAIT_MAP.get(job.id):
            _pmap = JOB_PORTRAIT_MAP[job.id]
            _scene_ref = ""
            if chars:
                for _nm in [x.strip() for x in str(chars).split(",") if x.strip()]:
                    if _nm in _pmap:
                        _scene_ref = _pmap[_nm]; break
            if not _scene_ref and speaking:
                for _nm in speaking:
                    if _nm in _pmap:
                        _scene_ref = _pmap[_nm]; break
            if not _scene_ref and _pmap:
                _scene_ref = next(iter(_pmap.values()))
            if _scene_ref and not is_no_character:
                job.ipadapter_reference_image = _scene_ref
                job.use_ipadapter = True
            else:
                # 无人物场景：关闭 IP-Adapter，避免强行生成人脸并节省显存
                job.use_ipadapter = False
                job.ipadapter_reference_image = ""

        # 选择工作流模板（PuLID > IP-Adapter > Hires.fix > 基础）
        if job.use_pulid and job.pulid_reference_image:
            # PuLID (SDXL): 上传参考图 → 加载 PuLID 模型 → 人脸一致性
            pulid_ref_path = job.pulid_reference_image
            if Path(pulid_ref_path).exists():
                try:
                    uploaded_ref = await comfyui.upload_image(pulid_ref_path)
                except Exception as e:
                    logger.warning(f"[PuLID] 上传参考图失败: {str(e)[:80]}")
                    uploaded_ref = Path(pulid_ref_path).name
            else:
                uploaded_ref = pulid_ref_path  # 可能已经是 ComfyUI input 目录中的文件名

            wf_template = load_workflow("txt2img_sdxl_pulid")
            replacements = {
                "POSITIVE_PROMPT": positive_prompt,
                "NEGATIVE_PROMPT": negative_prompt,
                "SEED": scene_seed,
                "WIDTH": img_w,
                "HEIGHT": img_h,
                "HIRES_WIDTH": (int(img_w * 1.5) // 8) * 8,     # v9.7: VAE 要求宽高 8 的倍数
                "HIRES_HEIGHT": (int(img_h * 1.5) // 8) * 8,
                "CHECKPOINT": job.img_checkpoint,
                "PULID_MODEL": job.pulid_model,
                "REFERENCE_IMAGE": uploaded_ref,
            }
        elif job.use_ipadapter and job.ipadapter_reference_image:
            # v7.1: reference_image 是 ComfyUI 上传文件名, 不是本地路径
            wf_template = load_workflow("txt2img_ipadapter")
            replacements = {
                "POSITIVE_PROMPT": positive_prompt,
                "NEGATIVE_PROMPT": negative_prompt,
                "SEED": scene_seed,
                "WIDTH": img_w,
                "HEIGHT": img_h,
                "HIRES_WIDTH": (int(img_w * 1.5) // 8) * 8,
                "HIRES_HEIGHT": (int(img_h * 1.5) // 8) * 8,
                "CHECKPOINT": job.img_checkpoint,
                "IPADAPTER_MODEL": job.ipadapter_model,
                "CLIP_VISION_MODEL": job.clip_vision_model,
                "REFERENCE_IMAGE": job.ipadapter_reference_image,
            }
        elif job.use_hires_fix:
            wf_template = load_workflow("txt2img_hires")
            replacements = {
                "POSITIVE_PROMPT": positive_prompt,
                "NEGATIVE_PROMPT": negative_prompt,
                "SEED": scene_seed,
                "WIDTH": img_w,
                "HEIGHT": img_h,
                "HIRES_WIDTH": (int(img_w * 1.5) // 8) * 8,
                "HIRES_HEIGHT": (int(img_h * 1.5) // 8) * 8,
                "CHECKPOINT": job.img_checkpoint,
            }
        else:
            wf_template = txt2img_template
            replacements = {
                "POSITIVE_PROMPT": positive_prompt,
                "NEGATIVE_PROMPT": negative_prompt,
                "SEED": scene_seed,
                "WIDTH": img_w,
                "HEIGHT": img_h,
                "CHECKPOINT": job.img_checkpoint,
            }

        img_workflow = fill_workflow(wf_template, replacements)

        # ── v6.2: 多维度图像质量评分系统 ──
        # 生成多个不同seed的图像，使用多维度评分选择最佳版本
        best_image_path = None
        best_score = -1.0
        max_samples = 2 if job.use_pulid and job.pulid_reference_image else 3  # PuLID模式用2版节省时间
        for sample_i in range(max_samples):
            sample_seed = scene_seed + sample_i * 777  # 不同seed间距
            replacements["SEED"] = sample_seed
            sample_workflow = fill_workflow(wf_template, replacements)
        
            print(f"[Sampling] 场景 {scene.id} 第{sample_i+1}/{max_samples}版 (seed={sample_seed})", flush=True)
            prompt_id = await comfyui.submit_workflow(sample_workflow)
            result = await comfyui.wait_for_result_ws(prompt_id, job_id=job_id, scene_id=scene.id, timeout=900)
        
            outputs = result.get("outputs", {})
            sample_filename = None
            sample_subfolder = ""
            for node_id, node_out in outputs.items():
                if "images" in node_out:
                    img_info = node_out["images"][0]
                    sample_filename = img_info["filename"]
                    sample_subfolder = img_info.get("subfolder", "")
                    break
        
            if not sample_filename:
                continue
        
            sample_path = await comfyui.download_output(sample_filename, sample_subfolder, save_dir=scene_dir)
            if not sample_path or not Path(sample_path).exists():
                continue
        
            # v7.0: 多维度质量评分（Seedream蒸馏: 三维加权）
            img_size = Path(sample_path).stat().st_size
            quality_score = await _calculate_image_quality_score(sample_path, prompt_en=positive_prompt)
            print(f"[Quality] 场景 {scene.id} 第{sample_i+1}版: {img_size/1024:.0f}KB, 质量分={quality_score:.2f}", flush=True)
        
            if quality_score > best_score:
                best_score = quality_score
                # 清理旧的最佳版本
                if best_image_path and best_image_path != sample_path:
                    Path(best_image_path).unlink(missing_ok=True)
                best_image_path = sample_path
            elif sample_path != best_image_path:
                Path(sample_path).unlink(missing_ok=True)
    
        if not best_image_path:
            raise RuntimeError("图片生成未返回输出文件")
    
        local_img = best_image_path
        scene.image_path = local_img
        print(f"[Sampling] 场景 {scene.id} 最终选择: {Path(best_image_path).stat().st_size/1024:.0f}KB, 质量分={best_score:.2f}", flush=True)

        # v12.0: 图片生成成功后自动构建角色素材库
        try:
            await _build_character_material_library(job, scene, scene_dir)
        except Exception as e:
            print(f"[MatLib] 素材库构建异常(不阻塞): {str(e)[:80]}", flush=True)
    
        # v7.0: 双帧模式 — 为首尾帧视频额外生成一张尾帧图片
        end_img = None
        if job.use_dual_frame:
            print(f"[DualFrame] 场景 {scene.id}: 生成尾帧...", flush=True)
            end_seed = scene_seed + 9999
            replacements["SEED"] = end_seed
            end_workflow = fill_workflow(wf_template, replacements)
            try:
                end_prompt_id = await comfyui.submit_workflow(end_workflow)
                end_result = await comfyui.wait_for_result_ws(end_prompt_id, job_id=job_id, scene_id=scene.id, timeout=600)
                end_outputs = end_result.get("outputs", {})
                for node_id, node_out in end_outputs.items():
                    if "images" in node_out:
                        end_info = node_out["images"][0]
                        end_subfolder = end_info.get("subfolder", "")
                        end_path = await comfyui.download_output(end_info["filename"], end_subfolder, save_dir=scene_dir)
                        if end_path and Path(end_path).exists():
                            end_img = end_path
                            print(f"[DualFrame] 场景 {scene.id}: 尾帧已生成 ({Path(end_path).stat().st_size/1024:.0f}KB)", flush=True)
                        break
            except Exception as e:
                print(f"[DualFrame] 场景 {scene.id}: 尾帧生成失败 ({str(e)[:80]}), 回退到单帧", flush=True)
    
    scene.status = "generating_vid"
    

    await broadcast_progress(job_id, {
        "type": "scene_status",
        "scene_id": scene.id,
        "status": "generating_vid",
    })

    # ── Step 2: 图生视频 ──
    current_vid = None
    intensity = getattr(scene, 'emotional_intensity', 5)
    rhythm = getattr(scene, 'storytelling_rhythm', '') or ''
    
    # v8.7: 动态帧数 — storytelling_rhythm 驱动镜头时长
    # [v2 全面修复] 提高帧数下限，让 LTX 输出更长的真实运动片段，循环填充时重复更少、观感更顺。
    _RHYTHM_FRAMES = {
        "cliffhanger": 121, "hook": 121, "conflict": 145, "action": 97,
        "reversal": 169, "emotional_peak": 169, "info_drop": 145, "suspense": 169,
    }
    scene_frames = _RHYTHM_FRAMES.get(rhythm, 121)
    camera = getattr(scene, 'camera', '') or ''
    is_action = any(kw in camera for kw in ['跟随', '快速', '切换', '甩', '晃'])
    # v8.7: 动作场景用更短帧数，但设下限 97 帧（≈4s），避免过短导致冻帧/单图感
    if is_action:
        scene_frames = min(scene_frames, 97)
    
    # 构建视频提示词 (所有真视频模式共用) — v9.10 参数化运镜
    vid_base_prompt = scene.video_prompt or await _build_fallback_image_prompt(scene, global_character_desc, job=job)
    camera_motion = _generate_camera_motion(scene, job)
    if camera_motion and "slow push" not in vid_base_prompt and "dolly" not in vid_base_prompt:
        vid_base_prompt = f"{vid_base_prompt}, {camera_motion}"
    
    # v9.9: 全局风格统一 — 根据 job.style 动态选择，不再硬编码 wuxia
    _STYLE_SUFFIXES = {
        "cinematic": "cinematic realism, moody cinematic lighting, film grain, professional color grading, 9:16 vertical cinematic, consistent visual continuity",
        "anime": "anime style, manhwa art style, vibrant saturated colors, clean crisp line art, cel shading, 9:16 vertical cinematic, consistent visual continuity",
        "realistic": "photorealistic, cinematic film still, realistic textures, 35mm film grain, 9:16 vertical cinematic, consistent visual continuity",
        "ink": "chinese ink wash painting, xianxia illustration, wuxia fantasy art, 9:16 vertical cinematic, consistent visual continuity",
        "folk_horror": "dark folk horror atmosphere, muted earthy tones, grainy texture, eerie lighting, 9:16 vertical cinematic, consistent visual continuity",
    }
    _job_style = getattr(job, 'style', 'cinematic') or 'cinematic'
    _GLOBAL_STYLE = _STYLE_SUFFIXES.get(_job_style, _STYLE_SUFFIXES["cinematic"])
    _style_check = _job_style.split("_")[0] if _job_style else "cinematic"
    if _style_check not in vid_base_prompt.lower() and "cinematic" not in vid_base_prompt.lower():
        vid_base_prompt = f"{vid_base_prompt}, {_GLOBAL_STYLE}"

    # 同样统一 image_prompt（v9.9: 只在缺少当前风格词时追加，不强制 wuxia）
    if hasattr(scene, 'image_prompt') and scene.image_prompt:
        if _style_check not in scene.image_prompt.lower() and "cinematic" not in scene.image_prompt.lower():
            scene.image_prompt = f"{scene.image_prompt}, {_GLOBAL_STYLE}"
    
    # v8.6 Bug2修复: 视频提示词也经清理（移除anime污染+场景类型感知）
    vid_base_prompt = _clean_image_prompt(vid_base_prompt, scene, job)
    
    # v8.1: T2V 模式增强 — 加入动作/Narrative/镜头语言，避免只有「会动的照片」
    if job.video_mode == "ltx_t2v":
        scene_text = scene.subtitle_text or scene.description or ""
        # 提取场景动作词或核心元素，追加到 prompt 中
        t2v_action_boost = ""
        if any(kw in scene_text for kw in ['走', '跑', '冲', '赶', '追', '找', '看', '听见', '喊', '说', '响', '停', '亮', '灭']):
            t2v_action_boost += ", narrative action scene, character performing clear motion"
        if any(kw in scene_text for kw in ['雾', '风', '雨', '火', '烟', '锣', '钟', '铃', '灯']):
            t2v_action_boost += ", atmospheric environmental effects, dynamic weather and lighting"
        if len(scene_text) > 80:
            t2v_action_boost += ", story-driven cinematography, clear visual narrative progression"
        else:
            t2v_action_boost += ", cinematic shot composition, visual storytelling"
        vid_base_prompt = f"{vid_base_prompt}{t2v_action_boost}"
    
    # v12.0: 统一视频生成调度 (video_engine.py) — 替换 365 行内联代码
    vid_ctx = {
        "comfyui": comfyui,
        "job": job,
        "load_workflow": load_workflow,
        "fill_workflow": fill_workflow,
        "ken_burns_func": _generate_ken_burns_video,
        "find_output_file": ComfyUIClient.find_output_file,
        "vid_base_prompt": vid_base_prompt,
        "scene_frames": scene_frames,
        "merge_videos_func": merge_videos,
    }
    current_vid = await video_engine.dispatch(scene, scene_dir, vid_ctx)
    if current_vid:
        scene.video_path = current_vid
    else:
        # 如果全部失败，至少保留图片
        current_vid = local_img
        scene.video_path = local_img
        scene.final_video_path = local_img
        print(f"[WARN] 场景 {scene.id}: 未能生成任何视频，回退到静态图片", flush=True)
    
    # 漫剧伪声字特效
    if job.use_manga_fx and current_vid and Path(current_vid).exists():
        try:
            fx_path = await _add_manga_fx(current_vid, scene, scene_dir)
            if fx_path != current_vid:
                if scene.video_path == current_vid:
                    scene.video_path = fx_path
                if scene.final_video_path == current_vid:
                    scene.final_video_path = fx_path
                current_vid = fx_path
                print(f"[MangaFX] 场景 {scene.id}: 伪声字特效已添加", flush=True)
        except Exception as e:
            print(f"[MangaFX] 场景 {scene.id}: 失败 ({str(e)[:60]})", flush=True)

    scene.status = "generating_tts"

    # ── Step 3: 智能分角色配音（v4.0）──
    if job.tts_enabled and scene.subtitle_text:
        if job.smart_dubbing and job.characters:
            # v4.0: 智能分角色配音
            await broadcast_progress(job_id, {
                "type": "scene_status",
                "scene_id": scene.id,
                "status": "generating_tts_smart",
            })
            scene.status = "generating_tts"
            try:
                current_vid = await _smart_dubbing(job, scene, scene_dir, current_vid, char_map)
            except Exception as e:
                # 智能配音失败，回退到单声音配音
                print(f"[SmartDubbing] Fallback to single voice: {str(e)[:100]}")
                current_vid = await _single_voice_dubbing(job, scene, scene_dir, current_vid)
        else:
            # v3.0: 原始单声音配音
            current_vid = await _single_voice_dubbing(job, scene, scene_dir, current_vid)

        # P2-⑨: 口型同步 — 用配音音频驱动角色口型
        try:
            current_vid = await _apply_lip_sync(scene, scene_dir, current_vid, job)
        except Exception as e:
            print(f"[LipSync] 口型同步失败（降级）: {str(e)[:100]}", flush=True)
    
    # ── Step 4: 烧录字幕（v5.0: ASS动态字幕 或 SRT字幕）──
    subtitle_vid = current_vid
    if scene.subtitle_timings:
        final_path = str(scene_dir / f"scene_{scene.id:03d}_final.mp4")
        if job.use_ass_subtitles:
            # v12.0: ASS 漫剧级动态字幕（思源黑体+智能分行+角色配色+安全区）
            char_list = [c.model_dump() if hasattr(c, 'model_dump') else dict(c) for c in job.characters] if job.characters else None
            await burn_ass_subtitles(current_vid, scene.subtitle_timings, final_path, characters=char_list)
        else:
            # v4.0: SRT 时间轴字幕
            await burn_timed_subtitles(current_vid, scene.subtitle_timings, final_path)
        subtitle_vid = final_path
        scene.final_video_path = final_path
    else:
        # 回退：静态字幕烧录（支持中文，使用微软雅黑字体）
        subtitle = scene.subtitle_display or scene.subtitle_text
        if subtitle and find_ffmpeg():
            final_path = str(scene_dir / f"scene_{scene.id:03d}_final.mp4")
            await burn_subtitles(current_vid, subtitle, final_path)
            subtitle_vid = final_path
            scene.final_video_path = final_path
        else:
            scene.final_video_path = current_vid

    # ── Step 4.5: v6.0 自动配乐 BGM（根据场景情绪，优先使用预生成和弦BGM）──
    if scene.mood and scene.final_video_path and find_ffmpeg():
        try:
            bgm_path = str(scene_dir / f"scene_{scene.id:03d}_with_bgm.mp4")
            result = await add_scene_bgm(scene.final_video_path, bgm_path, scene.mood, bgm_volume=0.15, scene_setting=scene.setting)
            if Path(bgm_path).exists() and Path(bgm_path).stat().st_size > Path(scene.final_video_path).stat().st_size * 0.5:
                scene.final_video_path = bgm_path
                print(f"[BGM] 场景 {scene.id}: 自动添加{scene.mood}情绪BGM", flush=True)
        except Exception as bgm_err:
            print(f"[BGM] 场景 {scene.id}: 自动BGM失败 ({str(bgm_err)[:60]})", flush=True)

    # ── Step 4.7: v6.0 自动音效 SFX（根据场景内容匹配环境音/动作音）──
    if scene.final_video_path and find_ffmpeg():
        try:
            sfx_path = str(scene_dir / f"scene_{scene.id:03d}_sfx.mp4")
            # v8.7: SFX 音量随情绪强度动态变化
            intensity = getattr(scene, 'emotional_intensity', 5)
            dyn_vol = 0.12 + (intensity - 1) * 0.03  # 5→0.24, 10→0.39
            result = await add_scene_sfx(scene.final_video_path, scene, sfx_path, sfx_volume=dyn_vol)
            if Path(sfx_path).exists() and Path(sfx_path).stat().st_size > Path(scene.final_video_path).stat().st_size * 0.8:
                scene.final_video_path = sfx_path
        except Exception as sfx_err:
            print(f"[SFX] 场景 {scene.id}: SFX失败 ({str(sfx_err)[:60]})", flush=True)

    # ── Step 5: 电影感色彩分级（v5.0）──
    if job.use_color_grading and scene.final_video_path and find_ffmpeg():
        try:
            graded_path = str(scene_dir / f"scene_{scene.id:03d}_graded.mp4")
            # v8.7: 情绪驱动色彩分级
            mood = getattr(scene, 'mood', '') or ''
            grade_style = "cinematic"
            if any(kw in mood for kw in ['恐惧', '紧张', '惊悚']): grade_style = "cold"
            elif any(kw in mood for kw in ['喜悦', '温暖', '温馨']): grade_style = "warm"
            elif any(kw in mood for kw in ['悲伤', '压抑', '惆怅']): grade_style = "vintage"
            await apply_color_grading(scene.final_video_path, graded_path, style=grade_style)
            if Path(graded_path).exists() and Path(graded_path).stat().st_size > 1000:
                scene.final_video_path = graded_path
                print(f"[INFO] 场景 {scene.id}: 色彩分级完成", flush=True)
        except Exception as cg_err:
            print(f"[WARN] 场景 {scene.id}: 色彩分级失败 ({str(cg_err)[:60]})", flush=True)

    # ── Step 5.5: v8.7 视觉特效 (震动/速度线) ──
    if find_ffmpeg():
        try:
            fx_path = await _apply_visual_fx(scene.final_video_path, scene)
            if fx_path != scene.final_video_path and Path(fx_path).exists():
                scene.final_video_path = fx_path
                print(f"[VFX] 场景 {scene.id}: 视觉特效已应用", flush=True)
        except Exception as fx_err:
            print(f"[WARN] 场景 {scene.id}: 视觉特效失败 ({str(fx_err)[:60]})", flush=True)

    # ── Step 6: 淡入淡出转场（v5.0）──
    if job.use_fade_transition and scene.final_video_path and find_ffmpeg():
        try:
            faded_path = str(scene_dir / f"scene_{scene.id:03d}_faded.mp4")
            await apply_fade_transition(scene.final_video_path, faded_path, fade_in=0.3, fade_out=0.3)
            if Path(faded_path).exists() and Path(faded_path).stat().st_size > 1000:
                scene.final_video_path = faded_path
        except Exception as fade_err:
            print(f"[WARN] 场景 {scene.id}: 转场效果失败 ({str(fade_err)[:60]})", flush=True)

    # ── Step 7: 清理中间文件 ──
    cleanup_patterns = ["*_graded*", "*_faded*", "*_with_audio*"]
    for pattern in cleanup_patterns:
        for f in scene_dir.glob(pattern):
            try:
                # 只清理不在 final_video_path 中的文件
                if str(f) != scene.final_video_path:
                    f.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"[Cleanup] 清理文件失败 {f}: {str(e)[:80]}")

    scene.status = "done"
    scene.comfyui_progress = 1.0

    await broadcast_progress(job_id, {
        "type": "scene_status",
        "scene_id": scene.id,
        "status": "done",
    })

async def _single_voice_dubbing(job: JobState, scene: Scene, scene_dir: Path,
                                 current_vid: str) -> str:
    """v3.0 原始单声音配音"""
    await broadcast_progress(job.id, {
        "type": "scene_status",
        "scene_id": scene.id,
        "status": "generating_tts",
    })
    scene.status = "generating_tts"

    audio_path = str(scene_dir / f"scene_{scene.id:03d}.mp3")
    try:
        # v7.0: 自动检测 CosyVoice 2, 优先使用电影级配音
        tts_engine = "cosyvoice" if _is_cosyvoice_available() else "edge"
        audio_dur = await generate_tts(
            scene.subtitle_text, audio_path,
            voice=job.tts_voice, rate=job.tts_rate, volume=job.tts_volume,
            engine=tts_engine, mood=getattr(scene, 'mood', ''),
            intensity=getattr(scene, 'emotional_intensity', 5),
            is_narration=True  # 单声音模式整体作为旁白处理
        )
        scene.audio_path = audio_path
        scene.audio_duration = audio_dur
    except Exception:
        scene.audio_path = None
        scene.audio_duration = 0.0

    if scene.audio_path and scene.audio_duration > 0:
        av_merged_path = str(scene_dir / f"scene_{scene.id:03d}_with_audio.mp4")
        await combine_audio_video(current_vid, scene.audio_path, av_merged_path, scene.audio_duration)
        return av_merged_path
    return current_vid


def _rule_based_dialogue_split(text: str, job) -> list[dict]:
    """v9.9: 本地规则拆分对白 — 当 DeepSeek 不可用时的 fallback。

    用正则识别中文引号内的对白和引号外的旁白，
    通过「角色名：」前缀或上下文猜测说话者。
    """
    import re
    if not text or not text.strip():
        return []

    segments = []
    char_names = _get_character_names(job)

    # 匹配：角色名 + 冒号/： + 引号对话，或 直接引号对话
    # 支持 "..." 「...」 "..."
    pattern = re.compile(
        r'(?:(?P<speaker>[^\s，。：:]{1,6})\s*[：:]\s*)?'
        r'(?P<quote>[""「」]|)[""「](?P<dialogue>[^""」]+)[""」]'
        r'|(?P<narration>[^""」]+)'
    )

    pos = 0
    last_speaker = "旁白"

    # 更简单可靠的方式：按引号分割
    parts = re.split(r'([""「」])', text)

    i = 0
    current_narration = ""
    while i < len(parts):
        part = parts[i]
        if part in ('"', '"', '「', '」'):
            if part in ('"', '「'):
                # 开始引号，收集对话内容
                dialogue_text = parts[i + 1] if i + 1 < len(parts) else ""
                # 从前面的旁白中提取说话者
                speaker = "旁白"
                # 检查旁白末尾是否有 "XXX说" "XXX道" 等
                narr_trimmed = current_narration.rstrip()
                for cname in char_names:
                    if cname in narr_trimmed[-20:]:
                        speaker = cname
                        break
                if speaker == "旁白":
                    # 检查通用说话动词
                    m = re.search(r'([^\s，。]{1,4})\s*(?:说|道|问|答|喊|叫|笑道|说道|问道)', narr_trimmed[-30:])
                    if m and m.group(1) in char_names:
                        speaker = m.group(1)

                if current_narration.strip():
                    segments.append({"type": "narration", "speaker": "旁白", "text": current_narration.strip()})
                current_narration = ""

                if dialogue_text.strip():
                    segments.append({"type": "dialogue", "speaker": speaker, "text": dialogue_text.strip()})
                    last_speaker = speaker
                i += 2  # 跳过引号和内容
            else:
                # 结束引号
                i += 1
        else:
            current_narration += part
            i += 1

    if current_narration.strip():
        segments.append({"type": "narration", "speaker": "旁白", "text": current_narration.strip()})

    return segments if segments else [{"type": "narration", "speaker": "旁白", "text": text.strip()}]


async def _smart_dubbing(job: JobState, scene: Scene, scene_dir: Path,
                          current_vid: str, char_map: dict) -> str:
    """v4.0 智能分角色配音 - 每个角色用不同声音，旁白单独声音"""
    char_map_local = char_map

    # 用 DeepSeek 拆分旁白和对白
    segments = None
    try:
        result = await call_deepseek(
            job.deepseek_key,
            DIALOGUE_SPLIT_SYSTEM,
            f"请将以下文本拆分为旁白和对白，标注说话角色：\n\n{scene.subtitle_text}",
            max_tokens=2048,
            temperature=0.3  # 文本分类需要确定性
        )
        segments = extract_json_array(result)
    except Exception as e:
        print(f"[SmartDubbing] DeepSeek拆分失败({str(e)[:80]})，尝试规则拆分", flush=True)

    # v9.9: DeepSeek 失败时用本地规则拆分对白，而不是直接回退单声音
    if not segments:
        segments = _rule_based_dialogue_split(scene.subtitle_text, job)
        if segments:
            print(f"[SmartDubbing] 规则拆分成功，{len(segments)}段", flush=True)

    if not segments:
        raise RuntimeError("对白拆分结果为空")

    # 为每段生成独立音频
    audio_segments = []  # [(audio_path, duration, speaker, text), ...]
    total_duration = 0.0

    for idx, seg in enumerate(segments):
        text = seg.get("text", "").strip()
        if not text:
            continue

        speaker = seg.get("speaker", "旁白")

        # 确定声音 — 优先用 cosyvoice_voice（如果已分角色预分配）
        if speaker == "旁白" or seg.get("type") == "narration":
            voice_id = job.narrator_voice
        elif speaker in char_map_local:
            char = char_map_local[speaker]
            # v11: 优先用 CosyVoice2 speaker（自动翻译兜底）
            cv_voice = getattr(char, 'cosyvoice_voice', '') or ''
            if cv_voice and _is_cosyvoice_available():
                voice_id = cv_voice  # 已是 CosyVoice2 speaker 名
            else:
                voice_id = char.voice_id or job.narrator_voice
        else:
            # v8.7 Phase 5b: 未知角色按性别猜测（不再全部回退旁白）
            guessed_gender = guess_character_gender(speaker, job)
            voice_id = "zh-CN-YunxiNeural" if guessed_gender == "男" else "zh-CN-XiaoxiaoNeural"

        seg_audio_path = str(scene_dir / f"scene_{scene.id:03d}_seg{idx:02d}.mp3")
        try:
            # v9.9: 传入 intensity 和 is_narration，实现情绪差异化配音
            is_narr = (speaker == "旁白" or seg.get("type") == "narration")
            # v11: CosyVoice2 优先，不可用时回退 Edge-TTS
            tts_engine = "cosyvoice" if _is_cosyvoice_available() else "edge"
            dur = await generate_tts(text, seg_audio_path, voice=voice_id,
                                      rate=job.tts_rate, volume=job.tts_volume,
                                      engine=tts_engine,
                                      mood=scene.mood,
                                      intensity=getattr(scene, 'emotional_intensity', 5),
                                      is_narration=is_narr)
            audio_segments.append({
                "path": seg_audio_path,
                "duration": dur,
                "speaker": speaker,
                "text": text,
                "start": total_duration
            })
            total_duration += dur
        except Exception:
            # 单段失败跳过
            continue

    if not audio_segments:
        raise RuntimeError("所有音频段生成失败")

    # 合并所有音频段为一个完整音频
    merged_audio_path = str(scene_dir / f"scene_{scene.id:03d}_merged.mp3")
    await _concat_audio_files([s["path"] for s in audio_segments], merged_audio_path)

    scene.audio_path = merged_audio_path
    scene.audio_duration = total_duration

    # 构建字幕时间轴
    subtitle_timings = []
    for seg in audio_segments:
        subtitle_timings.append({
            "start": round(seg["start"], 2),
            "end": round(seg["start"] + seg["duration"], 2),
            "text": seg["text"] if len(seg["text"]) <= 80 else seg["text"][:77] + "...",
            "speaker": seg["speaker"]
        })
    scene.subtitle_timings = subtitle_timings

    # 合并音视频（音频为基准调整视频速度）
    av_merged_path = str(scene_dir / f"scene_{scene.id:03d}_with_audio.mp4")
    await combine_audio_video(current_vid, merged_audio_path, av_merged_path, total_duration)

    return av_merged_path

async def _concat_audio_files(audio_paths: list[str], output_path: str) -> str:
    """将多个音频文件合并为一个"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or len(audio_paths) == 0:
        if audio_paths and Path(audio_paths[0]).exists():
            shutil.copy2(audio_paths[0], output_path)
        return output_path

    if len(audio_paths) == 1:
        shutil.copy2(audio_paths[0], output_path)
        return output_path

    # 创建 concat 文件列表
    concat_file = Path(output_path).parent / f"audio_concat_{uuid.uuid4().hex[:6]}.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for ap in audio_paths:
            safe_path = str(ap).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    cmd = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c:a", "libmp3lame", "-b:a", "128k",
        output_path
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

    # 清理临时文件
    concat_file.unlink(missing_ok=True)

    if proc.returncode != 0:
        # 合并失败，使用第一段
        if audio_paths and Path(audio_paths[0]).exists():
            shutil.copy2(audio_paths[0], output_path)

    return output_path

async def burn_timed_subtitles(video_path: str, timings: list[dict], output_path: str,
                                font_size: int = 18, margin_bottom: int = 30) -> str:
    """基于时间轴烧录字幕 - 声音/画面/字幕三者同步"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(video_path, output_path)
        return output_path

    # 生成 SRT 字幕文件
    srt_path = Path(output_path).parent / f"sub_{uuid.uuid4().hex[:6]}.srt"
    srt_content = ""
    for i, t in enumerate(timings):
        start_time = _seconds_to_srt_time(t["start"])
        end_time = _seconds_to_srt_time(t["end"])
        text = t.get("text", "")
        speaker = t.get("speaker", "")
        # 如果有说话角色，在字幕中标注
        if speaker and speaker != "旁白":
            display_text = f"[{speaker}] {text}"
        else:
            display_text = text
        # 截取字幕长度
        if len(display_text) > 80:
            display_text = display_text[:77] + "..."
        srt_content += f"{i+1}\n{start_time} --> {end_time}\n{display_text}\n\n"

    srt_path.write_text(srt_content, encoding="utf-8")

    # 用 ffmpeg 烧录 SRT 字幕
    # v8.7 Bug修复: 跨平台字体选择 — Windows用Microsoft YaHei，Linux/macOS用Noto Sans CJK
    escaped_srt = str(srt_path).replace(":", "\\:").replace("'", "\\'")
    if sys.platform == "win32":
        font_name = "Microsoft YaHei"
    elif sys.platform == "darwin":
        font_name = "PingFang SC"
    else:
        font_name = "Noto Sans CJK SC"
    
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", f"subtitles='{escaped_srt}'"
               f":force_style='FontName={font_name},FontSize={font_size},"
               f"PrimaryColour=&HFFFFFF,OutlineColour=&H40000000,Outline=1,MarginV={margin_bottom}'",
        "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
        "-c:a", "copy",
        output_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            # SRT字幕烧录失败，回退到drawtext方式
            # 用最后一段文本作为静态字幕
            last_text = timings[-1].get("text", "") if timings else ""
            await burn_subtitles(video_path, last_text, output_path)
    finally:
        srt_path.unlink(missing_ok=True)

    return output_path


# ─── v8.7 Phase 4: 视觉特效 ──────────────────────────────

async def _add_screen_shake(video_path: str, scene) -> str:
    """屏幕震动 — 高情绪场景 (intensity>=7 或 恐惧/紧张/惊悚)"""
    ffmpeg = find_ffmpeg()
    intensity = getattr(scene, 'emotional_intensity', 5)
    mood = getattr(scene, 'mood', '') or ''
    if intensity < 7 and not any(kw in mood for kw in ['恐惧', '紧张', '惊悚']):
        return video_path
    
    output = str(Path(video_path).with_suffix('.shaken.mp4'))
    shake_strength = min(0.06, 0.01 + (intensity - 7) * 0.015)
    
    # crop + random offset 实现震动
    expr = (f"if(not(mod(n,2)), crop=iw-iw*{shake_strength*0.8}:ih-ih*{shake_strength*0.8}:"
            f"iw*{shake_strength*0.2}:ih*{shake_strength*0.2}, "
            f"crop=iw-iw*{shake_strength*0.6}:ih-ih*{shake_strength*0.6}:"
            f"iw*{shake_strength*0.4}:ih*{shake_strength*0.4}), "
            f"scale=iw:ih")
    
    cmd = [ffmpeg, "-y", "-i", video_path,
           "-vf", f"crop=iw-iw*{shake_strength}:ih-ih*{shake_strength}:n*{shake_strength}*iw:n*{shake_strength}*ih:eval=frame,scale=iw:ih",
           "-c:a", "copy", output]
    try:
        await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.sleep(2)
        if Path(output).exists() and Path(output).stat().st_size > 10000:
            return output
    except Exception as e:
        logger.warning(f"[VFX] 屏幕震动特效失败: {e}")
    return video_path


async def _add_speed_lines(video_path: str, scene) -> str:
    """速度线 — 动作/快速镜头场景 (camera 含 跟随/快速/切换/甩/晃)"""
    ffmpeg = find_ffmpeg()
    camera = getattr(scene, 'camera', '') or ''
    if not any(kw in camera for kw in ['跟随', '快速', '切换', '甩', '晃']):
        return video_path
    
    output = str(Path(video_path).with_suffix('.speedlines.mp4'))
    # 方向性模糊 (横向) 模拟速度线
    vf = ("smartblur=1.5:-0.35:-3.5:0.65:0.25:2.0,"
          "hue=s=0.8:enable='between(n,0,30)',"
          "unsharp=5:5:0.8:3:3:0.4")
    cmd = [ffmpeg, "-y", "-i", video_path, "-vf", vf, "-c:a", "copy", output]
    try:
        await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.sleep(2)
        if Path(output).exists() and Path(output).stat().st_size > 10000:
            return output
    except Exception as e:
        logger.warning(f"[VFX] 速度线特效失败: {e}")
    return video_path


async def _apply_visual_fx(video_path: str, scene) -> str:
    """v8.7: 协调视觉特效应用"""
    result = video_path
    result = await _add_screen_shake(result, scene)
    result = await _add_speed_lines(result, scene)
    return result


def _seconds_to_srt_time(seconds: float) -> str:
    """将秒数转为 SRT 时间格式 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def apply_color_grading(video_path: str, output_path: str, style: str = "cinematic") -> str:
    """v5.0 电影感色彩分级 - 使用 ffmpeg 色彩曲线实现 LUT 效果
    
    style 选项:
      - "cinematic" : 青橙色调（好莱坞电影标准）
      - "warm"      : 暖色调（温情故事）
      - "cold"      : 冷色调（悬疑/科幻）
      - "vintage"   : 老电影胶片感
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(video_path, output_path)
        return output_path

    # 色彩分级预设（ffmpeg 色彩曲线）
    style_filters = {
        "cinematic": (
            # 青橙色调：降低高光红色，提升阴影蓝/青，轻微降低饱和度
            "curves=r='0/0 0.5/0.42 1/0.85':"
            "g='0/0 0.5/0.5 1/0.95':"
            "b='0/0.05 0.5/0.58 1/1',"
            "eq=saturation=0.85:contrast=1.05:brightness=-0.02,"
            "vignette=PI/4"  # 暗角效果
        ),
        "warm": (
            "curves=r='0/0 0.5/0.55 1/1':"
            "g='0/0 0.5/0.5 1/0.95':"
            "b='0/0 0.5/0.42 1/0.82',"
            "eq=saturation=1.1:contrast=1.02:brightness=0.01"
        ),
        "cold": (
            "curves=r='0/0 0.5/0.42 1/0.85':"
            "g='0/0 0.5/0.5 1/0.98':"
            "b='0/0.05 0.5/0.58 1/1.0',"
            "eq=saturation=0.8:contrast=1.1:brightness=-0.03"
        ),
        "vintage": (
            "curves=r='0/0.05 0.5/0.5 1/0.9':"
            "g='0/0.02 0.5/0.48 1/0.88':"
            "b='0/0.04 0.5/0.44 1/0.82',"
            "eq=saturation=0.75:contrast=1.05,"
            "noise=alls=3:allf=t"  # 胶片噪点
        ),
    }

    vf = style_filters.get(style, style_filters["cinematic"])
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "21", "-preset", "fast",
        "-c:a", "copy",
        output_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode != 0:
            print(f"[WARN] 色彩分级失败，保留原视频: {stderr.decode()[:100]}", flush=True)
            shutil.copy2(video_path, output_path)
    except Exception as e:
        print(f"[WARN] 色彩分级异常: {e}", flush=True)
        shutil.copy2(video_path, output_path)

    return output_path


async def apply_fade_transition(video_path: str, output_path: str,
                                 fade_in: float = 0.3, fade_out: float = 0.3) -> str:
    """v5.0 添加淡入淡出转场效果"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(video_path, output_path)
        return output_path

    # 获取视频时长
    duration = await get_audio_duration(video_path)
    if duration <= 0 or duration <= (fade_in + fade_out):
        shutil.copy2(video_path, output_path)
        return output_path

    fade_out_start = duration - fade_out
    vf = (f"fade=t=in:st=0:d={fade_in}:alpha=0,"
          f"fade=t=out:st={fade_out_start:.2f}:d={fade_out}:alpha=0")

    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "21", "-preset", "fast",
        "-c:a", "copy",
        output_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            shutil.copy2(video_path, output_path)
    except Exception:
        shutil.copy2(video_path, output_path)

    return output_path


def _smart_break_text(text: str, max_chars_per_line: int = 18) -> str:
    """智能分行 — 在标点符号处断行，最多2行，避免截断词语
    
    Args:
        text: 原始字幕文本
        max_chars_per_line: 每行最大字符数
        
    Returns:
        ASS 格式文本（用 \\N 表示换行）
    """
    text = text.strip()
    if len(text) <= max_chars_per_line:
        return text
    
    # 在标点处分割（保留标点）
    import re
    parts = re.split(r'([，。！？；：、—…\n])', text)
    
    # 重新组合为不超过 max_chars_per_line 的行
    lines = []
    current_line = ""
    for part in parts:
        if not part:
            continue
        if part == "\n":
            if current_line:
                lines.append(current_line)
                current_line = ""
            continue
        if len(current_line) + len(part) <= max_chars_per_line:
            current_line += part
        else:
            if current_line:
                lines.append(current_line)
            current_line = part
    
    if current_line:
        lines.append(current_line)
    
    # 最多2行
    if len(lines) > 2:
        # 合并多余的行到第二行
        lines = [lines[0], "".join(lines[1:])]
        if len(lines[1]) > max_chars_per_line * 2:
            lines[1] = lines[1][:max_chars_per_line * 2 - 3] + "..."
    
    return "\\N".join(lines)


def _get_role_color(speaker: str, characters: list[dict] | None = None,
                    fallback_idx: int = 0) -> str:
    """根据角色属性自动配色
    
    主角 → 金色, 反派 → 红色, 配角 → 青色, 路人 → 绿色, 旁白 → 白色
    未知角色 → 按顺序分配池中颜色
    """
    if speaker in ("旁白", "narrator", ""):
        return "&H00FFFFFF"  # 白色
    
    # 角色池（ASS BGR格式 &HAABBGGRR）
    role_colors = {
        "主角": "&H0000D7FF",   # 金色 (RGB 255,215,0)
        "反派": "&H005050FF",   # 红色 (RGB 255,80,80)
        "配角": "&H00FFFF80",   # 青色 (RGB 128,255,255)
        "路人": "&H0000AA55",   # 绿色 (RGB 85,170,0)
    }
    fallback_pool = [
        "&H0000D7FF", "&H00FF99FF", "&H0066CCFF",
        "&H00FFCC33", "&H0033FF66", "&H00CC66FF",
    ]
    
    # 查找角色信息
    if characters:
        for char in characters:
            if char.get("name") == speaker:
                role = char.get("role_type", "")
                for key, color in role_colors.items():
                    if key in role:
                        return color
                break
    
    # 未知角色按顺序分配
    return fallback_pool[fallback_idx % len(fallback_pool)]


async def burn_ass_subtitles(video_path: str, timings: list[dict], output_path: str,
                              characters: list[dict] | None = None) -> str:
    """v12.0 ASS 动态字幕烧录 — 漫剧级字幕系统
    
    v12 改进:
    - 1080x1920 竖屏标准分辨率（之前 480x854 非标准）
    - 思源黑体 (Noto Sans SC) 跨平台字体（之前 Microsoft YaHei 仅 Windows）
    - 3px 外描边 + 2px 阴影，保证任何背景上可读
    - 半透明底条（BorderStyle=4 低层）增强可读性
    - 角色属性自动配色（主角金色/反派红色/配角青色）
    - 智能分行（标点处断行，最多2行）
    - 竖屏安全区（底部 150px 避让手机导航栏/刘海）
    - 逐字淡入动效
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        shutil.copy2(video_path, output_path)
        return output_path

    # 角色颜色缓存
    speaker_color_map: dict[str, str] = {"旁白": "&H00FFFFFF", "narrator": "&H00FFFFFF"}
    speaker_idx = 0

    def get_speaker_color(spk: str) -> str:
        nonlocal speaker_idx
        if spk not in speaker_color_map:
            speaker_color_map[spk] = _get_role_color(spk, characters, speaker_idx)
            speaker_idx += 1
        return speaker_color_map[spk]

    # ASS 文件头 — 1080x1920 竖屏标准
    ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans SC,54,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,2,60,60,150,1
Style: Narrator,Noto Sans SC,46,&H00DDDDDD,&H000000FF,&H00000000,&H80000000,0,-1,0,0,100,100,0,0,1,2,1,2,60,60,150,1
Style: SpeakerName,Noto Sans SC,38,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,1,8,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def _ass_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = sec % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    for t in timings:
        raw_text = t.get("text", "")
        speaker = t.get("speaker", "旁白")
        start_t = _ass_time(t["start"])
        end_t = _ass_time(t["end"])
        color = get_speaker_color(speaker)
        duration = t["end"] - t["start"]

        # 智能分行
        text = _smart_break_text(raw_text)

        # 计算淡入时间（不超过总时长的 15%）
        fade_in = min(int(duration * 150), 200)
        fade_out = min(int(duration * 100), 150)

        if speaker and speaker != "旁白":
            # 对白：角色名标签 + 正文
            # Layer 0: 半透明底条（增强可读性）
            # Layer 1: 角色名（上方）
            # Layer 2: 正文
            
            # 半透明底条
            bar_height = 90 if "\\N" in text else 50
            ass_content += (
                f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,"
                f"{{\\p1\\bord0\\shad0\\1a&HFF&\\4c&H80000000}}m 0 0 l 1080 0 1080 {bar_height} 0 {bar_height}{{\\p0}}\n"
            )
            
            # 角色名标签（顶部小字）
            name_y = 120  # 底部安全区上方
            ass_content += (
                f"Dialogue: 1,{start_t},{end_t},SpeakerName,,0,0,0,,"
                f"{{\\c{color}\\fad({fade_in},{fade_out})}}{speaker}\n"
            )
            
            # 正文（带描边和淡入）
            ass_content += (
                f"Dialogue: 2,{start_t},{end_t},Default,,0,0,0,,"
                f"{{\\c&H00FFFFFF\\fad({fade_in},{fade_out})}}{text}\n"
            )
        else:
            # 旁白：斜体灰色 + 淡入淡出
            ass_content += (
                f"Dialogue: 0,{start_t},{end_t},Narrator,,0,0,0,,"
                f"{{\\fad({fade_in},{fade_out})}}{text}\n"
            )

    ass_path = Path(output_path).parent / f"sub_{uuid.uuid4().hex[:6]}.ass"
    ass_path.write_text(ass_content, encoding="utf-8")

    # 字体目录 — 优先使用内嵌思源黑体
    fonts_dir = PROJECT_ROOT / "resources" / "fonts"
    fonts_arg = f":fontsdir='{str(fonts_dir.as_posix()).replace(chr(39), '').replace(':', chr(92) + ':')}'" if fonts_dir.exists() else ""
    
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", f"ass='{str(ass_path.as_posix()).replace(':', chr(92) + ':')}'{fonts_arg}",
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy",
        output_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode != 0:
            print(f"[WARN] ASS字幕失败，回退SRT: {stderr.decode(errors='replace')[-500:]}", flush=True)
            await burn_timed_subtitles(video_path, timings, output_path)
    except Exception as e:
        print(f"[WARN] ASS字幕异常: {e}", flush=True)
        await burn_timed_subtitles(video_path, timings, output_path)
    finally:
        ass_path.unlink(missing_ok=True)

    return output_path


async def mix_audio_high_quality(video_path: str, bgm_path: str,
                               output_path: str, bgm_volume: float = 0.25) -> str:
    """
    v6.2: 使用 pydub 做专业级音频混音（质量优先）
    - 音量归一化（防止忽大忽小）
    - 智能淡入淡出（音乐起止更自然）
    - 动态范围压缩（让声音更饱满）
    - 三层混音（配音 + BGM + 音效）
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(bgm_path).exists():
        shutil.copy2(video_path, output_path)
        return output_path

    try:
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "novel2vid_audio"
        temp_dir.mkdir(exist_ok=True)

        # 1. 提取视频中的音频（配音）
        voice_path = str(temp_dir / f"voice_{uuid.uuid4().hex[:8]}.wav")
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            voice_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        if not Path(voice_path).exists():
            shutil.copy2(video_path, output_path)
            return output_path

        # 2. 用 pydub 加载音频
        voice = AudioSegment.from_file(voice_path)
        bgm = AudioSegment.from_file(bgm_path)

        # 3. 音量归一化（防止忽大忽小）
        voice = normalize(voice)
        bgm = normalize(bgm) - 12  # BGM 降低 12dB

        # 4. 调整 BGM 音量
        bgm = bgm - (1.0 - bgm_volume) * 20  # 转换音量比例到 dB

        # 5. 循环 BGM 以匹配视频长度
        video_duration_ms = len(voice)
        while len(bgm) < video_duration_ms:
            bgm = bgm + bgm
        bgm = bgm[:video_duration_ms]

        # P0-④: BGM 动态音量（sidechain ducking）
        # 在有配音时 BGM -10dB 降低让位，无配音时恢复
        try:
            from pydub import AudioSegment as _AS
            # 找配音段（音量 > 阈值 = -30dB）
            chunk_ms = 100  # 100ms 一段
            threshold_db = -30
            ducked_bgm = _AS.silent(duration=video_duration_ms)
            for start in range(0, video_duration_ms, chunk_ms):
                end = min(start + chunk_ms, video_duration_ms)
                voice_chunk = voice[start:end]
                # 计算该段平均音量
                if len(voice_chunk) > 0:
                    chunk_db = voice_chunk.dBFS
                else:
                    chunk_db = -100
                # 有配音 → BGM -10dB；无 → 原始音量
                if chunk_db > threshold_db:
                    bgm_segment = bgm[start:end] - 10
                else:
                    bgm_segment = bgm[start:end]
                ducked_bgm = ducked_bgm.overlay(bgm_segment, position=start)
            bgm = ducked_bgm
            print(f"[Audio] P0-④ BGM 动态 ducking 已应用", flush=True)
        except Exception as e:
            print(f"[Audio] BGM ducking 失败（降级固定音量）: {e}", flush=True)

        # 6. 智能淡入淡出（音乐起止更自然）
        fade_in_ms = min(2000, int(video_duration_ms * 0.1))  # 前10%，最多2秒
        fade_out_ms = min(3000, int(video_duration_ms * 0.15))  # 后15%，最多3秒
        bgm = bgm.fade_in(fade_in_ms).fade_out(fade_out_ms)

        # 7. 混音（配音 + BGM）
        mixed = voice.overlay(bgm, position=0)

        # 8. 动态范围压缩（让声音更饱满）
        mixed = compress_dynamic_range(mixed, threshold=-20, ratio=2.0)

        # 9. 导出混音后的音频
        mixed_path = str(temp_dir / f"mixed_{uuid.uuid4().hex[:8]}.wav")
        mixed.export(mixed_path, format="wav")

        # 10. 重新合并音频和视频 — v8.1: 保持视频完整时长，不截取
        vid_duration = await get_audio_duration(video_path)
        cmd = [
            ffmpeg, "-y",
            "-i", video_path,
            "-i", mixed_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", str(vid_duration),
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)

        # 清理临时文件
        for p in [voice_path, mixed_path]:
            Path(p).unlink(missing_ok=True)

        if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
            print(f"[Audio] pydub 专业混音完成: {Path(output_path).name}", flush=True)
            return output_path
        else:
            shutil.copy2(video_path, output_path)
            return output_path

    except Exception as e:
        print(f"[Audio] pydub 混音失败，回退 ffmpeg: {e}", flush=True)
        # 回退到原来的 ffmpeg 混音
        return await add_bgm_to_video_legacy(video_path, bgm_path, output_path, bgm_volume)


# ─── 环境音/音效匹配（v12.0 三轨混音） ─────────────────────────

# 场景关键词 → 环境音映射
_AMBIENT_KEYWORD_MAP = {
    "森林": "forest", "树林": "forest", "山林": "forest", "丛林": "forest",
    "雨": "rain", "暴雨": "rain", "细雨": "rain", "雷雨": "rain",
    "风": "wind", "狂风": "wind", "寒风": "wind", "高空": "wind",
    "夜": "night", "夜晚": "night", "深夜": "night", "午夜": "night",
    "市场": "market", "集市": "market", "街道": "market", "闹市": "market",
    "心跳": "heartbeat", "紧张": "heartbeat", "恐惧": "heartbeat",
}

# 情绪 → 环境音映射（当场景关键词未匹配时使用）
_MOOD_AMBIENT_MAP = {
    "紧张": "heartbeat", "恐惧": "heartbeat", "诡异": "night",
    "悲伤": "rain", "惆怅": "rain", "孤独": "wind",
    "神秘": "night", "宁静": "forest", "温馨": "forest",
    "壮阔": "wind", "压抑": "heartbeat",
}


def _select_ambient_sound(scene_setting: str = "", scene_mood: str = "") -> str | None:
    """v12.0: 根据场景设定和情绪自动选择环境音效
    
    Args:
        scene_setting: 场景描述（如"雨夜的森林"）
        scene_mood: 场景情绪（如"紧张"）
    
    Returns:
        环境音文件路径，或 None（无匹配）
    """
    sfx_dir = PROJECT_ROOT / "sfx" / "ambient"
    if not sfx_dir.exists():
        return None
    
    # 1. 优先按场景关键词匹配
    combined = f"{scene_setting} {scene_mood}"
    for keyword, sfx_name in _AMBIENT_KEYWORD_MAP.items():
        if keyword in combined:
            sfx_path = sfx_dir / f"{sfx_name}.mp3"
            if sfx_path.exists():
                return str(sfx_path)
    
    # 2. 按情绪匹配
    if scene_mood and scene_mood in _MOOD_AMBIENT_MAP:
        sfx_name = _MOOD_AMBIENT_MAP[scene_mood]
        sfx_path = sfx_dir / f"{sfx_name}.mp3"
        if sfx_path.exists():
            return str(sfx_path)
    
    return None


async def mix_audio_3track(video_path: str, bgm_path: str, output_path: str,
                            ambient_path: str | None = None,
                            bgm_volume: float = 0.25,
                            ambient_volume: float = 0.15) -> str:
    """v12.0: 三轨专业混音 — 对白(主) + 环境音(背景) + BGM(循环)
    
    在 mix_audio_high_quality 基础上增加环境音轨:
    - 环境音根据场景自动选择（rain/forest/wind/night/market/heartbeat）
    - 环境音音量低于 BGM，作为氛围烘托
    - 三轨均经过 sidechain ducking（对白出现时自动降低背景音量）
    
    Args:
        video_path: 输入视频（含对白音轨）
        bgm_path: BGM 文件路径
        output_path: 输出文件路径
        ambient_path: 环境音文件路径（None 则降级为双轨）
        bgm_volume: BGM 音量 (0-1)
        ambient_volume: 环境音音量 (0-1)
    
    Returns:
        输出文件路径
    """
    # 如果没有环境音，降级到双轨混音
    if not ambient_path or not Path(ambient_path).exists():
        return await mix_audio_high_quality(video_path, bgm_path, output_path, bgm_volume)
    
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(bgm_path).exists():
        shutil.copy2(video_path, output_path)
        return output_path
    
    try:
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "novel2vid_audio"
        temp_dir.mkdir(exist_ok=True)
        
        # 1. 提取视频中的音频（对白）
        voice_path = str(temp_dir / f"voice_3t_{uuid.uuid4().hex[:8]}.wav")
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            voice_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        if not Path(voice_path).exists():
            shutil.copy2(video_path, output_path)
            return output_path
        
        # 2. 用 pydub 加载三轨音频
        voice = AudioSegment.from_file(voice_path)
        bgm = AudioSegment.from_file(bgm_path)
        ambient = AudioSegment.from_file(ambient_path)
        
        # 3. 音量归一化
        voice = normalize(voice)
        bgm = normalize(bgm) - 12
        ambient = normalize(ambient) - 18  # 环境音最低
        
        # 4. 调整音量
        bgm = bgm - (1.0 - bgm_volume) * 20
        ambient = ambient - (1.0 - ambient_volume) * 24
        
        # 5. 循环 BGM 和环境音以匹配视频长度
        video_duration_ms = len(voice)
        while len(bgm) < video_duration_ms:
            bgm = bgm + bgm
        bgm = bgm[:video_duration_ms]
        
        while len(ambient) < video_duration_ms:
            ambient = ambient + ambient
        ambient = ambient[:video_duration_ms]
        
        # 6. Sidechain ducking — 对白出现时降低 BGM 和环境音
        try:
            from pydub import AudioSegment as _AS
            chunk_ms = 100
            threshold_db = -30
            ducked_bgm = _AS.silent(duration=video_duration_ms)
            ducked_ambient = _AS.silent(duration=video_duration_ms)
            
            for start in range(0, video_duration_ms, chunk_ms):
                end = min(start + chunk_ms, video_duration_ms)
                voice_chunk = voice[start:end]
                chunk_db = voice_chunk.dBFS if len(voice_chunk) > 0 else -100
                
                if chunk_db > threshold_db:
                    # 有对白 → BGM -10dB, 环境音 -6dB
                    bgm_segment = bgm[start:end] - 10
                    amb_segment = ambient[start:end] - 6
                else:
                    bgm_segment = bgm[start:end]
                    amb_segment = ambient[start:end]
                
                ducked_bgm = ducked_bgm.overlay(bgm_segment, position=start)
                ducked_ambient = ducked_ambient.overlay(amb_segment, position=start)
            
            bgm = ducked_bgm
            ambient = ducked_ambient
            print(f"[Audio] v12.0 三轨 ducking 已应用 (BGM+Ambient)", flush=True)
        except Exception as e:
            print(f"[Audio] 三轨 ducking 失败（降级固定音量）: {e}", flush=True)
        
        # 7. 淡入淡出
        fade_in_ms = min(2000, int(video_duration_ms * 0.1))
        fade_out_ms = min(3000, int(video_duration_ms * 0.15))
        bgm = bgm.fade_in(fade_in_ms).fade_out(fade_out_ms)
        ambient = ambient.fade_in(fade_in_ms * 2).fade_out(fade_out_ms)
        
        # 8. 三轨混音: 对白 + 环境音 + BGM
        mixed = voice.overlay(ambient, position=0).overlay(bgm, position=0)
        
        # 9. 动态范围压缩
        mixed = compress_dynamic_range(mixed, threshold=-20, ratio=2.0)
        
        # 10. 导出
        mixed_path = str(temp_dir / f"mixed_3t_{uuid.uuid4().hex[:8]}.wav")
        mixed.export(mixed_path, format="wav")
        
        # 11. 重新合并音频和视频
        vid_duration = await get_audio_duration(video_path)
        cmd = [
            ffmpeg, "-y",
            "-i", video_path,
            "-i", mixed_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", str(vid_duration),
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        
        # 清理临时文件
        for p in [voice_path, mixed_path]:
            Path(p).unlink(missing_ok=True)
        
        if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
            print(f"[Audio] v12.0 三轨混音完成: {Path(output_path).name}", flush=True)
            return output_path
        else:
            shutil.copy2(video_path, output_path)
            return output_path
        
    except Exception as e:
        print(f"[Audio] 三轨混音失败，回退双轨: {e}", flush=True)
        return await mix_audio_high_quality(video_path, bgm_path, output_path, bgm_volume)


async def add_bgm_to_video_legacy(video_path: str, bgm_path: str,
                                   output_path: str, bgm_volume: float = 0.25) -> str:
    """旧版 ffmpeg 混音（回退方案）"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(bgm_path).exists():
        shutil.copy2(video_path, output_path)
        return output_path

    vid_duration = await get_audio_duration(video_path)
    fade_out_start = max(vid_duration - 3, 0)
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-stream_loop", "-1", "-i", bgm_path,
        "-filter_complex",
        f"[1:a]volume={bgm_volume},afade=t=in:ss=0:d=2,afade=t=out:st={fade_out_start:.1f}:d=3[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            shutil.copy2(video_path, output_path)
    except Exception:
        shutil.copy2(video_path, output_path)

    return output_path


async def run_generation(job_id: str):
    """后台执行生成流水线（v4.0 含QA自测试）"""
    job = jobs[job_id]
    scene_dir = OUTPUT_DIR / job_id
    scene_dir.mkdir(exist_ok=True)

    txt2img_template = load_workflow("txt2img")
    img2vid_template = load_workflow("img2vid")

    try:
        await _run_generation_impl(job, scene_dir, txt2img_template, img2vid_template)
    except Exception as e:
        job.current_step = "error"
        job.error = f"生成流水线异常: {str(e)[:400]}"
        job.progress = {"phase": "error", "error": job.error}
        try:
            await JobStorage.save(job)
            await broadcast_progress(job_id, {
                "type": "error",
                "message": job.error,
                "phase": job.progress.get("phase", "unknown")
            })
        except Exception:
            pass  # 尽力保存，即使保存本身失败也不再抛异常
        raise  # 让 asyncio 记录未处理的异常日志

async def _run_generation_impl(job: JobState, scene_dir: Path,
                                txt2img_template: dict, img2vid_template: dict):
    """v6.0: 3路并发生成场景，使用 Semaphore 控制并发数"""
    job_id = job.id
    pending_scenes = [s for s in job.scenes if s.status != "done"]
    
    if not pending_scenes:
        return
    
    # v6.0: 3路并发控制
    max_concurrent = 3
    semaphore = asyncio.Semaphore(max_concurrent)
    active_count = 0  # v8.7.1: 替代 semaphore._value 私有属性访问
    completed_count = 0
    lock = asyncio.Lock()
    
    async def generate_one(scene: Scene, idx: int):
        nonlocal completed_count, active_count
        if job.cancel_flag:
            return
        
        async with semaphore:
            if job.cancel_flag:
                return
            active_count += 1  # v8.7.1: 进入并发槽
            async with lock:
                job.progress = {
                    "current": completed_count + 1,
                    "total": len(pending_scenes),
                    "phase": "generating",
                    "scene_id": scene.id,
                    "subtitle": scene.subtitle_display[:30] if scene.subtitle_display else "",
                    "concurrent": active_count,  # 当前并发数 (v8.7.1: 避免访问私有属性)
                }
            
            try:
                await _generate_scene(job, scene, scene_dir, txt2img_template, img2vid_template)
                async with lock:
                    completed_count += 1
                    job.progress["current"] = completed_count
                await JobStorage.save(job)
            except Exception as e:
                scene.status = "error"
                scene.error_msg = str(e)[:300]
                async with lock:
                    completed_count += 1
                    job.progress = {
                        "current": completed_count,
                        "total": len(pending_scenes),
                        "phase": "error",
                        "scene_id": scene.id,
                        "error": scene.error_msg
                    }
                await broadcast_progress(job_id, {
                    "type": "scene_status",
                    "scene_id": scene.id,
                    "status": "error",
                    "error": scene.error_msg,
                })
                await JobStorage.save(job)
            finally:
                active_count -= 1  # v8.7.1: 退出并发槽
    
    # 并发执行所有待处理场景
    tasks = [generate_one(s, i) for i, s in enumerate(pending_scenes)]
    await asyncio.gather(*tasks, return_exceptions=True)

    if job.cancel_flag:
        job.current_step = "interrupted"
        job.progress["phase"] = "cancelled"
        await JobStorage.save(job)
        return

    # ── v4.0: 自动 QA 测试 ──
    if job.qa_enabled:
        await broadcast_progress(job_id, {
            "type": "qa", "status": "running"
        })
        job.current_step = "qa_testing"

        qa_results = await run_qa_tests(job)
        job.qa_results = qa_results
        job.qa_passed = all(r["passed"] for r in qa_results)

        # 自动修复失败项
        failed_tests = [r for r in qa_results if not r["passed"]]
        if failed_tests:
            await broadcast_progress(job_id, {
                "type": "qa", "status": "fixing", "failed_count": len(failed_tests)
            })

            fixed = await auto_fix_issues(job, failed_tests, scene_dir, txt2img_template, img2vid_template)

            # 重新测试修复后的场景
            retest_results = await run_qa_tests(job, scene_ids=fixed)
            for r in retest_results:
                # 更新QA结果
                for idx, orig in enumerate(job.qa_results):
                    if orig["scene_id"] == r["scene_id"] and orig["test"] == r["test"]:
                        job.qa_results[idx] = r
                        break

            job.qa_passed = all(r["passed"] for r in job.qa_results)

        await broadcast_progress(job_id, {
            "type": "qa", "status": "done", "passed": job.qa_passed,
            "results": job.qa_results
        })

    job.current_step = "done"
    job.progress = {"current": len(job.scenes), "total": len(job.scenes), "phase": "complete"}
    await JobStorage.save(job)

async def run_qa_tests(job: JobState, scene_ids: list[int] = None) -> list[dict]:
    """自动QA测试 - 检查每个场景的音视频同步、文件完整性等"""
    results = []
    test_scenes = job.scenes
    if scene_ids:
        test_scenes = [s for s in job.scenes if s.id in scene_ids]

    for scene in test_scenes:
        # 测试1: 视频文件完整性
        video_ok = False
        if scene.final_video_path and Path(scene.final_video_path).exists():
            vid_dur = await get_audio_duration(scene.final_video_path)
            video_ok = vid_dur > 0
        results.append({
            "scene_id": scene.id, "test": "video_integrity",
            "passed": video_ok,
            "detail": "视频文件存在且时长>0" if video_ok else "视频文件缺失或时长为0"
        })

        # 测试2: 音频文件完整性（如果启用了TTS）
        audio_ok = True  # 音频是可选的
        if job.tts_enabled and scene.audio_path:
            if Path(scene.audio_path).exists():
                audio_dur = await get_audio_duration(scene.audio_path)
                audio_ok = audio_dur > 0
            else:
                audio_ok = False
        results.append({
            "scene_id": scene.id, "test": "audio_integrity",
            "passed": audio_ok,
            "detail": "音频文件正常" if audio_ok else "音频文件缺失或时长为0"
        })

        # 测试3: 音视频时长同步（偏差不超过2秒）
        sync_ok = True
        if scene.final_video_path and scene.audio_path:
            vid_dur = await get_audio_duration(scene.final_video_path)
            aud_dur = scene.audio_duration or await get_audio_duration(scene.audio_path)
            if vid_dur > 0 and aud_dur > 0:
                diff = abs(vid_dur - aud_dur)
                sync_ok = diff < 2.0
                results.append({
                    "scene_id": scene.id, "test": "audio_video_sync",
                    "passed": sync_ok,
                    "detail": f"音视频时长偏差{diff:.1f}秒" + ("（正常）" if sync_ok else "（过大）")
                })

        # 测试4: 字幕时间轴覆盖（字幕应覆盖音频的80%以上时长）
        if scene.subtitle_timings and scene.audio_duration > 0:
            subtitle_coverage = 0.0
            for t in scene.subtitle_timings:
                subtitle_coverage += t["end"] - t["start"]
            coverage_ratio = subtitle_coverage / scene.audio_duration if scene.audio_duration > 0 else 0
            coverage_ok = coverage_ratio >= 0.7  # 70%以上覆盖即可
            results.append({
                "scene_id": scene.id, "test": "subtitle_coverage",
                "passed": coverage_ok,
                "detail": f"字幕覆盖率为{coverage_ratio*100:.0f}%" + ("（正常）" if coverage_ok else "（不足）")
            })

        # 测试5: 场景状态一致性
        status_ok = scene.status == "done"
        results.append({
            "scene_id": scene.id, "test": "scene_status",
            "passed": status_ok,
            "detail": f"场景状态: {scene.status}" + ("（正常）" if status_ok else f"（异常: {scene.error_msg[:50]}）")
        })

    return results

async def auto_fix_issues(job: JobState, failed_tests: list[dict],
                           scene_dir: Path, txt2img_template: dict, img2vid_template: dict) -> list[int]:
    """自动修复QA发现的问题，返回修复的场景ID列表"""
    fixed_scene_ids = set()

    # 按场景分组问题
    scene_issues: dict[int, list[dict]] = {}
    for test in failed_tests:
        sid = test["scene_id"]
        if sid not in scene_issues:
            scene_issues[sid] = []
        scene_issues[sid].append(test)

    for scene_id, issues in scene_issues.items():
        scene = next((s for s in job.scenes if s.id == scene_id), None)
        if not scene:
            continue

        await broadcast_progress(job.id, {
            "type": "qa_fix", "scene_id": scene_id,
            "issues": [i["test"] for i in issues]
        })

        for issue in issues:
            test_name = issue["test"]

            if test_name == "video_integrity" or test_name == "scene_status":
                # 视频缺失或场景出错 -> 重试整个场景生成
                try:
                    scene.status = "pending"
                    scene.error_msg = ""
                    scene.comfyui_progress = 0.0
                    await _generate_scene(job, scene, scene_dir, txt2img_template, img2vid_template)
                    fixed_scene_ids.add(scene_id)
                except Exception as e:
                    scene.status = "error"
                    scene.error_msg = f"QA修复失败: {str(e)[:200]}"

            elif test_name == "audio_integrity":
                # 音频缺失 -> 重新生成配音
                try:
                    if job.smart_dubbing and job.characters:
                        char_map = {c.name: c for c in job.characters}
                        current_vid = scene.final_video_path or scene.video_path
                        if current_vid and Path(current_vid).exists():
                            await _smart_dubbing(job, scene, scene_dir, current_vid, char_map)
                            fixed_scene_ids.add(scene_id)
                    else:
                        current_vid = scene.final_video_path or scene.video_path
                        if current_vid and Path(current_vid).exists():
                            await _single_voice_dubbing(job, scene, scene_dir, current_vid)
                            fixed_scene_ids.add(scene_id)
                except Exception as e:
                    logger.warning(f"[QA] 配音修复失败 (scene {scene_id}): {e}")

            elif test_name == "audio_video_sync":
                # 音视频不同步 -> 重新合并
                try:
                    if scene.video_path and scene.audio_path and Path(scene.video_path).exists() and Path(scene.audio_path).exists():
                        av_path = str(scene_dir / f"scene_{scene.id:03d}_with_audio.mp4")
                        await combine_audio_video(scene.video_path, scene.audio_path, av_path, scene.audio_duration)
                        # 重新烧录字幕
                        if scene.subtitle_timings:
                            final_path = str(scene_dir / f"scene_{scene.id:03d}_final.mp4")
                            await burn_timed_subtitles(av_path, scene.subtitle_timings, final_path)
                            scene.final_video_path = final_path
                        else:
                            scene.final_video_path = av_path
                        fixed_scene_ids.add(scene_id)
                except Exception as e:
                    logger.warning(f"[QA] 音视频同步修复失败 (scene {scene_id}): {e}")

            elif test_name == "subtitle_coverage":
                # 字幕覆盖不足 -> 尝试用完整文本重新生成字幕
                try:
                    if scene.subtitle_text and scene.final_video_path:
                        final_path = str(scene_dir / f"scene_{scene.id:03d}_final.mp4")
                        await burn_subtitles(scene.final_video_path, scene.subtitle_text, final_path)
                        scene.final_video_path = final_path
                        fixed_scene_ids.add(scene_id)
                except Exception as e:
                    logger.warning(f"[QA] 字幕修复失败 (scene {scene_id}): {e}")

    return list(fixed_scene_ids)

# ─── v4.0 QA 测试 API ─────────────────────────────────────

@app.post("/api/qa-test/{job_id}")
async def api_qa_test(job_id: str):
    """手动触发QA测试"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    qa_results = await run_qa_tests(job)
    job.qa_results = qa_results
    job.qa_passed = all(r["passed"] for r in qa_results)
    await JobStorage.save(job)
    return {
        "job_id": job_id,
        "passed": job.qa_passed,
        "results": qa_results,
        "total": len(qa_results),
        "failed": sum(1 for r in qa_results if not r["passed"])
    }

@app.post("/api/qa-fix/{job_id}")
async def api_qa_fix(job_id: str):
    """手动触发QA自修复"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.qa_results:
        raise HTTPException(400, "请先运行QA测试")

    failed_tests = [r for r in job.qa_results if not r["passed"]]
    if not failed_tests:
        return {"status": "no_issues", "message": "所有测试已通过，无需修复"}

    scene_dir = OUTPUT_DIR / job_id
    scene_dir.mkdir(exist_ok=True)
    txt2img_template = load_workflow("txt2img")
    img2vid_template = load_workflow("img2vid")

    fixed = await auto_fix_issues(job, failed_tests, scene_dir, txt2img_template, img2vid_template)

    # 重新测试
    retest_results = await run_qa_tests(job, scene_ids=fixed)
    for r in retest_results:
        for idx, orig in enumerate(job.qa_results):
            if orig["scene_id"] == r["scene_id"] and orig["test"] == r["test"]:
                job.qa_results[idx] = r
                break

    job.qa_passed = all(r["passed"] for r in job.qa_results)
    await JobStorage.save(job)
    return {
        "status": "ok",
        "fixed_scenes": fixed,
        "passed": job.qa_passed,
        "results": job.qa_results
    }

@app.get("/api/characters/{job_id}")
async def get_characters(job_id: str):
    """获取角色列表"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return {"characters": [c.model_dump() for c in jobs[job_id].characters]}

@app.post("/api/qa-settings")
async def update_qa_settings(job_id: str, qa_enabled: bool = True):
    """更新QA设置"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    jobs[job_id].qa_enabled = qa_enabled
    await JobStorage.save(jobs[job_id])
    return {"status": "ok"}

@app.get("/api/jobs")
async def list_jobs_api():
    """获取所有项目列表（用于历史记录管理）"""
    return {"jobs": await JobStorage.list_jobs()}


@app.get("/api/jobs/{job_id}/export")
async def export_job_api(job_id: str):
    """v12.1: 导出单个项目为 JSON"""
    data = await JobStorage.export_job(job_id)
    if data is None:
        raise HTTPException(404, "Job not found")
    return {"job": data}


@app.post("/api/jobs/import")
async def import_job_api(file: UploadFile = File(...)):
    """v12.1: 从 JSON 文件导入项目"""
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        if isinstance(data, dict) and "job" in data:
            data = data["job"]
        job = await JobStorage.import_job(data)
        if job is None:
            raise HTTPException(400, "Invalid job data")
        jobs[job.id] = job
        return {"job_id": job.id, "status": "imported"}
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON file")
    except Exception as e:
        raise HTTPException(500, f"Import failed: {e}")


@app.post("/api/jobs/archive")
async def archive_old_jobs_api(days: int = 30):
    """v12.1: 归档指定天数未更新的项目（默认 30 天）"""
    archived = await JobStorage.archive_old_jobs(days)
    # 从内存中移除已归档任务
    for jid in archived:
        jobs.pop(jid, None)
    return {"archived": archived, "count": len(archived)}


@app.get("/api/jobs/archived")
async def list_archived_jobs_api():
    """v12.1: 列出已归档项目"""
    return {"jobs": await JobStorage.list_archived()}


@app.post("/api/jobs/archived/{job_id}/restore")
async def restore_archived_job_api(job_id: str):
    """v12.1: 从归档恢复项目"""
    job = await JobStorage.restore_archived(job_id)
    if job is None:
        raise HTTPException(404, "Archived job not found")
    jobs[job.id] = job
    return {"job_id": job.id, "status": "restored"}


@app.get("/api/jobs/{job_id}/prompts")
async def export_prompts_api(job_id: str):
    """v12.1: 导出所有场景的提示词（Markdown 格式）"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    lines = [f"# {job.novel_title or 'Untitled'} — 提示词汇总\n", ""]
    for idx, scene in enumerate(job.scenes, 1):
        lines.append(f"## 场景 {idx}: {scene.id}\n")
        lines.append(f"**画面描述：** {scene.image_prompt or '（未生成）'}\n")
        lines.append(f"**镜头描述：** {scene.camera_prompt or '（未生成）'}\n")
        lines.append(f"**氛围：** {scene.mood or '—'}\n")
        lines.append(f"**角色：** {', '.join(scene.characters) if scene.characters else '—'}\n")
        lines.append(f"---\n")
    return {"title": job.novel_title or "Untitled", "markdown": "\n".join(lines)}

@app.post("/api/auto-pipeline/{job_id}")
async def auto_pipeline(job_id: str, skip_completed: bool = True):
    """一键出片：自动完成所有步骤（分镜->角色->提示词->生成->合并）"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.novel_text:
        raise HTTPException(400, "请先上传小说文本")
    if not job.scenes:
        raise HTTPException(400, "请先生成分镜")

    # 自动触发角色分析（如果未分析）
    if not job.characters and job.smart_dubbing:
        try:
            await analyze_characters(job_id)
        except Exception:
            pass  # 角色分析失败不阻塞

    # 自动拆分对白（如果未拆分）
    if job.smart_dubbing and job.characters:
        try:
            await split_dialogues(job_id)
        except Exception:
            pass

    # 自动跳过分镜/提示词生成（如果已存在）
    if not any(s.image_prompt for s in job.scenes):
        # 需要生成提示词
        try:
            await generate_prompts(job_id)
        except Exception as e:
            raise HTTPException(500, f"生成提示词失败: {e}")

    # 开始生成
    await start_generation(job_id)
    return {"job_id": job_id, "status": "auto_pipeline_started"}

async def generate_cover(job: JobState, merged_video_path: str):
    """v6.0: 从最终视频中提取高潮场景帧 + 叠加标题文字生成封面（1080×1920）"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    
    cover_dir = OUTPUT_DIR / job.id
    cover_dir.mkdir(exist_ok=True)
    
    # 1. 选 emotional_intensity 最高的场景
    peak_scene = max((s for s in job.scenes if s.emotional_intensity > 0), 
                     key=lambda s: s.emotional_intensity, default=job.scenes[0] if job.scenes else None)
    if not peak_scene:
        return None
    
    # 2. 获取该场景视频路径，从中间截取一帧
    scene_vid = peak_scene.final_video_path or peak_scene.video_path
    if not scene_vid or not Path(scene_vid).exists():
        # 如果场景视频不存在，从合并视频中截取
        scene_vid = merged_video_path
    
    # P0-② 升级：先取帧，再用 PIL 合成专业封面（粗体+阴影+渐变+多行标题）
    title = job.novel_title or "未命名作品"

    # 阶段 A: 截帧
    if not Path(scene_vid).exists():
        return None

    cover_frame = str(cover_dir / "cover_frame.jpg")
    # 获取场景时长，智能选取帧位置
    dur = await get_audio_duration(scene_vid) or 5.0
    # 70% 处取帧（高潮中后段，避开黑屏和淡入）
    ss = max(dur * 0.7, 0.5)

    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-ss", str(ss), "-i", scene_vid,
        "-vframes", "1", "-q:v", "2",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        cover_frame,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await asyncio.wait_for(proc.communicate(), timeout=30)

    if not Path(cover_frame).exists() or Path(cover_frame).stat().st_size < 1000:
        return None

    # 阶段 B: PIL 合成封面（专业版：渐变蒙版 + 粗体标题 + 阴影 + 副标题）
    cover_final = str(cover_dir / f"{(job.novel_title or 'output').replace('/', '_')}_cover.jpg")

    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter

        img = Image.open(cover_frame).convert("RGB")
        W, H = img.size

        # B1: 顶部 40% 加深色渐变蒙版（让标题可读）
        gradient = Image.new("RGBA", (W, int(H * 0.5)), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gradient)
        for y in range(int(H * 0.5)):
            alpha = int(180 * (1 - y / (H * 0.5)) ** 1.5)  # 越往下越透明
            gd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
        img.paste(gradient, (0, 0), gradient)

        # B2: 底部 25% 加品牌信息条
        bottom_bar = Image.new("RGBA", (W, int(H * 0.25)), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bottom_bar)
        for y in range(int(H * 0.25)):
            alpha = int(160 * (y / (H * 0.25)) ** 1.5)
            bd.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
        img.paste(bottom_bar, (0, int(H * 0.75)), bottom_bar)

        draw = ImageDraw.Draw(img)

        # B3: 找中文字体
        font_paths = [
            "C:/Windows/Fonts/msyhbd.ttc",   # 微软雅黑 Bold
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑 Regular
            "C:/Windows/Fonts/simhei.ttf",    # 黑体
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        ]
        title_font = None
        sub_font = None
        for fp in font_paths:
            if Path(fp).exists():
                try:
                    title_font = ImageFont.truetype(fp, 90)
                    sub_font = ImageFont.truetype(fp, 38)
                    small_font = ImageFont.truetype(fp, 28)
                    break
                except Exception:
                    continue
        if not title_font:
            title_font = ImageFont.load_default()
            sub_font = ImageFont.load_default()
            small_font = ImageFont.load_default()

        # B4: 标题自动换行（每行最多 8 字，红果风格短促有力）
        max_chars = 8
        lines = []
        for i in range(0, len(title), max_chars):
            lines.append(title[i:i+max_chars])

        # B5: 计算总高度，居中绘制
        line_h = 110
        total_h = line_h * len(lines)
        start_y = int(H * 0.18)  # 顶部 1/5 处开始
        x_center = W // 2

        for idx, line in enumerate(lines):
            text = line
            # 测宽
            bbox = draw.textbbox((0, 0), text, font=title_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = x_center - tw // 2
            ty = start_y + idx * line_h

            # 阴影 (offset=6, blur=8)
            shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow_layer)
            for ox in range(-6, 7, 2):
                for oy in range(-6, 7, 2):
                    if ox * ox + oy * oy > 36:
                        continue
                    sd.text((tx + ox, ty + oy), text, font=title_font, fill=(0, 0, 0, 160))
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(4))
            img.paste(shadow_layer, (0, 0), shadow_layer)

            # 主文字（白+亮黄渐变 — 用白底 + 黄色描边）
            # 描边（黑色 4px）
            for dx in range(-4, 5, 2):
                for dy in range(-4, 5, 2):
                    if dx * dx + dy * dy > 16:
                        continue
                    if dx == 0 and dy == 0:
                        continue
                    draw.text((tx + dx, ty + dy), text, font=title_font, fill=(0, 0, 0))
            # 主体（白色）
            draw.text((tx, ty), text, font=title_font, fill=(255, 255, 255))

        # B6: 副标题 — 副情绪词（从 peak_scene.mood 取）
        mood_text = peak_scene.mood or "精彩短剧"
        if sub_font:
            bbox = draw.textbbox((0, 0), mood_text, font=sub_font)
            mw = bbox[2] - bbox[0]
            draw.text((x_center - mw // 2, start_y + total_h + 30),
                      mood_text, font=sub_font, fill=(255, 230, 100))

        # B7: 品牌水印（底部）
        brand = "墨影流光 · AI 短剧"
        if small_font:
            bbox = draw.textbbox((0, 0), brand, font=small_font)
            bw = bbox[2] - bbox[0]
            draw.text((x_center - bw // 2, int(H * 0.88)),
                      brand, font=small_font, fill=(255, 255, 255, 200))

        # B8: "上滑观看" 引导箭头
        hint = "↑ 上滑观看全集"
        if small_font:
            bbox = draw.textbbox((0, 0), hint, font=small_font)
            hw = bbox[2] - bbox[0]
            draw.text((x_center - hw // 2, int(H * 0.93)),
                      hint, font=small_font, fill=(255, 200, 200))

        # 保存
        img.save(cover_final, "JPEG", quality=92, optimize=True)
        print(f"[Cover] 升级版封面生成完成: {cover_final}", flush=True)

    except Exception as e:
        # PIL 失败则回退到 drawtext 旧方案
        print(f"[Cover] PIL 合成失败，回退 ffmpeg drawtext: {e}", flush=True)
        chinese_font = _find_chinese_font() if '_find_chinese_font' in dir() else None
        if chinese_font:
            fontfile = chinese_font
        elif sys.platform == "win32":
            fontfile = "C:/Windows/Fonts/msyh.ttc"
        else:
            fontfile = "C:/Windows/Fonts/msyh.ttc"

        max_chars_per_line = 8
        title_lines = []
        for i in range(0, len(title), max_chars_per_line):
            title_lines.append(title[i:i+max_chars_per_line])
        title_display = "\\n".join(title_lines)

        drawtext = (
            f"drawtext=fontfile='{fontfile}':"
            f"text='{title_display}':"
            f"fontcolor=white:fontsize=80:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-100:"
            f"box=1:boxcolor=black@0.5:boxborderw=25"
        )
        proc2 = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-i", cover_frame, "-vf", drawtext,
            cover_final,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc2.communicate(), timeout=30)

    if Path(cover_final).exists() and Path(cover_final).stat().st_size > 1000:
        job.cover_path = cover_final
        print(f"[Cover] 封面生成完成: {cover_final}", flush=True)
        return cover_final
    return None


@app.post("/api/merge-videos/{job_id}")
async def merge_all_videos(job_id: str, bgm_path: str = "", bgm_volume: float = 0.25):
    """合并所有场景视频为一个完整的有声小说视频"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]

    # 收集所有完成的视频路径（优先用带字幕的版本）
    video_paths = []
    scene_moods = []
    for scene in job.scenes:
        vp = scene.final_video_path or scene.video_path
        if vp and Path(vp).exists():
            video_paths.append(vp)
            scene_moods.append(getattr(scene, 'mood', '') or '')

    if not video_paths:
        raise HTTPException(400, "没有可合并的视频")

    output_path = str(OUTPUT_DIR / job_id / f"{job.novel_title or 'novel'}_merged.mp4")

    try:
        # v9.9: 阈值从10提高到20，支持更多场景使用xfade智能转场
        if len(video_paths) <= 20:
            merged_path = await merge_videos_with_transitions(video_paths, output_path,
                                                              scene_moods=scene_moods)
        else:
            merged_path = await merge_videos(video_paths, output_path)
        
        # 超分：将合并后的视频升至 1080×1920 @ 24fps (v6.0)
        title = job.novel_title or 'novel'
        upscaled_path = str(OUTPUT_DIR / job_id / f"{title}_upscaled.mp4")
        print(f"[Merge] 开始超分到1080p: {merged_path} -> {upscaled_path}")
        merged_path = await upscale_video(merged_path, upscaled_path, target_width=1080, target_height=1920)

        # P2-⑫: 检测高潮点 + 插入金币引导卡（合并后立即插入）
        try:
            insertion_points = _mark_coin_insertion_points(job.scenes)
            if insertion_points:
                # 取第一个高潮点（通常是最强冲突）
                first_peak = insertion_points[0]
                coin_path = str(OUTPUT_DIR / job_id / f"{title}_with_coin.mp4")
                merged_path = await _insert_coin_card(
                    merged_path, coin_path,
                    insertion_time=first_peak["time_pos"] + 1.0,  # 延迟1秒
                    duration=3.0
                )
        except Exception as e:
            print(f"[Coin] 金币引导位插入失败: {e}", flush=True)

        # v6.0: 自动生成封面图
        _spawn_background_task(generate_cover(job, merged_path), f"generate_cover({job_id})")
        
        # 如果有BGM，混音 - v6.2: 使用 pydub 专业混音（质量优先）
        if bgm_path:
            final_path = str(OUTPUT_DIR / job_id / f"{title}_final.mp4")
            await mix_audio_high_quality(merged_path, bgm_path, final_path, bgm_volume)
            # P1-⑧: 追加 3 秒片尾引导卡
            with_card_path = str(OUTPUT_DIR / job_id / f"{title}_with_ending.mp4")
            await _append_ending_card(
                final_path, with_card_path,
                title=title,
                series_name="墨影流光 · 短剧场"
            )
            # P1-⑧: 系列化命名副本
            series_name = _build_series_filename(title, genre=job.style, episode=1)
            series_path = str(OUTPUT_DIR / job_id / f"{series_name}.mp4")
            if Path(with_card_path).exists():
                import shutil as _sh
                _sh.copy2(with_card_path, series_path)
                print(f"[Series] P1-⑧ 系列化命名: {series_path}", flush=True)
            job.merged_video_path = series_path
            await JobStorage.save(job)
            return {"status": "ok", "merged_path": series_path, "scenes_merged": len(video_paths)}
        else:
            # P1-⑧: 无 BGM 也追加尾卡
            with_card_path = str(OUTPUT_DIR / job_id / f"{title}_with_ending.mp4")
            await _append_ending_card(
                merged_path, with_card_path,
                title=title,
                series_name="墨影流光 · 短剧场"
            )
            series_name = _build_series_filename(title, genre=job.style, episode=1)
            series_path = str(OUTPUT_DIR / job_id / f"{series_name}.mp4")
            if Path(with_card_path).exists():
                import shutil as _sh
                _sh.copy2(with_card_path, series_path)
            job.merged_video_path = series_path
            await JobStorage.save(job)
            return {"status": "ok", "merged_path": series_path, "scenes_merged": len(video_paths)}
    except Exception as e:
        raise HTTPException(500, f"合并视频失败: {str(e)[:300]}")

@app.get("/api/bgm-list")
async def list_bgm():
    """扫描BGM目录，返回可用背景音乐列表"""
    bgm_dir = PROJECT_ROOT / "bgm"
    bgm_dir.mkdir(exist_ok=True)
    bgms = []
    for path in sorted(bgm_dir.glob("*.mp3")):
        dur = 0.0
        try:
            ffmpeg = find_ffmpeg()
            if ffmpeg:
                ffprobe = ffmpeg.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
                import shutil as sh
                ffprobe = sh.which("ffprobe") or ffprobe
                if Path(ffprobe).exists():
                    proc = await asyncio.create_subprocess_exec(
                        ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                    if proc.returncode == 0 and stdout:
                        dur = float(stdout.decode().strip())
        except Exception as e:
            logger.warning(f"[BGM] 获取时长失败 {bgm}: {str(e)[:80]}")
        bgms.append({
            "name": path.stem,
            "path": str(path),
            "duration": round(dur, 1),
            "size_kb": round(path.stat().st_size / 1024, 1)
        })
    return {"bgms": bgms, "bgm_dir": str(bgm_dir)}

@app.post("/api/bgm-upload")
async def upload_bgm(file: UploadFile = File(...)):
    """上传BGM文件到BGM目录"""
    bgm_dir = PROJECT_ROOT / "bgm"
    bgm_dir.mkdir(exist_ok=True)
    if not file.filename.endswith(".mp3"):
        raise HTTPException(400, "只支持 MP3 格式")
    save_path = bgm_dir / file.filename
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    return {"status": "ok", "name": file.filename, "path": str(save_path)}


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = _get_job(job_id)  # v8.7.1: 统一使用 _get_job，支持磁盘恢复
    return {
        "job_id": job_id,
        "status": "done" if job.current_step == "done" else "running" if not job.error else "error",
        "current_step": job.current_step,
        "progress": job.progress,
        "novel_title": job.novel_title,
        "scenes_count": len(job.scenes),
        "done_count": sum(1 for s in job.scenes if s.status == "done"),
        "error_count": sum(1 for s in job.scenes if s.status == "error"),
        "error": job.error,
        "scenes": [s.model_dump() for s in job.scenes],
        "merged_video": job.merged_video_path,
    }

@app.get("/api/scenes/{job_id}")
async def get_scenes(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return {"scenes": [s.model_dump() for s in jobs[job_id].scenes]}

@app.get("/api/scene-image/{job_id}/{scene_id}")
async def get_scene_image(job_id: str, scene_id: int):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    scene = next((s for s in jobs[job_id].scenes if s.id == scene_id), None)
    if not scene or not scene.image_path:
        raise HTTPException(404, "Image not found")
    return FileResponse(scene.image_path)

@app.get("/api/scene-video/{job_id}/{scene_id}")
async def get_scene_video(job_id: str, scene_id: int):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    scene = next((s for s in jobs[job_id].scenes if s.id == scene_id), None)
    # 优先返回带字幕的版本
    vp = scene.final_video_path or scene.video_path if scene else None
    if not vp:
        raise HTTPException(404, "Video not found")
    return FileResponse(vp, media_type="video/mp4")

@app.get("/api/scene-audio/{job_id}/{scene_id}")
async def get_scene_audio(job_id: str, scene_id: int):
    """获取场景的 TTS 配音文件"""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    scene = next((s for s in jobs[job_id].scenes if s.id == scene_id), None)
    if not scene or not scene.audio_path:
        raise HTTPException(404, "Audio not found")
    return FileResponse(scene.audio_path, media_type="audio/mpeg")

@app.get("/api/merged-video/{job_id}")
async def get_merged_video(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.merged_video_path or not Path(job.merged_video_path).exists():
        raise HTTPException(404, "Merged video not found")
    return FileResponse(job.merged_video_path, media_type="video/mp4")

@app.get("/api/comfyui-check")
async def check_comfyui():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{COMFYUI_URL}/system_stats")
            data = resp.json()
            return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}

@app.get("/api/comfyui-models")
async def get_comfyui_models():
    """获取ComfyUI可用的模型列表（含类型和大小）"""
    try:
        all_models = await comfyui.get_models()
        models_list = []
        for model_type, names in all_models.items():
            if not isinstance(names, list):
                continue
            for name in names:
                # 尝试获取文件大小
                size = 0
                try:
                    ckpt_dir = COMFYUI_MODELS_DIR / model_type.replace("checkpoints", "checkpoints").replace("vae", "vae").replace("loras", "loras").replace("ipadapter", "ipadapter").replace("clip_vision", "clip_vision")
                    filepath = ckpt_dir / name
                    if filepath.exists():
                        size = filepath.stat().st_size
                except Exception:
                    pass
                models_list.append({"name": name, "type": model_type, "size": size})
        return {"models": models_list, "checkpoints": all_models.get("checkpoints", [])}
    except Exception as e:
        checkpoints = await comfyui.get_checkpoints()
        return {"models": [{"name": c, "type": "checkpoint", "size": 0} for c in checkpoints], "checkpoints": checkpoints}

@app.get("/api/comfyui-queue")
async def get_comfyui_queue():
    """获取ComfyUI队列状态"""
    try:
        data = await comfyui.get_queue()
        return data
    except Exception as e:
        return {"error": str(e)[:200]}

@app.get("/api/ffmpeg-check")
async def check_ffmpeg():
    """检查 ffmpeg 是否可用"""
    path = find_ffmpeg()
    return {"available": bool(path), "path": path}

@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    if job_id in jobs:
        del jobs[job_id]
    await JobStorage.delete(job_id)
    return {"status": "deleted"}

# ─── 工具函数 ──────────────────────────────────────────────
def extract_json_array(text: str) -> list:
    """从文本中提取 JSON 数组，含截断抢救逻辑"""
    text = text.strip()
    # 1. 完整 JSON 直接解析
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # 2. 从 markdown 代码块提取
    m = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 找到 [...] 范围提取
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass

    # 4. 截断抢救：响应被 max_tokens 截断，JSON 数组不完整
    #    策略：找到最后一个完整的对象 }，闭合数组并解析
    bracket_start = text.find("[")
    if bracket_start == -1:
        raise ValueError(f"无法从文本中提取 JSON 数组，响应中未找到 '[': {text[:200]}")
    truncated = text[bracket_start:]
    # 从后往前找最后一个完整对象：定位 "}," 或 "}\n" 或倒数第二个 "}"
    # 尝试逐步截短，找可解析的最长前缀
    best_result = None
    # 找最后一个 }, 的位置开始尝试
    last_comma_close = truncated.rfind("},")
    if last_comma_close == -1:
        last_comma_close = truncated.rfind("}\n")
    if last_comma_close == -1:
        last_comma_close = truncated.rfind("} ]")
    if last_comma_close > 0:
        # 从该位置后一个 } 开始逐个尝试闭合
        test_end = last_comma_close + 1  # 指向 }
        while test_end > 0:
            candidate = truncated[:test_end] + "]"
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list) and len(parsed) > 0:
                    best_result = parsed
                    break
            except json.JSONDecodeError:
                pass
            # 前移一个 }
            test_end = truncated.rfind("}", 0, test_end)
            if test_end == -1:
                break
            test_end += 1  # 指向 } 之后

    if best_result is not None:
        dropped = len(truncated) - len(truncated[:last_comma_close + 1])
        print(f"[WARN] JSON 被截断，抢救成功：{len(best_result)} 个对象，"
              f"丢弃 {dropped} 字符（含不完整对象）", flush=True)
        return best_result

    # 5. 最后尝试：找最后一个完整的 }，盲合数组
    last_brace = truncated.rfind("}")
    if last_brace > 0:
        try:
            candidate = truncated[:last_brace + 1] + "]"
            parsed = json.loads(candidate)
            if isinstance(parsed, list) and len(parsed) > 0:
                print(f"[WARN] JSON 截断，盲合抢救成功：{len(parsed)} 个对象", flush=True)
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"无法从文本中提取 JSON 数组（可能因 DeepSeek 输出被截断）。"
        f"请尝试缩短输入文本后重试。响应前200字符: {text[:200]}"
    )

def extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从文本中提取 JSON 对象: {text[:200]}")

# ─── 健康检查（不依赖 ComfyUI，仅确认服务器存活）─────────
@app.get("/api/health")
async def health_check():
    """Launcher 用此接口判断服务器是否启动成功，不受 ComfyUI 状态影响"""
    return {"status": "ok", "version": "6.3"}

# ─── 一键生成（Web UI 主入口）──────────────────────────────
@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    """一键生成：创建项目 → 分析分镜 → 生成图片/视频/配音"""
    from app.models import GenerateRequest as GR
    
    job_id = str(uuid.uuid4())[:8]
    
    # 创建 JobState
    job = JobState(
        id=job_id,
        novel_text=req.novel_text,
        novel_title=req.novel_title or "未命名项目",
        deepseek_key=req.deepseek_key or DEEPSEEK_DEFAULT_KEY,
        img_checkpoint=req.img_checkpoint,
        vid_checkpoint=req.vid_checkpoint,
        use_hires_fix=req.use_hires_fix,
        use_ipadapter=req.use_ipadapter,
        use_pulid=req.use_pulid,
        pulid_reference_image=req.pulid_reference_image if hasattr(req, 'pulid_reference_image') else "",
        kling_api_key=req.kling_api_key if hasattr(req, 'kling_api_key') else "",
        kling_face_description=req.kling_face_description if hasattr(req, 'kling_face_description') else "",
        use_wan21=req.use_wan21,
        use_color_grading=req.use_color_grading,
        use_fade_transition=req.use_fade_transition,
        smart_dubbing=req.smart_dubbing if hasattr(req, 'smart_dubbing') else True,
        tts_enabled=req.tts_enabled if hasattr(req, 'tts_enabled') else True,
        style=req.style if hasattr(req, 'style') else "cinematic",
        use_ken_burns=getattr(req, 'use_ken_burns', True),
        use_dual_frame=getattr(req, 'use_dual_frame', False),
        use_manga_fx=getattr(req, 'use_manga_fx', True),
        use_multi_shot=getattr(req, 'use_multi_shot', False),
        video_mode=getattr(req, 'video_mode', 'local'),
        current_step="storyboard",
    )
    jobs[job_id] = job

    # 根据风格自动选择图像模型（如果用户未指定或仍是默认 anime）
    _auto_select_checkpoint_by_style(job)

    # PuLID 开启时自动切换到 SDXL 模型（animagine-xl-4.0）
    if job.use_pulid and "xl" not in job.img_checkpoint.lower() and "animagine" not in job.img_checkpoint.lower():
        sdxl_path = COMFYUI_MODELS_DIR / "checkpoints" / "animagine-xl-4.0.safetensors"
        if sdxl_path.exists() and sdxl_path.stat().st_size > 5_000_000_000:
            job.img_checkpoint = "animagine-xl-4.0.safetensors"
            print(f"[Auto] PuLID 已开启，自动切换到 SDXL 模型: {job.img_checkpoint}", flush=True)
        else:
            print(f"[WARN] PuLID 需要 SDXL 模型，但 animagine-xl-4.0.safetensors 不存在或损坏", flush=True)

    # v8.7: IP-Adapter 开启时强制 SDXL checkpoint (SD1.5 IP-Adapter 与 SDXL 不兼容)
    if job.use_ipadapter and "xl" not in job.img_checkpoint.lower() and "animagine" not in job.img_checkpoint.lower():
        sdxl_path = COMFYUI_MODELS_DIR / "checkpoints" / "animagine-xl-4.0.safetensors"
        if sdxl_path.exists() and sdxl_path.stat().st_size > 5_000_000_000:
            job.img_checkpoint = "animagine-xl-4.0.safetensors"
            print(f"[Auto] IP-Adapter 已开启，切换到 SDXL: {job.img_checkpoint}", flush=True)
        else:
            print(f"[WARN] IP-Adapter 需 SDXL checkpoint，但 animagine-xl-4.0.safetensors 不可用", flush=True)

    await JobStorage.save(job)

    # 异步启动管道
    _spawn_background_task(_run_generate_pipeline(job_id), f"generate_pipeline({job_id})")
    
    return {"job_id": job_id, "status": "started"}


@app.post("/api/run-pipeline")
async def run_existing_pipeline(job_id: str):
    """v9.6: 对已有 job 启动后台生成管线（图片 + 视频 + 配音）。
    
    用于分步操作场景：先 create-job → upload-novel → generate-storyboard → generate-prompts，
    最后调用此端点启动后台生成。
    """
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.scenes:
        raise HTTPException(400, "请先生成分镜 (POST /api/generate-storyboard)")
    if job.current_step in ("generating_img", "generating_video", "done"):
        raise HTTPException(400, f"管线已在运行中 (当前阶段: {job.current_step})")
    
    job.current_step = "generating_img"
    job.error = ""  # v9.6: 清除旧错误，防止 status API 误判为 error
    await JobStorage.save(job)
    
    _spawn_background_task(_run_generate_pipeline(job_id), f"generate_pipeline({job_id})")

    return {"job_id": job_id, "status": "started", "scenes_count": len(job.scenes)}


@app.post("/api/regenerate-images")
async def regenerate_images_only(job_id: str):
    """v9.8: 跳过分镜/提示词重新生成，直接用已有 prompts 重新生成所有图片+视频。

    适用于：分镜和提示词已成功生成，但图片生成因环境问题（如 KSampler [Errno 22]）全部失败，
    修复环境后需要快速重试的场景。

    - 重置所有场景状态为 pending（保留已有 prompts）
    - 直接调用 _start_generation_pipeline（跳过 storyboard/prompt 阶段）
    """
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.scenes:
        raise HTTPException(400, "请先生成分镜 (POST /api/generate-storyboard)")
    if job.current_step in ("generating_img", "generating_video"):
        raise HTTPException(400, f"管线已在运行中 (当前阶段: {job.current_step})")

    # 检查是否所有场景都有 image_prompt
    missing = [s.id for s in job.scenes if not s.image_prompt]
    if missing:
        raise HTTPException(400, f"以下场景缺少 image_prompt，请先用 /api/run-pipeline 完整生成: {missing}")

    # v9.9: 只重置未完成的场景（保留已 done 的场景，支持断点续跑）
    reset_count = 0
    for scene in job.scenes:
        if scene.status != "done" or not scene.image_path:
            scene.status = "pending"
            scene.error_msg = ""
            scene.comfyui_progress = 0.0
            scene.image_path = None
            scene.video_path = None
            scene.final_video_path = None
            scene.audio_path = None
            scene.audio_duration = 0.0
            reset_count += 1
    done_count = sum(1 for s in job.scenes if s.status == "done")
    print(f"[regenerate-images] 保留 {done_count} 个已完成场景，重置 {reset_count} 个待生成场景", flush=True)

    job.current_step = "generating_img"
    job.error = ""
    job.merged_video_path = ""
    await JobStorage.save(job)

    async def _run_images_only():
        """直接调用 _start_generation_pipeline，跳过分镜/提示词"""
        try:
            await _start_generation_pipeline(jobs[job_id])
        except Exception as e:
            job = jobs.get(job_id)
            if job:
                job.error = str(e)[:500]
                job.current_step = "error"
                await JobStorage.save(job)
                print(f"[regenerate-images] 失败: {e}", flush=True)

    _spawn_background_task(_run_images_only(), f"regenerate_images({job_id})")

    return {"job_id": job_id, "status": "started", "scenes_count": len(job.scenes), "mode": "images_only"}


@app.post("/api/test-scene")
async def test_single_scene(job_id: str, scene_id: int = 1):
    """v9.7: 单场景快速测试 — 仅生成一张图片并返回耗时。
    用于验证配置是否可行，不跑完整管线。
    直接构建 txt2img 工作流提交到 ComfyUI，跳过所有视频/配音步骤。
    """
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if not job.scenes or scene_id > len(job.scenes):
        raise HTTPException(400, f"场景 {scene_id} 不存在，共 {len(job.scenes)} 个场景")
    
    scene = job.scenes[scene_id - 1]
    scene_dir = OUTPUT_DIR / job_id / "scenes" / f"scene_{scene_id:03d}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    
    # 显存检测 + 自适应配置
    vram_mb, vram_total_mb = await _get_comfyui_vram_info()
    config = {"img_width": 896, "img_height": 1152, "checkpoint": "animagine-xl-4.0.safetensors"}
    # v9.11 修复: 改用局部变量 img_w/img_h，避免修改全局 IMG_WIDTH/IMG_HEIGHT 造成并发污染
    img_w, img_h = IMG_WIDTH, IMG_HEIGHT
    if vram_mb > 0:
        config = _auto_select_generation_config(vram_mb, job, vram_total_mb)
        img_w, img_h = config["img_width"], config["img_height"]
    
    start = time.time()
    try:
        # 构建最简单的 txt2img 工作流
        scene_seed = (abs(hash(job_id)) % (2**31)) + scene_id * 1000
        positive_prompt = scene.image_prompt or scene.description
        negative_prompt = ("(worst quality:1.4), (low quality:1.4), (bad hands:1.4), "
                           "bad anatomy, watermark, blurry, ugly, disfigured")
        
        wf_template = load_workflow("txt2img")
        replacements = {
            "POSITIVE_PROMPT": positive_prompt,
            "NEGATIVE_PROMPT": negative_prompt,
            "SEED": scene_seed % (2**31),
            "WIDTH": img_w,
            "HEIGHT": img_h,
            "CHECKPOINT": config["checkpoint"],
        }
        img_workflow = fill_workflow(wf_template, replacements)
        
        prompt_id = await comfyui.submit_workflow(img_workflow)
        result = await comfyui.wait_for_result_ws(prompt_id, job_id=job_id, scene_id=scene_id, timeout=300)
        
        # 查找输出图片
        outputs = result.get("outputs", {})
        img_filename = None
        img_subfolder = ""
        for node_id, node_out in outputs.items():
            if "images" in node_out:
                img_info = node_out["images"][0]
                img_filename = img_info["filename"]
                img_subfolder = img_info.get("subfolder", "")
                break
        
        if not img_filename:
            raise RuntimeError("ComfyUI 返回结果中未找到图片")
        
        # 构建图片路径
        comfyui_output = COMFYUI_MODELS_DIR.parent / "output"
        img_path = comfyui_output / img_subfolder / img_filename if img_subfolder else comfyui_output / img_filename
        
        elapsed = time.time() - start
        return {
            "status": "ok",
            "scene_id": scene_id,
            "title": scene.title,
            "image_path": str(img_path),
            "image_size_bytes": img_path.stat().st_size if img_path.exists() else 0,
            "elapsed_seconds": round(elapsed, 1),
            "vram_free_mb": vram_mb if vram_mb > 0 else None,
            "config": config,
            "checkpoint_used": config["checkpoint"],
            "resolution": f"{img_w}×{img_h}"
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "status": "error",
            "scene_id": scene_id,
            "error": str(e)[:500],
            "elapsed_seconds": round(elapsed, 1),
            "vram_free_mb": vram_mb if vram_mb > 0 else None,
            "config": config,
        }


async def _run_generate_pipeline(job_id: str):
    """后台执行完整生成管道"""
    job = jobs.get(job_id)
    if not job:
        return
    
    try:
        # 前置检查：ComfyUI 是否在线
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{COMFYUI_URL}/system_stats")
                if resp.status_code != 200:
                    raise RuntimeError(f"ComfyUI 未响应 (HTTP {resp.status_code})")
        except httpx.ConnectError:
            raise RuntimeError(
                f"无法连接到 ComfyUI ({COMFYUI_URL})\n"
                f"请检查：\n"
                f"1. ComfyUI 是否已启动？\n"
                f"2. URL 是否正确？（当前: {COMFYUI_URL}）\n"
                f"3. 防火墙是否阻止了连接？\n"
                f"\n启动 ComfyUI 命令示例：\n"
                f"  {COMFYUI_URL.split(':')[0]}://{COMFYUI_URL.split(':')[1].split('/')[2]}/start_lowvram.bat"
            )
        except httpx.TimeoutException:
            raise RuntimeError(
                f"连接 ComfyUI ({COMFYUI_URL}) 超时\n"
                f"ComfyUI 可能正在启动中，请等待1-2分钟后再试"
            )
        except Exception as e:
            raise RuntimeError(f"无法连接到 ComfyUI ({COMFYUI_URL})，请确保 ComfyUI 已启动。错误: {str(e)[:100]}")


        # ── v12.2 更新：8GB 显存下 LTX 22B(FP8)+--lowvram 异步卸载可跑通，
        #   不再强制 Ken Burns。LTX 为主引擎，Ken Burns 仅用于大场景推拉/兜底。
        #   仅当完全缺失视频模型时才回退 Ken Burns。 ──
        if (job.video_mode in ("local", "", None)) and not job.vid_checkpoint:
            job.use_ken_burns = True
            print("[Pipeline] 未检测到视频模型，回退 Ken Burns 兜底", flush=True)

        # ── v5.0：先执行故事结构预分析（如果还没有） ──
        if not job.story_structure:
            await broadcast_progress(job_id, {
                "type": "step", "step": "story_structure_auto",
                "message": "自动执行故事结构预分析（好莱坞三幕式）..."
            })
            await _analyze_story_structure(job)
            await JobStorage.save(job)
        
        # ── v6.2: 角色+环境预分析（如果还没有） ──
        if not job.character_analysis or not job.environment_analysis:
            await broadcast_progress(job_id, {
                "type": "step", "step": "character_env_analysis",
                "message": "自动分析文本中的角色和环境（支撑跨镜一致性）..."
            })
            await _analyze_characters_and_environments(job)
            await JobStorage.save(job)
        
        story_structure = job.story_structure or {}
        
        # Step 1: 分镜分析（整体送入，不分批，保持故事全局视角）
        job.current_step = "storyboard"
        await broadcast_progress(job_id, {"type": "step", "step": "storyboard"})
        
        _prefilled = bool(job.scenes) and all(getattr(s, "image_prompt", "") for s in job.scenes)
        llm_key = job.deepseek_key or DEEPSEEK_DEFAULT_KEY
        if not llm_key and not _prefilled:
            raise ValueError("DeepSeek API Key 未设置")
        
        # 完整原文送入（v9.5: 上限 15000 字，避免超出 DeepSeek 64K 上下文）
        MAX_TEXT = 15000
        novel_text = job.novel_text
        is_truncated = len(novel_text) > MAX_TEXT
        analysis_text = novel_text[:MAX_TEXT]
        truncate_notice = f"\n\n【注意：原文较长，以下为前 {MAX_TEXT} 字节选，请覆盖所有已提供情节内容。】\n\n" if is_truncated else ""

        storyboard_user_prompt = f"""请将以下完整小说文本改编为商业漫剧的连续分镜脚本。

## 故事结构预分析结果（分镜设计必须与之对齐）
        {json.dumps(job.story_structure, ensure_ascii=False, indent=2) if job.story_structure else "（无预分析结果）"}

## 角色预分析档案（v9.5：精简压缩，跨镜角色一致性强制参考！！！）
        {_compact_character_context(job.character_analysis)}

## 环境预分析档案（v9.5：精简压缩，跨镜场景一致性强制参考！！！）
        {_compact_environment_context(job.environment_analysis)}

要求：
1. 分镜数量：根据文本长度合理划分（每300-500字大约1个分镜）
2. 必须覆盖原文的所有重要情节，不能跳过任何情节
3. 分镜之间必须连贯，形成完整的故事弧线
4. subtitle_text 必须直接引用对应的原文文字{truncate_notice}
## 原文开始 ##
{analysis_text}
## 原文结束 ##"""

        if _prefilled:
            # 离线模式：场景已预填 prompts，直接复用，避免调用 DeepSeek
            storyboard = [{
                "title": s.title,
                "description": s.description,
                "subtitle_text": s.subtitle_text,
                "characters": s.characters,
                "setting": s.setting,
                "mood": s.mood,
                "camera": s.camera,
                "image_prompt": s.image_prompt,
                "video_prompt": s.video_prompt,
                "negative_prompt": s.negative_prompt,
                "emotional_intensity": s.emotional_intensity,
                "continuity_note": s.continuity_note,
                "visual_motif_note": s.visual_motif_note,
                "story_act": s.story_act,
                "story_position": s.story_position,
                "duration": s.duration,
                "shot_size": s.shot_size,
            } for s in job.scenes]
            print(f"[Pipeline] 离线重建分镜（{len(storyboard)} 镜，沿用预填 prompts，跳过 DeepSeek）", flush=True)
        else:
            result = await call_deepseek(llm_key, STORYBOARD_SYSTEM,
                storyboard_user_prompt,
                max_tokens=16384,
                temperature=0.7)  # 分镜创意生成
            storyboard = extract_json_array(result)
        
        if not storyboard:
            raise ValueError("分镜分析返回空结果")
        
        job.scenes = []
        for i, sb in enumerate(storyboard, 1):
            characters = sb.get("characters", "")
            if isinstance(characters, list):
                characters = "; ".join(characters) if characters else "无"
            subtitle_text = sb.get("subtitle_text", sb.get("narration", ""))
            subtitle_display = subtitle_text[:57] + "..." if len(subtitle_text) > 60 else subtitle_text
            scene = Scene(
                id=i,
                title=sb.get("title", f"场景{i}"),
                description=sb.get("description", sb.get("setting", "")),
                subtitle_text=subtitle_text,
                subtitle_display=subtitle_display,
                characters=characters,
                setting=sb.get("setting", ""),
                mood=sb.get("mood", ""),
                camera=sb.get("camera", ""),
                image_prompt=sb.get("image_prompt", ""),
                video_prompt=sb.get("video_prompt", ""),
                negative_prompt=sb.get("negative_prompt", ""),
                continuity_note=sb.get("continuity_note", ""),
                emotional_intensity=int(float(sb.get("emotional_intensity", 5))),
                visual_motif_note=sb.get("visual_motif_note", ""),
                story_act=sb.get("story_act", ""),
                story_position=sb.get("story_position", ""),
                storytelling_rhythm=sb.get("storytelling_rhythm", ""),
                duration=sb.get("duration", "5s"),
                shot_size=sb.get("shot_size", ""),
                status="pending"
            )
            job.scenes.append(scene)

        # P0-③: 多样化运镜调度（强制相邻场景景别不重复）
        try:
            _diversify_cameras_for_scenes(job.scenes)
        except Exception as e:
            logger.warning(f"[Camera] 多样化运镜调度失败（降级为单场景自动）: {e}")

        # P1-⑤: 开篇冲突钩子（红果完播率关键）
        try:
            _apply_opening_hook(job.scenes)
        except Exception as e:
            logger.warning(f"[Hook] 开篇钩子注入失败: {e}")

        # P1-⑥: 8秒反转点检查
        try:
            _check_reversal_points(job.scenes)
        except Exception as e:
            logger.warning(f"[Reversal] 反转点检查失败: {e}")

        # P1-⑦: 动态场景时长（情绪→时长）
        try:
            _compute_dynamic_durations(job.scenes)
        except Exception as e:
            logger.warning(f"[Duration] 动态时长失败: {e}")

        # P2-⑩: POV 主观镜头识别
        try:
            _detect_pov_scenes(job.scenes)
        except Exception as e:
            logger.warning(f"[POV] POV 识别失败: {e}")

        # P2-⑪: 表情控制词注入
        try:
            for s in job.scenes:
                _inject_expression_to_prompt(s)
        except Exception as e:
            logger.warning(f"[Expression] 表情注入失败: {e}")

        job.progress = {"total": len(job.scenes), "current": 0, "phase": "storyboard_done"}
        await JobStorage.save(job)
        await broadcast_progress(job_id, {"type": "storyboard_done", "scenes": len(job.scenes)})
        
        # Step 2: 智能分析角色
        if job.smart_dubbing and llm_key:
            try:
                await _auto_analyze_characters(job, llm_key)
            except Exception as e:
                logger.warning(f"[Auto] 角色分析失败: {str(e)[:100]}")
        
        # Step 2b: 如果 PuLID 开启但没有参考图，且有可灵API Key，自动生成角色正脸
        if job.use_pulid and not job.pulid_reference_image and job.kling_api_key:
            try:
                # 构造可灵角色描述（优先级：用户自定义 > DeepSeek生成的kling_prompt > 外貌+着装拼接）
                face_desc = job.kling_face_description
                if not face_desc and job.characters:
                    main_char = job.characters[0]
                    # 优先使用 DeepSeek 直接生成的 kling_prompt
                    kling_prompt = getattr(main_char, 'kling_prompt', '')
                    if kling_prompt:
                        face_desc = kling_prompt
                    else:
                        # 用外貌+身体+着装特征拼接（安全访问，旧数据可能无这些字段）
                        parts = []
                        appearance = getattr(main_char, 'appearance', '')
                        body_type = getattr(main_char, 'body_type', '')
                        clothing = getattr(main_char, 'clothing', '')
                        if appearance:
                            parts.append(appearance)
                        if body_type:
                            parts.append(body_type)
                        if clothing:
                            parts.append(f"wearing {clothing}")
                        if parts:
                            face_desc = ", ".join(parts)
                        else:
                            face_desc = f"{main_char.gender}{main_char.age_range}, {main_char.personality}"
                if not face_desc:
                    face_desc = "young person, attractive, clear facial features"

                await broadcast_progress(job_id, {
                    "type": "step", "step": "kling_face",
                    "message": f"正在用可灵AI生成角色正脸: {face_desc[:80]}"
                })
                print(f"[Kling] 自动生成角色正脸: {face_desc}", flush=True)

                try:
                    from kling_client import KlingImageClient
                except ImportError:
                    logger.warning("[Kling] 可灵客户端未安装，跳过自动生成角色正脸")
                    if job.use_pulid and not job.pulid_reference_image:
                        job.use_pulid = False
                    face_result = None
                else:
                    kling_client = KlingImageClient(api_key=job.kling_api_key)
                    ref_dir = OUTPUT_DIR / job_id / "pulid_ref"
                    ref_dir.mkdir(parents=True, exist_ok=True)
                    face_result = await kling_client.generate_face_image(
                    character_description=face_desc,
                    save_dir=str(ref_dir),
                    filename=f"kling_face_{main_char.name if job.characters else 'char'}.png",
                    on_progress=lambda s: broadcast_progress(job_id, {"type": "kling_progress", "status": s})
                )
                if face_result and face_result.get("status") == "succeed":
                    job.pulid_reference_image = face_result["path"]
                    print(f"[Kling] 角色正脸生成成功: {face_result['path']}", flush=True)
                    await broadcast_progress(job_id, {
                        "type": "step", "step": "kling_face_done",
                        "path": face_result["path"]
                    })
                else:
                    msg = face_result.get('message', '未知错误')
                    print(f"[WARN] 可灵生成角色正脸失败: {msg}", flush=True)
                    # 失败时禁用 PuLID，避免后续生成失败
                    if job.use_pulid and not job.pulid_reference_image:
                        job.use_pulid = False
                        print(f"[Kling] 可灵生成失败，已自动禁用 PuLID", flush=True)
                    await broadcast_progress(job_id, {
                        "type": "step", "step": "kling_face_failed",
                        "message": msg
                    })
            except Exception as e:
                print(f"[WARN] 可灵生成角色正脸异常: {str(e)[:150]}", flush=True)
                # 异常时禁用 PuLID，避免后续生成失败
                if job.use_pulid and not job.pulid_reference_image:
                    job.use_pulid = False
                    print(f"[Kling] 可灵生成异常，已自动禁用 PuLID", flush=True)
        
        # Step 3: 为每个场景生成 AI 绘画提示词（image_prompt / video_prompt / negative_prompt）
        if job.scenes:
            # 检查是否已有 image_prompt
            has_prompts = any(s.image_prompt for s in job.scenes)
            if not has_prompts:
                try:
                    await broadcast_progress(job_id, {
                        "type": "step", "step": "generating_prompts",
                        "message": "正在为每个场景生成AI绘画提示词..."
                    })
                    print(f"[Pipeline] 开始生成 {len(job.scenes)} 个场景的提示词...", flush=True)

                    # 构建全局角色外貌表（确保跨场景角色一致性）
                    # 关键修复：提取角色在分镜中出现的外貌描述，统一固定下来
                    global_character_desc = _build_global_character_desc(job)
                    
                    # 逐个场景生成（不并发，保证前后连贯性）
                    for idx, scene in enumerate(job.scenes):
                        try:
                            # 前一场景的提示词摘要（用于保持角色外貌一致）
                            prev_prompt_hint = ""
                            if idx > 0 and job.scenes[idx-1].image_prompt:
                                prev_scene = job.scenes[idx-1]
                                # v9.9: 提取角色外貌锚点词（跳过通用质量前缀）
                                prev_pmt = prev_scene.image_prompt
                                for qp in ["masterpiece, best quality", "ultra detailed", "8k uhd", "sharp focus"]:
                                    prev_pmt = prev_pmt.replace(qp + ", ", "").replace(qp, "")
                                char_anchor = prev_pmt[:150].rstrip(",").strip()
                                prev_prompt_hint = f"\n【上一镜角色外貌锚点（必须字面保持一致）】：{char_anchor}"
                            
                            # v9.9: 只为当前场景提取出场角色外貌
                            scene_char = _build_scene_character_desc(job, scene)
                            user_msg = f"""## 【本分镜出场角色外貌设定 —— 仅描述以下角色】
{scene_char if scene_char else "（无特定角色）"}
{prev_prompt_hint}

## 【当前分镜完整信息】
分镜编号：#{scene.id} / 共{len(job.scenes)}个
标题：{scene.title}
原文台词/旁白（画面内容的唯一依据）：{scene.subtitle_text}
画面描述：{scene.description}
出场角色及当前状态：{scene.characters}
场景环境：{scene.setting}
情绪氛围：{scene.mood}
镜头类型：{scene.camera}
连贯说明：{scene.continuity_note}
情绪强度（1-10，来自故事结构预分析）：{scene.emotional_intensity}
视觉母题说明：{scene.visual_motif_note or "无"}
所属故事幕次：{scene.story_act or "未标注"}
故事位置：{scene.story_position or "未标注"}

## 【生成要求】
1. image_prompt 的角色外貌描述词必须与上方"全局角色外貌设定"完全一致（发色/发型/眼睛/服装等关键词必须字面相同）
2. 场景/背景描述必须来自本分镜的"场景环境"和"画面描述"，绝对不能使用通用背景
3. 如果本镜没有人物，专注描述场景环境
4. 生成竖屏 9:16 的 image_prompt、video_prompt 和 negative_prompt"""

                            result = await call_deepseek(
                                llm_key,
                                PROMPT_SYSTEM,
                                user_msg,
                                max_tokens=2560,
                                temperature=0.5  # 提示词生成：平衡创意与一致性（v6.3升级：更长提示词）
                            )
                            prompts = extract_json_object(result)
                            scene.image_prompt = prompts.get("image_prompt", "")
                            scene.video_prompt = prompts.get("video_prompt", "")
                            scene.negative_prompt = prompts.get("negative_prompt",
                                "(worst quality:1.5), (low quality:1.5), (bad hands:1.4), (extra fingers:1.4), blurry, deformed, watermark, text")
                            if scene.image_prompt:
                                print(f"[Prompt] 场景{scene.id}/{len(job.scenes)} '{scene.title}': OK ({len(scene.image_prompt)}chars)", flush=True)
                            
                            # 每5个场景广播一次进度
                            if (idx + 1) % 5 == 0 or idx == len(job.scenes) - 1:
                                await broadcast_progress(job_id, {
                                    "type": "step", "step": "prompts_progress",
                                    "current": idx + 1, "total": len(job.scenes)
                                })
                        except Exception as e:
                            print(f"[WARN] 场景{scene.id}提示词生成失败: {str(e)[:100]}", flush=True)
                            # 兜底：基于分镜信息构建尽量准确的 prompt
                            if not scene.image_prompt:
                                scene.image_prompt = await _build_fallback_image_prompt(scene, global_character_desc, job=job)
                            if not scene.video_prompt:
                                desc_en2 = _translate_to_english_keywords(scene.description) if scene.description else ""
                                mood_map_vp2 = {"紧张":"tense","温馨":"warm cozy","悲伤":"melancholic","壮阔":"epic",
                                    "神秘":"mysterious","热血":"passionate","恐惧":"fearful","喜悦":"joyful",
                                    "惆怅":"wistful","愤怒":"intense","压抑":"oppressive","释然":"relieved",
                                    "宁静":"peaceful","诡异":"eerie"}
                                mood_en2 = mood_map_vp2.get(scene.mood, "cinematic") if scene.mood else "cinematic"
                                style_vp2 = _get_style_video_suffix(getattr(job, 'style', 'cinematic'))
                                scene.video_prompt = f"{desc_en2}, {mood_en2} atmosphere, subtle camera motion, slow push in, {style_vp2}" if desc_en2 else f"{mood_en2} atmosphere, cinematic movement, slow push in, {style_vp2}"

                    await broadcast_progress(job_id, {
                        "type": "step", "step": "prompts_done",
                        "message": f"已生成 {len(job.scenes)} 个场景的提示词"
                    })
                    print(f"[Pipeline] 提示词生成完成", flush=True)
                except Exception as e:
                    print(f"[WARN] 提示词生成阶段出错(将使用兜底): {str(e)[:200]}", flush=True)
        
        # v12.0: 预生成环境参考图和关键道具特写图
        if job.environment_analysis and isinstance(job.environment_analysis.get("environments"), list):
            try:
                from environment_generator import EnvironmentGenerator
                env_gen = EnvironmentGenerator(
                    kling_api_key=job.kling_api_key,
                    deepseek_key=llm_key,
                )
                await broadcast_progress(job_id, {
                    "type": "step", "step": "env_pre_generation",
                    "message": "正在预生成环境参考图和关键道具特写..."
                })
                env_results = await env_gen.pre_generate_environments(
                    job,
                    str(OUTPUT_DIR / job_id),
                    on_progress=lambda name, status: broadcast_progress(job_id, {
                        "type": "env_progress", "name": name, "status": status
                    }),
                )
                # 存入 job 供后续场景生成使用
                job.environment_images = env_results.get("environments", {})
                job.prop_images = env_results.get("props", {})
                await JobStorage.save(job)
                print(f"[Pipeline] 环境预生成完成: {len(env_results['environments'])} 环境, {len(env_results['props'])} 道具", flush=True)
            except Exception as e:
                print(f"[WARN] 环境预生成失败(不阻塞): {str(e)[:150]}", flush=True)
        
        # Step 4: 在后台异步启动生成
        job.current_step = "generating"
        await JobStorage.save(job)
        
        await _start_generation_pipeline(job)
        
        # Step 5: _start_generation_pipeline 已内部完成合并，此处仅广播完成状态
        if job.merged_video_path:
            await broadcast_progress(job_id, {
                "type": "job_complete",
                "merged_video": job.merged_video_path,
                "scenes_count": len([s for s in job.scenes if s.status == "done"])
            })
        else:
            # 合并失败或无视频
            done_count = sum(1 for s in job.scenes if s.status == "done")
            error_count = sum(1 for s in job.scenes if s.status == "error")
            if error_count > 0:
                await broadcast_progress(job_id, {
                    "type": "status", "status": "error",
                    "text": f"生成完成（{done_count}成功/{error_count}失败），但合并失败"
                })
        
    except Exception as e:
        job.error = str(e)[:500]
        job.current_step = "error"
        await JobStorage.save(job)
        print(f"[Pipeline] 生成失败: {e}", flush=True)

async def _auto_analyze_characters(job: JobState, llm_key: str):
    """自动分析角色（含外貌/身体/着装特征，用于可灵AI生成角色正脸）
    
    v9.3 优化: 缓存优先 —— 当 _analyze_characters_and_environments() 已运行
    并生成 job.character_analysis 时，直接复用缓存数据，避免重复调用 DeepSeek。
    缓存未命中时才回退到 DeepSeek 调用。
    """
    chars = None
    
    # 优先从缓存读取（v9.3: 消除冗余 DeepSeek 调用）
    if job.character_analysis and isinstance(job.character_analysis.get("characters"), list) \
            and len(job.character_analysis["characters"]) > 0:
        chars = job.character_analysis["characters"]
        print(f"[角色分析] 从缓存复用 {len(chars)} 个角色（跳过重复 LLM 调用）", flush=True)
    else:
        # 缓存未命中: 调用 DeepSeek 分析
        result = await call_deepseek(llm_key, CHARACTER_ANALYSIS_SYSTEM,
            f"分析以下小说文本中的角色：\n\n{job.novel_text[:15000]}",
            max_tokens=4096,
            temperature=0.3)
        # v9.3: 使用 extract_json_object 统一解析对象格式
        char_data = extract_json_object(result)
        if char_data and isinstance(char_data.get("characters"), list) \
                and len(char_data["characters"]) > 0:
            chars = char_data["characters"]
            print(f"[角色分析] DeepSeek 分析成功，提取 {len(chars)} 个角色", flush=True)
    
    if chars:
        job.characters = []
        for c in chars:
            # v9.2 修复: 组合LLM细粒度字段 → Character对象的appearance
            # LLM输出: physical_description, face_detail, hair_style, eye_detail, skin_tone
            # Character对象需要: appearance (组合后的综合外貌描述)
            appearance_parts = []
            if c.get("physical_description"):
                appearance_parts.append(c["physical_description"])
            if c.get("face_detail"):
                appearance_parts.append(c["face_detail"])
            if c.get("hair_style"):
                appearance_parts.append(c["hair_style"])
            if c.get("eye_detail"):
                appearance_parts.append(c["eye_detail"])
            if c.get("skin_tone"):
                appearance_parts.append(c["skin_tone"])
            composed_appearance = ", ".join(appearance_parts) if appearance_parts else ""

            char = Character(
                name=c.get("name", ""),
                gender=c.get("gender", ""),
                age_range=c.get("age_range", ""),
                personality=c.get("personality", ""),
                speaking_style=c.get("speaking_style", ""),
                role_type=c.get("role", ""),           # LLM输出"role"不是"role_type"
                appearance=composed_appearance,         # 组合细粒度字段
                body_type=c.get("body_type", ""),
                clothing=c.get("typical_clothing", ""),  # LLM输出"typical_clothing"
                kling_prompt=c.get("kling_prompt", ""),
            )
            # v8.7 Phase 5a: 统一语音匹配（替换硬编码voice_map）
            # v11: 同时分配 CosyVoice2 speaker
            char = match_voice_for_character(char)
            char.cosyvoice_voice = get_cosyvoice_speaker(char)
            job.characters.append(char)

            # 打印角色特征（日志）
            if char.appearance or char.clothing:
                print(f"[角色分析] {char.name}: 外貌={char.appearance[:80]}... | 着装={char.clothing[:60]}...", flush=True)

async def _start_generation_pipeline(job: JobState):
    """启动场景生成（含智能兜底prompt + ComfyUI 预检 + 完整进度广播）"""
    job_id = job.id
    
    # ── ComfyUI 连接预检 ──
    await broadcast_progress(job_id, {
        "type": "step", "step": "image_gen_start",
        "message": "正在检查 ComfyUI 连接..."
    })
    print(f"[Pipeline] 检查 ComfyUI 连接 ({COMFYUI_URL})...", flush=True)
    
    comfyui_ok = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{COMFYUI_URL}/system_stats")
            if resp.status_code == 200:
                devices = resp.json().get("devices", [])
                gpu_info = devices[0].get("name", "unknown") if devices else "CPU"
                vram_free_mb = (devices[0].get("vram_free", 0) // (1024*1024)) if devices else 0
                print(f"[Pipeline] ComfyUI 连接成功: {gpu_info}, VRAM空闲: {vram_free_mb}MB", flush=True)
                comfyui_ok = True
                await broadcast_progress(job_id, {
                    "type": "step", "step": "image_gen_start",
                    "message": f"ComfyUI 已连接 ({gpu_info}, 空闲{vram_free_mb}MB)，开始生成图片..."
                })
            else:
                raise RuntimeError(f"ComfyUI 返回状态码 {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] ComfyUI 连接失败: {e}", flush=True)
        await broadcast_progress(job_id, {
            "type": "step", "step": "image_gen_start",
            "message": f"❌ ComfyUI 连接失败: {str(e)[:100]}"
        })
        # 不直接抛出异常，让后续 submit_workflow 报更具体的错误
        # 但先记录到 job 中
        job.error = f"ComfyUI 连接失败 ({COMFYUI_URL}): {str(e)[:200]}"
        await JobStorage.save(job)
    
    # 为每个场景生成提示词（如果还没有 — 使用结构化兜底，替代旧的中文拼接方案）
    global_character_desc = _build_global_character_desc(job)
    for scene in job.scenes:
        if not scene.image_prompt:
            scene.image_prompt = await _build_fallback_image_prompt(scene, global_character_desc, job=job)
            
        if not scene.video_prompt:
            # v5.5: 视频 prompt 必须全英文，Wan2.1/LTX 无法理解中文
            # 使用翻译后的场景描述构建英文视频 prompt
            desc_en = _translate_to_english_keywords(scene.description)
            if not desc_en or len(desc_en) < 20:
                # 翻译失败时用 setting + 基本描述拼英文
                setting_en = _translate_to_english_keywords(scene.setting) if scene.setting else ""
                desc_en = (setting_en + " " + scene.title).strip()
            if not desc_en or len(desc_en) < 15:
                desc_en = f"scene {scene.id}, cinematic scene"
            
            mood_map = {
                "紧张": "tense atmosphere", "温馨": "warm cozy atmosphere", "悲伤": "melancholic sorrowful mood",
                "壮阔": "epic grand scenery", "神秘": "mysterious atmosphere", "热血": "passionate energetic mood",
                "恐惧": "fearful terrifying atmosphere", "喜悦": "joyful happy mood",
                "惆怅": "wistful melancholic mood", "愤怒": "angry intense mood",
                "压抑": "oppressive dark atmosphere", "释然": "relieved peaceful mood",
                "宁静": "peaceful serene calm", "诡异": "eerie uncanny unsettling",
            }
            mood_en = mood_map.get(scene.mood, "cinematic atmosphere")

            # v9.10: 参数化运镜（即梦蒸馏）
            camera_motion = _generate_camera_motion(scene, job)

            scene.video_prompt = f"{desc_en}, {mood_en}, {camera_motion}, portrait video, 9:16 vertical"
        
        if not scene.negative_prompt:
            scene.negative_prompt = "(worst quality:1.4), (low quality:1.4), (bad hands:1.4), (bad fingers:1.3), (extra fingers:1.3), (missing fingers:1.3), bad anatomy, malformed limbs, blurry, out of focus, watermark, text, signature, deformed eyes, cross-eyed, ugly, disfigured, mutation"
    
    # 创建输出目录
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载工作流模板
    txt2img_base = load_workflow("txt2img")
    img2vid_base = load_workflow("img2vid")
    
    job.progress = {"total": len(job.scenes), "current": 0, "phase": "generating"}
    await JobStorage.save(job)
    
    # 逐个生成场景
    total_scenes = len(job.scenes)
    for i, scene in enumerate(job.scenes):
        # v9.9: 跳过已完成的场景（支持断点续跑）
        if scene.status == "done" and scene.image_path:
            print(f"[Pipeline] ⏭️ 场景 {scene.id} 已完成，跳过 ({i+1}/{total_scenes})", flush=True)
            continue

        # 每个场景开始前清理内存，防止lowvram模式下系统RAM耗尽
        gc.collect()

        # 广播：当前场景开始
        await broadcast_progress(job_id, {
            "type": "step",
            "step": "image_gen_start",
            "message": f"🎨 正在生成 ({i+1}/{total_scenes}) {scene.title or f'场景#{scene.id}'}..."
        })
        print(f"[Pipeline] 开始生成场景 {scene.id} ({i+1}/{total_scenes}): {scene.title}", flush=True)

        try:
            scene_dir = job_dir / f"scene_{scene.id:03d}"
            scene_dir.mkdir(parents=True, exist_ok=True)

            await _generate_scene(job, scene, scene_dir, txt2img_base, img2vid_base or txt2img_base)
            scene.status = "done"
            scene.comfyui_progress = 1.0
            print(f"[Pipeline] ✅ 场景 {scene.id} 完成 ({i+1}/{total_scenes})", flush=True)

        except Exception as e:
            scene.status = "error"
            scene.error_msg = str(e)[:300]
            err_type = type(e).__name__
            print(f"[Pipeline] ❌ 场景 {scene.id} 失败 [{err_type}]: {e}", flush=True)
            # 广播错误详情到前端
            await broadcast_progress(job_id, {
                "type": "scene_status",
                "scene_id": scene.id,
                "status": "error",
                "error": f"{err_type}: {str(e)[:200]}"
            })
            # 场景失败不阻塞后续场景，继续生成下一个

        job.progress["current"] = i + 1
        job.progress["phase"] = "generating"
        await JobStorage.save(job)
        
        # 只在非错误状态下发送成功状态（避免覆盖上面的错误广播）
        if scene.status != "error":
            await broadcast_progress(job_id, {
                "type": "scene_status",
                "scene_id": scene.id,
                "status": scene.status,
            })

        # 场景间短暂等待，让ComfyUI释放显存/内存
        if i < len(job.scenes) - 1:
            await asyncio.sleep(2)
    
    # 合并视频
    try:
        video_paths = []
        scene_moods = []
        for scene in job.scenes:
            vp = scene.final_video_path or scene.video_path
            if vp and Path(vp).exists() and Path(vp).stat().st_size > 10000:
                video_paths.append(vp)
                scene_moods.append(getattr(scene, 'mood', '') or '')
        
        if video_paths:
            merged_path = str(job_dir / f"{job.novel_title or 'output'}_merged.mp4")
            if len(video_paths) > 1:
                # v9.9: 传入场景情绪列表，实现情绪感知转场
                await merge_videos_with_transitions(video_paths, merged_path,
                                                    scene_moods=scene_moods)
            else:
                import shutil
                shutil.copy(video_paths[0], merged_path)
            job.merged_video_path = merged_path
            job.current_step = "done"
            job.progress["phase"] = "done"
            await broadcast_progress(job_id, {"type": "job_complete", "merged_video": merged_path})
    except Exception as e:
        print(f"[Pipeline] 合并失败: {e}", flush=True)
        # v9.8: 即使合并报错，也检查输出文件是否已实际生成（FFmpeg 可能返回非 0 但文件完整）
        if 'merged_path' in dir() and Path(merged_path).exists() and Path(merged_path).stat().st_size > 10000:
            print(f"[Pipeline] 合并报错但输出文件有效 ({Path(merged_path).stat().st_size//1024}KB)，使用该文件", flush=True)
            job.merged_video_path = merged_path
            job.current_step = "done"
            job.progress["phase"] = "done"
            await broadcast_progress(job_id, {"type": "job_complete", "merged_video": merged_path})
        else:
            job.current_step = "error"
            job.progress["phase"] = "merge_error"
            job.progress["error"] = f"视频合并失败: {str(e)[:300]}"
            await broadcast_progress(job_id, {
                "type": "error",
                "message": f"视频合并失败: {str(e)[:300]}",
                "phase": "merge_error"
            })
    
    await JobStorage.save(job)

def _get_job(job_id: str) -> JobState:
    """获取job：优先内存，找不到则从磁盘加载"""
    if job_id in jobs:
        return jobs[job_id]
    # 从磁盘尝试加载
    storage_path = JobStorage.STORAGE_DIR / f"{job_id}.json"
    if storage_path.exists():
        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # v5.5: 清理字段类型不匹配
            raw_scenes = data.get("scenes", [])
            cleaned_scenes = []
            for s in raw_scenes:
                if isinstance(s, dict) and 'emotional_intensity' in s:
                    try:
                        s['emotional_intensity'] = int(float(s['emotional_intensity']))
                    except (ValueError, TypeError):
                        s['emotional_intensity'] = 5
                cleaned_scenes.append(s)
            scenes = [Scene(**s) for s in cleaned_scenes]
            characters = [Character(**c) for c in data.get("characters", [])]
            data["scenes"] = scenes
            data["characters"] = characters
            job = JobState(**data)
            jobs[job_id] = job  # 缓存到内存
            print(f"[Job] Loaded job {job_id} from disk on demand", flush=True)
            return job
        except Exception as e:
            print(f"[Job] Failed to load {job_id} from disk: {e}", flush=True)
    raise HTTPException(404, "Job not found")

@app.get("/api/debug-prompts/{job_id}")
async def debug_prompts(job_id: str):
    """调试端点：查看所有场景的提示词，排查图文不符问题"""
    job = _get_job(job_id)
    result = []
    for scene in job.scenes:
        result.append({
            "id": scene.id,
            "title": scene.title,
            "original_text": scene.subtitle_text[:200] if scene.subtitle_text else "",
            "description": scene.description[:200] if scene.description else "",
            "characters": scene.characters,
            "setting": scene.setting,
            "mood": scene.mood,
            "image_prompt": scene.image_prompt[:500] if scene.image_prompt else "(空)",
            "video_prompt": scene.video_prompt[:300] if scene.video_prompt else "(空)",
            "negative_prompt": scene.negative_prompt[:200] if scene.negative_prompt else "(空)",
            "status": scene.status,
            "error": scene.error_msg,
        })
    return {
        "job_id": job_id,
        "title": job.novel_title,
        "img_checkpoint": job.img_checkpoint,
        "vid_checkpoint": job.vid_checkpoint,
        "use_pulid": job.use_pulid,
        "scenes": result
    }

@app.get("/api/scene-error/{job_id}")
async def get_scene_errors(job_id: str):
    """查看所有失败场景的详细错误信息"""
    job = _get_job(job_id)
    errors = []
    for scene in job.scenes:
        if scene.status == "error" or scene.error_msg:
            errors.append({
                "id": scene.id,
                "title": scene.title,
                "status": scene.status,
                "error": scene.error_msg,
            })
    return {
        "job_id": job_id,
        "total_scenes": len(job.scenes),
        "failed_scenes": len(errors),
        "job_error": job.error,
        "errors": errors,
    }

# ─── 模型列表 API ──────────────────────────────────────────
@app.get("/api/models")
async def api_list_models():
    """获取 ComfyUI 可用模型列表 + 本地 PuLID/InsightFace 检测"""
    try:
        result = await comfyui.get_models()
    except Exception as e:
        result = {"error": str(e), "checkpoints": [], "vae": [], "loras": []}

    # 附加本地 PuLID / InsightFace 可用性检测
    pulid_dir = COMFYUI_MODELS_DIR / "pulid"
    pulid_files = []
    if pulid_dir.exists():
        pulid_files = [f.name for f in pulid_dir.glob("*.safetensors")] + \
                       [f.name for f in pulid_dir.glob("*.bin")]

    insightface_dir = COMFYUI_MODELS_DIR / "insightface" / "models" / "antelopev2"
    insightface_ready = insightface_dir.exists() and any(insightface_dir.iterdir())

    result["pulid_models"] = pulid_files
    result["pulid_ready"] = len(pulid_files) > 0 and insightface_ready
    result["insightface_ready"] = insightface_ready

    # 标注哪些 checkpoint 是 SDXL
    checkpoints = result.get("checkpoints", [])
    result["sdxl_checkpoints"] = [c for c in checkpoints if "xl" in c.lower() or "animagine" in c.lower()]
    result["sd15_checkpoints"] = [c for c in checkpoints if c not in result["sdxl_checkpoints"]]

    return result

# ─── 场景重试/跳过 ─────────────────────────────────────────
@app.post("/api/scene/{job_id}/{scene_id}/retry")
async def api_retry_scene(job_id: str, scene_id: int):
    """重试失败的场景"""
    # 委托给现有的 retry-scene 端点
    return await retry_scene(job_id, scene_id)

@app.post("/api/scene/{job_id}/{scene_id}/skip")
async def api_skip_scene(job_id: str, scene_id: int):
    """跳过失败的场景"""
    job = _get_job(job_id)
    for scene in job.scenes:
        if scene.id == scene_id:
            scene.status = "done"
            scene.error_msg = "用户跳过"
            await JobStorage.save(job)
            return {"status": "ok"}
    raise HTTPException(404, "Scene not found")

# ─── 新增: 批量编辑分镜 (v12 前端) ──────────────────────────
@app.post("/api/scenes/{job_id}/batch-edit")
async def batch_edit_scenes(job_id: str, updates: dict):
    """批量更新分镜字段。updates 格式: {"scene_ids": [0,1,2], "fields": {"mood": "紧张", "camera": "zoom_in"}}"""
    job = _get_job(job_id)
    scene_ids = updates.get("scene_ids", [])
    fields = updates.get("fields", {})
    updated_count = 0
    for scene in job.scenes:
        if scene.id in scene_ids:
            for key, value in fields.items():
                if hasattr(scene, key):
                    setattr(scene, key, value)
            updated_count += 1
    await JobStorage.save(job)
    return {"status": "ok", "updated": updated_count}

# ─── 新增: 分镜排序 (v12 前端) ──────────────────────────────
@app.post("/api/scenes/{job_id}/reorder")
async def reorder_scenes(job_id: str, order: dict):
    """重新排序分镜。order 格式: {"scene_ids": [2, 0, 1, 3]}"""
    job = _get_job(job_id)
    new_order = order.get("scene_ids", [])
    if len(new_order) != len(job.scenes):
        raise HTTPException(400, "Scene count mismatch")
    scene_map = {s.id: s for s in job.scenes}
    new_scenes = []
    for sid in new_order:
        if sid in scene_map:
            new_scenes.append(scene_map[sid])
        else:
            raise HTTPException(400, f"Scene {sid} not found")
    job.scenes = new_scenes
    await JobStorage.save(job)
    return {"status": "ok"}

@app.get("/api/scenes/{job_id}/export-prompts")
async def export_scene_prompts(job_id: str, format: str = "txt"):
    """v12.1: 批量导出场景提示词。format=txt|json"""
    job = _get_job(job_id)
    if format == "json":
        prompts = []
        for s in job.scenes:
            prompts.append({
                "scene_id": s.id,
                "title": s.title,
                "description": s.description,
                "image_prompt": getattr(s, "image_prompt", ""),
                "video_prompt": getattr(s, "video_prompt", ""),
                "setting": getattr(s, "setting", ""),
                "mood": getattr(s, "mood", ""),
            })
        return {"job_id": job_id, "title": job.novel_title, "prompts": prompts}
    else:
        lines = [f"# {job.novel_title} — 场景提示词导出", f"# 共 {len(job.scenes)} 个场景", "=" * 60, ""]
        for s in job.scenes:
            lines.append(f"## 场景 {s.id}: {s.title}")
            lines.append(f"描述: {s.description}")
            if hasattr(s, "image_prompt") and s.image_prompt:
                lines.append(f"图片提示词: {s.image_prompt}")
            if hasattr(s, "video_prompt") and s.video_prompt:
                lines.append(f"视频提示词: {s.video_prompt}")
            if hasattr(s, "setting") and s.setting:
                lines.append(f"环境: {s.setting}")
            if hasattr(s, "mood") and s.mood:
                lines.append(f"情绪: {s.mood}")
            lines.append("")
        return {"content": "\n".join(lines), "format": "txt"}
from fastapi.staticfiles import StaticFiles
if not any("output" in str(r.path) for r in app.routes):
    app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output_files")

# ─── 启动检查 ──────────────────────────────────────────────
@app.on_event("startup")
async def startup_check():
    """启动时检查关键依赖 + 初始化 SQLite 存储"""
    # v12.0: 初始化 SQLite 存储并加载所有任务
    try:
        global jobs
        _storage = await db_storage.get_storage()
        jobs = await db_storage.sync_load_all()
        if jobs:
            print(f"[Storage] SQLite: 从数据库加载 {len(jobs)} 个任务", flush=True)
        else:
            print(f"[Storage] SQLite: 无已保存任务", flush=True)
    except Exception as e:
        print(f"[Storage] SQLite 初始化失败 (回退到空存储): {e}", flush=True)

    try:
        issues = []
        
        # 检查 DeepSeek API Key
        if not DEEPSEEK_DEFAULT_KEY:
            issues.append("[WARN] DEEPSEEK_API_KEY 未设置 - LLM 功能（分镜/角色分析）将不可用")
        
        # 检查 ComfyUI 连接
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                resp = await c.get(f"{COMFYUI_URL}/system_stats")
                if resp.status_code == 200:
                    print("[Startup] [OK] ComfyUI 已连接", flush=True)
        except Exception:
            issues.append(f"[WARN] ComfyUI 未响应 ({COMFYUI_URL}) - 图片/视频生成将不可用")
        
        # 检查模型目录
        if COMFYUI_MODELS_DIR.exists():
            ckpt_dir = COMFYUI_MODELS_DIR / "checkpoints"
            safetensors = list(ckpt_dir.glob("*.safetensors")) + list(ckpt_dir.glob("*/*.safetensors"))
            valid_models = [f.name for f in safetensors if f.stat().st_size > MIN_SAFETENSORS_SIZE]
            print(f"[Startup] 检测到 {len(valid_models)} 个可用模型: {valid_models[:5]}...", flush=True)
        else:
            issues.append(f"[WARN] 模型目录不存在: {COMFYUI_MODELS_DIR}")
        
        # v7.0: 检测 CosyVoice 2 是否已部署
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:50000/", method="GET")
            resp = urllib.request.urlopen(req, timeout=3)
            if resp.status == 200:
                print("[Startup] [OK] CosyVoice 2 已就绪 (localhost:50000) — 自动启用电影级配音", flush=True)
                import builtins
                builtins.__dict__['COSYVOICE_AVAILABLE'] = True
        except Exception:
            print("[Startup] [INFO] CosyVoice 2 未运行 (可选, 部署后自动启用电影级配音)", flush=True)
        
        if issues:
            print("[Startup] [WARN] 启动警告:", flush=True)
            for i in issues:
                print(f"  {i}", flush=True)
        else:
            print("[Startup] [OK] 所有依赖就绪", flush=True)
    except Exception as e:
        print(f"[Startup] [ERR] 启动检查失败 (非致命): {e}", flush=True)

# ─── 静态文件 ──────────────────────────────────────────────
class NoCacheStaticFiles(StaticFiles):
    """禁止浏览器缓存的静态文件服务"""
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

# 优先使用 web/dist (新 React 前端)，回退到 static/ (旧前端)
_WEB_DIST = PROJECT_ROOT / "web" / "dist"
_STATIC_DIR = PROJECT_ROOT / "static"
_SERVE_DIR = str(_WEB_DIST) if (_WEB_DIST / "index.html").exists() else str(_STATIC_DIR)
app.mount("/", NoCacheStaticFiles(directory=_SERVE_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    print("[Novel-to-Video v4.0] Starting...")
    print(f"[ComfyUI] {COMFYUI_URL}")
    print("[TTS] Edge-TTS enabled")
    print(f"[Browser] http://localhost:8190")
    print(f"[WebSocket] ws://localhost:8190/ws/progress/{{job_id}}")
    uvicorn.run(app, host="0.0.0.0", port=8190)
