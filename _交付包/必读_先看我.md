# 📦 先看这里（交付包说明）

这是**漫剧 AI 出片项目**的完整交付包。项目本体已全部打包；ComfyUI 的大模型（161GB）**未包含**，需按下方清单自行下载。

---

## 1. 包里有什么

```
novel-to-video-codex\            ← 项目本体（代码/文档/输出/训练集）
├─ 交付说明.md                   ← ★ 主交接文档，先读这个
├─ README.md / docs\             ← 项目既有文档
├─ engines\ pipeline\ config\ quality\ scheduler\ post\   ← 工业化出片管线
├─ scripts\                      ← 全部脚本（含本次新增）
├─ dataset\yhkf\                 ← 药铺 LoRA 训练集（20 张）
├─ output\opening_final\opening_final.mp4   ← ★ 最终成片（配音+字幕）
├─ output\wan5b_ac\ac_opening.mp4           ← 纯画面·最强一致性版
├─ _交付包\
│   ├─ 必读_先看我.md            ← 本文件
│   ├─ ComfyUI素材\              ← LoRA + 角色/场景参考图 + 关键帧（需放进 ComfyUI）
│   └─ 插件\                     ← 本次新增的 2 个 ComfyUI 插件 zip
└─ ...
```

## 2. 需要自己下载的模型（放 ComfyUI `models\` 下）

| 放到 | 文件 | 用途 |
|---|---|---|
| `checkpoints\` | `RealVisXL_V4.0.safetensors` | 关键帧文生图（SDXL） |
| `ipadapter\` | `ip-adapter-plus-face_sdxl_vit-h.safetensors` | 锁角色脸 |
| `ipadapter\` | `ip-adapter-plus_sdxl_vit-h.safetensors` | 锁场景 |
| `clip_vision\` | `clip_vision_h.safetensors` | IP-Adapter 依赖 |
| `insightface\models\antelopev2\` | antelopev2 全套 onnx | FaceID 人脸识别 |
| `diffusion_models\` | `Wan2.2-TI2V-5B-Q5_K_M.gguf` | 图生视频（5B） |
| `vae\` | `Wan2.2_VAE.safetensors` | Wan VAE |
| `text_encoders\` | `umt5-xxl-enc-fp8_e4m3fn.safetensors` | Wan 文本编码 |
| `upscale_models\` | `4x-UltraSharp.pth` | 超分 |

> 下载走镜像：`HF_ENDPOINT=https://hf-mirror.com`（HF 直连会超时）。
> GitHub 文件如被墙，用 `cdn.jsdelivr.net/gh/...` 或代理。

## 3. 本包里已带的素材，放回 ComfyUI

把 `_交付包\ComfyUI素材\` 里的文件放到 `ComfyUI\input\`，把 `ykf_scene.safetensors` 放到 `ComfyUI\models\loras\`。

- `ykf_scene.safetensors` = **药铺场景 LoRA**，触发词 `sks chinese herbal medicine shop`
- `asset_*.png` = 角色/场景参考图（叶玄机、掌柜、药铺三景）
- `lk*_kf.png` = 资产锁定后的 6 镜关键帧

## 4. 两个插件（放 ComfyUI `custom_nodes\`）

解压 `_交付包\插件\` 里的 zip 到 `custom_nodes\`：
- `comfyui-aesthetic-predictor-v2-5` — 审美评分（模型 `google/siglip-so400m-patch14-384` 走 HF 镜像）
- `ComfyUI-QwenFrameSelector` — 智能选帧（需 OpenRouter API key 才能跑）

## 5. 最短上手路径

1. 读 `交付说明.md`（第 2 节有可直接复制运行的命令）。
2. 装好 ComfyUI + 模型 + 素材 + 插件。
3. 跑 `scripts\build_opening_audio.py` + `scripts\assemble_opening_final.py` 复现最终成片。

---
如有疑问，`交付说明.md` 的「踩坑经验」一节列了 8 个必知陷阱。
