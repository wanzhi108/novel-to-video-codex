"""环境自检：把"缺包 / 缺 ffmpeg / ComfyUI 不可达 / 无模型 / 目录不可写 / 磁盘不足"
在启动阶段结构化暴露，而不是运行到一半才失败。

设计原则：
- 只依赖标准库（叶子模块），可被 CLI、launcher、main.py 复用；
- 区分 **fatal**（无法运行，如缺核心包、目录不可写）与 **warn**（可降级，如无 ComfyUI、无模型）；
- 网络探测使用极短超时（默认 2s）且失败不阻断。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

MIN_PYTHON = (3, 11)

# 核心依赖：缺失则视为致命（服务无法启动）
REQUIRED_PACKAGES = [
    "fastapi",      # Web 框架
    "uvicorn",      # ASGI 服务器
    "httpx",        # 出站 HTTP
    "multipart",    # python-multipart（表单/文件上传）
    "dotenv",       # python-dotenv
]

# 可选依赖：缺失只降级（提示 + 相应功能不可用）
OPTIONAL_PACKAGES = [
    "websockets",   # 前端进度推送
    "pydub",        # 音频处理
    "edge_tts",     # TTS 兜底
    "PIL",          # 图像处理（Pillow）
    "numpy",        # 数值/BGM
]

DEFAULT_COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")


@dataclass
class Check:
    name: str
    ok: bool
    level: str  # fatal | warn | info
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def fatal_failures(self) -> list[Check]:
        return [c for c in self.checks if c.level == "fatal" and not c.ok]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.level == "warn" and not c.ok]

    @property
    def ok(self) -> bool:
        return not self.fatal_failures


def _has_module(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def _check_python() -> Check:
    cur = sys.version_info[:2]
    ok = cur >= MIN_PYTHON
    return Check(
        "python", ok, "fatal",
        f"Python {sys.version.split()[0]}（要求 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}）"
        + ("" if ok else " —— 版本过低，请升级解释器"),
    )


def _check_package_group(name: str, mods: list[str], level: str) -> Check:
    missing = [m for m in mods if not _has_module(m)]
    if not missing:
        return Check(name, True, level, f"{len(mods)} 个依赖齐全")
    hint = "请执行: pip install -r requirements.txt"
    label = "缺失（致命）" if level == "fatal" else "缺失（功能降级）"
    return Check(name, False, level, f"{label}: {', '.join(missing)}；{hint}")


def _check_ffmpeg() -> Check:
    env_path = os.environ.get("FFMPEG_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return Check("ffmpeg", True, "warn", f"FFMPEG_PATH={env_path}")
    found = shutil.which("ffmpeg")
    if found:
        return Check("ffmpeg", True, "warn", f"PATH 中找到: {found}")
    candidates = [
        Path(os.environ.get("COMFYUI_PATH", "")) / "ffmpeg" / "ffmpeg.exe",
        Path("ComfyUI") / "ffmpeg" / "ffmpeg.exe",
    ]
    for c in candidates:
        try:
            if c.exists():
                return Check("ffmpeg", True, "warn", f"使用仓库内副本: {c}")
        except Exception:
            continue
    return Check("ffmpeg", False, "warn", "未找到 ffmpeg（合成/字幕/混音功能不可用）")


def _check_comfyui(url: str, timeout: float = 2.0) -> Check:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            ok = s.connect_ex((host, port)) == 0
        return Check(
            "comfyui", ok, "warn",
            f"{url} {'可达' if ok else '不可达（本地出片不可用，可先用 cloud 引擎）'}",
        )
    except Exception as e:  # 探测失败不应致命
        return Check("comfyui", False, "warn", f"{url} 探测失败: {e}")


def _check_models(models_dir: Path) -> Check:
    try:
        if not models_dir.exists():
            return Check("models", False, "warn", f"模型目录不存在: {models_dir}")
        hits = list(models_dir.rglob("*.safetensors")) + list(models_dir.rglob("*.gguf"))
        if hits:
            return Check("models", True, "warn", f"{models_dir} 下发现 {len(hits)} 个模型文件")
        return Check("models", False, "warn", f"{models_dir} 下未发现 .safetensors/.gguf 模型")
    except Exception as e:
        return Check("models", False, "warn", f"模型目录检查失败: {e}")


def _check_output_dir(output_dir: Path) -> Check:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = output_dir / ".health_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return Check("output_dir", True, "fatal", f"{output_dir} 可写")
    except Exception as e:
        return Check("output_dir", False, "fatal", f"{output_dir} 不可写: {e}")


def _check_tts_engines(check_network: bool = True, host: str = "127.0.0.1",
                       port: int = 50000, timeout: float = 1.5) -> Check:
    """配音引擎可用性：edge-tts（云端）/ Kokoro（本地包）/ CosyVoice2（本地服务 :50000）。

    配音决定成片"听感"，用户需要一眼看到当前在哪一档：
    - 仅 edge-tts：通用音色，多角色靠 voice_id 区分（去重逻辑见 app/voice_cast.py）；
    - CosyVoice2 就绪：音色克隆 + 情绪控制（电影级中文配音）。
    """
    edge = _has_module("edge_tts")
    kokoro = _has_module("kokoro_onnx")
    cv_ok = False
    if check_network:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                cv_ok = s.connect_ex((host, port)) == 0
        except Exception:
            cv_ok = False

    parts = [
        f"edge-tts {'✓' if edge else '✗（缺失，配音不可用）'}",
        f"kokoro {'✓' if kokoro else '✗'}",
        (f"CosyVoice2 :{port} " + ("✓ 就绪（音色克隆/情绪控制可用）" if cv_ok else "✗ 未就绪"))
        if check_network else f"CosyVoice2 :{port} 未探测",
    ]
    # edge-tts 缺失属安装不完整（致命）；其余引擎缺失只是降级
    return Check("tts_engines", edge, "fatal" if not edge else "warn", "；".join(parts))


def _check_disk(output_dir: Path, min_gb: float) -> Check:
    try:
        usage = shutil.disk_usage(str(output_dir))
        free_gb = usage.free / (1024 ** 3)
        return Check(
            "disk", free_gb >= min_gb, "warn",
            f"剩余 {free_gb:.1f} GB（建议 >= {min_gb:.0f} GB，单镜成片较大）",
        )
    except Exception as e:
        return Check("disk", False, "warn", f"磁盘检查失败: {e}")


def check_environment(
    *,
    output_dir=None,
    comfyui_url: str | None = None,
    models_dir=None,
    check_network: bool = True,
    min_disk_gb: float = 5.0,
) -> Report:
    """执行全部自检，返回结构化报告（不抛异常）。"""
    out = Path(output_dir) if output_dir else Path(os.environ.get("NOVEL2VID_OUTPUT_DIR", "output"))
    models = Path(models_dir) if models_dir else Path(
        os.environ.get("COMFYUI_MODELS_DIR", "") or "ComfyUI/models"
    )
    url = comfyui_url or DEFAULT_COMFYUI_URL

    checks = [
        _check_python(),
        _check_package_group("packages", REQUIRED_PACKAGES, "fatal"),
        _check_package_group("optional_packages", OPTIONAL_PACKAGES, "warn"),
        _check_ffmpeg(),
        _check_tts_engines(check_network),
        _check_output_dir(out),
        _check_disk(out, min_disk_gb),
        _check_models(models),
    ]
    if check_network:
        checks.append(_check_comfyui(url))
    else:
        checks.append(Check("comfyui", True, "info", "已跳过网络探测"))
    return Report(checks=checks)


def exit_code(report: Report) -> int:
    """致命项缺失 → 1；仅警告 → 0。"""
    return 1 if report.fatal_failures else 0


def format_report(report: Report) -> str:
    icon = {"fatal": "❌", "warn": "⚠️ ", "info": "ℹ️ "}
    lines = ["", "=" * 56, "  环境自检报告 (Environment Check)", "=" * 56]
    for c in report.checks:
        mark = "✅" if c.ok else icon.get(c.level, "❌")
        lines.append(f"  {mark} [{c.level:5}] {c.name:16} {c.detail}")
    lines.append("-" * 56)
    if report.fatal_failures:
        lines.append(f"  ❌ 致命问题 {len(report.fatal_failures)} 项 —— 服务无法正常启动，请先修复")
    elif report.warnings:
        lines.append(f"  ⚠️  警告 {len(report.warnings)} 项 —— 可运行，但部分功能会降级")
    else:
        lines.append("  ✅ 环境就绪")
    lines.append("=" * 56)
    return "\n".join(lines)
