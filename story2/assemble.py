# -*- coding: utf-8 -*-
"""Plan B assemble: 配音 + 字幕 + BGM → 成片

音频映射:
  Shot 1 → scene_1_cosy.wav
  Shot 2 → scene_2_cosy.wav
  Shot 3+4 → scene_3_cosy.wav

视频拉伸: 若视频短于旁白，用 ffmpeg setpts/atempo 对齐时长。
"""

import json, os, sys, time, subprocess, shutil, tempfile, re, glob

ROOT = "D:/CosyVoice2/jb_work"
PLANB = os.path.join(ROOT, "story2")
OUT_VID = os.path.join(PLANB, "videos")
FINAL_DIR = "D:/CosyVoice2/jb_work/story2/output"

FFMPEG_DIR = "C:/Users/Lenovo/ffmpeg-shared/ffmpeg-8.1.1-full_build-shared/bin"
FF = os.path.join(FFMPEG_DIR, "ffmpeg.EXE")
if not os.path.exists(FF):
    FF = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
if not os.path.exists(FF):
    FF = shutil.which("ffmpeg") or "ffmpeg"

FFP = os.path.join(FFMPEG_DIR, "ffprobe.EXE")
if not os.path.exists(FFP):
    FFP = os.path.join(FFMPEG_DIR, "ffprobe.exe")
if not os.path.exists(FFP):
    FFP = shutil.which("ffprobe") or "ffprobe"

# MuseTalk v15 口型同步
MUSE_DIR = "D:/ai-tools/MuseTalk"
MUSE_PYTHON = os.path.join(MUSE_DIR, "venv/Scripts/python.exe")
MUSE_TIMEOUT = 2400  # 40min / scene (dwpose CPU 慢, 长景需 ~40min, 超时则回退常规混音)

FONT = "C:/Windows/Fonts/msyh.ttc"
FPS = 30
FINAL_W, FINAL_H = 1080, 1920

# 字幕/字体用相对路径避免 Windows 盘符冒号导致 ffmpeg ass 滤镜解析失败
SUBS_DIR = os.path.join(PLANB, "subs")
FONT_DIR = os.path.join(SUBS_DIR, "fonts")

plan = json.load(open(os.path.join(PLANB, "shots.json"), encoding="utf-8"))

# 逐句中文台词(说话人前缀), 用于字幕
try:
    DIALOGUE = json.load(open(os.path.join(PLANB, "dialogue.json"), encoding="utf-8")).get("scenes", {})
except Exception:
    DIALOGUE = {}

# 多角色配音覆盖: gen_dialogue.py 生成的每镜音频 (老张/小李双声)
try:
    SCENE_AUDIO_OVERRIDE = json.load(open(os.path.join(PLANB, "scene_audio_map.json"), encoding="utf-8"))
except Exception:
    SCENE_AUDIO_OVERRIDE = {}


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)


