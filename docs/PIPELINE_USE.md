# 新工业化流水线使用手册（PIPELINE USE）

> 本文档说明如何用新模块（engines / quality / scheduler / pipeline / config / post）完成"小说 → 成片"的工业化生产。旧路径（scripts/main.py 桌面应用、story2 脚本）保持可用，二者共享 ComfyUI/FFmpeg 后端。

## 1. 环境准备

```powershell
# Python 3.11+，建议用仓库 venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 1.1 生成引擎（二选一或并用）

| 路径 | 前提 | 说明 |
|---|---|---|
| **本地 ComfyUI** | `restart_comfyui.bat` 启动（8188，`--lowvram --async-offload 2`） | LTX 22B I2V，960×1728 |
| **云端 API** | `OpenMontage\.env` 填 key | `ARK_API_KEY`(Seedance)/`KLING_API_KEY`(可灵)/`FAL_KEY` 等，原生 1080p+ |

检查引擎可用性：

```powershell
venv\Scripts\python.exe -m engines.cli status
```

### 1.2 配置（`settings.yaml`，仓库根）

```yaml
engines:
  video_mode: auto        # auto=云端优先失败降级本地 | cloud | local | hybrid
  max_cost_per_clip_usd: 1.0
queue:
  max_concurrency: 2
  budget_usd: 10.0
```

## 2. 快速上手

### 2.1 用现成素材合成成片（最快验证，无 GPU/API 成本）

```powershell
# story2 的 17 段视频 + 配音 + 字幕 → 42s 成片
venv\Scripts\python.exe scripts\compose_story2.py
# 产物: output\story2_final_MMDD.mp4（960×1728 / 42s / 30fps）
```

### 2.2 本地真实生成一段视频（需 ComfyUI 在线，约 5-15 分钟/段）

```powershell
venv\Scripts\python.exe scripts\smoke_render.py [首帧图]
# 产物: output\local_clips\smoke_render.mp4 + 质量门报告
```

### 2.3 云端生成（需 key）

```powershell
# 1. 填 key 到 OpenMontage\.env（如 ARK_API_KEY=...）
# 2. 验证
venv\Scripts\python.exe -m engines.cli status    # 应显示 provider AVAILABLE
# 3. 用代码调用
```

```python
import asyncio
from engines.registry import EngineRouter
from engines.base import GenerateRequest

async def main():
    router = EngineRouter.from_settings()      # 从 settings.yaml 读配置
    req = GenerateRequest(
        prompt="a man walks into the city night, slow push-in, cinematic",
        first_frame="story2/shot_04_kf.png",   # I2V 首帧；None=纯 T2V
        duration_seconds=5.0,
        output_dir="output/cloud_clips",
    )
    clip = await router.generate(req)          # 云端优先，失败自动降级本地
    print("成片:", clip.video_path, "引擎:", clip.engine, "成本$:", clip.cost_usd)

asyncio.run(main())
```

## 3. 工业化 API（模块指南）

### 3.1 编排器（推荐入口）—— `pipeline/orchestrator.py`

```python
from pipeline.orchestrator import Orchestrator, SceneReq

orch = Orchestrator()          # 自动读 settings.yaml

# 阶段 1：批量生成场景视频段（多引擎 + 质量门 + 成本 + 断点续传）
manifest = await orch.run_assets([
    SceneReq(id="s1", prompt="cat walks to bowl", first_frame=Path("kf1.png"), duration_seconds=3),
    SceneReq(id="s2", prompt="man types at night", first_frame=Path("kf2.png"), duration_seconds=4),
], output_dir=Path("output/pipeline"))
# manifest.scenes[].video / engine / cost_usd / quality

# 阶段 2：合成成片（xfade + 配音对齐 + BGM + 字幕）
await orch.run_compose(
    [Path(m["video"]) for m in manifest["scenes"]],
    output=Path("output/final.mp4"),
    narration=Path("voice/narration.wav"),
    subtitles={"texts": [...], "timings": timings},
    bgm=Path("bgm/epic.mp3"),
)
```

### 3.2 引擎抽象 —— `engines/`

| 模块 | 作用 |
|---|---|
| `base.py` | `GenerateRequest` / `ClipResult` / `BaseEngine` 统一接口 |
| `cloud.py` | 10 个云端 provider（Seedance Ark/可灵/MiniMax/即梦/Grok/fal/Runway/Veo），key 缺失时清晰报错 |
| `local.py` | 本地 ComfyUI 引擎（LTX I2V/T2V，960×1728） |
| `quality_loop.py` | 生成→质量门→重试闭环（reseed→换引擎→改写 prompt） |
| `registry.py` | `EngineRouter`：auto/cloud/local/hybrid 路由 + 降级链 |

### 3.3 质量门 —— `quality/`

```python
from quality.gate import QualityGate
gate = QualityGate()
report = await gate.check_video(clip_path, expect_duration=5.0)
# report: {passed, resolution, duration, frames, checks, issues}

from quality.face import FaceConsistencyChecker
face = FaceConsistencyChecker()          # insightface 人脸一致性（依赖就绪后）
face_report = face.check_video(reference_img, clip_video)
```

### 3.4 队列与成本 —— `scheduler/`

```python
from scheduler.tasks import Task, TaskQueue
from scheduler.cost import CostTracker

tracker = CostTracker(budget_usd=10.0, mode="cap")
q = TaskQueue(max_concurrency=2, resume=True)
q.submit(Task(id="scene-1", run=my_async_fn, retries=2))
await q.run()
```

### 3.5 后期 —— `post/`

| 函数 | 作用 |
|---|---|
| `concat_xfade` | 多段 xfade 拼接（含音频轨） |
| `mux_narration` | 配音接入 + 时长对齐（视频短则冻结补帧） |
| `mix_bgm` | BGM 混音（对白 ducking） |
| `burn_subtitles` | ASS 字幕烧录 |
| `compose_video` | 一键全链合成 |
| `build_line_timings` | **逐句精确时间轴**（替代旧均分） |

## 4. 质量痛点 → 本流水线对应解法

| 痛点 | 旧问题（代码证据） | 新解法 |
|---|---|---|
| 画质糊 | LTX 640×320/672×1152 放大 1080p | 本地 960×1728；云端原生 1080p+ |
| 动作僵硬 | 视频 setpts 拉伸对齐配音 | 配音为准 + 视频冻结补帧（`mux_narration`），不改动作速度 |
| 字幕对不上 | 均分时间轴偏差 0.5-0.9s/句 | 逐句精确时间轴（`build_line_timings`） |
| 角色漂移 | 无自动检测 | `FaceConsistencyChecker` 人脸一致性门 |
| 质量不可控 | QA 只查文件完整性 | `QualityGate` + `GenerationGate` 自动重试 |
| 不可批量 | 单文件巨核顺序执行 | `TaskQueue` + `Orchestrator.run_assets` |
| 成本失控 | 无预算概念 | `CostTracker`（budget cap） |

## 5. 测试

```powershell
# 全量回归（9 套）
foreach ($t in 'test_engines_smoke','test_quality_gate','test_queue','test_quality_loop','test_pipeline_integration','test_orchestrator','test_orchestrator_compose','test_subtitles','test_compose') {
    venv\Scripts\python.exe tests\$t.py
}
```

## 6. 已知限制

- 云端实测需真实 key + 外网（当前环境网络不可达）
- insightface 人脸一致性需 pip 网络安装依赖
- main.py 旧管线尚未迁移到新引擎（P6 目标，API 层保持兼容）
