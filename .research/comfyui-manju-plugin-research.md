# ComfyUI 漫剧/短剧/竖屏动画插件调研（2026）

> 场景：LTX 2.3 22B fp8 + RealVisXL/animagine SDXL，8GB 低显存，竖屏 9:16 漫剧（小说转视频、角色一致性）。
> 调研方式：web_search + GitHub API（star/最后推送为 API 实测）。注：用户称 "LTX 2.3 22B fp8"，ComfyUI 官方文档确认 LTX-2.3 原生支持；"H3" 系工具面向 MiniMax H3-22B（同为 22B，但属另一模型/节点栈）。

## 1. 逐候选详情

### 1.1 jiel71365-commits/ComfyUI-H3-Prompt-Builder（短剧剧本转分镜提示词）
- 功能：把剧本→分镜 JSON→逐镜 H3 官方规范提示词（三字段 integrated_multimodal_description / Ref2VA 六段式），含角色/场景/道具资产提取与参考图资源映射（每镜接线 ≤9 图）。
- 节点形态：6 个纯文本节点（漫剧预设默认 9:16 / 剧本→分镜 / 资源映射 / 分镜→镜头提示词 / LLM 配置 / H3 Prompt Builder），输出接 Show Text。
- 依赖：无本地模型；仅需 OpenAI 兼容 LLM API（config.json，默认 DeepSeek），纯文本 → 几乎零显存。
- 8GB 适配：高（不吃显存）。
- 安装：复制目录到 custom_nodes 或 git clone + 重启 ComfyUI；填 config.json API key。
- 活跃度：15★，最后推送 2026-08-26（活跃），内置 54 项自检。
- 适配评分：**中**（目标格式/接线面向 MiniMax H3 官方节点 MiniMaxH3ImageToVideo/ReferenceToVideo；若实际跑 H3-22B 则高；跑 LTX-2.3 时 JSON 与提示词文本可复用、需按 LTX 提示词习惯微调）。
- 来源：https://github.com/jiel71365-commits/ComfyUI-H3-Prompt-Builder

### 1.2 Work-Fisher/ComfyUI-Novel-Director（automated storytelling）
- 功能：有声小说/短剧/动态漫一键流水线：选角（6 人/节点，可串联无限角色，参考图供 IP-Adapter 锁脸）→ 有声剧/分镜/运镜 JSON 加载（LLM 生成）→ Scene Iterator 场景流式自动批量（对齐文本/语音/画面/运镜）→ TTS 适配（Qwen-TTS 角色名前缀、GPT-SoVITS 音色字典）→ 按音频时长算帧数+缓冲帧 → 逐镜存档 → ffmpeg 自动合并 Final_Movie.mp4 并可回传 ComfyUI。
- 节点形态：约 8 个编排/逻辑节点，视频生成用你自己的节点（LTX-2.3/Wan 均可接入）。
- 依赖：LLM JSON 剧本（外部生成）；TTS 可选；锁脸需 IPAdapter-Plus；视频引擎自备。逻辑节点不吃显存。
- 8GB 适配：高（本体轻量；显存压力集中在所接视频引擎）。
- 安装：git clone https://github.com/Work-Fisher/ComfyUI-Novel-Director.git 到 custom_nodes → pip install -r requirements.txt → 重启。
- 活跃度：208★，最后推送 2026-02-27。
- 适配评分：**高**（竖屏漫剧批量分集、角色一致性、音画对齐正是其设计目标；引擎无关）。
- 来源：https://github.com/Work-Fisher/ComfyUI-Novel-Director

### 1.3 角色一致性节点（InstantID/PuLID/anime）
- InstantID：仅写实 SDXL；对 anime/animagine 系 checkpoint 支持差。PuLID：SDXL/Flux 向，动漫适配弱。→ 对 anime 场景适配 **低**。
- 适用做法：IPAdapter-Plus FaceID（InsightFace）锁脸、ReActor 换脸（SDXL 可）、每角色训练 LoRA（最稳）；中文汇总文：CSDN《11 ComfyUI 一致性方案全解析》。
- comfyui.org 站内《漫画/小说视频自动重绘工具》：https://comfyui.org/zh/manga-novel-video-auto-repaint-tool
- 来源：https://blog.csdn.net/weixin_43951955/article/details/160287011、https://comfyui.org/zh/manga-novel-video-auto-repaint-tool

