# 漫剧 AI 出片项目 · 交付说明

> 本文档面向接手人，说明**这个项目是什么、本次交付了什么、怎么跑起来、坑在哪**。
> 项目根目录：`D:\novel-to-video-codex`　｜　整理日期：2026-09-23

---

## 0. 一句话定位

把**小说文本**自动变成**竖屏漫剧短视频**：分镜 → 关键帧 → 图生视频 → 配音 → 字幕 → 合成。
本次交付的重点是**「角色 / 场景 / 物品一致性」的完整落地方案（代号 A+B+C）**，以及一个可直接播放的**完整开场片**。

---

## 1. 本次交付物（先看这个）

| 类别 | 文件 | 说明 |
|---|---|---|
| 🎬 **完整开场片（最终交付）** | `output\opening_final\opening_final.mp4` | 46.25s，1408×2560@48fps，含**配音+烧录字幕**，65.4MB |
| 🎬 最强一致性纯画面版 | `output\wan5b_ac\ac_opening.mp4` | 11.1s，6 镜，同角色+同药铺，16.5MB |
| 🎬 A 版纯画面 | `output\wan5b_assetlock\assetlock_opening.mp4` | 11.1s，14.6MB |
| 🧠 **场景 LoRA** | `ComfyUI\models\loras\ykf_scene.safetensors`（ComfyUI 侧） | 药铺场景 LoRA，68.4MB，触发词 `sks chinese herbal medicine shop` |
| 🗂️ LoRA 训练集 | `dataset\yhkf\` | 20 张药铺场景图 |
| 🧑 资产库（角色/场景参考） | `ComfyUI\...\input\asset_*.png`（5 张） | 叶玄机脸、掌柜脸、药铺 3 景 |
| 🖼️ 资产锁定关键帧 | `ComfyUI\...\input\lk*_kf.png`（12 张） | A 版(`lk_`) 与 A+C 版(`lkL_`) |
| 🎨 B 背景复用样张 | `output\b_inpaint\b1_char.png`、`b2_obj.png` | 同一主背景 inpaint 换主体 |
| 🔌 新增插件 | aesthetic-predictor-v2-5、QwenFrameSelector | 见 §5 |

> ComfyUI 实际路径：`D:\ComfyUI-WorkFisher-V2\ComfyUI`（本项目的 `comfyui\` 只放工作流模板）。

---

## 2. 怎么跑（三条主流程）

### 2.1 一键复现「完整开场片」（配音+字幕）

```powershell
# 前置：ComfyUI 已在 8188 以 --lowvram 启动；venv 已装 edge-tts
# ① 生成配音（旁白/叶玄机/掌柜 三种音色）→ 逐镜 wav + timeline.json
venv\Scripts\python.exe scripts\build_opening_audio.py
# ② 按配音时长延时画面 + 拼接 + ASS 字幕 + 混音烧字幕
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\assemble_opening_final.py
# 产物：output\opening_final\opening_final.mp4
```

### 2.2 复现「A+C 资产锁定 6 镜」（同角色+同药铺）

```powershell
# ① 资产库（角色脸 + 药铺场景参考）
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\build_asset_bank.py
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\gen_zhanggui_asset.py
# ② 关键帧：LoRA(药铺) + IPAdapterFaceID(角色)
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\gen_assetlock_lora_keyframes.py
# ③ 逐镜出片：Wan 5B（加固两段式，~8min/镜）
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\wan5b_ac_batch.py
# ④ 拼接
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\compose_ac_opening.py
```

### 2.3 训练「药铺场景 LoRA」（可选，约 40min）

```powershell
# ① 自主生成训练集（20 张，场景参考 + 变化构图）
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\gen_yhkf_dataset.py
# ② 从单文件 RealVisXL 直接训 SDXL LoRA（无需下载 diffusers 版 SDXL）
$env:HF_ENDPOINT="https://hf-mirror.com"
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\train_sdxl_lora_ykf.py --epochs 5 --max_steps 100 --rank 16
# ③ 验证
D:\ComfyUI-WorkFisher-V2\python\python.exe scripts\test_ykf_lora.py
```

---

## 3. 核心方案：A + B + C 角色/场景一致性

问题是：**每个镜头独立文生图 → 每张脸都不一样、每个药铺都不一样**。三招解决：

### A. 双参考（即时可用）—— `IPAdapterFaceID` + `IPAdapter`
- **角色**：`IPAdapterUnifiedLoader("PLUS FACE (portraits)")` → `IPAdapterFaceID(image=角色参考脸)`，锁住同一张脸。
- **场景**：`IPAdapterUnifiedLoader("PLUS (high strength)")` → `IPAdapter(image=场景参考)`，锁住同一个药铺。
- 两者串联在同一关键帧生成里；参考图提前建好（资产库）。
- 实测：8GB 可用，~24s/张关键帧。

### B. 主背景复用 + inpaint（像素级同景）
- 同一张药铺主背景做底，只对**遮罩区**重绘主体/细节。
- **关键坑**：`VAEEncodeForInpaint` + KSampler 会因 VAE 编解码往返让遮罩外背景漂移（实测 mean|diff|=3.24）。
- **正解**：加 `ImageCompositeMasked(destination=原主背景, source=inpaint结果, mask=遮罩)` 把遮罩外贴回 → 实测 mean|diff|=**0.02、0% 像素变化**（像素级保留）。

### C. 场景 LoRA（最强一致性）
- 用**自主生成的 20 张药铺图**训练 SDXL LoRA，锁定"这家药铺"。
- 与 A 叠加 = **最强版**：药铺靠 LoRA、角色靠 FaceID。

### 出片引擎：Wan 2.2 TI2V-5B（已加固）
- **两段式**（避开 16GB 内存天花板）：
  1. 采样+解码 → 存**基础分辨率视频**（不超分）；
  2. `VHS_LoadVideo` 加载 → `RIFE VFI` 补帧(48fps) → `ImageScaleBy` **2x** 缩放 → 合成。
- 第二段不加载 umt5/5B，内存充足；**2x 输出批仅 ~4GB**（4x 模型超分要 **15.4GB，本机必 OOM**）。
- 实测：~8min/镜，1408×2560@48fps，稳定不出错。

---

## 4. 环境与硬件约束（重要）

| 项 | 值 / 说明 |
|---|---|
| 显卡 | RTX 5070 Laptop **8GB** VRAM；系统内存 **16GB** |
| ComfyUI | `D:\ComfyUI-WorkFisher-V2\ComfyUI`，启动：`python main.py --lowvram --reserve-vram 2 --port 8188 --listen 127.0.0.1` |
| Python | 出片/ComfyUI：`D:\ComfyUI-WorkFisher-V2\python\python.exe`；配音：`venv\Scripts\python.exe` |
| FFmpeg | `%USERPROFILE%\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffmpeg.exe`（含 libass） |
| **硬约束** | 4x 模型超分、22B 模型、大 LoRA 训练在 8GB/16GB 上都会崩或极慢，务必按上文低配跑 |
| **网络** | GitHub raw 被墙、HF 直连超时。用 **`HF_ENDPOINT=https://hf-mirror.com`** 下载 HF 模型；GitHub 文件走 **jsdelivr**（`cdn.jsdelivr.net/gh/...`）或代理 |

