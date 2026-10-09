"""CosyVoice2 服务烟测：健康 + 真实合成 + 音频有效性。

用途：
1. 首次部署后验证服务真的能出声（而不是只看端口通不通）；
2. 以后改动模型/依赖后做回归（`python scripts/cosyvoice_smoke.py`）。

    python scripts/cosyvoice_smoke.py                    # 默认 http://127.0.0.1:50000
    python scripts/cosyvoice_smoke.py --voice chinese_male_deep --text "你好，我是主角。"

退出码：0 = 健康且合成出有效音频；1 = 失败（并打印原因）。
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:50000"
DEFAULT_TEXT = "这是一段配音烟测，用来确认声音服务真的能出声。"


def wav_info(data: bytes) -> dict:
    """解析 WAV 头（RIFF/WAVE + fmt 块），返回 {ok, sample_rate, channels, bits, data_bytes}。"""
    info = {"ok": False, "sample_rate": 0, "channels": 0, "bits": 0, "data_bytes": 0}
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return info
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if chunk_id == b"fmt " and size >= 16:
            # fmt 块布局：audio_format(2) channels(2) sample_rate(4) byte_rate(4)
            #            block_align(2) bits_per_sample(2)
            info["channels"] = struct.unpack_from("<H", data, body + 2)[0]
            info["sample_rate"] = struct.unpack_from("<I", data, body + 4)[0]
            info["bits"] = struct.unpack_from("<H", data, body + 14)[0]
        elif chunk_id == b"data":
            info["data_bytes"] = size
            break
        pos = body + size + (size % 2)
    info["ok"] = info["sample_rate"] > 0 and info["data_bytes"] > 0
    return info


def _get(url: str, timeout: float = 10.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "LuminaForge-smoke/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def _post_json(url: str, payload: dict, timeout: float = 300.0) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                headers={"Content-Type": "application/json",
                                         "User-Agent": "LuminaForge-smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def run(base_url: str = DEFAULT_URL, text: str = DEFAULT_TEXT, voice: str = "default",
        mood: str = "", out_path: Path | None = None, timeout: float = 300.0) -> dict:
    """执行健康检查 + 一次真实合成，返回结构化报告。"""
    base = base_url.rstrip("/")
    report: dict = {"base_url": base, "steps": [], "ok": False}

    t0 = time.time()
    try:
        status, body = _get(base + "/")
        health = json.loads(body.decode("utf-8", "replace"))
        report["health"] = health
        loaded = bool(health.get("model_loaded"))
        report["steps"].append({
            "step": "health", "ok": status == 200 and loaded,
            "detail": f"HTTP {status}, model_loaded={loaded}, cuda={health.get('cuda')}, "
                      f"speakers={len(health.get('speakers') or [])}",
        })
        if not loaded:
            report["summary"] = "服务健康但模型未加载（预热失败？），无法合成"
            return report
    except Exception as e:
        report["steps"].append({"step": "health", "ok": False,
                                "detail": f"{type(e).__name__}: {e}"})
        report["summary"] = f"CosyVoice 服务不可达（{base}）：{type(e).__name__}"
        return report

    try:
        status, data = _post_json(base + "/generate",
                                  {"text": text, "voice": voice, "mood": mood},
                                  timeout=timeout)
    except Exception as e:
        report["steps"].append({"step": "generate", "ok": False,
                                "detail": f"{type(e).__name__}: {e}"})
        report["summary"] = f"合成请求失败：{type(e).__name__}"
        return report

    info = wav_info(data)
    report["audio"] = {**info, "bytes": len(data), "elapsed_seconds": round(time.time() - t0, 2)}
    report["steps"].append({
        "step": "generate", "ok": status == 200 and info["ok"],
        "detail": (f"HTTP {status}, {len(data)/1024:.0f} KB, {info['sample_rate']} Hz, "
                   f"{info['channels']}ch/{info['bits']}bit, 音频 {info['data_bytes']/1024:.0f} KB"),
    })
    if out_path and info["ok"]:
        Path(out_path).write_bytes(data)
        report["saved_to"] = str(out_path)

    report["ok"] = all(s["ok"] for s in report["steps"])
    report["summary"] = ("✅ 合成成功：服务健康且产出有效音频"
                         if report["ok"] else "❌ 烟测失败：见步骤明细")
    return report


def format_report(report: dict) -> str:
    lines = ["", "=" * 60, "  CosyVoice2 配音烟测 (Smoke)", "=" * 60]
    lines.append(f"  服务: {report.get('base_url')}")
    for s in report.get("steps", []):
        lines.append(f"  {'✅' if s['ok'] else '❌'} {s['step']:9} {s['detail']}")
    if "audio" in report:
        a = report["audio"]
        lines.append(f"  采样率: {a['sample_rate']} Hz（CosyVoice2 原生 24000）")
    lines.append("-" * 60)
    lines.append(f"  {report.get('summary', '')}")
    if report.get("saved_to"):
        lines.append(f"  已保存: {report['saved_to']}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CosyVoice2 服务烟测")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--voice", default="default")
    ap.add_argument("--mood", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    report = run(args.url, args.text, args.voice, args.mood,
                 Path(args.out) if args.out else None, args.timeout)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
