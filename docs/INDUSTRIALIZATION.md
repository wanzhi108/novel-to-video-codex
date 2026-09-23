# 工业化升级架构设计（INDUSTRIALIZATION PLAN）

> 版本：v1.0（草案）
> 目标：把 novel-to-video-codex 从"单文件巨核 + 本地 LTX 兜底链"升级为**模块化、配置驱动、双引擎（本地/云端）、质量门闭环、可批量生产**的工业化流水线。
> 决策输入：用户确认"云端为主（key 后补）、接受核心重构、全面解决画质/一致性/动作/音画/工程化问题"。

---

## 1. 现状与问题（代码事实）

| 维度 | 现状 | 代码证据 |
|---|---|---|
| 架构 | `scripts/main.py` 单文件 **11734 行**，承载 API 路由+ComfyUI 客户端+TTS+后期+LLM 集成 | main.py:1-11734 |
| 视频质量 | LTX 推理 672×1152 / 960×1728，短片段 ≤33 帧(1.4s) 循环填充，放大到 1080×1920 | `VID_WIDTH=672`、`_ltx_single LENGTH=min(frames,33)` |
| 降级链 | 无人物/全景→Ken Burns；LTX 失败→Ken Burns→静态图；TTS 失败→静音 | `_classify_scene_video_mode`、`generate_tts` 兜底 |
| 一致性 | 依赖 prompt 文本 + 可选 IP-Adapter/PuLID；无自动一致性检测 | `character_canonical`、`JOB_PORTRAIT_MAP` |
| 音画 | 视频 setpts 变速对齐音频；字幕按句数均分时间轴 | `combine_audio_video`、`build_ass` |
| QA | 只查时长/文件完整性，不查画质语义 | `run_qa_tests` |
| 工程化 | 无配置驱动、无批量队列、无成本统计、无回归测试 | — |
| 生成路径 | 仅本地 ComfyUI（8GB 显存 LTX 22B fp8），云端 key 未填 | `.env` 全空 |

---

## 2. 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│                    pipeline/ 编排器                          │
│   storyboard → prompts → assets → compose → qa → publish     │
│   (阶段可独立重跑，checkpoint 断点续传)                        │
└──────┬──────────────┬───────────────┬──────────────┬────────┘
       │              │               │              │
┌──────▼─────┐ ┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
│ engines/   │ │ quality/    │ │ post/       │ │ scheduler/ │
│ 生成引擎     │ │ 质量门       │ │ 后期         │ │ 批量队列    │
│ 适配器      │ │ 自动检查      │ │ 字幕/混音/    │ │ 并发/成本/  │
│            │ │ +重试策略    │ │ 转场/调色    │ │ 断点       │
└──────┬─────┘ └──────┬──────┘ └──────┬──────┘ └─────┬──────┘
       │              │               │              │
┌──────▼───────────────────────────────────────────▼──────┐
│              config/ 统一配置（YAML，驱动一切）              │
│   引擎选择/模型/分辨率/预算/并发/质量阈值/渠道规范              │
└──────────────────────────────────────────────────────────┘
```

### 2.1 模块划分（替代 main.py 巨核）

| 模块 | 职责 | 关键接口 |
|---|---|---|
| `pipeline/` | 阶段编排、checkpoint、进度广播 | `StoryboardStage` / `PromptStage` / `AssetStage` / `ComposeStage` / `QaStage` |
| `engines/` | 生成引擎统一抽象 + 各 provider 适配器 | `BaseEngine.generate_i2v() → ClipResult` |
| `quality/` | 自动质量检查与重试策略 | `QualityGate.check(clip) → Report` |
| `post/` | FFmpeg 后期 | `subtitle` / `mix` / `transition` / `grade` / `cover` |
| `scheduler/` | 批量队列、并发、成本 | `TaskQueue` / `CostTracker` |
| `storage/` | SQLite（沿用现有 `storage.py` 扩展） | `JobRepo` / `ClipRepo` / `QualityRepo` |
| `config/` | YAML 配置加载与校验 | `Settings`（pydantic） |
| `api/` | FastAPI 路由层（**对外接口不变**，前端零改动） | 现有 ~70 端点透传 |

### 2.2 生成引擎抽象（核心）

```python
# engines/base.py
@dataclass
class GenerateRequest:
    prompt: str                # 英文视频提示词（动作/运镜/情绪）
    first_frame: Path | None   # 首帧图（I2V）；None=纯 T2V
    last_frame: Path | None    # 尾帧（可选，双帧）
    width: int = 960
    height: int = 1728
    duration_seconds: float = 5.0
    fps: int = 24
    seed: int | None = None
    reference_images: list[Path] = []   # 角色参考图（一致性）
    budget: float | None = None         # 单段预算上限

