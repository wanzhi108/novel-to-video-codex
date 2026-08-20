# 墨影流光 / LuminaForge — 小说转视频 AI 管线

将小说文本自动转换为竖屏视频，支持 AI 分镜、关键帧生成、LTX 22B 图生视频、CosyVoice2 中文配音、MuseTalk 口型同步、FFmpeg 后期合成。

## 项目组成

本项目由两部分组成，可独立运行也可联合使用：

| 模块 | 路径 | 用途 |
|------|------|------|
| **LuminaForge 桌面应用** | `scripts/` `app/` `web/` `static/` | FastAPI 后端 + React 前端，PyInstaller 打包为桌面 exe，提供 Web UI 管理视频生成全流程 |
| **story2 管线脚本** | `story2/` | 独立 Python 脚本管线，直接通过 ComfyUI API + CosyVoice2 API + FFmpeg 生成视频，无需启动桌面应用 |
| **CosyVoice2 集成** | `cosyvoice2/` | 改造版 TTS 服务端（参考音按需放入 cn_refs/） |
| **ComfyUI 工作流** | `comfyui/` | LTX I2V / 文生图等 JSON 工作流模板 + 低显存重启脚本 |

## 快速开始

### 环境要求

- **Python 3.11+**（推荐 3.13）
- **Node.js 18+**（前端构建）
- **NVIDIA GPU**（RTX 5070 8.5GB VRAM 可跑，需低显存模式）
- **FFmpeg 6+**（系统 PATH 可用）
- **ComfyUI**（独立安装，端口 8188）
- **CosyVoice2**（独立安装，端口 50000）

### 1. 启动 ComfyUI（低显存模式）

```bat
:: 双击 comfyui/restart_comfyui.bat
:: 或手动启动：
python "<ComfyUI 安装目录>\main.py" --lowvram --async-offload 2 --port 8188 --listen 127.0.0.1
```

> **必须** 使用 `--lowvram --async-offload 2`，否则 LTX 22B 会 OOM 崩进程。

### 2. 启动 CosyVoice2 TTS 服务

```bash
cd <CosyVoice2 安装目录>
cosy_env/Scripts/python.exe server.py  # 端口 50000
```

### 3a. 运行 story2 管线（脚本方式）

```bash
cd story2/

# 第一步：生成配音（调用 CosyVoice2 API）
python gen_dialogue.py

# 第二步：生成视频段（调用 ComfyUI LTX I2V，耗时数小时）
python gen_ltx.py all

# 第三步：合成成片（FFmpeg 拼接 + 字幕 + BGM + 片尾）
python assemble.py
```

### 3b. 运行 LuminaForge 桌面应用

```bat
:: 安装依赖
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..

:: 启动
launch.bat
:: 访问 http://localhost:8190
```

## 项目结构

```
novel-to-video-codex/
├── scripts/               # 核心后端脚本
│   ├── main.py            # FastAPI 主应用（537KB，含全部分镜/生成/后期逻辑）
│   ├── launcher.py        # PyInstaller 桌面启动器
│   ├── video_engine.py    # 视频生成引擎
│   ├── storage.py          # 数据存储
│   ├── kling_client.py     # Kling 视频 API 客户端
│   ├── cloud_video.py     # 云端视频生成
│   └── environment_generator.py
├── app/                    # FastAPI 模块化组件
│   ├── config.py          # 统一配置
│   ├── models.py          # 数据模型
│   └── services/
│       └── comfyui_client.py  # ComfyUI API 客户端
├── web/                    # React + Vite + Tailwind 前端
│   ├── src/               # TypeScript 源码
│   │   ├── pages/         # Dashboard/StoryboardEditor/Settings 等
│   │   ├── hooks/         # useApi/useComfyUI/useWebSocket 等
│   │   └── stores/        # Zustand 状态管理
│   └── dist/              # 预构建前端（PyInstaller 打包用）
├── story2/                 # 独立视频生成管线
│   ├── gen_ltx.py         # LTX I2V 韧性驱动（孤儿回收+无限重试+skip）
│   ├── assemble.py        # 最终合成（xfade+拉伸+字幕+BGM+片尾+封面）
│   ├── gen_dialogue.py    # CosyVoice2 多角色中文配音
│   ├── clean_watermark.py # 关键帧水印去除
│   ├── shots.json         # 镜头定义（每镜多段独立关键帧+运镜）
│   ├── dialogue.json      # 台词文本（角色+内容）
│   └── scene_audio_map.json  # 场景→配音映射
├── comfyui/                # ComfyUI 工作流模板
│   ├── img2vid.json       # LTX 2.3 22B I2V（含占位符）
│   ├── txt2img_pulid.json # PULID 角色一致性文生图
│   ├── restart_comfyui.bat # 低显存重启脚本
│   └── start_comfyui.bat
├── cosyvoice2/             # CosyVoice2 集成
│   ├── server.py          # 改造版服务端（中文参考音 zero-shot）
│   ├── cn_refs.json       # 参考音元数据
│   └── cn_refs/           # 中文参考音样片（3种角色音色）
├── bgm/                    # 背景音乐库（17 首）
├── sfx/                    # 音效库（action/ambient/transition）
├── static/                 # 旧版 Web UI（HTML+CSS+JS）
├── resources/              # 字体 + 图标
│   └── fonts/             # NotoSansSC OTF（字幕烧录用）
├── docs/                   # 文档
│   ├── ARCHITECTURE.md    # 架构与数据流
│   ├── SETUP.md           # 环境搭建指南
│   ├── GOTCHAS.md         # 已知坑与解决方案
│   └── PIPELINE.md        # story2 管线详解
├── .env.example            # 环境变量模板
├── requirements.txt        # Python 依赖
├── luminaforge.spec        # PyInstaller 打包配置
├── Dockerfile              # Docker 部署
├── docker-compose.yml
├── launch.bat / launch.sh  # 启动脚本
└── install.ps1 / uninstall.ps1  # Windows 安装/卸载
```

> 二进制素材（BGM、SFX、字体、参考音）不入 Git，按需用 `bgm/generate_bgm.py`、`sfx/generate_sfx.py` 生成或从外部下载后放入对应目录。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | - | DeepSeek API Key（AI 分镜分析，必填） |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `COMFYUI_MODELS_DIR` | 留空（自动使用仓库内 `ComfyUI/models`） | 模型目录 |

## 技术栈

- **后端**: FastAPI + uvicorn + httpx + websockets
- **前端**: React 18 + TypeScript + Vite + Tailwind CSS + Zustand
- **视频生成**: ComfyUI + LTX 2.3 22B fp8 (I2V)
- **配音**: CosyVoice2 (zero-shot 中文参考音)
- **口型**: MuseTalk v15（可选，默认关闭）
- **后期**: FFmpeg 8.x（xfade 转场 + ASS 字幕 + drawtext）
- **打包**: PyInstaller（冻结桌面 exe）

## 许可证

MIT
