"""配音 A/B 对比：同一句台词，跨引擎/跨音色生成，输出可听文件与对比表。

用途：
- 部署 CosyVoice 后确认"真的换声音了"（不同 speaker → 不同音频）；
- 决定某类角色用哪个音色（听感决策留证据，而不是凭感觉）。

    python scripts/tts_ab_compare.py                        # 默认对比 cosyvoice 3 个 speaker + edge 2 个音色
    python scripts/tts_ab_compare.py --text "王总，您亲口说的，狗都不要的方案。"

产物：`_logs/tts_ab/` 下的音频文件 + `report.json`（时长/大小/哈希）。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DEFAULT_TEXT = "王总，您亲口说的，狗都不要的方案。"
DEFAULT_COSY = ["chinese_male_deep", "chinese_male_young", "chinese_female_soft"]
DEFAULT_EDGE = ["zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural"]
COSY_URL = "http://127.0.0.1:50000"


def _duration(path: Path) -> float:
    """用 ffprobe 读时长；失败返回 -1。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30)
        return round(float(r.stdout.strip()), 2)
    except Exception:
        return -1.0


def _sha16(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h[:16]


def pitch_hz(path: Path) -> float:
    """估计中位基频 F0（Hz），客观区分男/女声（男约 90-160，女约 170-280）。

    只用 numpy 自相关法（不引入新依赖）；解析失败返回 -1。
    """
    try:
        import wave
        import numpy as np

        with wave.open(str(path), "rb") as wf:
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if x.size < sr // 2:
            return -1.0
        x = x - x.mean()
        frame, hop = int(0.04 * sr), int(0.02 * sr)
        lo, hi = int(sr / 320), int(sr / 70)  # 搜索 70–320 Hz
        vals = []
        for start in range(0, x.size - frame, hop):
            seg = x[start:start + frame]
            if float(np.abs(seg).mean()) < 50:      # 跳过静音
                continue
            seg = seg * np.hanning(seg.size)
            ac = np.correlate(seg, seg, mode="full")[seg.size - 1:]
            if ac[0] <= 0:
                continue
            ac = ac / ac[0]
            window = ac[lo:hi]
            if window.size == 0:
                continue
            lag = int(np.argmax(window)) + lo
            if ac[lag] > 0.3:                       # 相关度阈值，滤噪
                vals.append(sr / lag)
        return round(float(np.median(vals)), 1) if vals else -1.0
    except Exception:
        return -1.0


def gen_cosyvoice(text: str, speaker: str, out: Path, mood: str = "",
                  base_url: str = COSY_URL, timeout: float = 600.0) -> dict:
    """调用 CosyVoice2 服务合成，返回记录。"""
    body = json.dumps({"text": text, "voice": speaker, "mood": mood}).encode("utf-8")
    req = urllib.request.Request(base_url.rstrip("/") + "/generate", data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        out.write_bytes(data)
        return {"engine": "cosyvoice", "voice": speaker, "file": str(out),
                "bytes": len(data), "duration": _duration(out), "sha16": _sha16(out),
                "pitch": pitch_hz(out), "ok": True}
    except Exception as e:
        return {"engine": "cosyvoice", "voice": speaker, "file": str(out),
                "ok": False, "error": f"{type(e).__name__}: {e}"}


async def _edge_synth(text: str, voice: str, out: Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice).save(str(out))


def gen_edge(text: str, voice: str, out: Path) -> dict:
    """调用 edge-tts 合成（需网络），返回记录。"""
    try:
        asyncio.run(_edge_synth(text, voice, out))
        return {"engine": "edge", "voice": voice, "file": str(out),
                "bytes": out.stat().st_size, "duration": _duration(out),
                "sha16": _sha16(out), "ok": True}
    except Exception as e:
        return {"engine": "edge", "voice": voice, "file": str(out),
                "ok": False, "error": f"{type(e).__name__}: {e}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="配音 A/B 对比")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--cosyvoice", nargs="*", default=DEFAULT_COSY)
    ap.add_argument("--edge", nargs="*", default=DEFAULT_EDGE)
    ap.add_argument("--mood", default="")
    ap.add_argument("--out-dir", default=str(ROOT / "_logs" / "tts_ab"))
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[A/B] 台词: {args.text}")
    print(f"[A/B] 输出目录: {out_dir}")

    records: list[dict] = []
    for speaker in args.cosyvoice or []:
        rec = gen_cosyvoice(args.text, speaker, out_dir / f"cosy_{speaker}.wav", args.mood)
        records.append(rec)
        print(f"  {'✅' if rec['ok'] else '❌'} cosyvoice/{speaker:22} "
              f"{rec.get('duration', '?')}s {rec.get('bytes', 0)/1024:.0f}KB "
              f"{rec.get('sha16', rec.get('error', ''))}")
    for voice in args.edge or []:
        rec = gen_edge(args.text, voice, out_dir / f"edge_{voice}.mp3")
        records.append(rec)
        print(f"  {'✅' if rec['ok'] else '❌'} edge/{voice:27} "
              f"{rec.get('duration', '?')}s {rec.get('bytes', 0)/1024:.0f}KB "
              f"{rec.get('sha16', rec.get('error', ''))}")

    ok = [r for r in records if r["ok"]]
    hashes = {r["sha16"] for r in ok}
    print(f"\n[A/B] 成功 {len(ok)}/{len(records)}；不同音频指纹 {len(hashes)}/{len(ok)}"
          f"{'（说明各音色确实是不同声音）' if len(hashes) == len(ok) and ok else ''}")
    (out_dir / "report.json").write_text(
        json.dumps({"text": args.text, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[A/B] 报告: {out_dir / 'report.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
