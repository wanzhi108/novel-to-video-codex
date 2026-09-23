"""云端视频生成引擎 —— 封装 OpenMontage 的成熟 provider 工具。

设计要点（勘察结论）：
- OpenMontage 云端工具只需填 .env key 即可直接运行，无额外 pip 依赖；
- fal 系工具轮询无超时上限，本引擎用 asyncio.wait_for 强制 deadline；
- 所有调用在 to_thread 中执行（OpenMontage 工具为同步 execute）；
- key 缺失/依赖缺失时抛 ProviderUnavailable 并附修复指引。

用法：
    from engines.cloud import CloudEngine
    engine = CloudEngine()
    print(engine.status_report())          # 各 provider 可用性
    clip = await engine.generate(req)      # 自动选可用 provider
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .base import (
    BaseEngine,
    ClipResult,
    EngineError,
    GenerateRequest,
    ProviderUnavailable,
)

# ─── OpenMontage 路径注入（惰性，仅在加载云端工具时执行）────────
# 不在模块级污染 sys.path——否则每次 import（含 httpx 内部 import）都会
# 扫描巨型 OpenMontage 目录，内存压力下触发 WinError 8。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OM_DIR = _PROJECT_ROOT / "OpenMontage"


def _ensure_om_path() -> None:
    """仅在首次加载 OpenMontage 工具时才把其目录加入 sys.path。"""
    if str(_OM_DIR) not in sys.path:
        sys.path.insert(0, str(_OM_DIR))


# ─── Provider 定义 ────────────────────────────────────────────
# 每项: 名称 -> dict(module, class, env_keys, priority, note)
# priority 越小越优先；国内直连（ark/kling/minimax/jimeng）优先于 fal（需代理）。
_PROVIDERS: dict[str, dict[str, Any]] = {
    "seedance_ark": {
        "module": "tools.video.seedance_ark",
        "class": "SeedanceArkVideo",
        "env_keys": ["ARK_API_KEY"],
        "priority": 10,
        "note": "火山方舟 Seedance 2.0/2.5 直连（国内可直连，中文理解强，质量高）",
    },
    "kling_official": {
        "module": "tools.video.kling_official_video",
        "class": "KlingOfficialVideo",
        "env_keys": ["KLING_API_KEY"],
        "priority": 20,
        "note": "可灵官方直连（新加坡端点，I2V/参考图/口型全支持）",
    },
    "minimax": {
        "module": "tools.video.minimax_video",
        "class": "MinimaxVideo",
        "env_keys": ["MINIMAX_API_KEY"],
        "priority": 30,
        "note": "MiniMax H3 官方（global/cn 双路由，2K 高画质）",
    },
    "jimeng": {
        "module": "tools.video.jimeng_video",
        "class": "JimengVideo",
        "env_keys": ["VOLC_ACCESSKEY", "VOLC_SECRETKEY"],
        "priority": 40,
        "note": "即梦 Jimeng 3.0 Pro（火山引擎 IAM 签名，国内直连）",
    },
    "grok": {
        "module": "tools.video.grok_video",
        "class": "GrokVideo",
        "env_keys": ["XAI_API_KEY"],
        "priority": 50,
        "note": "xAI Grok video（参考图视频，1-15s）",
    },
    "fal_kling": {
        "module": "tools.video.kling_video",
        "class": "KlingVideo",
        "env_keys": ["FAL_KEY", "FAL_AI_API_KEY"],
        "priority": 60,
        "note": "fal.ai 上的 Kling（需代理访问 queue.fal.run）",
    },
    "fal_seedance": {
        "module": "tools.video.seedance_video",
        "class": "SeedanceVideo",
        "env_keys": ["FAL_KEY", "FAL_AI_API_KEY"],
        "priority": 61,
        "note": "fal.ai 上的 Seedance 2.0（需代理）",
    },
    "fal_minimax": {
        "module": "tools.video.minimax_fal_video",
        "class": "MinimaxFalVideo",
        "env_keys": ["FAL_KEY", "FAL_AI_API_KEY"],
        "priority": 62,
        "note": "fal.ai 上的 MiniMax H3（需代理）",
    },
    "runway": {
        "module": "tools.video.runway_video",
        "class": "RunwayVideo",
        "env_keys": ["RUNWAY_API_KEY"],
        "priority": 70,
        "note": "Runway（Gen-4 / Seedance 2.5 / Gemini Omni Flash）",
    },
    "veo": {
        "module": "tools.video.veo_video",
        "class": "VeoVideo",
        "env_keys": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "priority": 80,
        "note": "Google Veo 3（google-genai SDK，1080p/4K）",
    },
}

# I2V 优先 provider（首帧图必传时先试这些）
_I2V_FIRST = ["seedance_ark", "kling_official", "minimax", "jimeng", "grok", "fal_kling", "fal_seedance", "fal_minimax", "runway", "veo"]


class CloudEngine(BaseEngine):
    """多 provider 云端视频引擎。自动选择可用且预算内的 provider。"""

    name = "cloud"
    kind = "cloud"
    capability = "both"

    def __init__(self, prefer: Optional[str] = None, max_cost_usd: float = 1.0,
                 timeout_seconds: float = 900.0):
        self.prefer = prefer
        self.max_cost_usd = max_cost_usd
        self.timeout_seconds = timeout_seconds
        self._tools: dict[str, Any] = {}

    # ─── 工具加载 ────────────────────────────────────────────
    def _tool(self, provider: str) -> Any:
        """懒加载 OpenMontage 工具实例（避免全量 registry import）。"""
        if provider in self._tools:
            return self._tools[provider]
        _ensure_om_path()  # 首次加载工具时才注入路径
        spec = _PROVIDERS[provider]
        try:
            module = __import__(spec["module"], fromlist=[spec["class"]])
            cls = getattr(module, spec["class"])
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(
                f"Provider '{provider}' 工具加载失败: {exc}"
            ) from exc
        tool = cls()
        self._tools[provider] = tool
        return tool

    def provider_status(self, provider: str) -> str:
        """返回 AVAILABLE / UNAVAILABLE（OpenMontage get_status 口径，统一字符串）。"""
        try:
            tool = self._tool(provider)
            status = tool.get_status()
            if hasattr(status, "value"):      # enum 成员
                return str(status.value)
            text = str(status)
            return text.replace("ToolStatus.", "") if text.startswith("ToolStatus.") else text
        except Exception:
            return "UNAVAILABLE"

    def status_report(self) -> dict[str, dict[str, str]]:
        """所有 provider 可用性报告（供 UI/诊断）。"""
        report = {}
        for name, spec in _PROVIDERS.items():
            report[name] = {
                "status": self.provider_status(name),
                "priority": str(spec["priority"]),
                "note": spec["note"],
            }
        return report

    # ─── 可用性 ──────────────────────────────────────────────
    def _available_providers(self, need_i2v: bool) -> list[str]:
        order = _I2V_FIRST if need_i2v else sorted(
            _PROVIDERS, key=lambda n: _PROVIDERS[n]["priority"])
        if self.prefer and self.prefer in _PROVIDERS:
            # prefer 的 provider 提到最前（仍需可用）
            order = [self.prefer] + [n for n in order if n != self.prefer]
        return [n for n in order if self.provider_status(n) == "AVAILABLE"]

    def is_available(self) -> bool:
        return bool(self._available_providers(need_i2v=False))

    # ─── 输入适配 ────────────────────────────────────────────
    @staticmethod
    def _aspect_ratio(width: int, height: int) -> str:
        if height >= width * 1.6:
            return "9:16"
        if width >= height * 1.6:
            return "16:9"
        return "1:1"

    def _build_inputs(self, provider: str, req: GenerateRequest, output_path: Path) -> dict[str, Any]:
        base: dict[str, Any] = {
            "prompt": req.prompt,
            "output_path": str(output_path),
            "timeout_seconds": int(req.timeout_seconds),
            "poll_interval": 5.0,
        }
        if req.negative_prompt:
            base["negative_prompt"] = req.negative_prompt

        if provider == "seedance_ark":
            base["model_variant"] = os.environ.get("ARK_SEEDANCE_MODEL_VARIANT", "2.5")
            base["duration"] = int(max(1, min(round(req.duration_seconds), 15)))
            base["generate_audio"] = False
            if req.first_frame:
                base["image_path"] = str(req.first_frame)
            if req.reference_images:
                base["reference_image_path"] = str(req.reference_images[0])

        elif provider == "kling_official":
            base["operation"] = "image_to_video" if req.first_frame else "text_to_video"
            base["model_name"] = os.environ.get("KLING_MODEL", "kling-v3")
            base["duration"] = str(int(max(1, min(round(req.duration_seconds), 10))))
            base["aspect_ratio"] = self._aspect_ratio(req.width, req.height)
            if req.first_frame:
                base["image_path"] = str(req.first_frame)
            if req.reference_images:
                base["reference_image_path"] = str(req.reference_images[0])

        elif provider == "minimax":
            base["model"] = "MiniMax-H3"
            base["duration"] = max(4, min(int(round(req.duration_seconds)), 15))
            if req.first_frame:
                base["image_path"] = str(req.first_frame)

        elif provider == "jimeng":
            base["model"] = os.environ.get("JIMENG_MODEL", "Jimeng3.0Pro")
            base["duration"] = max(1, min(int(round(req.duration_seconds)), 12))
            if req.first_frame:
                base["image_path"] = str(req.first_frame)

        elif provider in ("fal_kling", "fal_seedance", "fal_minimax"):
            base["duration"] = max(1, min(int(round(req.duration_seconds)), 10))
            if req.first_frame:
                base["image_path"] = str(req.first_frame)
            if req.reference_images:
                base["reference_image_path"] = str(req.reference_images[0])

        elif provider == "grok":
            base["duration"] = max(1, min(int(round(req.duration_seconds)), 15))
            if req.first_frame:
                base["image_path"] = str(req.first_frame)

        elif provider == "runway":
            base["model"] = os.environ.get("RUNWAY_MODEL", "seedance2")
            base["duration"] = max(1, min(int(round(req.duration_seconds)), 10))
            if req.first_frame:
                base["image_path"] = str(req.first_frame)

        elif provider == "veo":
            base["duration"] = "8s" if req.first_frame else f"{int(req.duration_seconds)}s"
            if req.first_frame:
                base["image_path"] = str(req.first_frame)
            if req.reference_images:
                base["reference_image_path"] = str(req.reference_images[0])

        # seed 透传（部分 provider 支持）
        if req.seed is not None:
            base["seed"] = req.seed
        return base

    # ─── 执行 ────────────────────────────────────────────────
    async def generate(self, req: GenerateRequest) -> ClipResult:
        need_i2v = req.first_frame is not None
        available = self._available_providers(need_i2v)
        if not available:
            missing = [
                f"{name}(缺 {'/'.join(spec['env_keys'])})"
                for name, spec in _PROVIDERS.items()
            ]
            raise ProviderUnavailable(
                "没有可用的云端视频 provider。请至少填一个 key：\n  - "
                + "\n  - ".join(missing)
                + "\n\n填好后重新运行。也可改用本地引擎（engines.local.ComfyUIEngine）。"
            )

        # 预算过滤
        affordable = [
            p for p in available
            if self.max_cost_usd is None
            or self.estimate_cost_for(p, req) <= self.max_cost_usd
        ]
        ordered = affordable or available

        last_err: Optional[str] = None
        for provider in ordered:
            try:
                return await self._generate_one(provider, req)
            except (EngineError, asyncio.TimeoutError, TimeoutError) as exc:
                last_err = f"{provider}: {exc}"
                print(f"[CloudEngine] {provider} 失败，尝试下一个: {exc}", flush=True)
                continue
        raise EngineError(f"所有云端 provider 均失败。最后错误: {last_err}")

    async def _generate_one(self, provider: str, req: GenerateRequest) -> ClipResult:
        tool = self._tool(provider)
        out_dir = req.output_dir or (_PROJECT_ROOT / "output" / "cloud_clips")
        out_dir.mkdir(parents=True, exist_ok=True)
        name = req.output_name or f"{provider}_{int(time.time())}"
        output_path = out_dir / f"{name}.mp4"

        inputs = self._build_inputs(provider, req, output_path)
        # 强制 deadline（fal 系工具内部轮询无上限）
        timeout = max(60.0, req.timeout_seconds or self.timeout_seconds)
        result = await asyncio.wait_for(
            asyncio.to_thread(tool.execute, inputs),
            timeout=timeout,
        )
        if result is None or not result.success:
            err = getattr(result, "error", "unknown")
            raise EngineError(f"{provider} 失败: {err}")

        video_path = None
        data = result.data or {}
        for key in ("output_path", "output"):
            v = data.get(key)
            if v and Path(v).exists():
                video_path = Path(v)
                break
        if video_path is None and result.artifacts:
            for a in result.artifacts:
                if Path(a).suffix.lower() in (".mp4", ".mov", ".webm"):
                    video_path = Path(a)
                    break
        if video_path is None or not video_path.exists():
            raise EngineError(f"{provider} 未返回有效视频文件: {data}")

        return ClipResult(
            video_path=video_path,
            engine=provider,
            cost_usd=float(getattr(result, "cost_usd", 0.0) or 0.0),
            duration_seconds=float(getattr(result, "duration_seconds", 0.0) or 0.0),
            seed=req.seed,
            task_id=data.get("task_id"),
            model=str(data.get("model", "")),
        )

    # ─── 成本 ────────────────────────────────────────────────
    def estimate_cost_for(self, provider: str, req: GenerateRequest) -> float:
        try:
            tool = self._tool(provider)
            inputs = {
                "prompt": req.prompt,
                "duration": str(int(max(1, min(round(req.duration_seconds), 10)))),
                "output_path": "x.mp4",
            }
            if req.first_frame:
                inputs["image_path"] = str(req.first_frame)
            return float(tool.estimate_cost(inputs) or 0.0)
        except Exception:
            return 0.0

    def estimate_cost(self, req: GenerateRequest) -> float:
        available = self._available_providers(need_i2v=req.first_frame is not None)
        if not available:
            return 0.0
        return min(self.estimate_cost_for(p, req) for p in available)