def get_duration(path):
    try:
        r = subprocess.run([FFP, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return 0


def get_audio_duration(path):
    try:
        r = subprocess.run([FFP, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return float(r.stdout.strip())
    except:
        pass
    return 0


def ff_filter_path(p):
    """转义 Windows 绝对路径中的盘符冒号，供 ffmpeg 滤镜使用 (C:/.. -> C\\:/..)"""
    p = os.path.abspath(p).replace("\\", "/")
    p = re.sub(r'^([A-Za-z]):', r'\1\\:', p)
    return p


def burn_ass_subtitles(video_path, ass_rel, font_rel, output_path):
    """用 ffmpeg 将 ASS 字幕烧录进视频。ass_rel/font_rel 为相对 cwd 的路径(避开盘符冒号)。"""
    cmd = [
        FF, "-y", "-i", video_path,
        "-vf", f"ass=filename={ass_rel}:fontsdir={font_rel}",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        output_path
    ]
    log(f"  burn_ass: {os.path.basename(output_path)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        stderr = r.stderr.strip()[-300:] if r.stderr else "none"
        log(f"  burn_ass ERROR: {stderr}")
        return False
    return True


def build_srt(subtitles, total_dur):
    """生成 SRT 字幕内容，按视频总时长均分"""
    n = len(subtitles)
    lines = []
    for i, sub in enumerate(subtitles):
        sid = i + 1
        t1 = total_dur * i / n
        t2 = total_dur * (i + 1) / n
        s1 = f"{int(t1//3600):02d}:{int((t1%3600)//60):02d}:{t1%60:06.3f}".replace(".", ",")
        s2 = f"{int(t2//3600):02d}:{int((t2%3600)//60):02d}:{t2%60:06.3f}".replace(".", ",")
        lines.append(f"{sid}\n{s1} --> {s2}\n{sub}\n")
    return "\n".join(lines)


def build_ass(subtitles, total_dur):
    """生成 ASS 字幕 (更美观的样式)"""
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,36,&H00FFFFFF,&H00000000,&H80000000,&H64000000,0,0,0,0,100,100,0,0,1,2.5,1.5,2,60,60,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    n = len(subtitles)
    events = []
    for i, sub in enumerate(subtitles):
        t1 = total_dur * i / n
        t2 = total_dur * (i + 1) / n
        s1 = f"{int(t1//3600):01d}:{int((t1%3600)//60):02d}:{t1%60:05.2f}"
        s2 = f"{int(t2//3600):01d}:{int((t2%3600)//60):02d}:{t2%60:05.2f}"
        text = sub.replace("\n", "\\N")
        events.append(f"Dialogue: 0,{s1},{s2},Default,,0,0,0,,{text}")
    return ass_header + "\n".join(events)


def has_audio(path):
    try:
        r = subprocess.run([FFP, "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        return bool(r.stdout.strip())
    except:
        return False


def stretch_video_to_duration(src, dest, target_dur):
    """拉伸视频到目标时长 (慢放)。源视频可能无声(如 LTX 生成)，无音轨时只拉伸视频。"""
    video_dur = get_duration(src)
    if video_dur <= 0:
        shutil.copy2(src, dest)
        return False

    ratio = video_dur / target_dur
    if 0.9 <= ratio <= 1.1:
        # 差距 <10%, 直接复制
        shutil.copy2(src, dest)
        log(f"  stretch: 不拉伸 (ratio={ratio:.2f})")
        return True

    # 用 setpts 拉伸视频 + atempo 拉伸音频
    setpts_factor = target_dur / video_dur

    vf = f"setpts={setpts_factor:.3f}*PTS,fps={FPS}"

    log(f"  stretch: {video_dur:.1f}s -> {target_dur:.1f}s (ratio={ratio:.2f})")

    if has_audio(src):
        atempo_factor = video_dur / target_dur
        atempo_filters = []
        remaining = atempo_factor
        while remaining > 2.0:
            atempo_filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            atempo_filters.append("atempo=0.5")
            remaining /= 0.5
        atempo_filters.append(f"atempo={remaining:.3f}")
        atempo_str = ",".join(atempo_filters)
        cmd = [FF, "-y", "-i", src,
               "-filter_complex", f"[0:v]{vf}[v];[0:a]{atempo_str}[a]",
               "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-crf", "22", "-preset", "medium",
               "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               dest]
    else:
        # 无声源：仅拉伸视频，音频由后续 mux 步骤添加
        cmd = [FF, "-y", "-i", src,
               "-vf", vf,
               "-an",
               "-c:v", "libx264", "-crf", "22", "-preset", "medium",
               "-pix_fmt", "yuv420p",
               dest]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        log(f"  stretch ERROR: {r.stderr[-200:] if r.stderr else 'none'}")
        shutil.copy2(src, dest)  # fallback
        return False
    return True


def apply_lip_sync(video_path, audio_path, result_dir, result_name="scene_lipsync.mp4"):
    """调用 MuseTalk v15 对 video_path 按 audio_path 做口型同步。
    返回 MuseTalk 输出视频路径；失败返回 None。
    """
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        return None
    if not os.path.exists(MUSE_PYTHON):
        log(f"  lipsync: MuseTalk python 不存在 {MUSE_PYTHON}, skip")
        return None

    os.makedirs(result_dir, exist_ok=True)
    config_path = os.path.join(result_dir, "inference.yaml")
    yaml_content = f"""task_0:
  video_path: {video_path}
  audio_path: {audio_path}
  result_name: {result_name}
"""
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    # MuseTalk 内部 os.system 调用裸 ffmpeg，必须注入 PATH
    env = os.environ.copy()
    env["PATH"] = FFMPEG_DIR + os.pathsep + env.get("PATH", "")

    cmd = [MUSE_PYTHON, "-m", "scripts.inference",
           "--inference_config", config_path,
           "--result_dir", result_dir,
           "--version", "v15"]
    log(f"  lipsync: {os.path.basename(video_path)} + {os.path.basename(audio_path)}")
    try:
        r = subprocess.run(cmd, cwd=MUSE_DIR, env=env, capture_output=True, text=True, timeout=MUSE_TIMEOUT)
        if r.returncode != 0:
            stderr_tail = r.stderr.strip()[-400:] if r.stderr else "none"
            log(f"  lipsync ERROR: {stderr_tail}")
            return None
    except subprocess.TimeoutExpired:
        log(f"  lipsync TIMEOUT after {MUSE_TIMEOUT}s")
        return None
    except Exception as e:
        log(f"  lipsync EXCEPTION: {e}")
        return None

    output_path = os.path.join(result_dir, "v15", result_name)
    if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
        log(f"  lipsync OK: {output_path}")
        return output_path
    log(f"  lipsync output missing/empty: {output_path}")
    return None


def concat_with_transitions(video_files, output, xfade_dur=0.5):
    """用 xfade 拼接多个视频，并保留音频 (acrossfade 同步转场)"""
    if len(video_files) == 1:
        shutil.copy2(video_files[0], output)
        return True

    # 为每个视频统一格式 (保留音频)
    normalized = []
    for i, vf in enumerate(video_files):
        nf = os.path.join(tempfile.gettempdir(), f"planB_norm_{i}.mp4")
        cmd = [FF, "-y", "-i", vf,
               "-vf", f"scale={FINAL_W}:{FINAL_H}:force_original_aspect_ratio=decrease,"
                      f"pad={FINAL_W}:{FINAL_H}:(ow-iw)/2:(oh-ih)/2,fps={FPS}",
               "-c:v", "libx264", "-crf", "18", "-preset", "fast",
               "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k",
               nf]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and os.path.exists(nf):
            normalized.append(nf)

    if len(normalized) < 2:
        if normalized:
            shutil.copy2(normalized[0], output)
        return False

    # 各段时长
    durs = [get_duration(nf) for nf in normalized]
    # 输出时间轴上的起始偏移
    offsets = [0.0]
    for i in range(len(normalized) - 1):
        offsets.append(offsets[-1] + durs[i] - xfade_dur)

    all_audio = all(has_audio(nf) for nf in normalized)

    # 视频 xfade 链
    vparts = [f"[{i}:v]setpts=PTS-STARTPTS[v{i}]" for i in range(len(normalized))]
    prev_v = "v0"
    for i in range(1, len(normalized)):
        vparts.append(
            f"[{prev_v}][v{i}]xfade=transition=fade:duration={xfade_dur}:offset={offsets[i]:.3f}[vx{i}]"
        )
        prev_v = f"vx{i}"
    final_v = prev_v

    if all_audio:
        # 音频 acrossfade 链 (与视频同步)
        aparts = [f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]" for i in range(len(normalized))]
        prev_a = "a0"
        for i in range(1, len(normalized)):
            aparts.append(
                f"[{prev_a}][a{i}]acrossfade=d={xfade_dur}:o=0[a{chr(120)}{i}]"
            )
            prev_a = f"a{chr(120)}{i}"
        final_a = prev_a
        filter_str = ";".join(vparts + aparts)
        map_args = ["-map", f"[{final_v}]", "-map", f"[{final_a}]"]
    else:
        filter_str = ";".join(vparts)
        map_args = ["-map", f"[{final_v}]", "-an"]

    input_args = []
    for nf in normalized:
        input_args.extend(["-i", nf])

    cmd = [FF, "-y"] + input_args + ["-filter_complex", filter_str] + map_args + [
        "-r", "30",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        output]
    log(f"  xfade: {len(normalized)} videos -> {os.path.basename(output)} (audio={'on' if all_audio else 'off'})")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        log(f"  xfade ERROR: {r.stderr[-300:] if r.stderr else 'none'}")
        # Fallback: 简单 concat (保留音视频)
        log(f"  xfade failed, fallback concat")
        concat_list = os.path.join(tempfile.gettempdir(), "planB_concat.txt")
        with open(concat_list, "w") as f:
            for nf in normalized:
                f.write(f"file '{nf.replace(chr(92), '/')}'\n")
        cmd2 = [FF, "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", output]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=300)
        if r2.returncode != 0:
            log(f"  concat also failed!")
            return False
    return True


def generate_cover(video_path, title, out_path):
    """截取高潮帧 + 标题 + 引导, 生成红果风格封面图(jpg)。"""
    try:
        dur = get_duration(video_path)
        ss = max(dur * 0.7, 0.5)
        frame = os.path.join(tempfile.gettempdir(), "planB_cover_frame.png")
        cmd = [FF, "-y", "-ss", f"{ss:.2f}", "-i", video_path, "-frames:v", "1", "-q:v", "2", frame]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if not os.path.exists(frame):
            log("  cover: 截帧失败")
            return False
        font_fp = ff_filter_path(FONT)
        vf = (
            f"drawbox=x=0:y=0:w=iw:h=ih*0.45:color=black@0.45:t=fill,"
            f"drawbox=x=0:y=ih*0.86:w=iw:h=ih*0.14:color=black@0.55:t=fill,"
            f"drawtext=text='{title}':fontfile='{font_fp}':fontcolor=white:"
            f"fontsize=72:x=(w-tw)/2:y=h*0.16:shadowcolor=black:shadowx=4:shadowy=4,"
            f"drawtext=text='↑ 上滑观看全集':fontfile='{font_fp}':fontcolor=white:"
            f"fontsize=40:x=(w-tw)/2:y=h*0.90:shadowcolor=black:shadowx=3:shadowy=3"
        )
        cmd2 = [FF, "-y", "-i", frame, "-vf", vf, out_path]
        r = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out_path):
            log(f"  cover OK: {out_path}")
            return True
        log(f"  cover ERROR: {r.stderr[-200:] if r.stderr else 'none'}")
    except Exception as e:
        log(f"  cover EXCEPTION: {e}")
    return False


def make_ending_card(out_path, duration=3):
    """生成 3 秒黑屏引导卡(带静音立体声音轨), 供 concat 到成片末尾。"""
    font_fp = ff_filter_path(FONT)
    vf = (
        f"drawtext=text='↑ 上滑看全集':fontfile='{font_fp}':fontcolor=white:"
        f"fontsize=72:x=(w-tw)/2:y=h*0.42:shadowcolor=black:shadowx=4:shadowy=4,"
        f"drawtext=text='点赞 + 关注':fontfile='{font_fp}':fontcolor=white:"
        f"fontsize=52:x=(w-tw)/2:y=h*0.54:shadowcolor=black:shadowx=3:shadowy=3"
    )
    cmd = [FF, "-y",
           "-f", "lavfi", "-i", f"color=c=black:s={FINAL_W}x{FINAL_H}:d={duration}:r={FPS}",
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-shortest", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode == 0 and os.path.exists(out_path):
        log(f"  ending card OK: {out_path}")
        return True
    log(f"  ending card ERROR: {r.stderr[-200:] if r.stderr else 'none'}")
    return False


def run_assemble():
    log("=== Phase A: 成片合成 ===")

    # 准备字幕/字体目录 (相对路径，避开盘符冒号)
    os.makedirs(FONT_DIR, exist_ok=True)
    if not os.path.exists(os.path.join(FONT_DIR, "msyh.ttc")):
        try:
            shutil.copy2(FONT, os.path.join(FONT_DIR, "msyh.ttc"))
            log(f"  字体已复制到 {FONT_DIR}")
        except Exception as e:
            log(f"  警告: 字体复制失败 {e}")

    # 1. 收集视频：每镜把多段 LTX 片段 xfade 拼成该镜完整片段
    video_files = []
    for sh in plan["shots"]:
        sid = sh["id"]
        segs = sorted(glob.glob(os.path.join(OUT_VID, "shot_%02d_*.mp4" % sid)))
        if not segs:
            log(f"  shot_{sid:02d}: 无任何片段, 用黑屏替代")
            bp = os.path.join(tempfile.gettempdir(), f"planB_black_{sid}.mp4")
            cmd = [FF, "-y", "-f", "lavfi", "-i", f"color=c=black:s={FINAL_W}x{FINAL_H}:d=3:r={FPS}",
                   "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                   "-pix_fmt", "yuv420p", bp]
            subprocess.run(cmd, capture_output=True, timeout=120)
            if os.path.exists(bp):
                video_files.append((sh, bp))
            continue
        if len(segs) == 1:
            vp = segs[0]
        else:
            vp = os.path.join(tempfile.gettempdir(), f"planB_shot{sid}_concat.mp4")
            concat_with_transitions(segs, vp)  # 片段间 xfade
            if not (os.path.exists(vp) and os.path.getsize(vp) > 10000):
                log(f"    shot_{sid:02d} 拼接失败, 回退首段")
                vp = segs[0]
        video_files.append((sh, vp))
        log(f"  shot_{sid:02d}: {len(segs)} 段 -> {os.path.getsize(vp)} bytes")

    if not video_files:
        log("ERROR: no videos at all!")
        return

    # 2. 场景音频映射
    scene_audio_map = {}
    for sh, vp in video_files:
        scene = sh["scene"]
        audio_path = SCENE_AUDIO_OVERRIDE.get(str(scene)) or plan["scenes_narration"].get(str(scene))
        if audio_path and os.path.exists(audio_path):
            scene_audio_map.setdefault(scene, []).append((sh, vp))

    # 3. 每个场景：拉伸视频 → 配音频 → 烧字幕
    scene_outputs = []
    all_subtitles = []
    scene_durs = []
    for scene_id in sorted(scene_audio_map.keys()):
        shots_vps = scene_audio_map[scene_id]
        audio_path = SCENE_AUDIO_OVERRIDE.get(str(scene_id)) or plan["scenes_narration"].get(str(scene_id))
        audio_dur = get_audio_duration(audio_path)
        log(f"")
        log(f"  Scene {scene_id}: {len(shots_vps)} shots, audio={audio_dur:.1f}s")

        if not shots_vps:
            continue

        # 拼接同一场景的多个 shot
        vp_list = [vp for sh, vp in shots_vps]
        scene_vid = os.path.join(tempfile.gettempdir(), f"planB_scene{scene_id}_concat.mp4")

        if len(vp_list) == 1:
            shutil.copy2(vp_list[0], scene_vid)
        else:
            concat_with_transitions(vp_list, scene_vid)

        video_dur = get_duration(scene_vid)
        log(f"    video_dur={video_dur:.1f}s, audio_dur={audio_dur:.1f}s")

        # 拉伸视频到音频时长
        stretched = os.path.join(tempfile.gettempdir(), f"planB_scene{scene_id}_stretched.mp4")
        if abs(video_dur - audio_dur) / max(video_dur, audio_dur) > 0.1:
            stretch_video_to_duration(scene_vid, stretched, audio_dur)
        else:
            shutil.copy2(scene_vid, stretched)

        # 口型同步已关闭（用户反馈"硬凑感"太强，改用常规混音；MuseTalk 函数保留以备未来）
        with_audio = os.path.join(tempfile.gettempdir(), f"planB_scene{scene_id}_audio.mp4")
        cmd = [FF, "-y", "-i", stretched, "-i", audio_path,
               "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-map", "0:v:0", "-map", "1:a:0",
               "-shortest",
               with_audio]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log(f"    audio mix ERROR, use video only")
            shutil.copy2(stretched, with_audio)

        # 字幕 (ASS): 逐句中文台词(说话人前缀), 从 dialogue.json 读取
        subs_ass = os.path.join(SUBS_DIR, f"scene{scene_id}.ass")
        scene_lines = DIALOGUE.get(str(scene_id), [])
        prefix_map = {"wang": "老板：", "yang": "小杨：", "narration": ""}
        scene_subs = [prefix_map.get(ln.get("speaker", ""), "") + ln.get("text", "") for ln in scene_lines]
        if not scene_subs:
            scene_subs = [sh.get("subtitle", "") for sh, vp in shots_vps]  # 兜底
        if not os.path.exists(subs_ass):
            ass_content = build_ass(scene_subs, audio_dur)
            with open(subs_ass, "w", encoding="utf-8") as f:
                f.write(ass_content)

        burnt = os.path.join(tempfile.gettempdir(), f"planB_scene{scene_id}_final.mp4")
        ass_rel = os.path.relpath(subs_ass, PLANB).replace("\\", "/")
        font_rel = os.path.relpath(FONT_DIR, PLANB).replace("\\", "/")
        burn_ass_subtitles(with_audio, ass_rel, font_rel, burnt)

        if os.path.exists(burnt) and os.path.getsize(burnt) > 10000:
            scene_outputs.append(burnt)
            all_subtitles.extend(scene_subs)
            scene_durs.append(audio_dur)
            log(f"    scene_{scene_id} final: {os.path.getsize(burnt)} bytes")
        else:
            scene_outputs.append(with_audio)
            scene_durs.append(audio_dur)
            log(f"    scene_{scene_id} subtitle failed, use audio-only")

    # 4. 全局拼接
    final_vid = os.path.join(tempfile.gettempdir(), "planB_merged.mp4")
    if not scene_outputs:
        log("ERROR: no scene outputs")
        return

    concat_with_transitions(scene_outputs, final_vid)

    # 5. BGM + SFX: 动态 ducking(对白压低BGM) + 滋啦(煎饼声) + 环境底噪
    bgm_path = plan.get("bgm", "")
    total_dur = get_duration(final_vid)

    # 各场景起始时间轴(用于滋啦定位: 仅煎饼制作镜 1/3 开头)
    xfade = 0.5
    offsets = [0.0]
    for d in scene_durs[:-1]:
        offsets.append(offsets[-1] + d - xfade)
    sizzle_at = offsets[2] if len(offsets) > 2 else (offsets[-1] if offsets else 0.0)

    if bgm_path and os.path.exists(bgm_path):
        bgm_proc = os.path.join(tempfile.gettempdir(), "planB_bgm_trim.wav")
        subprocess.run([FF, "-y", "-i", bgm_path, "-t", str(total_dur),
                        "-af", "afade=t=out:st=%f:d=2" % max(1, total_dur - 2),
                        "-ar", "48000", "-ac", "2", bgm_proc], capture_output=True, timeout=120)
        # 环境底噪(城市低频 hum, 极轻)
        amb_proc = os.path.join(tempfile.gettempdir(), "planB_amb.wav")
        subprocess.run([FF, "-y", "-f", "lavfi", "-i",
                        f"anoise=color=pink:duration={total_dur}:amplitude=0.04",
                        "-af", "lowpass=f=500,afade=t=in:st=0:d=1",
                        "-ar", "48000", "-ac", "2", amb_proc], capture_output=True, timeout=120)
        # 滋啦 SFX(煎饼声)
        sizzle_proc = os.path.join(tempfile.gettempdir(), "planB_sizzle.wav")
        subprocess.run([FF, "-y", "-f", "lavfi", "-i",
                        "anoise=color=brown:duration=1.3:amplitude=0.35",
                        "-af", "highpass=f=1800,lowpass=f=9000,afade=t=in:st=0:d=0.06,afade=t=out:st=1.05:d=0.25",
                        "-ar", "48000", "-ac", "2", sizzle_proc], capture_output=True, timeout=120)

        sz3_ms = int(sizzle_at * 1000)
        fc = (
            "[0:a]aformat=fltp[dlg];"
            "[1:a]volume=0.55[bgm];"
            "[2:a]volume=0.05[amb];"
            "[3:a]adelay=0|0[sz0];"
            f"[3:a]adelay={sz3_ms}|0[sz3];"
            "[bgm][dlg]sidechaincompress=threshold=0.008:ratio=5:attack=5:release=400[duck];"
            "[duck][amb]amix=inputs=2:normalize=0[da];"
            "[da][sz0]amix=inputs=2:normalize=0[m1];"
            "[m1][sz3]amix=inputs=2:normalize=0[mixed]"
        )
        with_bgm = os.path.join(tempfile.gettempdir(), "planB_bgm.mp4")
        cmd = [FF, "-y", "-i", final_vid, "-i", bgm_proc, "-i", amb_proc, "-i", sizzle_proc,
               "-filter_complex", fc,
               "-map", "0:v:0", "-map", "[mixed]",
               "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               with_bgm]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and os.path.exists(with_bgm):
            final_vid = with_bgm
            log(f"  BGM+SFX ducking mixed (sizzle@0 & {sizzle_at:.1f}s)")
        else:
            log(f"  ducking failed, keep dialogue-only: {r.stderr[-200:] if r.stderr else ''}")

    # 5.5 片尾引导卡
    ending = os.path.join(tempfile.gettempdir(), "planB_ending.mp4")
    if make_ending_card(ending):
        with_end = os.path.join(tempfile.gettempdir(), "planB_with_end.mp4")
        if concat_with_transitions([final_vid, ending], with_end):
            final_vid = with_end
            log(f"  ending card appended")

    # 6. 输出
    os.makedirs(FINAL_DIR, exist_ok=True)
    import datetime
    datestr = datetime.datetime.now().strftime("%m%d")
    final_out = os.path.join(FINAL_DIR, f"{plan.get('title','story2')}_{datestr}.mp4")
    shutil.copy2(final_vid, final_out)

    # 6.5 封面图
    cover_out = os.path.join(FINAL_DIR, f"{plan.get('title','story2')}_{datestr}_cover.jpg")
    title = plan.get("title", "会算命的煎饼摊")
    generate_cover(final_out, title, cover_out)

    log(f"")
    log(f"========== FINAL ==========")
    log(f"  路径: {final_out}")
    log(f"  封面: {cover_out}")
    log(f"  大小: {os.path.getsize(final_out)} bytes ({os.path.getsize(final_out)/1e6:.1f}MB)")
    log(f"  时长: {get_duration(final_out):.1f}s")
    log(f"============================")


if __name__ == "__main__":
    run_assemble()
