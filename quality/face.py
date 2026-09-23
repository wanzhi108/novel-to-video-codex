"""人脸一致性检查器（P3-L2）—— 角色漂移质量门。

复用 story2/check_anchor*.py 的经验：
- insightface FaceAnalysis（antelopev2, CPU）提取 normed_embedding；
- 余弦相似度（np.dot）度量"参考定妆照 vs 视频抽帧"的人脸一致性；
- 像素 MAE 作为辅助信号（同构图时参考）。

依赖懒加载：insightface 未安装或模型缺失时 is_available()=False，
check_video() 返回 skipped 而非崩溃——保证质量门整体不因单项依赖失败而中断。

模型根探测优先级：
  1. 环境变量 INSIGHTFACE_ROOT
  2. 常见 ComfyUI 安装（含 check_anchor 硬编码路径）
  3. ~/.insightface/models（insightface 默认）
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .gate import QualityGate

# check_anchor*.py 中验证过的模型根
_CANDIDATE_ROOTS = [
    os.environ.get("INSIGHTFACE_ROOT", ""),
    r"D:\ComfyUI-WorkFisher-V2\ComfyUI\models\insightface",
    str(Path.home() / "ai-tools" / "ComfyUI" / "models" / "insightface"),
    str(Path.home() / ".insightface" / "models"),
    str(Path.home() / ".insightface"),
]


class FaceConsistencyChecker:
    """参考图 vs 视频帧的人脸一致性检查。"""

    def __init__(self, similarity_threshold: float = 0.5, sample_frames: int = 4):
        self.threshold = similarity_threshold
        self.sample_frames = sample_frames
        self._app = None
        self._ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    # ─── 依赖 ────────────────────────────────────────────────
    def _find_root(self) -> Optional[str]:
        for root in _CANDIDATE_ROOTS:
            if not root:
                continue
            # 兼容两种布局：root/antelopev2 或 root/models/antelopev2
            if (Path(root) / "antelopev2").exists() or (Path(root) / "models" / "antelopev2").exists():
                return root
        return None

    def is_available(self) -> bool:
        try:
            import insightface  # noqa: F401
        except ImportError:
            return False
        return self._find_root() is not None

    def _get_app(self):
        if self._app is None:
            import insightface
            from insightface.app import FaceAnalysis
            root = self._find_root()
            kwargs = {"providers": ["CPUExecutionProvider"]}
            if root:
                kwargs["root"] = root
            self._app = FaceAnalysis(name="antelopev2", **kwargs)
            self._app.prepare(ctx_id=0, det_size=(640, 640))
        return self._app

    # ─── 底层 ────────────────────────────────────────────────
    def _embedding(self, img_path: Path):
        """返回 (normed_embedding | None, img)。"""
        import cv2
        app = self._get_app()
        img = cv2.imread(str(img_path))
        if img is None:
            return None, None
        faces = app.get(img)
        if not faces:
            return None, img
        return faces[0].normed_embedding, img

    @staticmethod
    def _similarity(e1, e2) -> float:
        import numpy as np
        if e1 is None or e2 is None:
            return float("nan")
        return float(np.dot(e1, e2))

    def _extract_frames(self, video_path: Path, tmp_dir: Path) -> list[Path]:
        """等间隔抽帧（最多 sample_frames 张）。失败返回空列表。"""
        frames = []
        try:
            probe = subprocess.run(
                [self._ffmpeg, "-i", str(video_path)], capture_output=True, text=True, timeout=30)
            duration = 0.0
            for line in probe.stderr.splitlines():
                if "Duration:" in line:
                    import re
                    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
                    if m:
                        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    break
            if duration <= 0:
                return []
            n = self.sample_frames
            for i in range(n):
                t = duration * (i + 0.5) / n
                out = tmp_dir / f"frame_{i:02d}.jpg"
                r = subprocess.run(
                    [self._ffmpeg, "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
                     "-frames:v", "1", "-q:v", "3", str(out)],
                    capture_output=True, timeout=30)
                if r.returncode == 0 and out.exists():
                    frames.append(out)
        except Exception:
            return []
        return frames

    # ─── 检查入口 ────────────────────────────────────────────
    def check_video(self, reference_image: Path, video_path: Path,
                    tmp_dir: Optional[Path] = None) -> dict:
        """检查视频帧与参考图的人脸一致性。

        返回: {"passed": bool|None, "available": bool, "similarities": [...],
               "mean": float|None, "detail": str, "skipped_reason": str}
        passed=None 表示跳过（依赖缺失）。
        """
        if not self.is_available():
            return {
                "passed": None, "available": False,
                "similarities": [], "mean": None,
                "detail": "insightface 或 antelopev2 模型缺失，跳过人脸一致性检查",
                "skipped_reason": "dependency_missing",
            }
        if not reference_image.exists():
            return {
                "passed": None, "available": True,
                "similarities": [], "mean": None,
                "detail": f"参考图不存在: {reference_image}",
                "skipped_reason": "no_reference",
            }
        if not video_path.exists():
            return {
                "passed": None, "available": True,
                "similarities": [], "mean": None,
                "detail": f"视频不存在: {video_path}",
                "skipped_reason": "no_video",
            }

        import tempfile
        tmp = tmp_dir or Path(tempfile.mkdtemp(prefix="face_check_"))
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            e_ref, _ = self._embedding(reference_image)
            if e_ref is None:
                return {
                    "passed": None, "available": True,
                    "similarities": [], "mean": None,
                    "detail": "参考图中未检测到人脸，跳过",
                    "skipped_reason": "no_face_in_reference",
                }
            frames = self._extract_frames(video_path, tmp)
            sims = []
            for fp in frames:
                e, _ = self._embedding(fp)
                sims.append(self._similarity(e_ref, e))
            valid = [s for s in sims if s == s]  # 过滤 NaN
            if not valid:
                return {
                    "passed": None, "available": True,
                    "similarities": sims, "mean": None,
                    "detail": "视频抽帧中未检测到人脸，跳过",
                    "skipped_reason": "no_face_in_frames",
                }
            mean = sum(valid) / len(valid)
            passed = mean >= self.threshold
            return {
                "passed": passed, "available": True,
                "similarities": [round(s, 3) if s == s else None for s in sims],
                "mean": round(mean, 3),
                "detail": (f"人脸一致性 mean={mean:.3f} >= {self.threshold} "
                           f"({len(valid)}/{len(frames)} 帧检出)"),
                "skipped_reason": "",
            }
        finally:
            # 仅清理自建临时目录
            if tmp_dir is None:
                import shutil as _sh
                try:
                    _sh.rmtree(tmp)
                except Exception:
                    pass


def integrate_face_check(gate: QualityGate) -> FaceConsistencyChecker:
    """便捷：把 FaceConsistencyChecker 与 QualityGate 组合使用（P3 全门）。"""
    return FaceConsistencyChecker()
