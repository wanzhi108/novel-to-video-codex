"""安全纯函数（叶子模块）——架构收敛第一阶段。

从 `scripts/main.py`（1.2 万行）下沉：路径包含性校验、上传限额与文件名清洗、
凭据脱敏、来源（Host/Origin）校验。下沉后这些能力可被 launcher、cosyvoice2、
pipeline CLI 复用，并可独立单测。

约定：**只依赖标准库与 fastapi，不 import 任何项目内部模块**（防循环依赖）；
媒体根目录与上传上限由调用方注入或经环境变量提供。
"""
from __future__ import annotations

import ipaddress
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile

# ── 媒体路径白名单 ─────────────────────────────────────────
_MEDIA_ROOTS: list[Path] = [Path(tempfile.gettempdir()).resolve()]
for _r in os.environ.get("NOVEL2VID_MEDIA_ROOTS", "").split(os.pathsep):
    if _r.strip():
        _MEDIA_ROOTS.append(Path(_r.strip()).resolve())


def set_media_roots(roots: Iterable) -> None:
    """由主程序在确定输出目录后注入允许的媒体根目录（始终包含系统临时目录）。"""
    global _MEDIA_ROOTS
    resolved = [Path(r).resolve() for r in roots if r]
    tmp = Path(tempfile.gettempdir()).resolve()
    if tmp not in resolved:
        resolved.append(tmp)
    _MEDIA_ROOTS = resolved


def media_roots() -> list[Path]:
    return list(_MEDIA_ROOTS)


def safe_media_path(p, label: str = "文件") -> Path:
    """把媒体路径限制在允许的根目录内（防目录穿越 / 任意文件读取）。"""
    if not p:
        raise HTTPException(404, f"{label}不存在")
    try:
        rp = Path(str(p)).resolve()
    except Exception:
        raise HTTPException(400, f"{label}路径非法")
    for root in _MEDIA_ROOTS:
        try:
            if rp == root or rp.is_relative_to(root):
                return rp
        except Exception:
            continue
    raise HTTPException(403, f"禁止访问该路径: {label}")


# ── 上传限额 ───────────────────────────────────────────────
MAX_UPLOAD_MB = int(os.environ.get("NOVEL2VID_MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def set_upload_limit(max_mb: int) -> None:
    global MAX_UPLOAD_MB, MAX_UPLOAD_BYTES
    MAX_UPLOAD_MB = int(max_mb)
    MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


async def read_upload_capped(file: UploadFile, label: str = "文件") -> bytes:
    """分块读取上传内容，超过上限直接 413。"""
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{label}超过上限 {MAX_UPLOAD_MB}MB")
        chunks.append(chunk)
    return b"".join(chunks)


def safe_upload_name(filename: str, fallback: str = "upload.bin") -> str:
    """取纯文件名并清洗，防上传文件名目录穿越（如 ..\\..\\x.png）。"""
    name = Path(str(filename or "")).name.replace("\\", "_").replace("/", "_").strip()
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    if not name or name in (".", ".."):
        return fallback
    return name


# ── 凭据脱敏 ───────────────────────────────────────────────
_SENSITIVE_KEYS = ("deepseek_key", "api_key")


def redact_secrets(data, sensitive_keys: tuple = _SENSITIVE_KEYS):
    """递归清除对外响应中的凭据字段（API Key 不外泄）。"""
    if isinstance(data, dict):
        return {
            k: ("" if k in sensitive_keys else redact_secrets(v, sensitive_keys))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_secrets(v, sensitive_keys) for v in data]
    return data


# ── 导入数据路径清洗 ───────────────────────────────────────
def _looks_like_unsafe_path(v) -> bool:
    """判断导入数据中的路径是否可疑（绝对路径 / 上级目录穿越）。"""
    if not isinstance(v, str) or not v.strip():
        return False
    s = v.strip()
    if s.startswith("\\\\") or s.startswith("//"):
        return True
    if len(s) > 1 and s[1] == ":":  # C:\... / D:/...
        return True
    return ".." in s.replace("/", "\\").split("\\")


def sanitize_imported_paths(data: dict) -> dict:
    """导入外部任务时清掉可疑本地路径，避免其被当作媒体文件读取。"""
    if not isinstance(data, dict):
        return data
    for k in ("pulid_reference_image", "merged_video_path", "reference_image"):
        if _looks_like_unsafe_path(data.get(k)):
            data[k] = None
    for sc in data.get("scenes") or []:
        if isinstance(sc, dict):
            for k in ("image_path", "video_path", "final_video_path", "audio_path"):
                if _looks_like_unsafe_path(sc.get(k)):
                    sc[k] = None
    return data


# ── 来源校验（CSRF / DNS rebinding）─────────────────────────
_TRUSTED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}
for _h in os.environ.get("NOVEL2VID_TRUSTED_HOSTS", "").split(","):
    if _h.strip():
        _TRUSTED_HOSTS.add(_h.strip().lower())


def _hostname(raw: str) -> str:
    """从 Host / Origin 值取主机名（去端口，兼容 IPv6 中括号）。"""
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        return raw.split("]")[0] + "]"
    return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw


def _is_private_literal(host: str) -> bool:
    """回环 / 私有网段 / link-local 的字面 IP（域名不算，防 DNS rebinding）。"""
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:
        return False


def host_is_trusted(raw: str) -> bool:
    h = _hostname(raw)
    return h in _TRUSTED_HOSTS or _is_private_literal(h)


def origin_is_trusted(origin: str) -> bool:
    """Origin 为 null（file:// 页面）时不据此判定，交由 Host 判定。"""
    o = (origin or "").strip().lower()
    if not o or o == "null":
        return True
    try:
        return host_is_trusted(urlparse(o).netloc)
    except Exception:
        return False
