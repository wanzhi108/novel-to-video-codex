# AI 漫剧制作 Skill / 插件生态调研报告（2026-09）

> 调研目标：为 novel-to-video-codex（墨影流光/LuminaForge，小说→竖屏漫剧本地流水线：
> DeepSeek 分镜 → SDXL 关键帧 → LTX 2.3 22B 图生视频 → 配音 → 字幕 → 合成，8GB 显存）
> 寻找"非常好用、可装进来"的 skill 或插件。
> 调研方式：web_search ×3 轮 + 4 个并行子代理深挖 + GitHub API 实测（star/推送/许可）。

---

## 一、结论速览（按"能直接装进本项目"排序）

| 优先级 | 名称 | 形态 | 装到哪 | 一句话 |
|---|---|---|---|---|
| ★★★ | **ComfyUI-Novel-Director** | ComfyUI 插件 | `custom_nodes/` | 整剧批量流水线：选角锁脸→剧本/分镜→逐镜批量→音画对齐→自动合并，引擎无关可驱动 LTX-2.3 |
| ★★★ | **Dramake（ai-short-drama-skill）** | Agent Skill | `.codex/skills/dramake/` | 剧本/分镜/质检/发布全环节导演级 Skill（视频后端需从云端换成本地 LTX） |
| ★★☆ | **TE_MAN** | ComfyUI 插件 | `custom_nodes/` | 首个 ComfyUI 漫剧/增强生图/生视频插件，387★ 活跃 |
| ★★☆ | **ComfyUI-Storyboard-LLM** | ComfyUI 插件 | `custom_nodes/` | 小说章节→分镜表（仅需 LLM API，零显存） |
| ★★☆ | **cast-lock-skill** | Agent Skill | `.codex/skills/` | 连载角色一致性"提示词锁定"，零显存，8GB 友好 |
| ★★☆ | **comicframes** | Python 库 | pip 进 venv | 分镜解析 + RIFE/FILM 插帧微动效，8GB 可跑 |
| ★☆☆ | **ComfyUI-H3-Prompt-Builder** | ComfyUI 插件 | `custom_nodes/` | 剧本→分镜→逐镜提示词（面向 MiniMax H3 格式，跑 LTX 需微调） |
| ★☆☆ | **LTX-2.3 官方 Anime2Real 工作流** | 工作流 | comfy.org | 9:16 动漫转写实官方工作流，可参考提示词/接线 |

---

## 二、Agent Skills（装到 `.codex/skills/<name>/SKILL.md`）

### 1. Dramake — xixihhhh/ai-short-drama-skill ★9 MIT（⭐最贴合"skill"诉求）
- **形态确认**：标准 Agent Skill（`skills/dramake/SKILL.md`，YAML frontmatter + 正文），支持 Codex / Claude Code / WorkBuddy；`npx skills add xixihhhh/ai-short-drama-skill --skill dramake` 即可装，或复制目录。
- **能力**：一句话/小说/剧本 → 剧本诊断、编剧、分镜、角色/道具一致性、模型选路（Wan3/Seedance/MiniMax H3）、15–30s 长段、原生对白、配音、预算、连续性剪辑、物理质检、冷观众验收。10 条铁律（因果链、静音可懂、锁身份/材质/服装、接触物理、文字后期叠加等）非常有工业化参考价值。
- **适配本项目的关键**：视频后端指向**云端 API**；要接本地 LTX 需把"模型选路"段改写为调用本项目 `engines/local.py` / `industrial_bridge.py`（P6 已完成的可复用）。
- **装后用法**：`使用 Dramake，把这段故事做成 90 秒竖屏漫剧，视频走本地 ComfyUI LTX…`

### 2. cast-lock-skill — yazelin/cast-lock-skill ★1 MIT
- 连载插画/漫画的角色一致性技能——把角色外貌/服装锁定为提示词常量，防止跨镜漂移。零显存，与现有 SDXL+IPAdapter 互补（它是"文本层"锁定，IPAdapter 是"图像层"锁定）。

### 3. fiction-to-ai-video-production — FuFicFac ★(新)
- Codex skill：小说散文 → AI 视频生产包（剧本/分镜/提示词等前置环节），awesomeskills.dev 收录。

