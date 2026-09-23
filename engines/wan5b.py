"""本地 ComfyUI Wan 2.2 TI2V-5B 轻量 I2V 引擎（单模型非 MoE，专为低显存）。

两段式加固：16GB 内存下 4x 模型超分会在 umt5(6.27GB)+5B(3.5GB) 驻留时 OOM。
故拆成两个 ComfyUI prompt：
  1) sample+decode → 存基础分辨率视频（24fps，不超分）
  2) 加载该视频 → RIFE 补帧(48fps) → 4x UltraSharp 超分 → 合成
第二段不再加载 umt5/5B，ComfyUI lowvram 会将其卸载 → 超分时内存充足，不再 OOM。
"""
from __future__ import annotations

import random, shutil
from pathlib import Path
from typing import Optional

from .base import ClipResult, EngineError, GenerateRequest
from .local import ComfyUIEngine

WAN5B = "Wan2.2-TI2V-5B-Q5_K_M.gguf"
WAN5B_VAE = "Wan2.2_VAE.safetensors"
WAN_UMT5 = "umt5-xxl-enc-fp8_e4m3fn.safetensors"
WAN_UPSCALE = "4x-UltraSharp.pth"
WAN_RIFE = "rife47.pth"
COMFY_INPUT = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input")

DEFAULT_FRAME_RATE = 48
DEFAULT_STEPS = 30
WAN_NEG = ("blurry, low quality, distorted, watermark, text, logo, jpeg artifacts, "
           "extra limbs, bad hands, deformed face, static, dark, flicker, jitter")


