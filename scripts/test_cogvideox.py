"""CogVideoX 引擎冒烟测试：T2V 生成一段短视频。

首次运行会触发主模型 THUDM/CogVideoX-2b 自动下载（~5GB，走 ComfyUI 进程代理）。
用法：venv\\Scripts\\python.exe scripts\\test_cogvideox.py
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engines.cogvideox import CogVideoXEngine  # noqa: E402
from engines.base import GenerateRequest  # noqa: E402


async def main() -> int:
    eng = CogVideoXEngine()
    if not eng.is_available():
        print("ComfyUI 不可达")
        return 1
    req = GenerateRequest(
        prompt="a cat walking across a wooden table in a cozy room, warm sunlight, cinematic, slow motion",
        negative_prompt="blurry, low quality, distorted",
        width=720, height=480,
        duration_seconds=6.0,   # 49 帧 @8fps
        output_dir=Path("output/cogvideox"),
        output_name="smoke_cogvideox",
        timeout_seconds=1800.0,  # 首次含模型下载，放宽
    )
    print(f"[CogVideoX] 提交 T2V 测试（首次含模型下载，可能 10-30 分钟）...")
    t0 = time.time()
    try:
        clip = await eng.generate(req)
    except Exception as exc:  # noqa: BLE001
        print(f"[CogVideoX] ❌ 失败: {exc}")
        return 1
    print(f"[CogVideoX] ✅ 完成: {clip.video_path} ({time.time()-t0:.0f}s, "
          f"{clip.duration_seconds}s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
