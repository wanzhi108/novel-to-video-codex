"""共享测试夹具（conftest）。

统一约定：
- `client`：TestClient 基址固定为可信回环地址 —— CSRF/Host 守卫会拒绝默认的 `testserver`。
- `app_module`：被测 FastAPI 应用模块。
- `multipart_bytes`：multipart/form-data 请求体构造器（上传类接口复用）。
"""
import io
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def app_module():
    import main  # noqa: WPS433 - 被测应用

    return main


@pytest.fixture()
def client(app_module):
    from fastapi.testclient import TestClient

    return TestClient(app_module.app, base_url="http://127.0.0.1:8190")


def _build_multipart(fields: dict, filename: str | None = None, content: bytes = b"{}"):
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    if filename is not None:
        out.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/json\r\n\r\n'.encode()
            + content
            + b"\r\n"
        )
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


@pytest.fixture()
def multipart():
    """返回 multipart 构造器：multipart(fields, filename=..., content=...) -> (body, content_type)。"""
    return _build_multipart