### 关键模型（ComfyUI 侧）
- 基座：`checkpoints\RealVisXL_V4.0.safetensors`（SDXL 文生图/关键帧）
- IP-Adapter：`ipadapter\ip-adapter-plus-face_sdxl_vit-h.safetensors`（角色）、`ip-adapter-plus_sdxl_vit-h.safetensors`（场景）
- CLIP Vision：`clip_vision\clip_vision_h.safetensors`；人脸：`insightface\models\antelopev2\*`
- 视频：`diffusion_models\Wan2.2-TI2V-5B-Q5_K_M.gguf` + `vae\Wan2.2_VAE.safetensors` + `text_encoders\umt5-xxl-enc-fp8_e4m3fn.safetensors`
- 超分：`models\upscale_models\4x-UltraSharp.pth`；补帧：`custom_nodes\comfyui-frame-interpolation\ckpts\rife\rife47.pth`
- 场景 LoRA：`loras\ykf_scene.safetensors`（本次训练产物）

---

## 5. 本次新增插件

| 插件 | 作用 | 状态 |
|---|---|---|
| `comfyui-aesthetic-predictor-v2-5` | **SigLIP 审美评分**（图像→审美分） | 已装；模型 `google/siglip-so400m-patch14-384`（走 HF 镜像），预测头已放 torch hub 缓存 |
| `ComfyUI-QwenFrameSelector` | 多维度选帧（清晰度/构图/**审美**/技术/内容，`aesthetic_focused` 策略） | 已装；**依赖 OpenRouter 云 API key** 才能跑 |
| `ComfyUI-Novel-Director`（原有） | **编导**：脚本/分镜解析→选角→批产→按时长对齐→合并 | 已装 |
| `ComfyUI_Qwen3-VL-Instruct`（原有，节点 `Qwen3_VQA`） | **视觉大模型**：看图评判构图/审美/是否符合分镜 | 已装 |

