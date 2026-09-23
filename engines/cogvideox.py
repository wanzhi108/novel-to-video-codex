"""CogVideoX 本地引擎（轻量视频模型，16GB RAM 友好）。

基于 ComfyUI-CogVideoXWrapper 节点，T2V 工作流：
  DownloadAndLoadCogVideoModel → CLIPLoader(T5) → CogVideoTextEncode(正/负)
  → EmptyLatentImage → CogVideoSampler → CogVideoDecode → VHS_VideoCombine

主模型由节点自动下载（首次运行触发），T5/VAE 用本地已有文件。

用法：
    from engines.cogvideox import CogVideoXEngine
    eng = CogVideoXEngine()
    clip = await eng.generate(req)   # T2V（暂不支持 I2V，后续加）
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Optional

import httpx

from .base import BaseEngine, ClipResult, EngineError, GenerateRequest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 节点参数（与 ComfyUI-CogVideoXWrapper 对齐）
MODEL_2B = "THUDM/CogVideoX-2b"          # 2b 轻量版（16GB RAM 友好）
T5_CLIP = "t5xxl_fp8_e4m3fn.safetensors"  # 本地 text_encoders 已有
DEFAULT_STEPS = 30                        # 降低步数加速（默认 50）
DEFAULT_CFG = 6.0
DEFAULT_FRAMES = 49                       # CogVideoX 默认 49 帧
DEFAULT_FPS = 8                           # CogVideoX 原生 8fps


class CogVideoXEngine(BaseEngine):
    """CogVideoX 2b T2V 引擎（ComfyUI 后端）。"""

    name = "cogvideox"
    kind = "local"
    capability = "t2v"

    def __init__(self, base_url: str = "http://127.0.0.1:8188",
                 model: str = MODEL_2B, steps: int = DEFAULT_STEPS):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.steps = steps

    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                return client.get(f"{self.base_url}/system_stats").status_code == 200
        except Exception:
            return False

    def _build_workflow(self, prompt: str, negative: str, seed: int,
                        width: int, height: int, frames: int,
                        filename_prefix: str) -> dict:
        """构造 ComfyUI API 格式 T2V 工作流。"""
        return {
            "36": {"class_type": "DownloadAndLoadCogVideoModel",
                   "inputs": {"model": self.model, "precision": "bf16",
                              "quantization": "disabled",
                              "enable_sequential_cpu_offload": False,
                              "attention_mode": "sdpa", "load_device": "main_device"}},
            "20": {"class_type": "CLIPLoader",
                   "inputs": {"clip_name": T5_CLIP, "type": "sd3"}},
            "30": {"class_type": "CogVideoTextEncode",
                   "inputs": {"clip": ["20", 0], "prompt": prompt,
                              "strength": 1.0, "force_offload": True}},
            "31": {"class_type": "CogVideoTextEncode",
                   "inputs": {"clip": ["20", 0], "prompt": negative,
                              "strength": 1.0, "force_offload": True}},
            "37": {"class_type": "EmptyLatentImage",
                   "inputs": {"width": width, "height": height, "batch_size": 1}},
            "35": {"class_type": "CogVideoSampler",
                   "inputs": {"model": ["36", 0], "positive": ["30", 0],
                              "negative": ["31", 0], "num_frames": frames,
                              "steps": self.steps, "cfg": DEFAULT_CFG, "seed": seed,
                              "scheduler": "CogVideoXDDIM", "denoise_strength": 1.0,
                              "samples": ["37", 0]}},
            "11": {"class_type": "CogVideoDecode",
                   "inputs": {"vae": ["36", 1], "samples": ["35", 0],
                              "enable_vae_tiling": True, "tile_sample_min_height": 240,
                              "tile_sample_min_width": 360,
                              "tile_overlap_factor_height": 0.2,
                              "tile_overlap_factor_width": 0.2,
                              "auto_tile_size": True}},
            "33": {"class_type": "VHS_VideoCombine",
                   "inputs": {"images": ["11", 0], "frame_rate": DEFAULT_FPS,
                              "loop_count": 0, "filename_prefix": filename_prefix,
                              "format": "video/h264-mp4", "pix_fmt": "yuv420p",
                              "crf": 19, "save_metadata": True, "pingpong": False,
                              "save_output": True}},
        }

    async def generate(self, req: GenerateRequest) -> ClipResult:
        if not self.is_available():
            raise EngineError(f"ComfyUI 不可达: {self.base_url}")
        if req.first_frame is not None:
            raise EngineError("CogVideoXEngine 当前仅支持 T2V（first_frame=None）")
        seed = req.seed if req.seed is not None else random.randint(0, 2**31)
        width = req.width or 720
        height = req.height or 480
        frames = int(min(max(req.duration_seconds, 1.0), 8.0) * DEFAULT_FPS)
        frames = max(frames, 25)
        prefix = f"cogvideox/{req.output_name or 'clip'}"

        workflow = self._build_workflow(
            prompt=req.prompt, negative=req.negative_prompt or "blurry, low quality",
            seed=seed, width=width, height=height, frames=frames, filename_prefix=prefix)
        payload = json.dumps({"prompt": workflow}, ensure_ascii=False).encode("utf-8")
        print(f"[CogVideoX] 提交 T2V: {width}x{height} {frames}f/{self.steps}steps "
              f"model={self.model}", flush=True)

        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            r = await client.post(f"{self.base_url}/prompt", content=payload,
                                  headers={"Content-Type": "application/json"})
            if r.status_code != 200:
                raise EngineError(f"ComfyUI 提交失败 {r.status_code}: {r.text[:300]}")
            prompt_id = r.json()["prompt_id"]

        entry = await self._wait(prompt_id, req.timeout_seconds)
        found = self._find_output(entry.get("outputs", {}))
        if not found:
            raise EngineError("CogVideoX 无输出")
        filename, subfolder, out_type = found
        out_dir = req.output_dir or (PROJECT_ROOT / "output" / "cogvideox")
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{req.output_name or 'clip'}.mp4"
        async with httpx.AsyncClient(timeout=900, trust_env=False) as client:
            resp = await client.get(f"{self.base_url}/view",
                                    params={"filename": filename, "subfolder": subfolder,
                                            "type": out_type})
            if resp.status_code != 200:
                raise EngineError(f"下载输出失败: HTTP {resp.status_code}")
            dest.write_bytes(resp.content)
        return ClipResult(video_path=dest, engine=self.name, seed=seed,
                          duration_seconds=round(frames / DEFAULT_FPS, 2), model=self.model)

    async def _wait(self, prompt_id: str, timeout: float) -> dict:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            start = time.time()
            while time.time() - start < timeout:
                r = await client.get(f"{self.base_url}/history/{prompt_id}")
                if r.status_code == 200:
                    data = r.json()
                    if prompt_id in data and data[prompt_id]["status"].get("completed"):
                        return data[prompt_id]
                    if data.get(prompt_id, {}).get("status", {}).get("status_str") == "error":
                        raise EngineError("ComfyUI 执行失败")
                import asyncio
                await asyncio.sleep(3)
        raise EngineError(f"超时 {timeout}s")

    @staticmethod
    def _find_output(outputs: dict):
        for key in ("gifs", "videos", "images"):
            for node, val in (outputs or {}).items():
                if isinstance(val, dict) and key in val and val[key]:
                    it = val[key][0]
                    if isinstance(it, dict) and "filename" in it:
                        return it["filename"], it.get("subfolder", ""), it.get("type", "output")
        return None

    def estimate_cost(self, req: GenerateRequest) -> float:
        return 0.0