### 4. LobeHub 市场（image-video-generation 类）
- `manga-drama`（freestylefly/canghe-skills，漫剧）、`comfyui-video-pipeline`（对接本地 ComfyUI）、`manga-novel-generator`、短剧剧本类——形态多为复制目录安装；质量参差，需逐个 clone 核实。

> ⚠️ 2025 下半年短剧/漫剧 skill 爆发，同质仓库很多（Hao0321/ai-short-drama、zenstory-ai/drama-skills、jxshow/jingju-skills 等），**无现成"绑定本地 ComfyUI LTX"的成熟包**——都需做视频后端本地化改写，这正是本项目 P1–P6 已铺好的路基。

---

## 三、ComfyUI 插件（装到 `D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\`）

> ⚡ 关键环境事实：你的 ComfyUI 整合包名为 **WorkFisher-V2**，而 Novel-Director 正是 **Work-Fisher 组织**出品——同源，兼容性风险最低。

### 1. ComfyUI-Novel-Director ★208（⭐ComfyUI 侧首选）
- **功能**：有声小说/短剧/动态漫一键流水线：选角（6人/节点可串联，参考图供 IP-Adapter 锁脸）→ 有声剧/分镜/运镜 JSON → Scene Iterator 逐场景流式批量 → TTS 适配（Qwen-TTS/GPT-SoVITS 音色库）→ 按音频时长算帧数+缓冲帧 → 自动合并 `Final_Movie.mp4`。
- **引擎无关**：视频生成仍用你自己的 LTX-2.3 节点。
- **安装**：`git clone https://github.com/Work-Fisher/ComfyUI-Novel-Director.git` → `pip install -r requirements.txt` → 重启。
- **与本项目的配合**：它的 JSON 剧本输入可来自本项目 DeepSeek 分镜输出；它的批量/合并能力可替代本项目部分 `post/compose.py` 职责（或互补）。

### 2. TE_MAN — tl2012tl/TE_MAN ★387（NOASSERTION 许可，需自查）
- "首个为 ComfyUI 打造的漫剧/增强生图/生视频插件"，2026-08 仍活跃。覆盖漫剧增强出图/出视频。

### 3. ComfyUI-Storyboard-LLM — Lbunc ★3 MIT
- 小说章节 → storyboard 表格（ComfyUI 节点），仅需 LLM API（DeepSeek 兼容），零显存——可作为本项目分镜能力的可视化补充。

### 4. ComfyUI-H3-Prompt-Builder ★15
- 短剧剧本 → 分镜 JSON → 逐镜提示词（H3 官方三字段格式）+ 角色/场景/道具资源映射（每镜 ≤9 参考图）。纯文本节点，DeepSeek 可用。**注意**：格式面向 MiniMax H3；跑 LTX-2.3 需做提示词格式微调（节点输出的 JSON/接线仍可复用）。

### 5. ComfyUI_MangaNinjia ★58（smthemex）
- MangaNinja 线稿上色（精确参考跟随），适合漫画转绘环节。

### 6. 视频引擎/一致性（你已有，标注定位）
- **LTX-2.3**：ComfyUI 官方原生支持，无需 wrapper（你已跑通）；官方低显存指南 + comfy.org 市场《LTX 2.3 - Anime2Real》9:16 工作流可参考。
- **ComfyUI-WanVideoWrapper** 6682★：Wan 2.1/2.2，8GB 需 fp8/GGUF 量化（你已装，作备选）。
- **IPAdapter-Plus FaceID / ReActor / 角色 LoRA**：对 **animagine 动漫** 角色一致性，InstantID/PuLID 适配差（写实向），IPAdapter FaceID + 逐角色 LoRA 是正解（你已装 IPAdapter_plus）。
- H3 生态（仅当你上 MiniMax H3-22B 时）：Fantastic-MiniMaxH3-PromptBuilder 134★、MiniMax-H3-LongMedia 145★（带低显存保护，8GB 友好）、H3-Conditioning-Cache-AI-Drama-Production-Suite 16★（预编码 .pt 缓存抽卡）。

---

## 四、独立全流程工具（参考/可选部署，非"插件"）

