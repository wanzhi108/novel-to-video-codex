"""架构收敛第一阶段：安全能力下沉到 `app/security.py` 的回归测试。

动机：`scripts/main.py` 已达 1.2 万行，安全纯函数混在路由中无法单测、也无法被
其它入口（launcher / cosyvoice2 / pipeline CLI）复用。本模块把纯函数抽到
`app/security.py`，`main.py` 只保留注入与调用。
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_security_module_exposes_pure_helpers():
    from app import security

    for name in (
        "safe_media_path",
        "read_upload_capped",
        "safe_upload_name",
        "redact_secrets",
        "sanitize_imported_paths",
        "host_is_trusted",
        "origin_is_trusted",
        "set_media_roots",
    ):
        assert hasattr(security, name), f"app.security 缺少 {name}"


def test_security_module_has_no_project_internal_imports():
    """security 必须是叶子模块：只依赖标准库 + fastapi，避免循环导入。"""
    src = (ROOT / "app" / "security.py").read_text(encoding="utf-8")
    bad = re.findall(r'^\s*(?:from|import)\s+(scripts|app\.(?!security)|engines|pipeline|config)\b', src, re.M)
    assert not bad, f"app/security.py 引入了项目内部模块：{bad}"


def test_safe_media_path_blocks_outside_roots(tmp_path):
    from app import security
    from fastapi import HTTPException

    security.set_media_roots([tmp_path])
    with pytest.raises(HTTPException) as e:
        security.safe_media_path(r"C:\Windows\win.ini")
    assert e.value.status_code == 403


def test_safe_media_path_allows_inside_roots(tmp_path):
    from app import security

    security.set_media_roots([tmp_path])
    f = tmp_path / "ok.txt"
    f.write_text("ok", encoding="utf-8")
    assert security.safe_media_path(str(f)).exists()


def test_safe_upload_name_sanitizes_traversal():
    from app import security

    assert security.safe_upload_name("..\\..\\evil.png") == "evil.png"
    assert security.safe_upload_name("../../evil.mp3") == "evil.mp3"
    assert security.safe_upload_name("") == "upload.bin"


def test_redact_secrets_masks_keys_recursively():
    from app import security

    out = security.redact_secrets(
        {"deepseek_key": "sk-x", "nested": {"api_key": "sk-y", "keep": 1}, "list": [{"api_key": "sk-z"}]}
    )
    assert out["deepseek_key"] == ""
    assert out["nested"]["api_key"] == "" and out["nested"]["keep"] == 1
    assert out["list"][0]["api_key"] == ""


def test_host_and_origin_rules():
    from app import security

    assert security.host_is_trusted("127.0.0.1:8190") is True
    assert security.host_is_trusted("192.168.1.102:8190") is True
    assert security.host_is_trusted("evil.example.com") is False
    assert security.origin_is_trusted("http://evil.example.com") is False
    assert security.origin_is_trusted("null") is True


def test_main_reuses_security_module():
    """main.py 应引用 app.security，且不再本地重复定义这些函数。"""
    src = (ROOT / "scripts" / "main.py").read_text(encoding="utf-8")
    assert "from app.security import" in src, "main.py 未引用 app.security"
    for name in ("safe_media_path", "read_upload_capped", "safe_upload_name", "redact_secrets"):
        assert f"def {name}(" not in src, f"main.py 仍本地定义 {name}()"
