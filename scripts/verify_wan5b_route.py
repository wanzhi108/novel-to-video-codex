"""验证配置驱动的本地引擎路由：应选中 Wan 5B。"""
import sys
sys.path.insert(0, r"D:\novel-to-video-codex")
from config.settings import load_settings
from engines.registry import EngineRouter

s = load_settings()
print("cloud.video_mode =", s.engines.cloud.video_mode)
print("local.local_kind =", s.engines.local.local_kind)
r = EngineRouter.from_settings()
print("router.video_mode =", r.video_mode)
print("router.local_kind =", r.local_kind)
local = r._get_local()
print("local engine name =", getattr(local, "name", "?"))
print("is_available =", local.is_available())
