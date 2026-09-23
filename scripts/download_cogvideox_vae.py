"""下载 CogVideoX VAE（411MB）到 ComfyUI 目录（走代理）。

用法：venv\\Scripts\\python.exe scripts\\download_cogvideox_vae.py
"""
import sys
import urllib.request
from pathlib import Path

DEST = Path(r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\CogVideo\VAE\cogvideox_vae.safetensors")
URL = "https://huggingface.co/Kijai/CogVideoX-Fun-pruned/resolve/main/cogvideox_vae.safetensors"
PROXY = "http://127.0.0.1:7897"


def main() -> int:
    if DEST.exists() and DEST.stat().st_size > 300_000_000:
        print(f"VAE 已存在: {DEST} ({DEST.stat().st_size/1e6:.0f}MB)")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".safetensors.part")
    print(f"下载 CogVideoX VAE → {DEST}")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    try:
        with opener.open(URL, timeout=60) as resp, open(tmp, "wb") as f:
            total = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                if total % (100 << 20) < (1 << 20):
                    print(f"  {total/1e6:.0f} MB ...")
        tmp.rename(DEST)
        print(f"✅ 完成: {DEST} ({DEST.stat().st_size/1e6:.0f}MB)")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 下载失败: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
