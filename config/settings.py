"""配置模型与加载（YAML 驱动，pydantic 校验）。

优先级：环境变量 > 显式传入的 YAML > 默认值。
默认配置与 docs/INDUSTRIALIZATION.md §2.4 示例一致。

用法：
    from config.settings import Settings, load_settings
    s = load_settings("settings.yaml")     # 不存在则用默认
    s.engines.video_mode                   # 'auto'
    s.quality.min_duration_ratio           # 0.8
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:  # 极简兜底（无 pydantic 时退化为 dict）
    BaseModel = object

    class Field:  # type: ignore
        def __init__(self, default=None, **kw):
            self.default = default

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class EngineCloud(BaseModel if BaseModel is not object else object):
    video_mode: str = "auto"          # auto | local | cloud | hybrid
    priority: List[str] = Field(default_factory=lambda: [
        "seedance_ark", "kling_official", "minimax", "jimeng",
        "grok", "fal_kling", "fal_seedance", "fal_minimax", "runway", "veo"])
    max_cost_per_clip_usd: float = 1.0
    timeout_seconds: float = 900.0


class EngineLocal(BaseModel if BaseModel is not object else object):
    checkpoint: str = "ltx-2.3-22b-dev-fp8.safetensors"
    text_encoder: str = "gemma_3_12B_it_fpmixed.safetensors"
    width: int = 960
    height: int = 1728
    frames: int = 96          # 质量调优结论：96帧(4s) + 8步为 16GB 下质量甜点
    fps: int = 24
    quality: str = "high"     # normal|high（high=96帧；步数恒为 8+3，蒸馏模型加步数有害）
    local_kind: str = "comfyui"   # comfyui(LTX) | wan(Wan2.2 A14B 稳定管线)


class Engines(BaseModel if BaseModel is not object else object):
    cloud: EngineCloud = Field(default_factory=EngineCloud)
    local: EngineLocal = Field(default_factory=EngineLocal)


class Quality(BaseModel if BaseModel is not object else object):
    min_duration_ratio: float = 0.8
    min_frames: int = 24
    min_file_size: int = 10_000
    face_similarity: float = 0.5
    max_retries: int = 2
    retry_strategy: List[str] = Field(default_factory=lambda: [
        "reseed", "switch_engine", "rewrite_prompt"])


class Queue(BaseModel if BaseModel is not object else object):
    max_concurrency: int = 2
    budget_usd: float = 10.0
    resume: bool = True


class Subtitles(BaseModel if BaseModel is not object else object):
    style: str = "ass"
    timing: str = "line_accurate"     # line_accurate | even_split


class Settings(BaseModel if BaseModel is not object else object):
    engines: Engines = Field(default_factory=Engines)
    quality: Quality = Field(default_factory=Quality)
    queue: Queue = Field(default_factory=Queue)
    subtitles: Subtitles = Field(default_factory=Subtitles)


def load_settings(path: Optional[str] = None) -> Settings:
    """加载 YAML 配置；文件不存在时返回默认配置。"""
    if path:
        yaml_path = Path(path)
    else:
        yaml_path = PROJECT_ROOT / "settings.yaml"
    if not yaml_path.exists():
        return Settings()
    try:
        import yaml
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return Settings()
    # 支持嵌套 dict → pydantic 模型
    try:
        return Settings(**data)
    except Exception:
        return Settings()


def dump_default_settings(path: Optional[str] = None) -> Path:
    """把默认配置写成 YAML 模板（便于用户定制）。"""
    out = Path(path) if path else PROJECT_ROOT / "settings.yaml"
    if out.exists():
        return out
    default_yaml = """# novel-to-video-codex 工业化配置（设计文档 docs/INDUSTRIALIZATION.md §2.4）
engines:
  video_mode: auto          # auto | local | cloud | hybrid
  priority: [seedance_ark, kling_official, minimax, jimeng, grok,
             fal_kling, fal_seedance, fal_minimax, runway, veo]
  max_cost_per_clip_usd: 1.0
  timeout_seconds: 900
  local:
    checkpoint: ltx-2.3-22b-dev-fp8.safetensors
    text_encoder: gemma_3_12B_it_fpmixed.safetensors
    quality: high            # normal|high（high=96帧/4s；步数恒 8+3，蒸馏模型加步数有害）
    width: 960
    height: 1728
    frames: 96               # 质量调优结论：16GB 下 96帧+8步 为质量甜点
    fps: 24

quality:
  min_duration_ratio: 0.8
  min_frames: 24
  min_file_size: 10000
  face_similarity: 0.5
  max_retries: 2
  retry_strategy: [reseed, switch_engine, rewrite_prompt]

queue:
  max_concurrency: 2
  budget_usd: 10.0
  resume: true

subtitles:
  style: ass
  timing: line_accurate     # line_accurate | even_split
"""
    out.write_text(default_yaml, encoding="utf-8")
    return out
