"""
BGM 背景音乐生成器 v6.0 - 简化版
使用 ffmpeg 合成基于和弦的情绪配乐，生成到 bgm/ 目录
"""
import asyncio, subprocess, shutil, os
from pathlib import Path

BGM_DIR = Path(__file__).parent

def find_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe", r"D:\ffmpeg\bin\ffmpeg.exe"]:
        if Path(p).exists():
            return p
    return None


async def _simple_bgm(name: str, freqs: list[float], tempo_bpm: float,
                       duration: float, output_path: str,
                       wave_type: str = "sine",
                       volume: float = 0.12) -> bool:
    """
    简化的 BGM 生成：使用两个正弦波层（根音+泛音）+ 噪音底垫
    比之前单正弦波丰富得多，但足够简单能稳定运行
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False

    dur = max(duration, 15)
    notes_per_cycle = 4
    note_dur = 60.0 / tempo_bpm * 4 / notes_per_cycle  # 每音符持续时长

    # 层1: 稳定的根音（低频垫底）
    # 层2: 泛音层（高频点缀）  
    # 层3: 极轻微的噪音底垫增加质感
    filter_str = (
        # 根音持续
        f"sine=frequency={freqs[0]:.1f}:duration={dur},volume={volume * 0.7:.3f}[root];"
        # 泛音（高八度，更弱）
        f"sine=frequency={freqs[1]:.1f}:duration={dur},volume={volume * 0.25:.3f}[harm];"
        # 噪音底垫
        f"anoisesrc=d={dur}:c=pink:a=0.03,lowpass=f=300,highpass=f=30[noise];"
        # 混合所有层
        f"[root][harm][noise]amix=inputs=3:duration=longest:dropout_transition=0,"
        f"afade=t=in:d=2,afade=t=out:st={dur - 4}:d=4,volume=0.8[out]"
    )

    cmd = [
        ffmpeg, "-y",
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "128k",
        "-t", str(dur),
        output_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore")[-200:]
            print(f"    [{name}] ffmpeg error: {err}")
        return proc.returncode == 0 and Path(output_path).exists() and Path(output_path).stat().st_size > 1000
    except Exception as e:
        print(f"    [{name}] exception: {e}")
        return False


# ── 各情绪BGM参数 ──
# 频率对：(根音频率, 泛音频率)
BGM_CONFIGS = {
    "mysterious":  {"freqs": [110, 330],  "tempo": 50,  "vol": 0.10},
    "horror":      {"freqs": [98, 294],   "tempo": 35,  "vol": 0.08},
    "warm":        {"freqs": [130, 392],  "tempo": 65,  "vol": 0.12},
    "happy":       {"freqs": [146, 440],  "tempo": 80,  "vol": 0.14},
    "sad":         {"freqs": [105, 315],  "tempo": 45,  "vol": 0.10},
    "epic":        {"freqs": [87, 349],   "tempo": 60,  "vol": 0.13},
    "tense":       {"freqs": [123, 369],  "tempo": 75,  "vol": 0.11},
    "action":      {"freqs": [165, 495],  "tempo": 90,  "vol": 0.15},
}


async def generate_all_bgm(duration: float = 60):
    """生成所有 BGM 文件"""
    results = {}
    for name, cfg in BGM_CONFIGS.items():
        out_path = BGM_DIR / f"{name}.mp3"
        if out_path.exists() and out_path.stat().st_size > 10000:
            results[name] = ("skip", str(out_path))
            print(f"  [SKIP] {name} -> {out_path.name} (已存在)")
            continue
        
        print(f"  [GEN]  {name}...", end=" ", flush=True)
        try:
            ok = await _simple_bgm(
                name, cfg["freqs"], cfg["tempo"],
                duration, str(out_path),
                volume=cfg["vol"]
            )
            results[name] = ("ok" if ok else "fail", str(out_path))
            size = out_path.stat().st_size if out_path.exists() else 0
            status = "OK" if ok else "FAIL"
            print(f"[{status}] ({size/1024:.0f}KB)")
        except Exception as e:
            results[name] = ("error", str(e)[:80])
            print(f"[ERR] {e}")
    return results


if __name__ == "__main__":
    asyncio.run(generate_all_bgm(60))
