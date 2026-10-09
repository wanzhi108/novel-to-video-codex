"""快速预览档（app/preview.py）回归测试。

目标：把"改一版先看节奏"从 ~8min/镜 降到分钟级 —— 通过**显式降档参数**实现，
且不得改变正式出片的默认参数（预览必须显式开启）。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BASE = {"width": 960, "height": 1728, "frames": 96, "fps": 24, "steps": 8,
        "upscale": True, "interpolate": True, "duration_seconds": 4.0}


def test_preview_module_api():
    from app import preview

    for name in ("PREVIEW_PROFILE", "build_overrides", "estimate_gain", "summarize"):
        assert hasattr(preview, name), f"app.preview 缺少 {name}"


def test_overrides_are_strictly_smaller_than_base():
    from app import preview

    ov = preview.build_overrides(BASE, enabled=True)
    assert ov, "预览档应产生覆盖项"
    assert set(ov) <= set(BASE), f"覆盖项不得引入 base 之外的键: {set(ov) - set(BASE)}"
    for key in ("width", "height", "frames", "steps"):
        assert key in ov, f"预览档应降低 {key}"
        assert ov[key] <= BASE[key] and ov[key] != BASE[key], f"{key} 未降档: {ov[key]}"
    assert ov.get("upscale") is False and ov.get("interpolate") is False


def test_disabled_returns_empty_overrides():
    from app import preview

    assert preview.build_overrides(BASE, enabled=False) == {}


def test_estimate_gain_shows_speedup():
    from app import preview

    gain = preview.estimate_gain(BASE)
    assert gain["pixels_ratio"] < 1.0, gain
    assert gain["frames_ratio"] < 1.0, gain
    assert gain["est_time_ratio"] < 1.0, gain
    assert "summary" in gain and gain["summary"]


def test_summarize_is_human_readable():
    from app import preview

    text = preview.summarize(BASE)
    assert "预览" in text and "%" in text


def test_settings_expose_preview_flag_default_off():
    from config.settings import EngineLocal

    assert EngineLocal().preview is False, "预览必须默认关闭，避免影响正式出片"


def test_settings_yaml_documents_preview():
    text = (ROOT / "settings.yaml").read_text(encoding="utf-8")
    assert "preview" in text, "settings.yaml 未暴露 preview 档位开关"
