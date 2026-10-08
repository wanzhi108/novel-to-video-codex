"""验证配置驱动的本地引擎路由：应选中 Wan 5B。"""
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(_ROOT))
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