@dataclass
class ClipResult:
    video_path: Path
    engine: str                # 实际使用的引擎名
    cost_usd: float
    duration_seconds: float
    seed: int
    quality_report: dict | None = None

class BaseEngine(ABC):
    name: str
    capability: str            # "i2v" | "t2v" | "both"
    @abstractmethod
    async def generate(self, req: GenerateRequest) -> ClipResult: ...
    def is_available(self) -> bool: ...      # key/依赖检查
    def estimate_cost(self, req) -> float: ...
```

**引擎注册表**（`engines/registry.py`）：
- 本地：`ComfyUIEngine`（LTX 22B / Wan2.1，封装现有 video_engine 逻辑）
- 云端：`FalEngine`（Kling / Veo / MiniMax H3 / Seedance / FLUX）、`KlingOfficialEngine`、`SeedanceArkEngine`、`MinimaxEngine`、`JimengEngine`、`RunwayEngine`、`GrokEngine`
- 路由策略（`engines/router.py`）：`video_mode: "auto" | "local" | "cloud" | "hybrid"` + 每 provider `priority` / `max_cost_per_clip` / `min_quality_score`。默认 `auto`：cloud 优先（key 就绪且预算内），失败/低于质量线→降级 local，都失败→Ken Burns 兜底（记录 downgrade 原因）。

### 2.3 质量门（quality/）

每个 clip 生成后**强制**过门，失败触发重试（最多 2 轮，换 seed → 换引擎 → 重写 prompt）：

| 检查项 | 实现 | 阈值 |
|---|---|---|
| 技术完整性 | ffprobe：时长/分辨率/码率/静态帧率 | 时长≥要求的 80%，帧率≥24 |
| 画质评分 | CLIP 美学评分 / 无参考 IQA（如 musiq），可选 | ≥ 配置阈值（可调） |
| 人脸一致性 | insightface 余弦相似度（复用 story2 `check_anchor.py` 经验），首帧 vs 视频帧 | ≥0.5，主角镜头必检 |
| 角色/环境锚定 | 首帧 vs 参考图相似度（LPIPS/CLIP） | ≥ 阈值 |
| 音画同步 | 音频时长 vs 视频时长、字幕时间轴覆盖率 | ±10%，字幕覆盖≥90% |
| 内容安全 | DeepSeek 审核（复用现有 `content_safety_check`） | pass |

`quality/` 输出 `quality_report.json` 落到项目目录，前端可展示；QA 阶段汇总成 `final_review`。

### 2.4 配置驱动（config/settings.yaml 示例）

```yaml
project:
  title: ""
  channel: hongguo          # 渠道规范：红果 1080×1920 竖屏 30fps
  max_scenes: 0

engines:
  video_mode: auto          # auto | local | cloud | hybrid
  priority: [fal, kling_official, seedance_ark, minimax, comfyui]
  max_cost_per_clip_usd: 0.5
  local:
    checkpoint: ltx-2.3-22b-dev-fp8.safetensors
    width: 960
    height: 1728
    frames: 65
    fps: 24
  cloud:
    resolution: [960, 1728]     # 各 provider 实际档位
    duration: 5

quality:
  min_duration_ratio: 0.8
  min_frames: 24
  face_similarity: 0.5
  max_retries: 2
  retry_strategy: [reseed, switch_engine, rewrite_prompt]

queue:
  max_concurrency: 2
  budget_usd: 10.0
  resume: true                # 断点续传

tts:
  engine: cosyvoice2          # cosyvoice2 | edge | cloud(后补)
  voices: {narration: cn03, wang: cn07, yang: cn06}

