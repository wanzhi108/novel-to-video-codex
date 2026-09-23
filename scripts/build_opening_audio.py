"""完整开场片 第1步：生成配音（edge-tts 多音色：旁白/叶玄机/掌柜），输出逐镜片段 wav + 时长。"""
import os
import subprocess, os, json, sys

PY = r"D:\novel-to-video-codex\venv\Scripts\python.exe"
FFMPEG = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffmpeg.exe")
FFPROBE = os.path.expanduser(r"~\ffmpeg-shared\ffmpeg-8.1.1-full_build-shared\bin\ffprobe.exe")
WORK = r"D:\novel-to-video-codex\output\opening_final"
os.makedirs(WORK, exist_ok=True)

NARR = "zh-CN-YunyangNeural"   # 旁白（沉稳播报）
YEXJ = "zh-CN-YunxiNeural"     # 叶玄机（年轻男）
ZGUI = "zh-CN-YunjianNeural"   # 掌柜（成熟男）

# 每镜的台词/旁白（按镜序）
SEGMENTS = {
    1: [("narration", "药铺不大，三间门面打通，靠墙一溜乌沉沉的药柜，抽屉上贴着褪色的红纸墨字。", NARR)],
    2: [("narration", "黎明前的黑暗浓稠得像一碗陈年药渣。叶玄机摸黑起了身，动作行云流水，像一只在黑暗中穿行的猫。", NARR)],
    3: [("narration", "后院传来咕嘟咕嘟的煎药声，老炉子上坐着一只豁了口的陶罐。", NARR)],
    4: [("narration", "他拿起一把干薄荷放在掌心，用指腹碾了碾，动作极慢，极认真。", NARR)],
    5: [("掌柜", "起了？药罐子看着点，别熬干了。", ZGUI),
        ("叶玄机", "起了掌柜的，周寡妇的药快好了，火撤了，再闷半刻就能滤。", YEXJ)],
    6: [("narration", "指尖触到柜台下沿，一道很深的划痕。三年前那个深夜的触感，忽然变得清晰。", NARR)],
}


def tts(text, voice, out_mp3, retries=5):
    import time
    for attempt in range(retries):
        r = subprocess.run([PY, "-m", "edge_tts", "--voice", voice, "--text", text,
                            "--write-media", out_mp3], capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1000:
            return True
        print(f"  TTS retry {attempt+1}/{retries} ({voice}): {r.stderr.strip()[-120:]}", flush=True)
        time.sleep(2)
    print("TTS FAIL permanently:", voice, text[:20], flush=True)
    return False


def dur(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def main():
    timeline = {}
    for shot, lines in SEGMENTS.items():
        seg_wavs = []
        for i, (spk, text, voice) in enumerate(lines):
            mp3 = os.path.join(WORK, f"s{shot}_{i}.mp3")
            wav = os.path.join(WORK, f"s{shot}_{i}.wav")
            if not tts(text, voice, mp3):
                sys.exit(1)
            subprocess.run([FFMPEG, "-y", "-v", "error", "-i", mp3, "-ar", "48000", "-ac", "2", wav],
                           capture_output=True, text=True)
            seg_wavs.append(wav)
        # 合并该镜的多条为一段
        seg_out = os.path.join(WORK, f"seg_{shot}.wav")
        if len(seg_wavs) == 1:
            subprocess.run([FFMPEG, "-y", "-v", "error", "-i", seg_wavs[0], seg_out], capture_output=True, text=True)
        else:
            listf = os.path.join(WORK, f"seg_{shot}.txt")
            open(listf, "w", encoding="utf-8").write("".join(f"file '{w}'\n" for w in seg_wavs))
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listf, seg_out],
                           capture_output=True, text=True)
        d = dur(seg_out)
        timeline[shot] = d
        print(f"shot{shot}: {d:.2f}s  ({' / '.join(l[0] for l in lines)})", flush=True)

    total = sum(timeline.values())
    print(f"TOTAL AUDIO = {total:.2f}s", flush=True)
    with open(os.path.join(WORK, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"seg_dur": timeline, "total": total}, f, ensure_ascii=False, indent=2)
    print("saved timeline.json", flush=True)


if __name__ == "__main__":
    main()
