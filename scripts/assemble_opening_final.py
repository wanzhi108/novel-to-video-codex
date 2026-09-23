"""完整开场片 第2步：按配音时长延时画面 → 拼接 → 生成 ASS 字幕 → 混音+烧字幕 → 成片。"""
import os
import subprocess, os, json

FFMPEG = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffmpeg.exe")
FFPROBE = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffprobe.exe")
WORK = r"D:\novel-to-video-codex\output\opening_final"
AC = r"D:\novel-to-video-codex\output\wan5b_ac"

# 每镜的台词行（顺序与 build_opening_audio.py 一致）
LINES = {
    1: [("旁白", "药铺不大，三间门面打通，靠墙一溜乌沉沉的药柜，抽屉上贴着褪色的红纸墨字。")],
    2: [("旁白", "黎明前的黑暗浓稠得像一碗陈年药渣。叶玄机摸黑起了身，动作行云流水，像一只在黑暗中穿行的猫。")],
    3: [("旁白", "后院传来咕嘟咕嘟的煎药声，老炉子上坐着一只豁了口的陶罐。")],
    4: [("旁白", "他拿起一把干薄荷放在掌心，用指腹碾了碾，动作极慢，极认真。")],
    5: [("掌柜", "起了？药罐子看着点，别熬干了。"),
        ("叶玄机", "起了掌柜的，周寡妇的药快好了，火撤了，再闷半刻就能滤。")],
    6: [("旁白", "指尖触到柜台下沿，一道很深的划痕。三年前那个深夜的触感，忽然变得清晰。")],
}


def dur(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def ts(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def main():
    tl = json.load(open(os.path.join(WORK, "timeline.json"), encoding="utf-8"))
    seg = {int(k): v for k, v in tl["seg_dur"].items()}

    # 逐镜：把 1.85s 的镜头循环填充到该段配音时长
    retimed = []
    for i in range(1, 7):
        src = os.path.join(AC, f"ac_shot{i}.mp4")
        d = seg[i] + 0.35   # 留一点余量
        out = os.path.join(WORK, f"rt_{i}.mp4")
        subprocess.run([FFMPEG, "-y", "-v", "error", "-stream_loop", "-1", "-i", src, "-t", f"{d:.2f}",
                        "-an", "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p",
                        "-r", "48", out], capture_output=True, text=True)
        print(f"retime shot{i} -> {d:.2f}s", flush=True)
        retimed.append(out)

    # 拼接视频
    vlist = os.path.join(WORK, "vlist.txt")
    open(vlist, "w", encoding="utf-8").write("".join(f"file '{p}'\n" for p in retimed))
    video = os.path.join(WORK, "video_full.mp4")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", vlist,
                    "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", video], capture_output=True, text=True)
    print("video_full:", round(dur(video), 2), "s", flush=True)

    # 拼接音频
    alist = os.path.join(WORK, "alist.txt")
    open(alist, "w", encoding="utf-8").write("".join(f"file '{os.path.join(WORK, f'seg_{i}.wav')}'\n" for i in range(1, 7)))
    audio = os.path.join(WORK, "audio_full.wav")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", alist,
                    "-ar", "48000", "-ac", "2", audio], capture_output=True, text=True)
    print("audio_full:", round(dur(audio), 2), "s", flush=True)

    # 生成 ASS 字幕（按各行真实时长排时间轴）
    ass = os.path.join(WORK, "subs.ass")
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1408
PlayResY: 2560
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,84,&H00FFFFFF,&H000000FF,&H00202020,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,90,90,160,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    t = 0.0

    def wrap(txt, n=15):
        return "\\N".join(txt[i:i + n] for i in range(0, len(txt), n))

    for i in range(1, 7):
        seg_start = t
        lines = LINES[i]
        # 该镜各行时长
        line_durs = []
        for j in range(len(lines)):
            w = os.path.join(WORK, f"s{i}_{j}.wav")
            line_durs.append(dur(w) if os.path.exists(w) else seg[i] / len(lines))
        lt = seg_start
        for (spk, txt), ld in zip(lines, line_durs):
            ev.append(f"Dialogue: 0,{ts(lt)},{ts(lt + ld)},Default,,0,0,0,,{wrap(txt)}")
            lt += ld
        t += seg[i] + 0.35
    open(ass, "w", encoding="utf-8").write(head + "\n".join(ev) + "\n")
    print("subs.ass lines:", len(ev), flush=True)

    # 混音 + 烧字幕（用 cwd=WORK + 相对路径，避免 Windows 路径在滤镜参数里被 ':'/'\\' 破坏）
    final = os.path.join(WORK, "opening_final.mp4")
    r = subprocess.run([FFMPEG, "-y", "-v", "error", "-i", video, "-i", audio,
                        "-vf", "ass=subs.ass", "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", os.path.basename(final)],
                       capture_output=True, text=True, cwd=WORK)
    if r.returncode != 0:
        print("MUX ERR:", r.stderr[-1200:]); return
    print("FINAL:", final, round(os.path.getsize(final) / 1e6, 1), "MB", flush=True)
    p = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-show_entries", "stream=codec_type,width,height,r_frame_rate",
                        "-of", "default=noprint_wrappers=1", final], capture_output=True, text=True)
    print(p.stdout.strip(), flush=True)


if __name__ == "__main__":
    main()
