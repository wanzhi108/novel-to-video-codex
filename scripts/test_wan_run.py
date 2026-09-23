"""Wan 2.2 GGUF I2V（ImageToVideoEncode 不带 clip_embeds，同官方模板）。"""
import os
import json
import urllib.request
from pathlib import Path
import uuid

BASE = "http://127.0.0.1:8188"


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


import glob
kf = glob.glob(os.path.expanduser(r"~\AppData\Local\Programs\LuminaForge\output\cfb52fe4\scene_001\*.png"))
img = upload_image(kf[0]) if kf else None
print("首帧上传:", img)

prompt = {
    "1": {"class_type": "WanVideoModelLoader", "inputs": {
        "model": "Wan2.2-Animate-14B-Q4_K_M.gguf",
        "base_precision": "fp16_fast", "quantization": "disabled", "load_device": "offload_device"}},
    "2": {"class_type": "WanVideoVAELoader", "inputs": {"model_name": r"wanvideo\Wan2_1_VAE_bf16.safetensors", "precision": "bf16"}},
    # Wan T5 文本编码加载器（输出 WANTEXTENCODER）
    "10": {"class_type": "LoadWanVideoT5TextEncoder", "inputs": {"model_name": "umt5-xxl-enc-bf16.safetensors", "precision": "bf16", "load_device": "offload_device", "quantization": "disabled"}},
    "3": {"class_type": "WanVideoTextEncode", "inputs": {
        "t5": ["10", 0], 
        "positive_prompt": "a cat walking on rainy street at night, cinematic, moody",
        "negative_prompt": "blurry, low quality, distorted, watermark", "device": "cpu"}},
    # I2V：不带 clip_embeds（同官方模板），只带 vae + start_image + 尺寸
    "4": {"class_type": "WanVideoImageToVideoEncode", "inputs": {
        "vae": ["2", 0], "start_image": ["5", 0],
        "width": 672, "height": 480, "num_frames": 33,
        "noise_aug_strength": 0.0, "start_latent_strength": 0.0, "end_latent_strength": 0.0,
        "force_offload": False}},
    "5": {"class_type": "LoadImage", "inputs": {"image": img}},
    "6": {"class_type": "WanVideoSampler", "inputs": {
        "model": ["1", 0], "image_embeds": ["4", 0], "text_embeds": ["3", 0],
        "steps": 20, "cfg": 5.0, "shift": 8.0, "seed": 12345, "force_offload": False,
        "scheduler": "dpm++_sde", "riflex_freq_index": 0}},
    "8": {"class_type": "WanVideoDecode", "inputs": {
        "vae": ["2", 0], "samples": ["6", 0], "enable_vae_tiling": True,
        "tile_x": 256, "tile_y": 256, "tile_stride_x": 128, "tile_stride_y": 128}},
    "9": {"class_type": "VHS_VideoCombine", "inputs": {
        "images": ["8", 0], "frame_rate": 16, "filename_prefix": "Wan22_test",
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
    print("提交失败:", body[:500])
