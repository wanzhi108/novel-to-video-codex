"""quality/visual 测试：无参考画质评估（清晰度/黑帧/模糊检测）。"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quality.visual import (  # noqa: E402
    assess_frame, assess_video, brightness, is_black, sharpness, DEFAULT_SHARPNESS_MIN)


def main():
    # 1. 用真实关键帧图测清晰度（story2 关键帧，应该锐利）
    kf = Path("story2/shot_01_kf.png")
    if kf.exists():
        s = sharpness(kf)
        b = brightness(kf)
        print(f"关键帧: sharpness={s:.0f} brightness={b:.0f} black={is_black(kf)}")
        assert s > DEFAULT_SHARPNESS_MIN, f"关键帧应锐利: {s}"

    # 2. 纯色图（应该低清晰度/疑似模糊）
    from PIL import Image
    import tempfile
    import numpy as np
    tmp = Path(tempfile.mkdtemp(prefix="vqtest_"))
    flat = tmp / "flat.png"
    Image.fromarray(np.full((100, 100, 3), 128, dtype=np.uint8)).save(flat)
    s_flat = sharpness(flat)
    print(f"纯色图: sharpness={s_flat:.0f}（应远低于关键帧）")
    assert s_flat < s, "纯色图清晰度应更低"

    # 3. 纯黑图（黑帧检测）
    black = tmp / "black.png"
    Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8)).save(black)
    assert is_black(black), "纯黑应判为黑帧"
    print("✅ 单帧评估: 锐利图/纯色图/黑帧 判定正确")

    # 4. 真实视频抽帧评估（smoke_render）
    clip = Path("output/local_clips/smoke_render.mp4")
    if clip.exists():
        vq = assess_video(clip)
        print(f"视频画质: {vq}")
        assert "passed" in vq

    shutil.rmtree(tmp, ignore_errors=True)
    print("VISUAL TEST OK")


if __name__ == "__main__":
    main()
