"""本地 ComfyUI 生成引擎（P1：完整实现，行为与 scripts/main.py 现有路径一致）。

自包含实现，不依赖 scripts/main.py 内部函数（避免导入巨核与循环依赖）：
- 复用 comfyui/ 工作流模板（img2vid.json / t2vid.json）与 {{KEY}} 占位符系统；
- 通过 ComfyUI HTTP API（/upload/image → /prompt → /history → /view）；
- 支持 I2V（首帧图）与 T2V 两种模式；
- 输出可被 engines/registry.py 统一路由（云端失败降级本地）。

引擎是"瘦客户端"：LTX 22B 仍在 ComfyUI 服务端低显存模式运行，本类只负责提交与取回。
"""
from __future__ import annotations

import asyncio
import copy
import json
import random
import time
from pathlib import Path
from typing import Optional

import httpx

from .base import BaseEngine, ClipResult, EngineError, GenerateRequest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = PROJECT_ROOT / "comfyui"

# LTX 22B fp8（与 story2/video_engine 验证值一致）
LTX_CHECKPOINT = "ltx-2.3-22b-dev-fp8.safetensors"
LTX_TEXT_ENCODER = "gemma_3_12B_it_fpmixed.safetensors"
DEFAULT_W, DEFAULT_H = 960, 1728
DEFAULT_FRAMES = 65
DEFAULT_FPS = 24

_NEG = (
    "low quality, blurry, deformed hands, extra fingers, bad anatomy, watermark, "
    "text, letters, signs, chinese characters, oversaturated, harsh lighting, ugly, "
    "distorted face, mutated, disfigured, double face, two heads, duplicated face, "
    "clone, multiple faces, extra head, jitter, flicker, sudden camera cut"
)