| 项目 | star | 许可 | 定位 | 与本项目关系 |
|---|---|---|---|---|
| **LocalMiniDrama** | 1512 | MIT | Electron 本地一站式（剧本→角色→分镜→成片），数据不出本机 | 形态最贴近"本地优先"，可作 UI/流程对照；JS 栈，难直接复用 |
| **wind-comic** | 553 | MIT | Next.js 多 Agent 工作室，Provider 无关（可接 ComfyUI） | 架构参考价值高（角色一致/分集），重 TS 栈 |
| **openframe** | 110 | AGPL-3.0 | 漫剧创作工作台，FCPXML/EDL 导出 | 剪辑导出（PR/达芬奇）能力值得借鉴 |
| **novelvids（猫影短剧）** | 288 | CC BY-NC | FastAPI+Vue 生产平台，纯云端视频 API | 流程设计参考；许可与云端依赖不适合直接装 |
| **Koma Studio** | 93 | GPL-3.0 | 本地桌面漫剧工具，Provider 框架（ComfyUI/Kling/Runway） | 桌面形态对照 |
| **ai-comic-studio** | 10 | Apache-2.0 | 漫剧工作流（源自 AIComicBuilder） | 轻量参考 |

---

## 五、建议行动（按增量价值排序）

1. **装 ComfyUI-Novel-Director**（同源、208★、直接驱动 LTX）→ 整剧批量 + 锁脸 + 音画对齐。
2. **装 Dramake skill** → 拿到工业化"剧本→分镜→质检→发布"方法论；再写一个薄包装 skill 把它的视频段指向本项目本地引擎（复用 P6 的 industrial_bridge）。
3. **装 cast-lock-skill** → 跨镜角色一致性文本锁定（零成本）。
4. **评估 TE_MAN**（387★ 活跃）→ 若其漫剧增强工作流质量高，可纳入。
5. **comicframes**（可选）→ 如需"静态分镜微动效"风格而非全 LTX 视频时启用。
6. 全程注意：ComfyUI 插件装后重启；skill 装后新会话生效；许可自查（TE_MAN/MangaNinjia 未标注 SPDX）。

## 六、数据来源

GitHub API 实测（star/许可/推送日期）、各仓库 README/SKILL.md 原文抓取、
LobeHub skills 市场、comfy.org 工作流市场、阿里云开发者社区（8G 漫剧全开源方案 1753130）、CSDN 一致性方案汇总。

---

## 七、已安装与对接交付（2026-09-02）

### 已安装
1. **ComfyUI-Novel-Director** → `D:\ComfyUI-WorkFisher-V2\ComfyUI\custom_nodes\ComfyUI-Novel-Director\`
   （10 节点已加载验证：DirectorCasting / AudioScriptLoader / VisualStoryboardLoader / VideoPromptLoader / SceneIterator / AudioFrameCalc / OrderGate / StreamSaver / FinalRender / DictToString）
2. **Dramake skill** → `%USERPROFILE%\.codex\skills\dramake\`（SKILL.md v0.6.0 + 22 references + 18 模板）
3. **LuminaForge 本地漫剧包装** → `%USERPROFILE%\.codex\skills\luminaforge-local-dramake\`
   （薄层：Dramake 方法论 × 本地 LTX 引擎路由，视频段全走 `engines/local.py`，不碰云端生成 API）

### 对接脚本（本项目内）
- **`scripts/novel_director_bridge.py`**：小说/分镜 → Novel-Director 三份 JSON
  （`audio.json` role_list+juben / `visual.json` storyboard_list / `video.json` video_prompts）。
  已实测《雨夜的便利店》：4 角色/15 台词行/6 镜/6 运镜，并用 Novel-Director 真实解析器
  （`novel_nodes.py` 的 parse_* 方法）验证全部可解析且数量一致。示例产物：`output/nd_demo/`。

### 用法
- **ComfyUI 路径**：`scripts\novel_director_bridge.py novel.txt --out output\nd_project`
  → 三份 JSON 分别粘贴到 DirectorAudioScriptLoader / DirectorVisualStoryboardLoader / DirectorVideoPromptLoader。
- **Codex 路径**：新会话中说"用 luminaforge-local-dramake 把这篇小说做成本地漫剧"。
