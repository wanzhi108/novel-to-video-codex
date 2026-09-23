"""无参考画质评估（质量门 L2 增强，纯 Pillow+numpy，无重依赖）。

针对"画面糊/黑帧/静止"三大视觉问题提供可量化指标：
  - sharpness  : Laplacian 方差近似（边缘强度方差），越低越糊
  - brightness : 平均亮度，过低=黑帧/灰暗
  - is_black   : 黑帧检测
  - motion     : 相邻抽帧差异（0=完全静止，异常低值=疑似动画/静态图）

不依赖 insightface/onnxruntime，可作为质量门的快速视觉层。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

# 经验阈值（可调，按实际视频标定）
DEFAULT_SHARPNESS_MIN = 40.0    # 低于此值疑似模糊（Laplacian 方差）
DEFAULT_BLACK_THRESHOLD = 15.0  # 平均亮度低于此视为黑帧
DEFAULT_MOTION_MIN = 0.5        # 相邻抽帧归一化差异低于此疑似静态


def _load_gray(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)


def sharpness(path) -> float:
    """Laplacian 方差（numpy 手动实现，避免 PIL FIND_EDGES 的 uint8 溢出伪影）。"""
    a = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
    lap = (np.roll(a, 1, axis=0) + np.roll(a, -1, axis=0)
           + np.roll(a, 1, axis=1) + np.roll(a, -1, axis=1) - 4 * a)
    return float(lap.var())


def brightness(path) -> float:
    """平均亮度 [0,255]。"""
    return float(_load_gray(path).mean())


def is_black(path, threshold: float = DEFAULT_BLACK_THRESHOLD) -> bool:
    return brightness(path) < threshold


def _extract_frame(video_path, t: float, tmp_dir) -> str:
    import shutil
    import subprocess
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    out = tmp_dir / f"frame_{t:.2f}.jpg"
    subprocess.run([ffmpeg, "-y", "-ss", f"{t:.2f}", "-i", str(video_path),
                    "-frames:v", "1", "-q:v", "2", str(out)],
                   capture_output=True, timeout=30)
    return str(out)


def assess_frame(path) -> dict:
    """单帧画质评估。"""
    return {
        "sharpness": round(sharpness(path), 1),
        "brightness": round(brightness(path), 1),
        "black": is_black(path),
    }


def assess_video(video_path, sample_frames: int = 3, tmp_dir=None) -> dict:
    """视频整体画质评估：清晰度/黑帧/运动。

    motion 用【首尾帧像素差异】检测（而非亮度均值）：真实运动（含慢镜头）首尾
    画面必有像素变化；冻结/真静止则接近 0。阈值采用像素差异均值，量大更稳健。

    Returns: {sharpness, black_frames, motion, passed, issues}
    """
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    tmp = Path(tmp_dir) if tmp_dir else Path(tempfile.mkdtemp(prefix="vq_"))
    tmp.mkdir(parents=True, exist_ok=True)

    # 时长
    probe = subprocess.run([ffmpeg, "-i", str(video_path)], capture_output=True, text=True, timeout=20)
    duration = 0.0
    import re
    for line in probe.stderr.splitlines():
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
        if m:
            duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            break
    if duration <= 0:
        return {"passed": False, "issues": ["无法读取视频时长"]}

    # 抽帧评估：均匀采样 + 首尾两帧（运动检测用）
    frames = []
    n = sample_frames
    sample_points = [(i + 0.5) / n for i in range(n)]
    sample_points = [0.08, 0.5, 0.92]  # 首/中/尾
    for j, frac in enumerate(sample_points):
        fp = tmp / f"v_{j}.jpg"
        subprocess.run([ffmpeg, "-y", "-ss", f"{duration * frac:.2f}", "-i", str(video_path),
                        "-frames:v", "1", "-q:v", "2", str(fp)],
                       capture_output=True, timeout=30)
        if fp.exists():
            frames.append(str(fp))
    if len(frames) < 2:
        return {"passed": False, "issues": ["抽帧失败"]}

    sharp = [sharpness(f) for f in frames]
    bright = [brightness(f) for f in frames]
    black = [b for b, f in zip(bright, frames) if b < DEFAULT_BLACK_THRESHOLD]

    # 运动：首尾帧像素差异（归一化 np.abs 均值），对慢镜头也敏感
    first, last = _load_gray(frames[0]), _load_gray(frames[-1])
    # 尺寸对齐（抽帧.jpg 尺寸可能不同）
    h = min(first.shape[0], last.shape[0]); w = min(first.shape[1], last.shape[1])
    pixel_diff = float(np.abs(first[:h, :w] - last[:h, :w]).mean() / 255.0)

    sharpness_min = min(sharp)
    issues = []
    if sharpness_min < DEFAULT_SHARPNESS_MIN:
        issues.append(f"模糊: 最小 Laplacian 方差 {sharpness_min:.0f} < {DEFAULT_SHARPNESS_MIN}")
    if black:
        issues.append(f"黑帧: {len(black)}/{len(frames)}")
    # 首尾像素差异 < 0.5% ≈ 完全静止（真静态）
    if pixel_diff < 0.005:
        issues.append(f"疑似静态/冻结: 首尾像素差异 {pixel_diff:.4f}")

    passed = not issues
    return {
        "passed": passed, "sharpness_min": round(sharpness_min, 1),
        "sharpness_mean": round(sum(sharp) / len(sharp), 1),
        "motion": round(pixel_diff, 4), "black_frames": len(black), "issues": issues,
    }
