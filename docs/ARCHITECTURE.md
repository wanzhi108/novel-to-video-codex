# 架构文档

## 系统全景

```
                    ┌─────────────────────────────────────────┐
                    │           LuminaForge 桌面应用            │
                    │  (PyInstaller exe, 端口 8190)             │
                    │                                          │
                    │  ┌──────────┐    ┌───────────────────┐  │
                    │  │ launcher  │───▶│  main.py (uvicorn) │  │
                    │  │  .py      │    │  FastAPI 后端       │  │
                    │  └──────────┘    └───────┬───────────┘  │
                    │                          │              │
                    │  ┌──────────┐           │              │
                    │  │ web/dist │◀──────────┘              │
                    │  │ (React)  │  WebSocket + REST         │
                    │  └──────────┘                          │
                    └─────────────────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
            │   ComfyUI    │   │ CosyVoice2   │   │   FFmpeg     │
            │  :8188       │   │  :50000      │   │  (subprocess)│
            │              │   │              │   │              │
            │ LTX 22B I2V  │   │ zero-shot    │   │ xfade/字幕   │
            │ txt2img      │   │ 中文 TTS     │   │ BGM/片尾     │
            │ PULID        │   │              │   │ 封面         │
            └──────────────┘   └──────────────┘   └──────────────┘
                    │                   │
                    ▼                   ▼
            ┌──────────────┐   ┌──────────────┐
            │ RTX 5070     │   │  cosy_env    │
            │ 8.5GB VRAM   │   │  (venv)      │
            │ 16GB RAM     │   │  transformers│
            │              │   │  4.51.3      │
            └──────────────┘   └──────────────┘
```

## 端口与服务

| 服务 | 端口 | 启动方式 | 说明 |
|------|------|----------|------|
| LuminaForge | 8190 | `launch.bat` | 桌面应用 Web UI |
| ComfyUI | 8188 | `restart_comfyui.bat` | 图片/视频生成引擎 |
| CosyVoice2 | 50000 | `python server.py` | TTS 配音服务 |

## 数据流（story2 管线）

```
1. 关键帧准备
   dialogue.json ──▶ gen_dialogue.py ──▶ CosyVoice2 :50000 ──▶ voice_lines/scene_*.wav (48k立体声)
                                                        │
   shots.json (镜头定义)                                │
     └─ shot[].segments[]                               │
         └─ kf (关键帧路径)                              │
         └─ camera (运镜)                               │
         └─ emotion (情绪)                              │
                  │                                      │
                  ▼                                      │
2. LTX I2V 渲染                                         │
   gen_ltx.py all                                       │
     │ 读取 comfyui/img2vid.json (工作流模板)             │
     │ 填充占位符:                                       │
     │   {{CHECKPOINT}} {{INPUT_IMAGE}}                 │
     │   {{POSITIVE_PROMPT}} {{SEED}}                   │
     │   {{LENGTH}} {{FRAME_RATE}} 等                   │
     │                                                  │
     ▼ 提交到 ComfyUI :8188                              │
   videos/shot_0N_MM.mp4 (每段 65帧/2.7s)               │
                                                        │
3. 最终合成                                              ◀
   assemble.py                                          
     │ 1. 每镜内部 xfade 拼接 ──▶ scene_N_xfaded.mp4    
     │ 2. 拉伸对齐配音时长 ──▶ scene_N_stretched.mp4    
     │ 3. 混音 (48k AAC) ──▶ scene_N_mixed.mp4         
     │ 4. ASS 字幕烧录 ──▶ scene_N_subbed.mp4           
     │ 5. 全局 xfade 拼接 ──▶ final_concat.mp4          
     │ 6. BGM 混音 + 片尾卡 + 封面图                    
     ▼                                                  
   output/被辞退那天xxx_0820.mp4 (1080×1920 30fps)      
```

## ComfyUI 工作流占位符

`comfyui/img2vid.json` 是 LTX 2.3 22B I2V 工作流模板，含以下占位符（`gen_ltx.py` 运行时替换）：

| 占位符 | 说明 | 示例值 |
|--------|------|--------|
| `{{CHECKPOINT}}` | LTX 模型路径 | `ltx-video-2b-v0.9.1-distilled-i2v.safetensors` |
| `{{TEXT_ENCODER}}` | 文本编码器 | `gemma_3_12b` |
| `{{INPUT_IMAGE}}` | 输入关键帧 | `shot_01_kf_wang.png` |
| `{{POSITIVE_PROMPT}}` | 正向提示词 | `cinematic, slow zoom in...` |
| `{{NEGATIVE_PROMPT}}` | 负向提示词 | `blurry, low quality...` |
| `{{FILENAME_PREFIX}}` | 输出前缀 | `shot01-00` |
| `{{FRAME_RATE}}` | 帧率 | `24` |
| `{{LENGTH}}` | 总帧数 | `65` |
| `{{SEED}}` | 随机种子 | `3100` |
| `{{WIDTH_BASE}}` / `{{HEIGHT_BASE}}` | 分辨率 | `960` / `1728` |

### 关键节点参数

| 节点 ID | 参数 | 值 | 说明 |
|---------|------|-----|------|
| 4987 | `bypass_i2v` | `false` | 必须为 false，否则退化为 T2V |
| 3159 | `strength` | `0.7` | 0.5 会静默失败（outputs={}） |

## CosyVoice2 角色配音机制

CosyVoice2 不支持 `inference_instruct`（仅 v1 支持），因此角色区分靠**不同中文参考音**的 zero-shot 克隆：

| 角色 | 参考音文件 | 特征 |
|------|-----------|------|
| 旁白/narration | `cn03_女_36_四川.wav` | 女声，沉稳 |
| 老板/wang | `cn07_男_24_安徽.wav` | 男声，中年 |
| 小杨/yang | `cn06_男_20_上海.wav` | 男声，年轻 |

`dialogue.json` 中 `voices` 字段映射角色到参考音文件名。`gen_dialogue.py` 逐句调用 CosyVoice2 `/generate` API（传 `ref_wav` 参数走 `inference_cross_lingual`），拼接后升采样为 48kHz 立体声。

## PyInstaller 打包机制

- 入口：`launcher.py`（GUI 启动器）
- 主应用：`main.py` 以子线程方式运行 uvicorn（`import main`）
- 前端：`web/dist/` 作为 datas 打进 exe
- 配置：`launcher_config.json`（同目录，含 port/comfyui_url/api_key 等）
- 打包命令：`pyinstaller luminaforge.spec`
- 安装位置：`AppData\Local\Programs\LuminaForge\LuminaForge.exe`

修改 `main.py` / `launcher.py` / 前端后必须重新打包。
