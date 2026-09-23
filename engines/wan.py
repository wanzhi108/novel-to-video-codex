"""本地 ComfyUI Wan 2.2 I2V-A14B 稳定引擎。

复用 engines/local.py 的 ComfyUIEngine HTTP 助手（上传/提交/轮询/下载），
把生成逻辑替换为 Wan 2.2 A14B 双专家 MoE 稳定管线：
  稳定采样(unipc/24步) -> RIFE 补帧(24->48fps) -> 4x-UltraSharp 超分。
适配 8GB 显存 / 16GB 内存：Q3_K_M 双专家 GGUF + fp8 umt5 + 块交换 + SageAttention。
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

from .base import ClipResult, EngineError, GenerateRequest
from .local import ComfyUIEngine

# Wan 2.2 A14B 双专家 + 组件（Q3_K_M 适配 16GB 内存）
WAN_HIGH = "Wan2.2-I2V-A14B-HighNoise-Q3_K_M.gguf"
WAN_LOW = "Wan2.2-I2V-A14B-LowNoise-Q3_K_M.gguf"
WAN_UMT5 = "umt5-xxl-enc-fp8_e4m3fn.safetensors"
WAN_VAE = r"wanvideo\Wan2_1_VAE_bf16.safetensors"
WAN_UPSCALE = "4x-UltraSharp.pth"
WAN_RIFE = "rife47.pth"

# 默认低分辨率（8GB 显存下稳定步道），上采样与补帧在后处理提升
DEFAULT_W, DEFAULT_H = 384, 672
DEFAULT_FRAME_RATE = 48   # RIFE 补帧后
DEFAULT_STEPS = 24
DEFAULT_BOUNDARY = 12     # MoE 边界：高噪[0,12)，低噪[12,24)

WAN_NEG = (
    "blurry, low quality, distorted, watermark, text, logo, jpeg artifacts, "
    "extra limbs, bad hands, deformed face, static, dark, flicker, jitter"
)


class WanEngine(ComfyUIEngine):
    """本地 ComfyUI Wan 2.2 I2V-A14B 稳定引擎。"""

    name = "wan_i2v"
    kind = "local"
    capability = "i2v"

    def __init__(self, base_url: str = "http://127.0.0.1:8188", lora: Optional[list] = None, **kw):
        super().__init__(base_url=base_url, **kw)
        self.wan_high = WAN_HIGH
        self.wan_low = WAN_LOW
        self.wan_umt5 = WAN_UMT5
        self.wan_vae = WAN_VAE
        self.wan_upscale = WAN_UPSCALE
        self.wan_rife = WAN_RIFE
        # 角色 LoRA 列表：[{"name": "xxx.safetensors", "strength": 0.8}, ...]
        # GGUF 模型强制 merge_loras=False（按需加载，不能合并）。
        self.lora = lora or []

    def describe(self) -> str:
        return "本地 Wan 2.2 I2V-A14B（双专家 MoE + 稳定采样 + RIFE 补帧 + 4x 超分）"

    # ─── 构建 Wan 稳定工作流 ────────────────────────────────
    def _build_wan_workflow(self, req: GenerateRequest, seed: int, frames: int,
                            width: int, height: int, uploaded: str, ref_uploaded: Optional[str] = None):
        prompt = req.prompt
        # I2V：忠于首帧角色/构图，加微动约束
        prompt = (prompt + ". locked camera, subtle micro motion, keep first frame "
                  "composition and character identity").strip()
        boundary = DEFAULT_BOUNDARY
        wf = {
            "vae": {"class_type": "WanVideoVAELoader", "inputs": {"model_name": self.wan_vae, "precision": "bf16"}},
            "t5": {"class_type": "LoadWanVideoT5TextEncoder", "inputs": {
                "model_name": self.wan_umt5, "precision": "bf16",
                "load_device": "offload_device", "quantization": "disabled"}},
            "tenc": {"class_type": "WanVideoTextEncode", "inputs": {
                "t5": ["t5", 0], "positive_prompt": prompt,
                "negative_prompt": req.negative_prompt or WAN_NEG, "device": "cpu", "use_disk_cache": True}},
            "img": {"class_type": "LoadImage", "inputs": {"image": uploaded}},
            "ienc": {"class_type": "WanVideoImageToVideoEncode", "inputs": {
                "vae": ["vae", 0], "start_image": ["img", 0], "width": width, "height": height,
                "num_frames": frames, "noise_aug_strength": 0.0,
                "start_latent_strength": 0.7, "end_latent_strength": 1.0, "force_offload": True}},
            "bs": {"class_type": "WanVideoBlockSwap", "inputs": {
                "blocks_to_swap": 40, "offload_img_emb": True, "offload_txt_emb": True,
                "use_non_blocking": False, "prefetch_blocks": 1}},
            "mh": {"class_type": "WanVideoModelLoader", "inputs": {
                "model": self.wan_high, "base_precision": "fp16_fast", "quantization": "disabled",
                "load_device": "offload_device", "attention_mode": "sageattn"}},
            "ml": {"class_type": "WanVideoModelLoader", "inputs": {
                "model": self.wan_low, "base_precision": "fp16_fast", "quantization": "disabled",
                "load_device": "offload_device", "attention_mode": "sageattn"}},
            "sbs_h": {"class_type": "WanVideoSetBlockSwap", "inputs": {"model": ["mh", 0], "block_swap_args": ["bs", 0]}},
            "sbs_l": {"class_type": "WanVideoSetBlockSwap", "inputs": {"model": ["ml", 0], "block_swap_args": ["bs", 0]}},
        }
        # 参考图强化（角色一致性）：若提供 reference image，用 CLIP-vision 编码后作为 clip_embeds 附加条件
        if ref_uploaded:
            wf["cvl"] = {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}}
            wf["refimg"] = {"class_type": "LoadImage", "inputs": {"image": ref_uploaded}}
            wf["clipenc"] = {"class_type": "WanVideoClipVisionEncode", "inputs": {
                "clip_vision": ["cvl", 0], "image_1": ["refimg", 0], "strength_1": 1.0,
                "strength_2": 1.0, "crop": "center", "combine_embeds": "average", "force_offload": True}}
            wf["ienc"]["inputs"]["clip_embeds"] = ["clipenc", 0]
        # 若配置了角色 LoRA，在块交换后串联 WanVideoSetLoRAs（GGUF 强制 merge_loras=False）
        high_model_ref, low_model_ref = ("sbs_h", 0), ("sbs_l", 0)
        if self.lora:
            high_model_ref = self._chain_lora(wf, "sbs_h", 0, "h")
            low_model_ref = self._chain_lora(wf, "sbs_l", 0, "l")
        wf["sh"] = {"class_type": "WanVideoSampler", "inputs": {
            "model": [high_model_ref[0], high_model_ref[1]], "image_embeds": ["ienc", 0], "text_embeds": ["tenc", 0],
            "steps": DEFAULT_STEPS, "cfg": 5.0, "shift": 8.0, "seed": seed, "force_offload": True,
            "scheduler": "unipc", "riflex_freq_index": 0, "start_step": 0, "end_step": boundary}}
        wf["sl"] = {"class_type": "WanVideoSampler", "inputs": {
            "model": [low_model_ref[0], low_model_ref[1]], "image_embeds": ["ienc", 0], "text_embeds": ["tenc", 0],
            "samples": ["sh", 0], "steps": DEFAULT_STEPS, "cfg": 3.0, "shift": 8.0, "seed": seed,
            "force_offload": True, "scheduler": "unipc", "riflex_freq_index": 0,
            "start_step": boundary, "end_step": -1}}
        wf["dec"] = {"class_type": "WanVideoDecode", "inputs": {
            "vae": ["vae", 0], "samples": ["sl", 0], "enable_vae_tiling": True,
            "tile_x": 272, "tile_y": 272, "tile_stride_x": 128, "tile_stride_y": 128}}
        wf["upm"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": self.wan_upscale}}
        wf["rife"] = {"class_type": "RIFE VFI", "inputs": {
            "ckpt_name": self.wan_rife, "frames": ["dec", 0], "clear_cache_after_n_frames": 10,
            "multiplier": 2, "fast_mode": True, "ensemble": True, "scale_factor": 1.0}}
        wf["up"] = {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["upm", 0], "image": ["rife", 0]}}
        wf["vid"] = {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["up", 0], "frame_rate": DEFAULT_FRAME_RATE,
            "filename_prefix": f"engines/{req.output_name or 'wan_clip'}",
            "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 19,
            "save_output": True, "loop_count": 0, "pingpong": False, "save_metadata": False}}
        return wf

    def _chain_lora(self, wf: dict, model_node: str, slot: int, tag: str):
        """在模型节点后串联配置的 LoRA，返回 (最后节点key, 0)。"""
        cur = (model_node, slot)
        prev_lora = None
        for i, lora in enumerate(self.lora):
            lora_key = f"lorasel_{tag}{i}"
            inputs = {"lora": lora["name"], "strength": float(lora.get("strength", 1.0)),
                      "merge_loras": False}  # GGUF 不能合并
            if prev_lora is not None:
                inputs["prev_lora"] = prev_lora
            wf[lora_key] = {"class_type": "WanVideoLoraSelect", "inputs": inputs}
            set_key = f"setlora_{tag}{i}"
            wf[set_key] = {"class_type": "WanVideoSetLoRAs",
                           "inputs": {"model": [cur[0], cur[1]], "lora": [lora_key, 0]}}
            cur = (set_key, 0)
            prev_lora = [lora_key, 0]
        return cur

    # ─── 生成（覆盖 ComfyUIEngine.generate）────────────────
    async def generate(self, req: GenerateRequest) -> ClipResult:
        if not self.is_available():
            raise EngineError(f"ComfyUI 不可达: {self.base_url}（请确认已启动 --lowvram）")
        if req.first_frame is None:
            raise EngineError("WanEngine 仅支持 I2V：需提供 first_frame 关键帧")

        seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
        width = req.width or DEFAULT_W
        height = req.height or DEFAULT_H
        # 8GB 显存稳定：3s 上限（帧数转 24fps 基准）
        frames = int(min(max(req.duration_seconds, 1.0), 3.0) * 24)
        frames = max(frames, 33)
        frames = min(frames, 81)

        uploaded = await self._upload_image(req.first_frame)
        ref_uploaded = None
        if req.reference_images:
            ref_uploaded = await self._upload_image(req.reference_images[0])
        workflow = self._build_wan_workflow(req, seed, frames, width, height, uploaded, ref_uploaded)
        prompt_id = await self._submit(workflow)
        print(f"[WanEngine] 已提交 {prompt_id[:12]}… (I2V {width}x{height} {frames}f, seed={seed}, "
              f"ref={'yes' if ref_uploaded else 'no'})", flush=True)

        entry = await self._wait_result(prompt_id, timeout=max(req.timeout_seconds, 2400))
        found = self.find_output(entry.get("outputs", {}))
        if not found:
            raise EngineError("Wan 工作流无输出（可能静默失败，检查模型/节点）")

        filename, subfolder, out_type = found
        out_dir = req.output_dir or (Path(__file__).resolve().parent.parent / "output" / "wan_clips")
        out_dir.mkdir(parents=True, exist_ok=True)
        name = req.output_name or f"wan_{int(__import__('time').time())}"
        dest = out_dir / f"{name}.mp4"
        await self._download(filename, subfolder, out_type, dest)
        if not dest.exists() or dest.stat().st_size < 10000:
            raise EngineError(f"Wan 输出文件缺失或过小: {dest}")

        return ClipResult(
            video_path=dest,
            engine=self.name,
            cost_usd=0.0,
            duration_seconds=round(frames / 24, 2),  # 采样基准；实际已是 48fps 超分
            seed=seed,
            model=f"{self.wan_high.split('-')[0]}..A14B",
        )

    def estimate_cost(self, req: GenerateRequest) -> float:
        return 0.0

    # ─── 批处理：一次加载双专家，多镜头共享模型逐段采样 ─────────
    def _add_shot_branch(self, wf: dict, tag: str, uploaded: str, ref_uploaded: Optional[str],
                         prompt: str, negative: str, seed: int, frames: int, width: int, height: int):
        """向 wf 追加一个镜头分支；返回 vid 节点 key。模型/编码器/块交换为共享节点。"""
        wf[f"img_{tag}"] = {"class_type": "LoadImage", "inputs": {"image": uploaded}}
        wf[f"tenc_{tag}"] = {"class_type": "WanVideoTextEncode", "inputs": {
            "t5": ["t5", 0], "positive_prompt": prompt, "negative_prompt": negative, "device": "cpu"}}
        ienc = {"class_type": "WanVideoImageToVideoEncode", "inputs": {
            "vae": ["vae", 0], "start_image": [f"img_{tag}", 0], "width": width, "height": height,
            "num_frames": frames, "noise_aug_strength": 0.0,
            "start_latent_strength": 0.7, "end_latent_strength": 1.0, "force_offload": True}}
        if ref_uploaded:
            wf[f"refimg_{tag}"] = {"class_type": "LoadImage", "inputs": {"image": ref_uploaded}}
            wf[f"clipenc_{tag}"] = {"class_type": "WanVideoClipVisionEncode", "inputs": {
                "clip_vision": ["cvl", 0], "image_1": [f"refimg_{tag}", 0], "strength_1": 1.0,
                "strength_2": 1.0, "crop": "center", "combine_embeds": "average", "force_offload": True}}
            ienc["inputs"]["clip_embeds"] = [f"clipenc_{tag}", 0]
        wf[f"ienc_{tag}"] = ienc
        wf[f"sh_{tag}"] = {"class_type": "WanVideoSampler", "inputs": {
            "model": ["sbs_h", 0], "image_embeds": [f"ienc_{tag}", 0], "text_embeds": [f"tenc_{tag}", 0],
            "steps": DEFAULT_STEPS, "cfg": 5.0, "shift": 8.0, "seed": seed, "force_offload": True,
            "scheduler": "unipc", "riflex_freq_index": 0, "start_step": 0, "end_step": DEFAULT_BOUNDARY}}
        wf[f"sl_{tag}"] = {"class_type": "WanVideoSampler", "inputs": {
            "model": ["sbs_l", 0], "image_embeds": [f"ienc_{tag}", 0], "text_embeds": [f"tenc_{tag}", 0],
            "samples": [f"sh_{tag}", 0], "steps": DEFAULT_STEPS, "cfg": 3.0, "shift": 8.0, "seed": seed,
            "force_offload": True, "scheduler": "unipc", "riflex_freq_index": 0,
            "start_step": DEFAULT_BOUNDARY, "end_step": -1}}
        wf[f"dec_{tag}"] = {"class_type": "WanVideoDecode", "inputs": {
            "vae": ["vae", 0], "samples": [f"sl_{tag}", 0], "enable_vae_tiling": True,
            "tile_x": 272, "tile_y": 272, "tile_stride_x": 128, "tile_stride_y": 128}}
        wf[f"rife_{tag}"] = {"class_type": "RIFE VFI", "inputs": {
            "ckpt_name": self.wan_rife, "frames": [f"dec_{tag}", 0], "clear_cache_after_n_frames": 10,
            "multiplier": 2, "fast_mode": True, "ensemble": True, "scale_factor": 1.0}}
        wf[f"up_{tag}"] = {"class_type": "ImageUpscaleWithModel", "inputs": {
            "upscale_model": ["upm", 0], "image": [f"rife_{tag}", 0]}}
        wf[f"vid_{tag}"] = {"class_type": "VHS_VideoCombine", "inputs": {
            "images": [f"up_{tag}", 0], "frame_rate": DEFAULT_FRAME_RATE,
            "filename_prefix": f"engines/{tag}", "format": "video/h264-mp4", "pix_fmt": "yuv420p",
            "crf": 19, "save_output": True, "loop_count": 0, "pingpong": False, "save_metadata": False}}
        return f"vid_{tag}"

    async def generate_batch(self, shots: list[dict], output_dir: Optional[Path] = None,
                             width: int = DEFAULT_W, height: int = DEFAULT_H,
                             duration_seconds: float = 2.0, base_seed: Optional[int] = None,
                             timeout: float = 3600.0) -> list[ClipResult]:
        """shots: list of {first_frame:Path, prompt:str, reference_image?:Path, output_name:str}。
        一次加载双专家模型与共享节点，多镜头共享模型逐段采样并各自输出稳定超分片。"""
        if not self.is_available():
            raise EngineError(f"ComfyUI 不可达: {self.base_url}")
        if not shots:
            return []
        frames = int(min(max(duration_seconds, 1.0), 3.0) * 24)
        frames = max(frames, 33); frames = min(frames, 81)

        # 上传所有起始帧 + 参考图
        ups = []
        any_ref = False
        for s in shots:
            u = await self._upload_image(Path(s["first_frame"]))
            ru = None
            if s.get("reference_image"):
                ru = await self._upload_image(Path(s["reference_image"]))
                any_ref = True
            ups.append((u, ru))

        wf = {
            "vae": {"class_type": "WanVideoVAELoader", "inputs": {"model_name": self.wan_vae, "precision": "bf16"}},
            "t5": {"class_type": "LoadWanVideoT5TextEncoder", "inputs": {
                "model_name": self.wan_umt5, "precision": "bf16", "load_device": "offload_device", "quantization": "disabled"}},
            "bs": {"class_type": "WanVideoBlockSwap", "inputs": {
                "blocks_to_swap": 40, "offload_img_emb": True, "offload_txt_emb": True,
                "use_non_blocking": False, "prefetch_blocks": 1}},
            "mh": {"class_type": "WanVideoModelLoader", "inputs": {
                "model": self.wan_high, "base_precision": "fp16_fast", "quantization": "disabled",
                "load_device": "offload_device", "attention_mode": "sageattn"}},
            "ml": {"class_type": "WanVideoModelLoader", "inputs": {
                "model": self.wan_low, "base_precision": "fp16_fast", "quantization": "disabled",
                "load_device": "offload_device", "attention_mode": "sageattn"}},
            "sbs_h": {"class_type": "WanVideoSetBlockSwap", "inputs": {"model": ["mh", 0], "block_swap_args": ["bs", 0]}},
            "sbs_l": {"class_type": "WanVideoSetBlockSwap", "inputs": {"model": ["ml", 0], "block_swap_args": ["bs", 0]}},
            "upm": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": self.wan_upscale}},
        }
        if any_ref:
            wf["cvl"] = {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}}

        vid_keys = []
        for i, s in enumerate(shots):
            u, ru = ups[i]
            tag = s.get("output_name", f"shot{i:02d}")
            seed = (base_seed if base_seed is not None else random.randint(0, 2**32 - 1)) + i
            vid = self._add_shot_branch(wf, tag, u, ru, s["prompt"], s.get("negative_prompt", WAN_NEG),
                                        seed, frames, width, height)
            vid_keys.append((tag, vid))

        prompt_id = await self._submit(wf)
        print(f"[WanEngine] 批处理已提交 {prompt_id[:12]}… ({len(shots)} 镜头共享一次模型加载)", flush=True)
        entry = await self._wait_result(prompt_id, timeout=max(timeout, 3600))
        outputs = entry.get("outputs", {})

        out_dir = output_dir or (Path(__file__).resolve().parent.parent / "output" / "wan_clips")
        out_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for tag, vid in vid_keys:
            node_out = outputs.get(vid, {})
            f = self.find_output(node_out)
            if not f:
                print(f"  ⚠ {tag}: 无输出", flush=True)
                continue
            filename, subfolder, out_type = f
            dest = out_dir / f"{tag}.mp4"
            await self._download(filename, subfolder, out_type, dest)
            if dest.exists() and dest.stat().st_size >= 10000:
                results.append(ClipResult(video_path=dest, engine=self.name, cost_usd=0.0,
                                          duration_seconds=round(frames / 24, 2), model="wan_a14b"))
        return results