class Wan5BEngine(ComfyUIEngine):
    """本地 ComfyUI Wan 2.2 TI2V-5B 轻量 I2V 引擎（两段式，内存安全）。"""

    name = "wan5b"
    kind = "local"
    capability = "i2v"

    def __init__(self, base_url: str = "http://127.0.0.1:8188", lora: Optional[list] = None, **kw):
        super().__init__(base_url=base_url, **kw)
        self.wan5b = WAN5B
        self.wan5b_vae = WAN5B_VAE
        self.lora = lora or []

    def describe(self) -> str:
        return "本地 Wan 2.2 TI2V-5B（轻量单模型 + 稳定采样 + 两段式 RIFE补帧+4x超分）"

    # ─── 第一段：采样 + 解码 + 存基础分辨率视频（不超分，避免模型驻留 OOM） ───
    def _build_workflow(self, req, seed, frames, width, height, uploaded):
        prompt = (req.prompt + ". locked camera, subtle micro motion, keep first frame "
                  "composition and character identity").strip()
        wf = {
            "vae": {"class_type": "WanVideoVAELoader", "inputs": {"model_name": self.wan5b_vae, "precision": "bf16"}},
            "t5": {"class_type": "LoadWanVideoT5TextEncoder", "inputs": {
                "model_name": WAN_UMT5, "precision": "bf16", "load_device": "offload_device", "quantization": "disabled"}},
            "tenc": {"class_type": "WanVideoTextEncode", "inputs": {
                "t5": ["t5", 0], "positive_prompt": prompt,
                "negative_prompt": req.negative_prompt or WAN_NEG, "device": "cpu", "use_disk_cache": True}},
            "img": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
            "rimg": {"class_type": "ImageResizeKJv2", "inputs": {
                "image": ["img", 0], "width": width, "height": height, "upscale_method": "lanczos",
                "keep_proportion": "stretch", "pad_color": "0, 0, 0", "crop_position": "center",
                "divisible_by": 16}},
            "ienc": {"class_type": "WanVideoEncode", "inputs": {
                "vae": ["vae", 0], "image": ["rimg", 0], "enable_vae_tiling": True,
                "tile_x": 272, "tile_y": 272, "tile_stride_x": 128, "tile_stride_y": 128}},
            "iem": {"class_type": "WanVideoEmptyEmbeds", "inputs": {
                "width": width, "height": height, "num_frames": frames, "extra_latents": ["ienc", 0]}},
            "bs": {"class_type": "WanVideoBlockSwap", "inputs": {
                "blocks_to_swap": 30, "offload_img_emb": True, "offload_txt_emb": True,
                "use_non_blocking": False, "prefetch_blocks": 1}},
            "m": {"class_type": "WanVideoModelLoader", "inputs": {
                "model": self.wan5b, "base_precision": "fp16_fast", "quantization": "disabled",
                "load_device": "offload_device", "attention_mode": "sageattn"}},
            "sbs": {"class_type": "WanVideoSetBlockSwap", "inputs": {"model": ["m", 0], "block_swap_args": ["bs", 0]}},
            "sh": {"class_type": "WanVideoSampler", "inputs": {
                "model": ["sbs", 0], "image_embeds": ["iem", 0], "text_embeds": ["tenc", 0],
                "steps": DEFAULT_STEPS, "cfg": 5.0, "shift": 8.0, "seed": seed, "force_offload": True,
                "scheduler": "flowmatch_pusa", "riflex_freq_index": 0, "start_step": 0, "end_step": -1}},
            "dec": {"class_type": "WanVideoDecode", "inputs": {
                "vae": ["vae", 0], "samples": ["sh", 0], "enable_vae_tiling": True,
                "tile_x": 272, "tile_y": 272, "tile_stride_x": 128, "tile_stride_y": 128}},
            "vid": {"class_type": "VHS_VideoCombine", "inputs": {
                "images": ["dec", 0], "frame_rate": 24,
                "filename_prefix": f"engines/{req.output_name or 'wan5b'}_base",
                "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 19,
                "save_output": True, "loop_count": 0, "pingpong": False, "save_metadata": False}},
        }
        return wf

    # ─── 第二段：加载基础视频 → RIFE 补帧 → 2x 缩放 → 合成（不加载 umt5/5B）。
    # 4x 模型超分(ImageUpscaleWithModel) 会一次性分配整个输出批（90帧 2816x5120 ≈ 15.4GB）
    # 在 16GB 机上必然 OOM；改用 ImageScaleBy 逐帧缩放，低内存、稳定。
    def _build_post_workflow(self, req, base_video_abs):
        wf = {
            "load": {"class_type": "VHS_LoadVideo", "inputs": {
                "video": base_video_abs, "force_rate": 24, "custom_width": 0, "custom_height": 0,
                "frame_load_cap": 0, "skip_first_frames": 0, "select_every_nth": 1}},
            "rife": {"class_type": "RIFE VFI", "inputs": {
                "ckpt_name": WAN_RIFE, "frames": ["load", 0], "clear_cache_after_n_frames": 10,
                "multiplier": 2, "fast_mode": True, "ensemble": True, "scale_factor": 1.0}},
            "up": {"class_type": "ImageScaleBy", "inputs": {
                "image": ["rife", 0], "upscale_method": "lanczos", "scale_by": 2.0}},
            "vid": {"class_type": "VHS_VideoCombine", "inputs": {
                "images": ["up", 0], "frame_rate": DEFAULT_FRAME_RATE,
                "filename_prefix": f"engines/{req.output_name or 'wan5b'}",
                "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 19,
                "save_output": True, "loop_count": 0, "pingpong": False, "save_metadata": False}},
        }
        return wf

    async def generate(self, req: GenerateRequest) -> ClipResult:
        if not self.is_available():
            raise EngineError(f"ComfyUI 不可达: {self.base_url}")
        if req.first_frame is None:
            raise EngineError("Wan5BEngine 仅支持 I2V：需提供 first_frame")
        seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
        width = req.width or 704
        height = req.height or 1280
        frames = int(min(max(req.duration_seconds, 1.0), 4.0) * 24)
        frames = max(frames, 33); frames = min(frames, 97)

        # 第一段：采样+解码 → 基础视频
        uploaded = await self._upload_image(req.first_frame)
        wf = self._build_workflow(req, seed, frames, width, height, uploaded)
        prompt_id = await self._submit(wf)
        print(f"[Wan5B] 已提交 {prompt_id[:12]}… (I2V {width}x{height} {frames}f, seed={seed})", flush=True)
        entry = await self._wait_result(prompt_id, timeout=max(req.timeout_seconds, 2400))
        found = self.find_output(entry.get("outputs", {}))
        if not found:
            raise EngineError("Wan 5B 工作流无输出（采样段）")
        bfile, bsub, btype = found
        out_dir = req.output_dir or (Path(__file__).resolve().parent.parent / "output" / "wan5b_clips")
        out_dir.mkdir(parents=True, exist_ok=True)
        base_local = out_dir / f"{(req.output_name or 'wan5b')}_base.mp4"
        await self._download(bfile, bsub, btype, base_local)
        if not base_local.exists() or base_local.stat().st_size < 10000:
            raise EngineError(f"Wan 5B 基础视频缺失或过小: {base_local}")

        # 复制基础视频到 ComfyUI input 目录，供第二段加载
        COMFY_INPUT.mkdir(parents=True, exist_ok=True)
        base_input = COMFY_INPUT / f"{(req.output_name or 'wan5b')}_base.mp4"
        shutil.copyfile(base_local, base_input)

        # 第二段：加载 → RIFE → 4x 超分 → 合成（不加载 umt5/5B，内存充足）
        pwf = self._build_post_workflow(req, str(base_input))
        pid2 = await self._submit(pwf)
        print(f"[Wan5B] 超分段已提交 {pid2[:12]}…", flush=True)
        entry2 = await self._wait_result(pid2, timeout=max(req.timeout_seconds, 2400))
        found2 = self.find_output(entry2.get("outputs", {}))
        if not found2:
            raise EngineError("Wan 5B 工作流无输出（超分段）")
        f2, s2, t2 = found2
        dest = out_dir / f"{(req.output_name or 'wan5b')}.mp4"
        await self._download(f2, s2, t2, dest)
        if not dest.exists() or dest.stat().st_size < 10000:
            raise EngineError(f"Wan 5B 输出缺失或过小: {dest}")
        return ClipResult(video_path=dest, engine=self.name, cost_usd=0.0,
                          duration_seconds=round(frames / 24, 2), seed=seed, model=self.wan5b)

    def estimate_cost(self, req: GenerateRequest) -> float:
        return 0.0
