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


# ── 媒体样本（质量门依赖真实媒体流，见下方说明）────────────────────────
@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """现造一个 5 秒真实小视频（ffprobe 可探测时长）。

    为什么不用仓库里的现成素材：`OpenMontage/**`、`story2/**` 等大资产已移出 git 索引
    （磁盘保留但不入库），CI runner 上没有它们 → 相关测试"本地过、runner 挂"
    （2026-10-11 首次真跑 CI 实测 4 个失败）。自造样本后测试自给自足、平台无关。
    """
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("未安装 ffmpeg，无法生成样本视频")
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    proc = subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=5",
         "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        pytest.skip(f"ffmpeg 生成样本失败: {proc.stderr[-200:]}")
    return out


@pytest.fixture(scope="session")
def fake_video(tmp_path_factory) -> Path:
    """冒充视频的非媒体文件（质量门必须判不通过）。"""
    p = tmp_path_factory.mktemp("media") / "not_a_video.mp4"
    p.write_bytes(b"this is definitely not a video")
    return p
