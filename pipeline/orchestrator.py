"""编排器（P4 落地：assets 阶段；其余阶段为接口占位）。

把 engines / quality / queue / config 组合成面向"场景批量生成"的工业 API：

    from pipeline.orchestrator import Orchestrator
    orch = Orchestrator()
    result = await orch.run_assets(scenes=[SceneReq(...), ...])

内部链路（与 tests/test_pipeline_integration.py 一致）：
  TaskQueue(并发) → GenerationGate(质量门+重试) → CostTracker(预算)
每条场景输出 ClipResult + quality_report + 成本，落盘 assets.json。

未来阶段（storyboard/prompts/compose/qa）在 Orchestrator 上以相同模式扩展。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config.settings import Settings, load_settings
from engines.base import BaseEngine, ClipResult, GenerateRequest
from engines.cloud import CloudEngine
from engines.local import ComfyUIEngine
from engines.wan import WanEngine
from engines.quality_loop import GenerationGate
from quality.gate import QualityGate
from scheduler.cost import CostTracker
from scheduler.tasks import Task, TaskQueue

logger = logging.getLogger("novel2vid.pipeline")


@dataclass
class SceneReq:
    """一个场景的视频段生成请求（业务层数据）。"""
    id: str
    prompt: str
    first_frame: Optional[Path] = None
    duration_seconds: float = 5.0
    width: int = 960
    height: int = 1728
    reference_images: list[Path] = field(default_factory=list)
    negative_prompt: str = ""


class Orchestrator:
    """工业化编排器：批量场景 → 双引擎 → 质量门 → 成本 → 产物清单。"""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or load_settings()
        self.tracker = CostTracker(
            budget_usd=self.settings.queue.budget_usd, mode="cap")

    # ─── 引擎组装（按配置）──────────────────────────────────
    def _build_engines(self) -> list[BaseEngine]:
        """按配置组装有序引擎列表：CloudEngine（内部多 provider 路由）+ ComfyUIEngine。

        注意：CloudEngine 本身是 BaseEngine（内部按 priority 路由各 provider），
        不要拆散成单个 OpenMontage 工具——那不符合 BaseEngine 接口。
        """
        engines: list[BaseEngine] = []
        cfg = self.settings.engines
        if cfg.cloud.video_mode in ("auto", "cloud", "hybrid"):
            cloud = CloudEngine(
                max_cost_usd=cfg.cloud.max_cost_per_clip_usd,
                timeout_seconds=cfg.cloud.timeout_seconds)
            if cloud.is_available():
                engines.append(cloud)
        if cfg.cloud.video_mode in ("auto", "local", "hybrid"):
            local_kind = getattr(cfg.local, "local_kind", "comfyui")
            if local_kind == "wan":
                local = WanEngine()
            elif local_kind == "wan5b":
                from engines.wan5b import Wan5BEngine
                local = Wan5BEngine()
            else:
                local = ComfyUIEngine()
            if local.is_available():
                engines.append(local)
        if not engines:
            raise RuntimeError(
                "没有任何可用引擎：云端 key 未配置 且 本地 ComfyUI 未在线。"
                "请填 OpenMontage/.env 的 key 或启动 ComfyUI。")
        return engines

    # ─── 场景批量生成（assets 阶段）─────────────────────────
    async def run_assets(self, scenes: list[SceneReq],
                         output_dir: Optional[Path] = None) -> dict:
        engines = self._build_engines()
        gate = GenerationGate(engines, QualityGate())
        out_root = output_dir or (Path(__file__).resolve().parent.parent / "output" / "pipeline")
        out_root.mkdir(parents=True, exist_ok=True)

        queue = TaskQueue(
            max_concurrency=self.settings.queue.max_concurrency,
            resume=self.settings.queue.resume,
            state_file=out_root / "queue_state.json")
        results: dict[str, ClipResult] = {}

        async def make_task(scene: SceneReq):
            async def run():
                req = GenerateRequest(
                    prompt=scene.prompt,
                    first_frame=scene.first_frame,
                    reference_images=scene.reference_images,
                    negative_prompt=scene.negative_prompt,
                    width=scene.width, height=scene.height,
                    duration_seconds=scene.duration_seconds,
                    output_dir=out_root,
                    output_name=f"scene_{scene.id}",
                    timeout_seconds=self.settings.engines.cloud.timeout_seconds,
                )
                eid = self.tracker.estimate("engine", f"scene {scene.id}",
                                            self.settings.engines.cloud.max_cost_per_clip_usd)
                if not self.tracker.reserve(eid):
                    raise RuntimeError(f"scene {scene.id}: 预算不足")
                clip = await gate.generate(req)
                self.tracker.reconcile(eid, clip.cost_usd)
                results[scene.id] = clip
            return run

        for scene in scenes:
            queue.submit(Task(id=f"scene-{scene.id}", run=await make_task(scene)))

        await queue.run()

        # 产物清单落盘
        manifest = {
            "scenes": [
                {
                    "id": cid,
                    "video": str(c.video_path),
                    "engine": c.engine,
                    "cost_usd": round(c.cost_usd, 4),
                    "duration": c.duration_seconds,
                    "quality": c.quality_report,
                }
                for cid, c in sorted(results.items())
            ],
            "queue": queue.summary(),
            "cost": self.tracker.summary(),
        }
        manifest_path = out_root / "assets.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[Pipeline] assets 完成: {len(results)} 场景, 清单 {manifest_path}")
        return manifest

    # ─── 合成（compose 阶段）────────────────────────────────
    async def run_compose(self, scene_videos: list[Path], output: Path,
                          narration: Optional[Path] = None,
                          subtitles: Optional[dict] = None,
                          bgm: Optional[Path] = None,
                          bgm_volume: float = 0.18,
                          transition: str = "fade") -> Path:
        """批量场景视频段 → 完整成片（xfade 拼接 → 配音对齐 → BGM → 字幕）。

        narration: 外部配音轨（自动时长对齐：视频短则冻结末帧补足）。
        subtitles: {"texts": [...], "timings": [Timing...], "styles": [...], "fonts_dir": ...}
        """
        from post.compose import compose_video, probe_duration
        out = await compose_video(
            scene_videos, output,
            narration=narration, subtitles=subtitles,
            bgm=bgm, bgm_volume=bgm_volume, transition=transition)
        logger.info(f"[Pipeline] compose 完成: {out} ({await probe_duration(out):.1f}s)")
        return out

    # ─── 分镜（storyboard 阶段）──────────────────────────────
    async def run_storyboard(self, novel_text: str, title: str = "",
                             api_key: Optional[str] = None,
                             max_scenes: int = 0) -> list[SceneReq]:
        """DeepSeek 分镜：小说 → 场景生成请求列表（供 run_assets 用）。

        通过 pipeline.storyboard.generate_storyboard 调用 DeepSeek，
        把 image_prompt/video_prompt 映射为 SceneReq.prompt。
        """
        from .storyboard import generate_storyboard
        scenes = generate_storyboard(novel_text, title=title, api_key=api_key,
                                     max_scenes=max_scenes)
        reqs = []
        for s in scenes:
            prompt = s.get("video_prompt") or s.get("image_prompt") or s.get("description", "")
            dur = self._parse_duration(s.get("duration", "5"))
            reqs.append(SceneReq(
                id=str(s.get("id", len(reqs) + 1)),
                prompt=prompt,
                duration_seconds=dur,
                negative_prompt=s.get("negative_prompt", ""),
            ))
        logger.info(f"[Pipeline] storyboard: {len(reqs)} 个场景（DeepSeek 分镜）")
        return reqs

    @staticmethod
    def _parse_duration(raw) -> float:
        """解析 '5' / '5s' / '5秒' → 5.0。"""
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", str(raw))
        return float(m.group(1)) if m else 5.0
