# v1.0 漫剧出片管线 · 交付包

本 Release 承载**仓库里放不下的大文件**（成片 / LoRA / 素材）。

## 附件说明

| 文件 | 大小 | 说明 |
|---|---|---|
| `opening_final.mp4` | ~65MB | ★ **最终成片**：46.25s，1408×2560@48fps，edge-tts 配音 + 烧录字幕 |
| `ac_opening.mp4` | ~17MB | A+C 最强一致性版纯画面（6 镜，11.1s） |
| `ComfyUI素材.zip` | ~85MB | 场景 LoRA(`ykf_scene.safetensors`) + 角色/场景参考图 + 资产锁定关键帧 |
| `交付说明.md` | — | ★ 主交接文档（方案/命令/环境/踩坑） |
| `必读_先看我.md` | — | 交付包说明 + 需自行下载的模型清单 |

## 快速上手

1. 读 `交付说明.md`。
2. 把 `ComfyUI素材.zip` 解压：`ykf_scene.safetensors` → `ComfyUI\models\loras\`；`asset_*.png` / `lk*_kf.png` → `ComfyUI\input\`。
3. 按 `必读_先看我.md` 的清单下载模型（走 `HF_ENDPOINT=https://hf-mirror.com`）。
4. 跑 `scripts\build_opening_audio.py` + `scripts\assemble_opening_final.py` 复现成片。

> 代码与文档已在本仓库（master 分支）；本 Release 只补大文件。
