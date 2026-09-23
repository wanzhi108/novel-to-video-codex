"""引擎注册与路由（设计文档 §2.2 engines/registry.py）。

路由策略（video_mode）：
  - auto   : 云端优先（可用且预算内），失败降级本地，再降级 Ken Burns
  - cloud  : 仅云端
  - local  : 仅本地（ComfyUI）
  - hybrid : 按场景特征混用（关键帧本地、视频段云端等，P2 细化）

用法：
    from engines.registry import EngineRouter
    router = EngineRouter()
    clip = await router.generate(req)          # 自动路由
    router.status_report()                     # 全引擎状态
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import BaseEngine, ClipResult, EngineError, GenerateRequest, ProviderUnavailable
from .cloud import CloudEngine


class EngineRouter:
    """统一生成入口：按配置路由到云端/本地引擎，含降级链。

    配置驱动：可用 EngineRouter.from_settings() 从 settings.yaml 初始化。
    """

    def __init__(
        self,
        video_mode: str = "auto",
        prefer_cloud: Optional[str] = None,
        max_cost_usd: float = 1.0,
        local_kind: str = "comfyui",   # comfyui(LTX) | wan(Wan2.2 A14B 稳定管线)
    ):
        self.video_mode = video_mode
        self.local_kind = local_kind
        self.cloud = CloudEngine(prefer=prefer_cloud, max_cost_usd=max_cost_usd)
        self._local: Optional[BaseEngine] = None  # P1 接入 ComfyUI 引擎

    @classmethod
    def from_settings(cls, settings=None) -> "EngineRouter":
        """从 Settings 构建（配置驱动入口）。"""
        if settings is None:
            from config.settings import load_settings
            settings = load_settings()
        cfg = settings.engines.cloud
        local_cfg = getattr(settings.engines, "local", None)
        local_kind = getattr(local_cfg, "local_kind", "comfyui") if local_cfg else "comfyui"
        return cls(
            video_mode=cfg.video_mode,
            prefer_cloud=None,
            max_cost_usd=cfg.max_cost_per_clip_usd,
            local_kind=local_kind,
        )

    # ─── 本地引擎（占位，P1 实现）────────────────────────────
    def _get_local(self) -> BaseEngine:
        if self._local is None:
            # 延迟导入，避免首屏引入 ComfyUI 依赖
            try:
                if self.local_kind == "wan":
                    from .wan import WanEngine
                    self._local = WanEngine()
                elif self.local_kind == "wan5b":
                    from .wan5b import Wan5BEngine
                    self._local = Wan5BEngine()
                else:
                    from .local import ComfyUIEngine
                    self._local = ComfyUIEngine()
            except Exception as exc:  # noqa: BLE001
                raise ProviderUnavailable(f"本地引擎不可用: {exc}")
        return self._local

    # ─── 路由 ────────────────────────────────────────────────
    async def generate(self, req: GenerateRequest) -> ClipResult:
        if self.video_mode == "local":
            return await self._get_local().generate(req)
        if self.video_mode == "cloud":
            return await self.cloud.generate(req)
        # auto / hybrid：云端优先，失败降级本地
        try:
            return await self.cloud.generate(req)
        except ProviderUnavailable as exc:
            if self.video_mode == "cloud":
                raise
            print(f"[Router] 云端不可用，降级本地: {exc}", flush=True)
            return await self._get_local().generate(req)
        except EngineError as exc:
            print(f"[Router] 云端失败，降级本地: {exc}", flush=True)
            local = await self._get_local().generate(req)
            local.downgraded_from = "cloud"
            return local

    def status_report(self) -> dict:
        return {
            "video_mode": self.video_mode,
            "cloud": self.cloud.status_report(),
            "local_comfyui": {"status": "P1 未接入"},
        }
