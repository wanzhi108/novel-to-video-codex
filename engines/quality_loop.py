"""质量门闭环：生成 → 自动检查 → 失败重试（设计文档 §2.3）。

重试策略按 retry_strategy 顺序：
  1. reseed          : 换随机种子重试（同引擎）
  2. switch_engine   : 换下一个可用引擎（云端失败→本地等）
  3. rewrite_prompt  : 由外部回调改写 prompt 后重试（LLM 改写）

每次重试输出日志并记录 retry_history；最终产物即使未过门也返回
（带 quality_report，供上层决定是否保留/重做）。
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from .base import BaseEngine, ClipResult, EngineError, GenerateRequest

logger = logging.getLogger("novel2vid.quality")


@dataclass
class RetryConfig:
    max_retries: int = 2
    strategy: list[str] = field(default_factory=lambda: ["reseed", "switch_engine", "rewrite_prompt"])
    min_duration_ratio: float = 0.8


class GenerationGate:
    """把 BaseEngine 与 QualityGate 组合成"生成即检查、失败即重试"的闭环。"""

    def __init__(self, engines: list[BaseEngine], gate, config: Optional[RetryConfig] = None,
                 visual_gate=None):
        """
        engines: 有序引擎列表（优先者在前），用于 switch_engine 重试。
        gate:    quality.gate.QualityGate（含 check_video，技术/静态/时长/音频）。
        visual_gate: 可选 callable(path)->dict（如 quality.visual.assess_video），
                    启用时额外做画质/运动检测，失败触发重试（解决"画面糊/动作僵硬"）。
        """
        self.engines = engines
        self.gate = gate
        self.config = config or RetryConfig()
        self.visual_gate = visual_gate

    async def generate(self, req: GenerateRequest,
                       prompt_rewriter: Optional[Callable[[str], Awaitable[str]]] = None) -> ClipResult:
        """执行带质量门与重试的生成。返回最终 ClipResult（含 quality_report 与 retry_history）。"""
        history: list[dict] = []
        current_req = req
        engine_index = 0

        for attempt in range(self.config.max_retries + 1):
            engine = self.engines[engine_index]
            try:
                clip = await engine.generate(current_req)
            except EngineError as exc:
                history.append({"attempt": attempt, "engine": engine.name, "error": str(exc)})
                logger.warning(f"[Gate] {engine.name} 生成失败({exc})，尝试换引擎")
                if engine_index < len(self.engines) - 1:
                    engine_index += 1
                    continue
                # 所有引擎失败
                clip = None
                break

            report = await self.gate.check_video(
                clip.video_path, expect_duration=req.duration_seconds)
            clip.quality_report = report
            history.append({
                "attempt": attempt, "engine": engine.name, "seed": clip.seed,
                "passed": report.get("passed"), "issues": report.get("issues", []),
            })

            # 可选：视觉画质/运动门（解决"画面糊/动作僵硬"）
            if report.get("passed") and self.visual_gate is not None:
                try:
                    vq = await asyncio.to_thread(self.visual_gate, clip.video_path)
                    if isinstance(vq, dict):
                        report["visual"] = vq   # 无论通过与否都记录，便于上层读 sharp/motion
                        if vq.get("issues"):
                            report["passed"] = vq.get("passed", True)
                            history[-1]["issues"] = (history[-1]["issues"] or []) + vq["issues"]
                            logger.info(f"[Gate] 视觉门未过: {vq['issues']}")
                except Exception:  # noqa: BLE001
                    pass  # 视觉检查失败不阻断

            if report.get("passed"):
                clip.quality_report["retry_history"] = history
                return clip

            # 未过门：按策略决定下一步
            action = self.config.strategy[min(attempt, len(self.config.strategy) - 1)] \
                if self.config.strategy else "reseed"
            logger.info(f"[Gate] {engine.name} 未过质量门({report['issues']})，策略={action}")
            if attempt >= self.config.max_retries:
                break

            if action == "switch_engine" and engine_index < len(self.engines) - 1:
                engine_index += 1
                current_req = self._new_seed(current_req)
            elif action == "rewrite_prompt" and prompt_rewriter:
                current_req.prompt = await prompt_rewriter(current_req.prompt)
                current_req = self._new_seed(current_req)
            else:  # reseed / 默认
                current_req = self._new_seed(current_req)

        # 全部失败：构造带错误信息的空结果（不静默）
        if clip is None:
            raise EngineError(
                f"所有引擎均失败。history={history}")

        clip.quality_report = clip.quality_report or {}
        clip.quality_report["retry_history"] = history
        clip.quality_report["passed"] = False
        return clip

    @staticmethod
    def _new_seed(req: GenerateRequest) -> GenerateRequest:
        import dataclasses
        return dataclasses.replace(req, seed=random.randint(0, 2**32 - 1))
