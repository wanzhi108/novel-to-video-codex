"""前端「速度档位」契约与产物新鲜度守卫。

背景（2026-10-09 实测）：Settings 页原来把 launcher 配置同步放在
`/api/update-settings` 之后且在同一个 try 里 —— 而该接口是**任务级**的（需要 job_id），
本页无任务上下文必定 422，异常被 catch 吞掉后 launcher 同步被连带跳过，
导致速度开关（以及既有的 auto_cosyvoice）点了"同步到后端"却存不上。

本测试把两条契约固化下来：
1. launcher 配置同步必须**先于**生成参数同步，且各自独立 try/catch；
2. 已构建的 web/dist 产物必须包含新接口调用（防止改了 src 忘记重新构建）。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS_TSX = ROOT / "web" / "src" / "pages" / "Settings.tsx"
DIST = ROOT / "web" / "dist"


def test_launcher_config_sync_precedes_task_level_settings():
    src = SETTINGS_TSX.read_text(encoding="utf-8")
    save = src[src.index("handleSaveToBackend"):]
    save = save[: save.index("return (")]
    i_launcher = save.index("updateLauncherConfig")
    i_settings = save.index("updateSettings")
    assert i_launcher < i_settings, "launcher 配置同步必须先执行（任务级接口失败时不能连带跳过）"


def test_speed_toggles_are_sent_to_launcher_config():
    src = SETTINGS_TSX.read_text(encoding="utf-8")
    assert "preview: settings.preview" in src, "预览档未提交到 launcher 配置"
    assert "cache_enabled: settings.cacheEnabled" in src, "资产缓存未提交到 launcher 配置"


def test_settings_page_reads_speed_profile():
    src = SETTINGS_TSX.read_text(encoding="utf-8")
    assert "getSpeedProfile" in src, "设置页未读取 /api/speed-profile（收益提示缺失）"
    api_ts = (ROOT / "web" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "/api/speed-profile" in api_ts, "api 封装未定义速度档位接口"


def test_built_dist_contains_speed_profile_call():
    """产物新鲜度：dist 由 src 构建而来，必须能看到新接口。"""
    assets = sorted((DIST / "assets").glob("*.js"))
    assert assets, "web/dist/assets 下没有构建产物"
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in assets)
    assert "/api/speed-profile" in blob, "dist 过旧：请重新执行 web/ 下的 npm run build"
    assert re.search(r"资产缓存", blob), "dist 中缺少速度档位文案（疑似未重新构建）"