> 编导+导演闭环建议：LLM 写分镜 JSON → Novel-Director 批产 → 审美评分 + Qwen3-VL 评审 → 保留高分镜头。

---

## 6. 关键脚本清单（本次新增）

**资产 / 关键帧**
- `build_asset_bank.py` 生成角色+场景资产库　｜ `gen_zhanggui_asset.py` 掌柜脸
- `gen_assetlock_keyframes.py`（A 版双参考）　｜ `gen_assetlock_lora_keyframes.py`（A+C 版）
- `t2i_kf.py` / `t2i_opening.py` / `t2i_shots_batch.py` 基础文生图关键帧

**场景 LoRA**
- `gen_yhkf_dataset.py` 生成训练集　｜ `train_sdxl_lora_ykf.py` 训练　｜ `test_ykf_lora.py` 验证

**出片（Wan 5B）**
- `engines\wan5b.py` **加固引擎（两段式）**　｜ `wan5b_ac_batch.py` / `wan5b_assetlock_batch.py` 批量
- `test_wan5b_shot.py` / `test_wan5b_opening.py` / `test_wan5b_kf.py` 单镜

**拼接 / 后期**
- `compose_ac_opening.py` / `compose_assetlock_opening.py` / `compose_opening.py` 拼接
- `build_opening_audio.py`（edge-tts 配音）　｜ `assemble_opening_final.py`（延时+ASSA字幕+混音）

**B 背景复用**
- `b_inpaint_reuse.py`（inpaint+像素级贴回）　｜ `check_b_bg_preserve.py`（量化验证）

**路由/集成（改动点）**
- `engines\registry.py`、`pipeline\orchestrator.py`、`scripts\video_engine.py`、`settings.yaml`（`video_mode: local`、`local_kind: wan5b`）

---

## 7. 踩坑经验（GOTCHAS，务必看）

1. **4x 模型超分必 OOM**：`ImageUpscaleWithModel` 对 RIFE 后 90 帧要一次性分配 **15.4GB**，16GB 机器必崩 → 改 **2x `ImageScaleBy`** + 两段式。
2. **同服务器跑过 22B 后会挤爆内存**：Wan 5B 出片前最好**重启 ComfyUI** 清掉驻留模型；否则超分阶段 free RAM 仅 ~0.3GB 易 OOM。
3. **inpaint 背景漂移**：必须加 `ImageCompositeMasked` 贴回原背景（见 §3.B）。
4. **CosyVoice 实际未安装**：`cosyvoice2\` 只有 `server.py` 桩 + 参考 wav，**没有引擎和模型** → 配音改用已装的 **edge-tts**（免费、无需 key、中文音质好）。
5. **libass 不会自动给无空格中文折行**：长句会被裁 → 字幕文本**手动插 `\N`** 折行。
6. **ffmpeg 烧字幕路径**：Windows 绝对路径在 `ass=` 滤镜里会被 `:`/`\` 破坏 → 用 `cwd=`+相对路径。
7. **IPAdapter `weight_type` 取值不同**：人脸节点支持 `composition` 等，**非人脸节点只支持** `standard / prompt is more important / style transfer`，填错会 HTTP 400。
8. **SDXL LoRA 训练**：LoRA 参数须保持 fp32（否则 AMP 报 "unscale FP16 gradients"）；`from_single_file` 加载单文件 SDXL；小 rank+少步数以避开 8GB 内存挤占导致的极慢。

---

## 8. 后续可继续的方向

- 把 B 的 inpaint 做成"换机位/换道具"的标准节点流程（当前只做了主体替换）。
- 装 CosyVoice2（仓库 + CosyVoice2-0.5B，~2-3GB）做**音色克隆**，替换 edge-tts。
- 把 `Novel-Director` 接上：用 LLM 把小说解析成标准分镜 JSON，串起"编导→出片→审美筛选"闭环。
- 规模化：把 A+C 资产锁定管线批量套到更多场景/更多集。
- 角色 LoRA（比 FaceID 更强）+ 表情/口型（MuseTalk）补齐"表演"层。

---

## 9. 交接备注

- 项目另有完整文档：`README.md`、`docs\`（ARCHITECTURE / SETUP / GOTCHAS / INDUSTRIALIZATION / PIPELINE_USE / PIPELINE / MANJU_ECOSYSTEM_RESEARCH）。
- 历史交接：`HANDOFF_DeepSeekHarness.md`（上一阶段，含 OpenMontage/overtime-cat 成片）。
- 本次会话中的**所有关键结论**已写入项目长期记忆（`.dsh-project-memory\` 与 `.dsh-memory\`），接手人可直接检索。
- 仓库工作区较脏，**交接前请勿 `git reset` / `git checkout`**，不要丢弃改动。
