"""GenerationGate 视觉门集成测试：真静态/冻结产物触发视觉门 → 重试换引擎。

用单帧图生成的静止视频（首尾帧相同）作为"真静态"样本，验证视觉门抓出
并触发 switch_engine 重试。
"""
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base import BaseEngine, ClipResult, GenerateRequest  # noqa: E402
from engines.quality_loop import GenerationGate  # noqa: E402
from quality.gate import QualityGate  # noqa: E402
from quality.visual import assess_video  # noqa: E402

GOOD_CLIP = Path("output/story2_final_0829.mp4")
KF = Path("story2/shot_01_kf.png")


def make_static_clip(out: Path) -> Path:
    """用单帧 loop 生成 2s 静止视频（首尾帧相同）。"""
    subprocess.run([shutil.which("ffmpeg"), "-y", "-loop", "1", "-t", "2", "-i", str(KF),
                    "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
                   capture_output=True, timeout=60)
    return out


class MockEngine(BaseEngine):
    def __init__(self, name, clip):
        self.name = name
        self.clip = clip
        self.calls = 0

    async def generate(self, req):
        self.calls += 1
        return ClipResult(video_path=self.clip, engine=self.name, seed=req.seed or 1)


async def main():
    if not GOOD_CLIP.exists() or not KF.exists():
        print("跳过（缺素材）")
        return
    static = make_static_clip(Path("output/visual_gate_static.mp4"))
    print("静态样本视觉判定:", assess_video(static).get("issues"))

    static_engine = MockEngine("static_maker", static)
    good_engine = MockEngine("good_maker", GOOD_CLIP)
    gate = GenerationGate([static_engine, good_engine], QualityGate(),
                          visual_gate=assess_video)
    req = GenerateRequest(prompt="test", duration_seconds=5.0)
    clip = await gate.generate(req)

    assert good_engine.calls == 1, f"应换到 good_engine: {good_engine.calls}"
    assert clip.engine == "good_maker"
    assert clip.quality_report["passed"] is True
    first = [h for h in clip.quality_report["retry_history"] if h["engine"] == "static_maker"]
    assert first and first[0].get("issues"), f"视觉门应记录 issues: {first}"
    print(f"✅ 视觉门集成: 真静态段被拒 → 换引擎成功")
    print(f"   static_maker issues: {first[0]['issues']}")
    print("VISUAL_GATE TEST OK")


if __name__ == "__main__":
    asyncio.run(main())
