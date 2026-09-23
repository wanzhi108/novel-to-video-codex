"""Orchestrator.run_storyboard 测试：DeepSeek 分镜（走代理，真实调用）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import Orchestrator  # noqa: E402
from pipeline.storyboard import get_deepseek_key  # noqa: E402

NOVEL = (
    "被辞退那天，我写的代码卖了八千万。\n"
    "七月的午后，老板王总把方案摔在桌上：\"小杨，你这方案，狗都不要。明天不用来了。\"\n"
    "所有人都觉得，小杨完了。\n"
    "小杨默默收拾东西：\"好，我走。但我写的算法，已经留在服务器上了。\"\n"
    "没人当真。可那行代码，三个月后值八千万。\n"
    "三个月后的招标会，王总瞪大了眼睛：\"这……这中标的是你？！\"\n"
    "小杨淡淡地说：\"王总，您亲口说的，狗都不要的方案。\"\n"
)


def test_parse_duration():
    orch = Orchestrator()
    assert orch._parse_duration("5") == 5.0
    assert orch._parse_duration("6s") == 6.0
    assert orch._parse_duration("5秒") == 5.0
    print("✅ 时长解析: '5'/'5s'/'5秒' → 5.0")


async def test_run_storyboard():
    key = get_deepseek_key()
    if not key:
        print("⚠️ 无 DEEPSEEK key，跳过真实分镜")
        return
    orch = Orchestrator()
    reqs = await orch.run_storyboard(NOVEL, title="被辞退那天", api_key=key, max_scenes=6)
    assert len(reqs) >= 4, f"期望 ≥4 个场景: {len(reqs)}"
    for r in reqs:
        assert r.prompt, f"场景 {r.id} 缺 prompt"
        assert r.duration_seconds > 0
    print(f"✅ run_storyboard: {len(reqs)} 个场景（DeepSeek 分镜，含英文 prompt）")
    print(f"   示例: {reqs[0].prompt[:60]}...")


if __name__ == "__main__":
    import asyncio
    test_parse_duration()
    asyncio.run(test_run_storyboard())
    print("STORYBOARD TEST OK")
