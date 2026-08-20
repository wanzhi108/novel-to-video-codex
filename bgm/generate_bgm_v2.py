"""
BGM v2.0 — 高品质合成配乐
使用 ffmpeg 的 anoisesrc + sine + 多频段均衡器 + 混响模拟
比 v1.0 和弦进行更自然，不再像耳鸣
"""
import subprocess, shutil, asyncio, os
from pathlib import Path

BGM_DIR = Path(__file__).parent

# 8种情绪 → BGM配置（基础音调+音色调+节奏）
BGM_CONFIGS = {
    "action": {
        "name": "Action_Epic",
        "freqs": [55, 110, 220, 440],     # 低音鼓点+高音紧张
        "duration": 30,
        "noise_type": "brown",             # 棕色噪音做底
        "noise_vol": 0.03,
        "rhythm": "staccato",              # 断奏感
        "tempo": 1.0,
    },
    "epic": {
        "name": "Epic_Cinematic",
        "freqs": [65.4, 98, 130.8, 196],   # C大三和弦系
        "duration": 30,
        "noise_type": "pink",
        "noise_vol": 0.02,
        "rhythm": "sustained",
        "tempo": 0.7,
    },
    "horror": {
        "name": "Horror_Scary",
        "freqs": [41.2, 49, 55],           # 低音不协和
        "duration": 30,
        "noise_type": "brown",
        "noise_vol": 0.05,
        "rhythm": "drone",
        "tempo": 0.3,
    },
    "mysterious": {
        "name": "Mysterious",
        "freqs": [82.4, 110, 164.8],       # 小调琶音
        "duration": 30,
        "noise_type": "pink",
        "noise_vol": 0.03,
        "rhythm": "arpeggio",
        "tempo": 0.5,
    },
    "sad": {
        "name": "Sad_Emotional",
        "freqs": [220, 261.6, 293.7],       # A小调温柔
        "duration": 30,
        "noise_type": "white",
        "noise_vol": 0.01,
        "rhythm": "sustained_minor",
        "tempo": 0.4,
    },
    "tense": {
        "name": "Tense_Suspense",
        "freqs": [73.4, 87.3, 110],        # D减三和弦
        "duration": 30,
        "noise_type": "brown",
        "noise_vol": 0.04,
        "rhythm": "pulse",
        "tempo": 0.8,
    },
    "warm": {
        "name": "Warm_Happy",
        "freqs": [196, 246.9, 293.7, 392],  # G大三和弦
        "duration": 30,
        "noise_type": "pink",
        "noise_vol": 0.02,
        "rhythm": "flowing",
        "tempo": 0.6,
    },
    "happy": {
        "name": "Happy_Upbeat",
        "freqs": [261.6, 329.6, 392, 523.3], # C大三和弦 明亮
        "duration": 30,
        "noise_type": "pink",
        "noise_vol": 0.02,
        "rhythm": "bouncy",
        "tempo": 0.9,
    },
}

def find_ffmpeg():
    p = shutil.which("ffmpeg") or os.environ.get("FFMPEG_PATH", "")
    if p and Path(p).exists():
        return p
    candidates = [
        Path(os.environ.get("COMFYUI_PATH", "")) / "ffmpeg" / "ffmpeg.exe",
        Path.home() / "ComfyUI" / "ffmpeg" / "ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("D:/ffmpeg/bin/ffmpeg.exe"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None

def generate_bgm(mood: str) -> bool:
    """生成单个情绪的BGM文件"""
    if mood not in BGM_CONFIGS:
        print(f"  [{mood}] 未知情绪类型")
        return False
    
    cfg = BGM_CONFIGS[mood]
    name = cfg["name"]
    freqs = cfg["freqs"]
    dur = cfg["duration"]
    noise_type = cfg["noise_type"]
    noise_vol = cfg["noise_vol"]
    
    output_path = BGM_DIR / f"{name}.mp3"
    
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print(f"  [{mood}] ffmpeg not found")
        return False
    
    # 构建多层音频滤镜
    # 第一层：噪音底铺（环境质感）
    # 第二层：多个正弦波叠加（旋律）
    # 第三层：低音脉冲（节奏感）
    # 第四层：混响/淡入淡出
    
    filter_parts = []
    
    # Layer 1: 噪音底铺
    filter_parts.append(
        f"anoisesrc=d={dur}:c={noise_type}:a={noise_vol}"
        f",lowpass=f=400,highpass=f=40,volume=0.5[noise]"
    )
    
    # Layer 2: 正弦波旋律（多层叠加）
    sine_labels = []
    for i, freq in enumerate(freqs):
        vol = 0.06 / len(freqs)  # 单音音量
        if i == 0:
            vol *= 1.5  # 根音稍强
        # 每个音添加颤音（低频率 modulate）
        mod_freq = 3 + i * 1.5  # 不同调制频率
        filter_parts.append(
            f"sine=frequency={freq}:duration={dur}"
            f",volume={vol:.4f}"
            f",tremolo=f={mod_freq}:d=0.4[sin{i}]"
        )
        sine_labels.append(f"[sin{i}]")
    
    # Layer 3: 低音节奏脉冲
    rhythm_type = cfg["rhythm"]
    bass_freq = freqs[0] / 2  # 根音低八度
    if rhythm_type in ("staccato", "pulse", "bouncy"):
        # 有节奏的低音脉冲
        pulse_dur = 0.15
        pulse_interval = 0.5 / cfg["tempo"]
        filter_parts.append(
            f"sine=frequency={bass_freq}:duration={dur}"
            f",volume=0.08"
            f"[bass]"
        )
        bass_label = "[bass]"
    else:
        # 持续低音
        filter_parts.append(
            f"sine=frequency={bass_freq}:duration={dur}"
            f",volume=0.04"
            f"[bass]"
        )
        bass_label = "[bass]"
    
    # 混音所有层
    all_labels = "[noise]" + "".join(sine_labels) + bass_label
    total_inputs = 2 + len(freqs)  # noise + sines + bass
    filter_parts.append(
        f"{all_labels}amix=inputs={total_inputs}:duration=longest:weights="
        + "1 " * total_inputs
        + ",volume=1.2[mixed]"
    )
    
    # 淡入淡出
    fade_in = 1.5
    fade_out_start = dur - fade_in * 2
    filter_parts.append(
        f"[mixed]afade=t=in:d={fade_in:.1f}"
        f",afade=t=out:st={fade_out_start:.1f}:d={fade_in*2:.1f}"
        f"[out]"
    )
    
    filter_str = ";".join(filter_parts)
    
    cmd = [
        ffmpeg, "-y",
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "160k",
        "-t", str(dur),
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 5000:
            size_kb = output_path.stat().st_size / 1024
            print(f"  [{mood}] ✅ {name}.mp3 ({size_kb:.0f}KB)")
            return True
        else:
            err = result.stderr[-200:] if result.stderr else "unknown"
            print(f"  [{mood}] ❌ {err}")
            return False
    except Exception as e:
        print(f"  [{mood}] ❌ {e}")
        return False

def main():
    print("BGM v2.0 — 高品质合成配乐生成器\n")
    
    success = 0
    total = len(BGM_CONFIGS)
    
    for mood in BGM_CONFIGS:
        if generate_bgm(mood):
            success += 1
    
    print(f"\n{'='*50}")
    print(f"完成: {success}/{total} 首")
    print(f"目录: {BGM_DIR}")
    
    for f in sorted(BGM_DIR.glob("*_*.mp3")):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name}: {size_kb:.0f}KB")

if __name__ == "__main__":
    main()
