"""质量门（设计文档 §2.3）—— 每个 clip 生成后的自动检查与重试判定。

L1 已实现（纯本地、零依赖）：
  - technical : ffprobe 时长/分辨率/帧率/码率/音频流
  - static    : 帧数检测（<24 帧视为静态/失败产物）
  - duration  : 时长 >= 请求时长的阈值比例
  - audio     : 是否有音频流（配音场景必检）

L2（P3 后续，可插拔）：
  - face_consistency : insightface 余弦相似度（复用 story2/check_anchor.py 经验）
  - quality_score    : 无参考 IQA / CLIP 美学评分
  - content_safety   : DeepSeek 审核

用法：
    from quality.gate import QualityGate
    gate = QualityGate()
    report = await gate.check_video(path, expect_duration=5.0)
    ok = report["passed"]
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GateConfig:
    min_duration_ratio: float = 0.8      # 实际/期望 时长比下限
    min_frames: int = 24                 # 低于视为静态产物
    min_file_size: int = 10_000          # bytes
    require_audio: bool = False          # 配音场景置 True


class QualityGate:
    """基于 ffprobe 的本地质量检查。"""

    def __init__(self, config: Optional[GateConfig] = None):
        self.config = config or GateConfig()
        self.ffprobe = shutil.which("ffprobe") or "ffprobe"

    # ─── 底层探测 ────────────────────────────────────────────
    def probe(self, path: Path) -> dict:
        """ffprobe JSON 摘要。失败返回 {"error": ...}。"""
        if not path.exists() or path.stat().st_size == 0:
            return {"error": "文件不存在或为空"}
        cmd = [
            self.ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return {"error": f"ffprobe 失败: {r.stderr.strip()[-200:]}"}
            return json.loads(r.stdout)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"ffprobe 异常: {exc}"}

    @staticmethod
    def _video_stream(probe: dict) -> Optional[dict]:
        for s in probe.get("streams", []):
            if s.get("codec_type") == "video":
                return s
        return None

    @staticmethod
    def _audio_stream(probe: dict) -> Optional[dict]:
        for s in probe.get("streams", []):
            if s.get("codec_type") == "audio":
                return s
        return None

    def count_frames(self, path: Path) -> int:
        """帧数统计（-count_frames）。失败返回 -1。"""
        try:
            r = subprocess.run(
                [self.ffprobe, "-v", "error", "-count_frames",
                 "-select_streams", "v:0", "-show_entries",
                 "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=60,
            )
            return int(r.stdout.strip() or -1)
        except Exception:
            return -1

    # ─── 检查 ────────────────────────────────────────────────
    async def check_video(self, path: Path, expect_duration: Optional[float] = None,
                          config: Optional[GateConfig] = None) -> dict:
        cfg = config or self.config
        probe = self.probe(path)
        checks: dict = {}
        issues: list[str] = []

        if "error" in probe:
            checks["technical"] = {"passed": False, "detail": probe["error"]}
            issues.append(probe["error"])
            return {"passed": False, "path": str(path), "checks": checks, "issues": issues}

        vstream = self._video_stream(probe)
        duration = float(probe.get("format", {}).get("duration", 0) or 0)
        size = int(probe.get("format", {}).get("size", 0) or 0)
        width = int(vstream.get("width", 0)) if vstream else 0
        height = int(vstream.get("height", 0)) if vstream else 0
        fps = float((vstream or {}).get("avg_frame_rate", "0").split("/")[0] or 0)

        # 1) 技术完整性
        tech_ok = vstream is not None and duration > 0 and size >= cfg.min_file_size
        checks["technical"] = {
            "passed": tech_ok,
            "detail": f"{width}x{height} {fps}fps {duration:.2f}s {size/1024:.0f}KB",
        }
        if not tech_ok:
            issues.append(f"技术检查失败: {checks['technical']['detail']}")

        # 2) 静态检测（帧数）
        frames = self.count_frames(path)
        static = frames >= 0 and frames < cfg.min_frames
        checks["static"] = {"passed": not static, "frames": frames, "detail": f"{frames} 帧"}
        if static:
            issues.append(f"疑似静态产物: {frames} 帧 < {cfg.min_frames}")

        # 3) 时长达标
        dur_ok = True
        if expect_duration and duration > 0:
            dur_ok = duration >= expect_duration * cfg.min_duration_ratio
            checks["duration"] = {
                "passed": dur_ok,
                "actual": round(duration, 2),
                "expected": expect_duration,
                "detail": f"{duration:.2f}s >= {expect_duration * cfg.min_duration_ratio:.2f}s",
            }
            if not dur_ok:
                issues.append(f"时长不达标: {duration:.2f}s < 期望 {expect_duration:.2f}s")

        # 4) 音频（可选）
        audio_ok = True
        if cfg.require_audio:
            audio_ok = self._audio_stream(probe) is not None
            checks["audio"] = {"passed": audio_ok}
            if not audio_ok:
                issues.append("缺少音频流")

        passed = tech_ok and not static and dur_ok and audio_ok
        return {
            "passed": passed,
            "path": str(path),
            "duration": round(duration, 3),
            "resolution": f"{width}x{height}" if width else "",
            "fps": round(fps, 2) if fps else 0,
            "frames": frames,
            "checks": checks,
            "issues": issues,
        }

    def should_retry(self, report: dict) -> bool:
        """质量门判定是否值得重试（技术/时长失败可重试；结构性失败不重试）。"""
        return not report.get("passed", False) and bool(report.get("issues"))
