"""Wan2.2 I2V A14B MoE 双专家 GGUF 测试（WanVideoWrapper 两段式：高噪专家[0,P] -> 低噪专家[P,N]）。
适配 8GB VRAM / 16GB RAM：Q3_K_M GGUF + fp8 umt5 + 块交换 + SageAttention。"""
import os
import json, urllib.request, uuid, glob
from pathlib import Path

BASE = "http://127.0.0.1:8188"
HIGH = "Wan2.2-I2V-A14B-HighNoise-Q3_K_M.gguf"
LOW  = "Wan2.2-I2V-A14B-LowNoise-Q3_K_M.gguf"
UMT5 = "umt5-xxl-enc-fp8_e4m3fn.safetensors"
VAE  = r"wanvideo\Wan2_1_VAE_bf16.safetensors"
PROMPT = ("a young man in a rain-soaked cyberpunk street at night, cinematic neon lighting, "
          "close-up, sharp details, high quality, film grain")
NEG = ("blurry, low quality, distorted, watermark, text, logo, jpeg artifacts, "
       "extra limbs, bad hands, deformed face, static, dark")
W, H, FRAMES = 384, 672, 33
STEPS, BOUNDARY = 24, 12  # 高噪专家[0,12)，低噪专家[12,24)

def upload_image(path):
    with open(path, "rb") as f:
        b = uuid.uuid4().hex
        body = b""
        body += f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{Path(path).name}\"\r\nContent-Type: image/png\r\n\r\n".encode()
        body += f.read()
        body += f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(f"{BASE}/upload/image", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        r = urllib.request.urlopen(req, timeout=60)
        return json.loads(r.read())["name"]

kf = glob.glob(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\*\scene_001_shot1.png"))
img = kf[0] if kf else r"D:\ComfyUI-WorkFisher-V2\ComfyUI\input\scene_001_shot1.png"
up = upload_image(img)
print("首帧上传:", up)

prompt = {
    "vae": {"class_type": "WanVideoVAELoader", "inputs": {"model_name": VAE, "precision": "bf16"}},
    "t5": {"class_type": "LoadWanVideoT5TextEncoder", "inputs": {
        "model_name": UMT5, "precision": "bf16", "load_device": "offload_device", "quantization": "disabled"}},
    "tenc": {"class_type": "WanVideoTextEncode", "inputs": {
        "t5": ["t5", 0], "positive_prompt": PROMPT, "negative_prompt": NEG, "device": "cpu"}},
    "img": {"class_type": "LoadImage", "inputs": {"image": up}},
    "ienc": {"class_type": "WanVideoImageToVideoEncode", "inputs": {
        "vae": ["vae", 0], "start_image": ["img", 0],
        "width": W, "height": H, "num_frames": FRAMES,
        "noise_aug_strength": 0.0, "start_latent_strength": 0.7, "end_latent_strength": 1.0,
        "force_offload": True}},
    "bs": {"class_type": "WanVideoBlockSwap", "inputs": {
        "blocks_to_swap": 40, "offload_img_emb": True, "offload_txt_emb": True,
        "use_non_blocking": False, "prefetch_blocks": 1}},
    "mh": {"class_type": "WanVideoModelLoader", "inputs": {
        "model": HIGH, "base_precision": "fp16_fast", "quantization": "disabled",
        "load_device": "offload_device", "attention_mode": "sageattn"}},
    "ml": {"class_type": "WanVideoModelLoader", "inputs": {
        "model": LOW, "base_precision": "fp16_fast", "quantization": "disabled",
        "load_device": "offload_device", "attention_mode": "sageattn"}},
    "sbs_h": {"class_type": "WanVideoSetBlockSwap", "inputs": {"model": ["mh", 0], "block_swap_args": ["bs", 0]}},
    "sbs_l": {"class_type": "WanVideoSetBlockSwap", "inputs": {"model": ["ml", 0], "block_swap_args": ["bs", 0]}},
    "sh": {"class_type": "WanVideoSampler", "inputs": {
        "model": ["sbs_h", 0], "image_embeds": ["ienc", 0], "text_embeds": ["tenc", 0],
        "steps": STEPS, "cfg": 5.0, "shift": 8.0, "seed": 12345, "force_offload": True,
        "scheduler": "unipc", "riflex_freq_index": 0, "start_step": 0, "end_step": BOUNDARY}},
    "sl": {"class_type": "WanVideoSampler", "inputs": {
        "model": ["sbs_l", 0], "image_embeds": ["ienc", 0], "text_embeds": ["tenc", 0],
        "samples": ["sh", 0],
        "steps": STEPS, "cfg": 3.0, "shift": 8.0, "seed": 12345, "force_offload": True,
        "scheduler": "unipc", "riflex_freq_index": 0, "start_step": BOUNDARY, "end_step": -1}},
    "dec": {"class_type": "WanVideoDecode", "inputs": {
        "vae": ["vae", 0], "samples": ["sl", 0], "enable_vae_tiling": True,
        "tile_x": 272, "tile_y": 272, "tile_stride_x": 128, "tile_stride_y": 128}},
    # ---- 后处理：RIFE 补帧(24→48fps) + 4x 超分，削除闪烁/抖动、恢复线条 ----
    "upm": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
    "rife": {"class_type": "RIFE VFI", "inputs": {
        "ckpt_name": "rife47.pth", "frames": ["dec", 0], "clear_cache_after_n_frames": 10,
        "multiplier": 2, "fast_mode": True, "ensemble": True, "scale_factor": 1.0}},
    "up": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["upm", 0], "image": ["rife", 0]}},
    "vid": {"class_type": "VHS_VideoCombine", "inputs": {
        "images": ["up", 0], "frame_rate": 48, "filename_prefix": "Wan22_I2V_A14B_stable",
        "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 19,
        "save_output": True, "loop_count": 0, "pingpong": False, "save_metadata": False}},
}

payload = {"prompt": prompt}
req = urllib.request.Request(f"{BASE}/prompt", data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"})
try:
    r = urllib.request.urlopen(req, timeout=30)
    resp = json.loads(r.read())
    print("✅ 提交成功 prompt_id:", resp.get("prompt_id"))
except Exception as e:
    body = e.read().decode() if hasattr(e, "read") else str(e)
    print("提交失败:", body[:800])
