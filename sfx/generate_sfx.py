"""
SFX 音效库生成器 v6.0 - 简化版
使用 ffmpeg 合成免版税音效
"""
import asyncio, subprocess, shutil, os
from pathlib import Path

SFX_DIR = Path(__file__).parent

def find_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe", r"D:\ffmpeg\bin\ffmpeg.exe"]:
        if Path(p).exists():
            return p
    return None


async def run_ffmpeg(cmd: list, timeout: int = 30) -> bool:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="ignore")[-200:]
        print(f"    ffmpeg error: {err}")
    return proc.returncode == 0


# ── 环境音 ──
async def gen_noise_sfx(output: str, noise_type: str, highpass: int, lowpass: int,
                          duration: int = 10, volume: float = 0.4):
    """通用噪音生成器"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg: return False
    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", f"anoisesrc=d={duration}:c={noise_type}:a={volume}",
        "-af", f"highpass=f={highpass},lowpass=f={lowpass},afade=t=in:d=1,afade=t=out:st={duration-2}:d=2",
        "-t", str(duration), output
    ]
    return await run_ffmpeg(cmd)


async def gen_wind(out): return await gen_noise_sfx(out, "white", 200, 800, 10, 0.3)
async def gen_rain(out): return await gen_noise_sfx(out, "pink", 100, 1500, 12, 0.35)
async def gen_night(out): return await gen_noise_sfx(out, "white", 3000, 8000, 10, 0.15)
async def gen_market(out): return await gen_noise_sfx(out, "brown", 100, 2000, 10, 0.3)
async def gen_forest(out): return await gen_noise_sfx(out, "pink", 500, 3000, 10, 0.2)


# ── 动作音 ──
async def gen_sine_burst(output: str, freq: float, duration: float, volume: float,
                          fade_out_start: float = 0.15, fade_out_dur: float = 0.3):
    """通用正弦脉冲生成器"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg: return False
    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", f"sine=f={freq}:d={duration}",
        "-af", f"volume={volume},afade=t=out:st={fade_out_start}:d={fade_out_dur}",
        "-t", str(duration), output
    ]
    return await run_ffmpeg(cmd)


async def gen_door(out): return await gen_sine_burst(out, 80, 0.6, 0.6, 0.2, 0.4)
async def gen_step(out): return await gen_sine_burst(out, 150, 0.4, 0.3, 0.1, 0.3)
async def gen_hit(out): return await gen_sine_burst(out, 100, 0.4, 0.7, 0.1, 0.3)
async def gen_bell(out): return await gen_sine_burst(out, 880, 1.5, 0.3, 0.3, 1.2)


# ── 转场音 ──
async def gen_whoosh(out):
    """嗖声 - 白噪音快速脉冲"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg: return False
    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "anoisesrc=d=0.8:c=white:a=0.5",
        "-af", "highpass=f=200,lowpass=f=4000,afade=t=in:d=0.05,afade=t=out:st=0.4:d=0.4,volume=0.5",
        "-t", "1", out
    ]
    return await run_ffmpeg(cmd)


async def gen_boom(out):
    """轰隆 - 低频多重脉冲"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg: return False
    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=f=50:d=2.5",
        "-af", "volume=0.6,lowpass=f=150,afade=t=out:st=1.5:d=1",
        "-t", "3", out
    ]
    return await run_ffmpeg(cmd)


async def gen_riser(out):
    """渐升音 - 白噪音渐强"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg: return False
    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "anoisesrc=d=3:c=white:a=0.4",
        "-af", "highpass=f=100,lowpass=f=3000,afade=t=in:d=2,afade=t=out:st=2.3:d=0.7,volume=0.4",
        "-t", "3", out
    ]
    return await run_ffmpeg(cmd)


async def gen_heartbeat(out):
    """心跳 - 低频双脉冲"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg: return False
    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "sine=f=55:d=0.15",
        "-af", "volume=0.7,adelay=0|800|1600|2400|3200,lowpass=f=120,afade=t=in:d=0.3,afade=t=out:st=4.5:d=0.5",
        "-t", "5", out
    ]
    return await run_ffmpeg(cmd)


SFX_GENERATORS = {
    "wind":      (gen_wind,      SFX_DIR / "ambient"),
    "rain":      (gen_rain,      SFX_DIR / "ambient"),
    "night":     (gen_night,     SFX_DIR / "ambient"),
    "market":    (gen_market,    SFX_DIR / "ambient"),
    "forest":    (gen_forest,    SFX_DIR / "ambient"),
    "door":      (gen_door,      SFX_DIR / "action"),
    "step":      (gen_step,      SFX_DIR / "action"),
    "hit":       (gen_hit,       SFX_DIR / "action"),
    "bell":      (gen_bell,      SFX_DIR / "action"),
    "whoosh":    (gen_whoosh,    SFX_DIR / "transition"),
    "boom":      (gen_boom,      SFX_DIR / "transition"),
    "riser":     (gen_riser,     SFX_DIR / "transition"),
    "heartbeat": (gen_heartbeat, SFX_DIR / "ambient"),
}


async def generate_all_sfx():
    results = {}
    for name, (gen_func, out_dir) in SFX_GENERATORS.items():
        out_path = out_dir / f"{name}.mp3"
        if out_path.exists() and out_path.stat().st_size > 500:
            results[name] = ("skip", str(out_path))
            print(f"  [SKIP] {name}")
            continue
        try:
            ok = await gen_func(str(out_path))
            results[name] = ("ok" if ok else "fail", str(out_path))
            status = "OK" if ok else "FAIL"
            print(f"  [{status}] {name}")
        except Exception as e:
            results[name] = ("error", str(e)[:80])
            print(f"  [ERR] {name}: {e}")
    return results


if __name__ == "__main__":
    asyncio.run(generate_all_sfx())
