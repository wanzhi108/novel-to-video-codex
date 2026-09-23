"""可行性检查：diffusers from_single_file 能否加载 RealVisXL (SDXL)。"""
import os, sys
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from diffusers import StableDiffusionXLPipeline

ckpt = r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\checkpoints\RealVisXL_V4.0.safetensors"
print("loading", ckpt, flush=True)
try:
    pipe = StableDiffusionXLPipeline.from_single_file(ckpt, torch_dtype="float32", local_files_only=True,
                                                      use_safetensors=True, variant=None)
    print("PIPE OK, unet cfg:", pipe.unet.config.in_channels, pipe.unet.config.sample_size, flush=True)
    print("has text_encoder2:", pipe.text_encoder_2 is not None, flush=True)
    print("vae cfg:", pipe.vae.config.sample_size, flush=True)
except Exception as e:
    print("FAIL:", type(e).__name__, str(e)[:500], flush=True)