class ComfyUIEngine(BaseEngine):
    """本地 ComfyUI 引擎（LTX 22B I2V/T2V）。"""

    name = "comfyui"
    kind = "local"
    capability = "both"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        workflow_dir: Optional[Path] = None,
        checkpoint: str = LTX_CHECKPOINT,
        text_encoder: str = LTX_TEXT_ENCODER,
        quality: str = "normal",   # normal | high（high 用 img2vid_hq 12+6 步采样）
    ):
        self.base_url = base_url.rstrip("/")
        self.workflow_dir = workflow_dir or WORKFLOW_DIR
        self.checkpoint = checkpoint
        self.text_encoder = text_encoder
        self.quality = quality

    # ─── 可用性 ──────────────────────────────────────────────
    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:  # 本地 ComfyUI 不走代理
                r = client.get(f"{self.base_url}/system_stats")
                return r.status_code == 200
        except Exception:
            return False

    # ─── 模板 ────────────────────────────────────────────────
    def load_workflow(self, name: str) -> dict:
        path = self.workflow_dir / f"{name}.json"
        if not path.exists():
            raise EngineError(f"工作流模板不存在: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EngineError(f"工作流模板 JSON 解析失败: {path}: {exc}") from exc

    @staticmethod
    def fill_workflow(template: dict, replacements: dict) -> dict:
        """占位符替换（与 main.py fill_workflow 同逻辑：按 key 长度降序防子串误替换）。"""
        workflow = copy.deepcopy(template)
        json_str = json.dumps(workflow, ensure_ascii=False)
        sorted_items = sorted(replacements.items(), key=lambda kv: -len(kv[0]))
        for key, val in sorted_items:
            placeholder = '"{{' + key + '}}"'
            if isinstance(val, (int, float)):
                json_str = json_str.replace(placeholder, str(val))
            else:
                json_str = json_str.replace(placeholder, json.dumps(str(val)))
        return json.loads(json_str)

    # ─── ComfyUI HTTP 交互 ───────────────────────────────────
    async def _upload_image(self, image_path: Path) -> str:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            with open(image_path, "rb") as f:
                resp = await client.post(
                    f"{self.base_url}/upload/image",
                    files={"image": (image_path.name, f, "image/png")},
                    data={"overwrite": "true"},
                )
            resp.raise_for_status()
            return resp.json().get("name", image_path.name)

    async def _submit(self, workflow: dict) -> str:
        payload = json.dumps({"prompt": workflow}, ensure_ascii=False).encode("utf-8")
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(
                f"{self.base_url}/prompt",
                content=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                raise EngineError(f"ComfyUI 提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()["prompt_id"]

    async def _wait_result(self, prompt_id: str, timeout: float) -> dict:
        """轮询 /history/{prompt_id}，带硬 deadline（避免无限等待）。"""
        start = time.time()
        last_err = ""
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            while time.time() - start < timeout:
                try:
                    resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                    if resp.status_code == 200:
                        data = resp.json()
                        if prompt_id in data:
                            entry = data[prompt_id]
                            status = entry.get("status", {})
                            if status.get("completed"):
                                return entry
                            if status.get("status_str") == "error":
                                msgs = status.get("messages", [])
                                for m in msgs:
                                    if m and m[0] == "execution_error":
                                        last_err = str(m[1])[:300]
                                raise EngineError(f"ComfyUI 执行失败: {last_err or 'unknown'}")
                except httpx.HTTPError as exc:
                    last_err = str(exc)  # 服务端重启等，继续轮询
                await asyncio.sleep(2)
        raise EngineError(f"ComfyUI 任务超时（>{timeout}s）: {prompt_id}，最后错误: {last_err}")

    @staticmethod
    def find_output(outputs: dict) -> Optional[tuple[str, str, str]]:
        """递归找输出文件，优先 videos > gifs > images。

        返回 (filename, subfolder, type) —— type 取 item 自身声明的 type 字段
        （LTX 输出在 gifs 键但 type=output，用键名当 type 会导致 /view 400）。
        文件名优先不带 '-audio' 后缀的变体（LTX 音频轨合并版）。
        """
        best: Optional[tuple[str, str, str, int]] = None
        order = {"videos": 0, "gifs": 1, "images": 2}

        def rank_item(filename: str, key: str, depth: int) -> int:
            return (order.get(key, 9), depth, 1 if "-audio" in filename else 0)

        def walk(data: dict, depth: int = 0):
            nonlocal best
            if depth > 10 or not isinstance(data, dict):
                return
            for key, val in data.items():
                if key in order and isinstance(val, list) and val:
                    for item in val:
                        if isinstance(item, dict) and "filename" in item:
                            r = rank_item(item["filename"], key, depth)
                            if best is None or r < best[3]:
                                best = (item["filename"], item.get("subfolder", ""),
                                        item.get("type", "output"), r)
                elif isinstance(val, dict):
                    walk(val, depth + 1)
                elif isinstance(val, list):
                    for v in val:
                        if isinstance(v, dict):
                            walk(v, depth + 1)

        walk(outputs)
        if best:
            return best[0], best[1], best[2]
        return None

    async def _download(self, filename: str, subfolder: str, out_type: str, dest: Path) -> Path:
        """下载输出；兼容 '-audio' 文件名变体与 type 探测。"""
        dest.parent.mkdir(parents=True, exist_ok=True)
        candidates = [(filename, subfolder, out_type)]
        # 变体 1：去掉 -audio（LTX 合并版文件名）
        if "-audio" in filename:
            candidates.append((filename.replace("-audio", ""), subfolder, out_type))
        # 变体 2：type 兜底 output/temp
        for t in ("output", "temp"):
            if t != out_type:
                candidates.append((filename, subfolder, t))

        last_err = ""
        async with httpx.AsyncClient(timeout=900, trust_env=False) as client:
            for fn, sub, typ in candidates:
                try:
                    resp = await client.get(
                        f"{self.base_url}/view",
                        params={"filename": fn, "subfolder": sub, "type": typ},
                    )
                    if resp.status_code == 200 and resp.content:
                        dest.write_bytes(resp.content)
                        return dest
                    last_err = f"HTTP {resp.status_code}"
                except httpx.HTTPError as exc:
                    last_err = str(exc)
        raise EngineError(f"下载输出失败（尝试 {len(candidates)} 种组合）: {last_err}")

    # ─── 生成 ────────────────────────────────────────────────
    async def generate(self, req: GenerateRequest) -> ClipResult:
        if not self.is_available():
            raise EngineError(f"ComfyUI 不可达: {self.base_url}（请确认 --lowvram 模式已启动）")

        seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
        # 8GB 显存稳定性：默认降到 VID_WIDTH/HEIGHT(672×1152) + 帧数 65(≈2.7s)，
        # 避免 960×1728×96帧 在 8GB 下 staging ~23GB / 每步 170s 导致的"卡死"(实为极慢换页)。
        # 提高质量时可在 settings/场景级调高（稳定性优先）。
        width = req.width or 672
        height = req.height or 1152
        frames = int(min(max(req.duration_seconds, 1.0), 3.0) * DEFAULT_FPS)  # 上限 3s/段(65帧)
        frames = max(frames, 25)

        prompt = req.prompt
        if req.first_frame is not None:
            # I2V：忠于首帧，抑制漂移（与 video_engine._ltx_single 一致）
            prompt = (prompt + ". locked camera, subtle micro motion, keep first frame "
                      "composition and character identity").strip()
            template = self.load_workflow("img2vid")  # 步数保持 8+3（蒸馏模型加步数收益低），质量靠帧数+关键帧
            uploaded = await self._upload_image(req.first_frame)
            replacements = {
                "CHECKPOINT": self.checkpoint,
                "TEXT_ENCODER": self.text_encoder,
                "INPUT_IMAGE": uploaded,
                "POSITIVE_PROMPT": prompt,
                "NEGATIVE_PROMPT": req.negative_prompt or _NEG,
                "FILENAME_PREFIX": f"engines/{req.output_name or 'clip'}",
                "FRAME_RATE": DEFAULT_FPS,
                "LENGTH": frames,
                "SEED": seed,
                "WIDTH_BASE": width,
                "HEIGHT_BASE": height,
            }
        else:
            template = self.load_workflow("t2vid")
            replacements = {
                "CHECKPOINT": self.checkpoint,
                "TEXT_ENCODER": self.text_encoder,
                "POSITIVE_PROMPT": prompt,
                "NEGATIVE_PROMPT": req.negative_prompt or _NEG,
                "FILENAME_PREFIX": f"engines/{req.output_name or 'clip'}",
                "FRAME_RATE": DEFAULT_FPS,
                "LENGTH": frames,
                "SEED": seed,
                "WIDTH_BASE": width,
                "HEIGHT_BASE": height,
            }

        workflow = self.fill_workflow(template, replacements)
        prompt_id = await self._submit(workflow)
        print(f"[ComfyUIEngine] 已提交 {prompt_id[:12]}… ({'I2V' if req.first_frame else 'T2V'}, {frames}f@{DEFAULT_FPS}fps)",
              flush=True)

        entry = await self._wait_result(prompt_id, timeout=req.timeout_seconds)
        found = self.find_output(entry.get("outputs", {}))
        if not found:
            raise EngineError("ComfyUI 无输出（可能静默失败，检查 strength/bypass_i2v 参数）")

        filename, subfolder, out_type = found
        out_dir = req.output_dir or (PROJECT_ROOT / "output" / "local_clips")
        out_dir.mkdir(parents=True, exist_ok=True)
        name = req.output_name or f"comfyui_{int(time.time())}"
        dest = out_dir / f"{name}.mp4"
        try:
            await self._download(filename, subfolder, out_type, dest)
        except Exception as exc:
            # 兼容 VHS 输出在 gifs 键但实际是 mp4 的情况
            raise EngineError(f"下载输出失败: {exc}") from exc

        if not dest.exists() or dest.stat().st_size < 10000:
            raise EngineError(f"输出文件缺失或过小: {dest}")

        return ClipResult(
            video_path=dest,
            engine=self.name,
            cost_usd=0.0,
            duration_seconds=round(frames / DEFAULT_FPS, 2),
            seed=seed,
            model=self.checkpoint,
        )

    def estimate_cost(self, req: GenerateRequest) -> float:
        return 0.0  # 本地电费不计入 API 成本

    # ─── 文生图（SDXL txt2img，生成关键帧）───────────────────
    async def generate_image(self, prompt: str,
                             width: int = 1080, height: int = 1920,
                             checkpoint: str = "animagine-xl-4.0.safetensors",
                             negative_prompt: str = "low quality, blurry, watermark, text",
                             output_dir: Optional[Path] = None,
                             output_name: str = "kf",
                             seed: Optional[int] = None) -> Path:
        """SDXL 文生图，用于生成场景关键帧。返回图片文件路径。"""
        if not self.is_available():
            raise EngineError(f"ComfyUI 不可达: {self.base_url}")
        template = self.load_workflow("txt2img")
        seed = seed if seed is not None else random.randint(0, 2**32 - 1)
        replacements = {
            "CHECKPOINT": checkpoint,
            "POSITIVE_PROMPT": prompt,
            "NEGATIVE_PROMPT": negative_prompt,
            "WIDTH": width, "HEIGHT": height, "SEED": seed,
        }
        workflow = self.fill_workflow(template, replacements)
        print(f"[ComfyUIEngine] 文生图: {checkpoint.split('/')[-1][:40]} {width}x{height} seed={seed}")
        prompt_id = await self._submit(workflow)
        entry = await self._wait_result(prompt_id, timeout=300.0)
        found = self.find_output(entry.get("outputs", {}))
        if not found:
            raise EngineError("文生图无输出")
        filename, subfolder, out_type = found
        out_dir = output_dir or (PROJECT_ROOT / "output" / "kf")
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{output_name}.png"
        await self._download(filename, subfolder, out_type, dest)
        if not dest.exists() or dest.stat().st_size < 1000:
            raise EngineError(f"图片输出缺失或过小: {dest}")
        return dest