subtitles:
  style: ass
  timing: line_accurate       # 逐句精确（替代均分）
```

### 2.5 兼容层

- FastAPI 路由层保留现有路径与请求/响应结构，`web/` 前端**零改动**。
- 内部把 `_run_generate_pipeline` 替换为 `pipeline.Orchestrator.run()`，行为渐进切换（先并行保留旧实现，diff 验证后下线）。
- `storage.py` 扩展表：`clips`（每段视频+引擎+seed+cost+quality）、`quality_reports`、`cost_log`。

---

## 3. 实施阶段

| Phase | 内容 | 交付 | 依赖 |
|---|---|---|---|
| **P0** | 本设计定稿 | 本文档 | — |
| **P1** | 模块骨架 + config + 本地引擎封装（从 main.py 抽取，**行为不变**） | `pipeline/` `engines/` `config/` 可运行；API 透传测试通过 | — |
| **P2** | 云端引擎适配器 + 双引擎路由 | FalEngine/KlingOfficial/SeedanceArk/MiniMax + router；key 空时清晰报错并可降级 local | 用户填 key |
| **P3** | 质量门 + 重试策略 | 画质/一致性/音画检查闭环；quality_report 落盘 | P1 |
| **P4** | 批量队列 + 成本统计 + 断点续传增强 | scheduler/ cost/ 落地 | P3 |
| **P5** | 验收：新故事出高质量样片（云端为主），对比旧版 | 2 条成片 + 对比报告 | P2-P4 + key |
| **P6**（可选） | 接入 OpenMontage 作为第二条出片路径（Remotion 包装） | 管线互操作 | P5 |

---

## 4. 关键风险与对策

| 风险 | 对策 |
|---|---|
| 重构引入回归 | P1 阶段新旧实现并行、API 透传 diff 测试；`max_scenes`/小故事冒烟 |
| 云端 key 未填导致 P2 不可测 | 适配器带 mock 模式（dry-run 打日志）；路由在 key 缺失时自动走 local |
| 国内网络访问 fal.ai 不稳 | 优先国产直连（可灵官方/Seedance Ark/即梦），fal 作为备选 |
| 云端成本失控 | `max_cost_per_clip_usd` + 总预算 `budget_usd` + CostTracker（沿用 OpenMontage cost_tracker 思路） |
| 角色一致性在云端 I2V 中漂移 | 首帧+参考图传入（Kling/Seedance 支持 reference），质量门人脸一致性兜底重试 |

---

## 5. 与现有代码的关系

- `scripts/main.py`：**逐步瘦身**，最终只保留 API 路由层 + 旧逻辑适配壳；删除死代码 `app/services/comfyui_client.py`。
- `scripts/video_engine.py`：降级为 `engines/local/comfyui.py` 的内部实现（保留 8 模式路由作为本地引擎的降级链）。
- `story2/`：保留为独立确定性管线；其 `gen_ltx.py` 的韧性模式（孤儿回收/无限重试）经验移植到 `scheduler/`。
- `OpenMontage/`：作为 P6 的第二出片路径与 provider 知识库；云端工具实现直接参考其 `tools/video/*`。

---

## 6. 实施进度（实时更新）

| Phase | 状态 | 交付物 |
|---|---|---|
| P0 设计定稿 | ✅ | 本文档 |
| P1 模块骨架 + 本地引擎 | ✅ | `engines/base.py`、`engines/local.py`（ComfyUIEngine）、`tests/test_engines_smoke.py`；真实出片冒烟：LTX I2V 已成功提交 ComfyUI（`scripts/smoke_render.py`） |
| P2 云端引擎 + 路由 | 🔶 引擎层完成，待 key 实测 | `engines/cloud.py`（10 provider）、`engines/registry.py`（auto/cloud/local/hybrid 路由+降级）、`engines/cli.py` |
| P3 质量门 | ✅ L1+L2 框架 + 闭环 | `quality/gate.py`、`quality/face.py`（insightface，降级路径验证）、`engines/quality_loop.py`（reseed/switch_engine/rewrite_prompt）、测试通过 |
| P4 批量队列 + 成本 | ✅ | `scheduler/tasks.py`（TaskQueue：并发/重试/断点续传）、`scheduler/cost.py`（CostTracker：estimate→reserve→reconcile）、测试通过 |
| 配置驱动 | ✅ | `config/settings.py` + `settings.yaml` |
| 编 排器 | ✅ 全阶段 | `pipeline/orchestrator.py`：`run_storyboard`（DeepSeek 分镜）+ `run_assets`（批量生成）+ `run_compose`（成片）；`pipeline/storyboard.py`（DeepSeek 分镜，实测生成 5-6 镜英文 prompt） |
| 一键入口 | ✅ | `scripts/industrial_pipeline.py`：小说 → DeepSeek 分镜 → 合成成片（`--dry-run`/`--demo`）；实测跑通 |
| 质量门闭环 | ✅ 技术+视觉双层 | `engines/quality_loop.py`：`GenerationGate` 支持 `visual_gate`（可选），生成后除技术/静态/时长/音频检查外，额外跑 `quality/visual.assess_video`（清晰度 Laplacian 方差 + 首尾帧像素差异运动检测），"画面糊/动作僵硬"自动触发 reseed/换引擎重试；`tests/test_visual_gate.py` |
| P2 云端引擎 | 🔶 就绪待 key | 网络已恢复（代理 127.0.0.1:7897）；无 key 时清晰报错降级已验证；**云端实测待用户填 key** |
| face.py 真实检测 | 🔶 有替代 | insightface 依赖（onnxruntime 约 500MB）在代理下下载超时；新增 **`quality/visual.py`**（无参考画质评估，Pillow+numpy 零重依赖）：`sharpness`(Laplacian 方差)/`is_black`/`assess_video`(清晰度+运动检测)——能量化"画面糊"与"动作僵硬"，`tests/test_visual.py` |
| 分镜（DeepSeek） | ✅ 已实现并真实调用 | `pipeline/storyboard.py`：`call_deepseek`（httpx+代理，重试+截断扩容）、`generate_storyboard`（长文分块+分镜解析）；实测生成 5-6 个英文 prompt 分镜 |
| P2 云端引擎 | 🔶 就绪待 key | 网络已恢复（代理 127.0.0.1:7897）；`engines/cli status` 检测 provider；无 key 时清晰报错降级已验证；**云端实测待用户填 key** |
| 本地优化：字幕 | ✅ | `post/subtitles.py`（**逐句精确时间轴**，替代旧均分逻辑；均分偏差实测 0.5-0.9s/句）、`tests/test_subtitles.py` |
| 后期合成 | ✅ 工业化 | `post/compose.py`：`concat_xfade`（链式 xfade，offset 计算已修）、`mux_narration`（配音接入+时长对齐：视频短则冻结补帧）、`mix_bgm`、`burn_subtitles`、`compose_video`（一键全链）；`tests/test_compose.py`、`tests/test_orchestrator_compose.py` |
| P5 样片验收 | 🔶 **本地完整样片已产出** | `scripts/compose_story2.py`：story2 17 段 LTX 素材 → **`output/story2_final_0829.mp4`（42s, 960×1728, 30fps, 14.6MB）**：xfade 拼接 → 配音对齐（tpad 补帧）→ BGM → 精确字幕；质量门全 PASS；云端样片待 key |

**P5 本地样片成果**（`output/story2_final_0829.mp4`）：
- 4 镜 17 段 LTX 视频 xfade 拼接（修复链式 xfade offset 计算 bug——旧实现只拼前 2 段）
- 视频无音频轨 → 配音直接作音轨；视频短于配音 → `tpad` 冻结末帧延展（保动作原生节奏 + 保全部台词）
- 精确逐句 ASS 字幕（4 场景时间轴合并）
- BGM ducking 混音；成片 960×1728 / 42s / 1259 帧 / 质量门 PASS
| P6 OpenMontage 互操作 | ⬜ | 可选 |
| P6 桌面接入（新引擎+质量门进 exe） | ✅ | `scripts/industrial_bridge.py`（新引擎优先、旧引擎兜底）、`scripts/main.py` 接入点、`luminaforge.spec` 打包 engines/quality/config、重新构建 `LuminaForge.exe`；`LF_INDUSTRIAL=0` 可关闭 |

> ⚠️ 命名注意：`queue/` 曾遮蔽 Python 标准库 `queue`（导致 httpx 导入失败），已更名为 **`scheduler/`**。新增 Python 包时避免与标准库同名。

**运行方式**：
- 引擎诊断：`python -m engines.cli status`（工作区根，用 `venv` Python）
- 测试：`venv\Scripts\python.exe tests\test_engines_smoke.py`、`tests\test_quality_gate.py`

**下一步（阻塞项）**：用户向 `OpenMontage/.env` 填入真实云端 key（推荐 `ARK_API_KEY` 或 `KLING_API_KEY`）后，`python -m engines.cli status` 应显示对应 provider AVAILABLE，随即用 `engines.registry.EngineRouter` 实测云端出片并进入 P3-L2/P4。

**当前测试命令**（仓库根，用 `venv` Python）：
```powershell
venv\Scripts\python.exe tests\test_engines_smoke.py     # 引擎模板填充
venv\Scripts\python.exe tests\test_quality_gate.py      # 质量门 4 场景
venv\Scripts\python.exe tests\test_queue.py             # 队列/成本
venv\Scripts\python.exe tests\test_quality_loop.py      # 质量门闭环
venv\Scripts\python.exe tests\test_pipeline_integration.py  # 骨架端到端
```

**待办**：
- insightface（人脸一致性）依赖安装中（清华镜像）；装好后跑 `quality/face.py` 真实检测（参考图 `story2/shot_01_kf*.png` vs 生成视频）。
- P2 云端实测（等 key）→ P5 样片验收。

---

## 7. LTX 22B 质量调优结论（2026-08 实测）

用《雨夜的便利店》做了三轮参数对照实验（8GB 显存 / 16GB 内存）：

| 配置 | 单段 | 成片视觉门 | 结论 |
|---|---|---|---|
| 65 帧 + 8+3 步（旧默认） | 2.7s | ❌ FAIL（2/6 镜模糊，sharp 31.8） | 基线 |
| 96 帧 + 12+6 步 | 4.0s | ❌ FAIL（sharp 31.8） | **步数过多反而糊**（蒸馏模型特性） |
| **96 帧 + 8+3 步（现默认）** | **4.0s** | ✅ **PASS（sharp 54.5）** | **16GB 下质量甜点** |

**结论与固化**：
1. **帧数 65→96（+48%）**：动作更完整（2.7s→4s），且不糊 —— 真正的质量提升。
2. **步数恒为 8+3**：LTX 是蒸馏模型，加步数（12+6）反而引入伪影导致模糊；已在 `engines/local.py` 固定用 `img2vid`（8+3 步）。
3. **关键帧 sharpness 把关**（<40 自动换 seed 重生成）+ **视觉门**（模糊/静态自动重试）：保证每段清晰。
4. 已固化到 `settings.yaml`：`engines.local.quality: high`、`frames: 96`；`local_pipeline.py` 从配置读取（配置驱动）。

**可复现**：`venv\Scripts\python.exe scripts\local_pipeline.py output\novel_rain_cat.txt --limit-scenes 2`（产出 `output/local_final_raincat_hq.mp4`，sharp 54.5 PASS）。

**硬件边界**：16GB 内存下 LTX 22B（96帧+8步）已是质量上限；更高质量需加内存至 32GB 后上 MiniMax H3（`scripts/download_h3.py` 已备好，H3 节点/工作流/引擎骨架已就绪）。

---

## 8. P6 桌面应用接入（LuminaForge.exe 用上新引擎）

**目标**：让桌面应用（`scripts/launcher.py` + `scripts/main.py` + React 前端打包的 `LuminaForge.exe`）的视频生成走工业化新引擎 + 质量门，而不是旧的 365 行内联调度。

**接入方式（最小侵入，新引擎优先、旧引擎兜底）**：

1. **`scripts/industrial_bridge.py`（新增）**：桥接模块，刻意不 import `scripts/main.py`（避免巨核循环依赖），只依赖 `engines/`、`quality/`、`config/` 新包。
   - 入口 `async generate_scene_video(job, scene, scene_dir, vid_base_prompt, first_frame, timeout_seconds=2400.0) -> Optional[str]`
   - 内部：`ComfyUIEngine(quality=settings.engines.local.quality)`（96帧/4s、8+3步，由 `settings.yaml` 驱动）→ `GenerationGate`（`QualityGate` 技术门 + `assess_video` 视觉门）→ 未过门自动 reseed 重试 → 仍失败返回 `None`。
   - 开关：环境变量 `LF_INDUSTRIAL=0` 关闭新引擎（全部走旧调度），默认开启。
   - 打包模式下优先读 **exe 旁**的 `settings.yaml`（用户可写），否则用默认（默认即调优值 high/96）。

2. **`scripts/main.py`（改动 1 处）**：`_generate_scene_impl` 的 Step 2 图生视频，在 `video_engine.dispatch(...)` 之前先调用 `industrial_bridge.generate_scene_video(...)`：
   ```python
   current_vid = None
   try:
       from industrial_bridge import generate_scene_video as _ind_gen
       current_vid = await _ind_gen(job, scene, scene_dir, vid_base_prompt, local_img)
   except Exception as e:
       print(f"[Industrial] 桥接调用异常({str(e)[:120]})，回退旧引擎", flush=True)
       current_vid = None
   if not current_vid:
       current_vid = await video_engine.dispatch(scene, scene_dir, vid_ctx)
   ```
   新引擎成功 → 用高质量 96 帧视频；失败/离线/质量门不过 → 回退旧引擎，**桌面 UI 永远有结果**。

3. **`luminaforge.spec`（打包配置）**：
   - 入口修正：`Analysis(['scripts/launcher.py'], pathex=[project_dir, project_dir/scripts])`（launcher.py 实际在 scripts/ 下）。
   - `datas` 新增 `engines/`、`quality/`、`config/`、`settings.yaml`（exe 旁可覆盖）。
   - `hiddenimports` 新增 `industrial_bridge`、`engines.*`、`quality.*`、`config.settings`、`yaml`。

4. **构建**：`venv\Scripts\python.exe -m PyInstaller --noconfirm --clean luminaforge.spec` → `dist/LuminaForge.exe`（安装到 `%USERPROFILE%\AppData\Local\Programs\LuminaForge\`）。

**验证**：`venv\Scripts\python.exe scripts\smoke_p6.py`（桥接导入/配置读取/请求构造）；`tests/` 12/12 全绿；桌面应用启动后 `/api/health` 正常、视频生成日志出现 `[Industrial] ✓ 场景 … 通过质量门`。

**P6 实测（2026-08-31，桌面 exe 端到端）**：
- 构建：`dist/LuminaForge.exe`（40.4MB，含 pywebview 内嵌 WebView2 + engines/quality/config 新模块）。
- 用 `POST /api/retry-scene/{job}/{scene}` 触发单场景生成，日志确认走新引擎：
  `[Industrial] 场景 1: LTX I2V 96f@24fps (4.0s) 质量门闭环生成中…` → `[ComfyUIEngine] 已提交 (I2V, 96f@24fps)` → `[Industrial] ✓ 场景 1: industrial_1.mp4 通过质量门 (sharp=369.3, motion=0.1107)`。
- 新旧对比（同场景 scene_001）：工业引擎 `sharp_min=369.3 PASS` vs 旧引擎 `sharp_min=11.4 FAIL（模糊）` —— 桌面应用出片质量已切换为工业化版本。
- 排查并修复了两个桌面端问题：① `launcher_config.json` 被写为带 BOM 的 UTF-8 导致 `json.load` 失败（DeepSeek key 读不到）→ 改为无 BOM UTF-8；② venv 缺 `pywebview` → exe 回退浏览器模式 → 安装 pywebview 6.2.1 后重打包恢复内嵌窗口。

**注意**：`queue/` 遮蔽 stdlib `queue` 的教训同样适用于打包——新包名 `engines`/`quality`/`config` 均不与 stdlib 冲突；`config` 与 `app/config.py` 共存（不同包），已在打包中验证。
