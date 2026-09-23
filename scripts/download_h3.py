"""下载 MiniMax H3 官方模型文件到 ComfyUI 目录（官方 ComfyUI 配置，INT8 低显存）。

来源：Comfy-Org/MiniMax-H3（HuggingFace），走代理（HTTP_PROXY/HTTPS_PROXY）。
支持断点续传（已存在且大小>1MB 则跳过）。

用法：venv\\Scripts\\python.exe scripts\\download_h3.py
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

# ComfyUI 模型根目录
MODELS_DIR = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models")
HF_BASE = "https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main"

# (仓库内相对路径, 本地相对 models/ 路径)
FILES = [
    ("diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
     "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
    ("text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
     "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    ("vae/minimax_h3_video_vae_fp16.safetensors",
     "vae/minimax_h3_video_vae_fp16.safetensors"),
    ("vae/minimax_h3_audio_vae_fp32.safetensors",
     "vae/minimax_h3_audio_vae_fp32.safetensors"),
    ("loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
     "loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"),
]

PROXY = "http://127.0.0.1:7897"


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  跳过(已存在 {dest.stat().st_size/1e9:.1f}GB): {dest.name}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  下载: {dest.name} ...")
    proxy_handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        with opener.open(url, timeout=60) as resp, open(tmp, "wb") as f:
            total = 0
            while True:
                chunk = resp.read(1 << 20)  # 1MB
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                if total % (50 << 20) < (1 << 20):
                    print(f"    {total/1e9:.1f} GB ...")
        tmp.rename(dest)
        print(f"  ✅ {dest.name} ({dest.stat().st_size/1e9:.2f} GB)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ {dest.name}: {exc}")
        return False


def main() -> int:
    if not MODELS_DIR.exists():
        print(f"模型目录不存在: {MODELS_DIR}")
        return 1
    print(f"下载 MiniMax H3 模型 → {MODELS_DIR}")
    print(f"代理: {PROXY}\n")
    failed = []
    for hf_path, local_rel in FILES:
        url = f"{HF_BASE}/{hf_path}"
        dest = MODELS_DIR / local_rel
        if not download(url, dest):
            failed.append(local_rel)
    print(f"\n完成: {len(FILES)-len(failed)}/{len(FILES)} 成功")
    if failed:
        print("失败项:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
