"""验证 video_engine 集成：wan5b 模式注册 + 智能路由默认 wan5b。"""
import sys
sys.path.insert(0, r"D:\novel-to-video-codex")

class FakeScene:
    id = 1
    description = "男主角在雨夜霓虹街头，特写"
    camera = "close-up, 缓慢推进"
    shot_size = "特写"
    characters = "男主角"
    video_prompt = "close-up of a young man in neon rain, subtle micro motion"

class FakeJob:
    video_mode = "local"
    use_dual_frame = False
    use_multi_shot = False
    use_wan21 = False
    use_ken_burns = False

import importlib
try:
    ve = importlib.import_module("scripts.video_engine")
except Exception:
    from scripts import video_engine as ve

print("has _wan5b =", hasattr(ve, "_wan5b"))
print("has Wan5B import path =", "wan5b" in ve.VIDEO_MODES)
print("_classify('wan5b'?) =", ve._classify_scene_video_mode(FakeScene(), FakeJob()))
print("VIDEO_MODES keys =", sorted(ve.VIDEO_MODES.keys()))