### 1.4 视频引擎节点（LTX-2.3 / Wan / CogVideoX 包装器）
- **LTX-2.3**：ComfyUI 官方原生支持（docs.comfy.org tutorials/video/ltx/ltx-2-3，含工作流示例），**无需 wrapper**；LTX 官方低显存运行指南 + 社区本地部署低显存优化教程；comfy.org 市场官方工作流《LTX 2.3 - Anime2Real（动漫转写实）》9:16 竖屏可用 → 高适配。
- kijai/ComfyUI-CogVideoXWrapper：1551★，最后推送 2025-08（用户已在用；面向 CogVideoX/CogVideoX-Fun 动漫模型，非 LTX）。
- kijai/ComfyUI-WanVideoWrapper：6682★，最后推送 2026-05（Wan 2.1/2.2，社区有 Wan 2.2 Qwen 多角度 9:16 工作流；模型体量大，8GB 需 fp8/GGUF 量化，紧张）→ 中适配，作备选引擎。
- VideoHelperSuite（Kosinkadink）是抽帧/拼接/解析视频的必备基础件。
- 来源：https://docs.comfy.org/zh/tutorials/video/ltx/ltx-2-3、https://comfy.org/zh/workflows/6fec31e40f4a-6fec31e40f4a/、https://github.com/kijai/ComfyUI-WanVideoWrapper、https://github.com/kijai/ComfyUI-CogVideoXWrapper、https://ltx.io/blog/run-video-generation-model-locally、https://wavespeed.ai/blog/zh-CN/posts/ltx-2-3-portrait-video-9-16-workflow-2026/

### 1.5 MiniMax H3 生态（若确用 H3-22B 才需关注）
- Adudeguyman/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder：134★，prompt builder + 媒体资产管理器（2026-08 活跃）。
- HEEEeeeeN/ComfyUI-H3-Conditioning-Cache-AI-Drama-Production-Suite：16★，漫剧生产套件——分镜导演/H3 提示词 skill、提示词审阅 Excel、批量预编码 .pt 缓存（昂贵条件编码只跑一次）、多链批量/云算力抽卡。
- vizart-vj/ComfyUI-MiniMax-H3-LongMedia：145★，H3 长视频/音频生成，含流式 attention、压缩 KV、**自适应显存保护与 chunked 优化（面向低显存）**。
- nazgut/ComfyUI-MiniMaxH3-CLSS：10★，H3 CLSS 节点（2026-09 活跃）。
- 8GB 适配：LongMedia 明确带低显存优化；其余为文本/编排节点。若引擎为 H3-22B，评分高；为 LTX-2.3 则无关。
- 来源：https://github.com/Adudeguyman/ComfyUI-Fantastic-MiniMaxH3-PromptBuilder、https://github.com/HEEEeeeeN/ComfyUI-H3-Conditioning-Cache-AI-Drama-Production-Suite、https://github.com/vizart-vj/ComfyUI-MiniMax-H3-LongMedia、https://github.com/nazgut/ComfyUI-MiniMaxH3-CLSS

### 1.6 comfy.org / 社区工作流市场
- comfy.org 官方《LTX 2.3 - Anime2Real》（6fec31e40f4a，动漫转写实，9:16）；头条《LTX2.3 20宫格工作流：一句话到 AI 漫剧一次直出》；aliyun 开发者社区有 8G 显存本地 AI 漫剧自动化搭建与 Qwen+ComfyUI 剧本分镜成片教程。
- 来源：https://comfy.org/zh/workflows/6fec31e40f4a-6fec31e40f4a/、https://developer.aliyun.com/article/1754055、https://developer.aliyun.com/article/1753130

## 2. Top 3 推荐（竖屏漫剧、角色一致性、小说转视频、8GB）
1. **ComfyUI-Novel-Director**——分集批量自动化 + IPAdapter 选角锁脸 + TTS 音画对齐 + 自动合并，引擎无关，可直接驱动 LTX-2.3。
2. **ComfyUI-H3-Prompt-Builder**（若确认 H3-22B 则并列第一）——剧本→分镜 JSON→逐镜提示词+参考图接线，纯文本零显存；跑 LTX-2.3 需把输出提示词做少量格式适配。
3. **LTX-2.3 官方原生工作流 + Anime2Real（comfy.org）作视频主干 + IPAdapter-Plus FaceID / 角色 LoRA 锁脸**；WanVideoWrapper(fp8/GGUF) 作备选引擎。
