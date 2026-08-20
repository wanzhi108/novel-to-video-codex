# story2 视频生成管线详解

## 概述

story2 是一套独立的 Python 脚本管线，通过 ComfyUI API（LTX 22B I2V）+ CosyVoice2 API（中文 TTS）+ FFmpeg 生成竖屏短视频。不依赖 LuminaForge 桌面应用，可直接在命令行运行。

## 管线三阶段

### 阶段 1：配音生成（gen_dialogue.py）

**输入**：
- `dialogue.json` — 台词文本（每句含角色 + 内容）
- `scene_audio_map.json` — 场景到配音文件的映射

**流程**：
1. 读取 `dialogue.json`，按 `scene` 分组
2. 逐句调用 CosyVoice2 `/generate` API：
   - 根据 `voices[role]` 查到参考音文件路径
   - 传 `ref_wav` 参数 → 走 `inference_cross_lingual`（复用模型不抢显存）
3. 按场景拼接所有句子的 wav
4. 升采样为 48kHz 立体声（`ffmpeg -y -ar 48000 -ac 2 -c:a pcm_s16le`）
5. 输出到 `voice_lines/scene_N.wav`

**输出**：`voice_lines/scene_1.wav` ~ `scene_4.wav`（48kHz 立体声）

**关键配置**（`dialogue.json`）：
```json
{
  "voices": {
    "wang": "cn07_男_24_安徽.wav",
    "narration": "cn03_女_36_四川.wav",
    "yang": "cn06_男_20_上海.wav"
  },
  "scenes": [
    {
      "scene": 1,
      "lines": [
        {"role": "narration", "text": "七月的午后..."},
        {"role": "wang", "text": "小杨，来我办公室。"}
      ]
    }
  ]
}
```

### 阶段 2：LTX 视频渲染（gen_ltx.py）

**输入**：
- `shots.json` — 镜头定义（每镜含多段独立关键帧 + 运镜 + 情绪）
- `comfyui/img2vid.json` — ComfyUI LTX 2.3 I2V 工作流模板
- 关键帧图片（`shot_0N_kf*.png`）

**流程**：
1. 读取 `shots.json`，展开为段列表（每镜的 `segments[]`）
2. 对每段：
   - 检查 `videos/shot_0N_MM.mp4` 是否存在且 >10KB → **skip**（断点续传）
   - 读取该段的关键帧路径（`segment.kf`）
   - 填充 `img2vid.json` 占位符（CHECKPOINT/INPUT_IMAGE/SEED 等）
   - POST 到 ComfyUI `/prompt` API
   - Poll `/history/{prompt_id}` 直到完成
   - 下载视频到 `videos/shot_0N_MM.mp4`
3. 韧性机制：
   - **孤儿回收**（`recover_orphans`）：检测 ComfyUI history 中已完成但未下载的任务
   - **无限重试**：submit/poll/download 任一步断连即 `wait_comfy_ready` 死等 ComfyUI 恢复后重跑
   - **段间冷却**：每段完成后 sleep 90s 降低 ComfyUI 压力

**输出**：`videos/shot_01_00.mp4` ~ `shot_04_02.mp4`（每段 65帧/2.7s/960×1728/24fps）

**关键配置**（`shots.json`）：
```json
[
  {
    "id": 1,
    "scene": 1,
    "base_kf": "shot_01_kf.png",
    "emotion": "tense",
    "segments": [
      {"kf": "shot_01_kf.png", "camera": "wide establishing shot", "emotion": "tense"},
      {"kf": "shot_01_kf_wang.png", "camera": "close-up, slow push in", "emotion": "cold"},
      {"kf": "shot_01_kf_yang.png", "camera": "medium shot, static", "emotion": "nervous"},
      {"kf": "shot_01_kf.png", "camera": "pull back to wide", "emotion": "somber"}
    ]
  }
]
```

**每镜多构图关键帧设计**：解决"相似镜头拼接"问题的核心。每段使用不同的关键帧（老板特写/小杨特写/手部/侧脸等），分别 I2V 生成不同构图的视频，再 xfade 组接，避免同帧抖动。

### 阶段 3：最终合成（assemble.py）

**输入**：
- `videos/shot_0N_MM.mp4` — 各段视频
- `voice_lines/scene_N.wav` — 场景配音
- `dialogue.json` — 逐句台词（生成 ASS 字幕）
- `bgm/*.mp3` — 背景音乐
- `resources/fonts/NotoSansSC-*.otf` — 字幕字体

**流程**：
1. **每镜内部 xfade 拼接**：同一 shot 的多段视频用 xfade 过渡拼接 → `scene_N_xfaded.mp4`
2. **拉伸对齐配音**：xfaded 视频时长可能 ≠ 配音时长 → `setpts` 拉伸视频匹配音频 → `scene_N_stretched.mp4`
3. **混音**：常规混音（**关口型**，不再调 MuseTalk）→ `ffmpeg -y -i stretched -i audio -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2`
4. **字幕烧录**：从 `dialogue.json` 读逐句台词生成 ASS 字幕（说话人着色）→ `ass` filter 烧录
5. **全局拼接**：4 个场景视频用 xfade 拼接 → `final_concat.mp4`
6. **BGM 混音 + 片尾卡 + 封面图** → 最终输出

**输出**：`output/被辞退那天xxx_MMDD.mp4`（1080×1920/30fps/AAC 48k 立体声）

**字幕生成逻辑**：
- 从 `dialogue.json` 读取逐句台词（带「老板：/小杨：」说话人前缀）
- 按场景内句子数均分音频时长，生成 ASS 时间轴
- 说话人着色：旁白=白色，老板=暖黄，小杨=青色

## 运行方式

```bash
# 前置：ComfyUI :8188 已启动（低显存模式），CosyVoice2 :50000 已启动

cd story2/

# 1. 生成配音
python gen_dialogue.py

# 2. 生成视频段（耗时数小时）
python gen_ltx.py all
# 可后台运行：
python gen_ltx.py all >> genB_ltx.log 2>&1 &

# 3. 合成成片
python assemble.py
```

## 断点续传

- **配音**：重复运行会覆盖（幂等）
- **视频段**：`gen_ltx.py` 的 skip 逻辑检查 `os.path.exists(dest) and os.path.getsize(dest) > 10000`，已完成的段自动跳过
- **合成**：每次重新运行会重新生成全部中间产物和最终视频

## 常见操作

### 换一个故事重做

1. 编辑 `dialogue.json`（换台词和角色映射）
2. 编辑 `shots.json`（换镜头定义和关键帧路径）
3. 生成新关键帧（用 ImageGen 或 ComfyUI txt2img）
4. 运行 `gen_dialogue.py` → `gen_ltx.py all` → `assemble.py`

### 只重做某一段视频

```bash
# 删除该段输出文件
rm videos/shot_02_01.mp4
# 重跑 driver（会跳过其他已完成段）
python gen_ltx.py all
# 重跑合成
python assemble.py
```

### 调整字幕样式

编辑 `assemble.py` 中的 `build_ass()` 函数，修改 ASS 样式行（`Style:` 行）。
