"""CosyVoice2 烟测脚本（scripts/cosyvoice_smoke.py）离线测试。

重点验证 WAV 解析与报告判定（真实合成由部署后的人工/CI 烟测执行）。
"""
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cosyvoice_smoke as S  # noqa: E402


def _make_wav(sample_rate: int = 24000, seconds: float = 0.5, channels: int = 1) -> bytes:
    n = int(sample_rate * seconds)
    data = b"\x00\x00" * n * channels
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, sample_rate * channels * 2,
                      channels * 2, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def test_wav_info_parses_native_rate():
    info = S.wav_info(_make_wav())
    assert info["ok"] is True
    assert info["sample_rate"] == 24000, "CosyVoice2 原生 24kHz，解析错会导致变速失真"
    assert info["channels"] == 1 and info["bits"] == 16
    assert info["data_bytes"] > 0


def test_wav_info_rejects_non_wav():
    assert S.wav_info(b"not a wav at all" * 4)["ok"] is False
    assert S.wav_info(b"")["ok"] is False


def test_wav_info_rejects_empty_data():
    body = b"RIFF" + struct.pack("<I", 4) + b"WAVE"
    assert S.wav_info(body)["ok"] is False


def test_run_reports_unreachable_service_cleanly():
    report = S.run(base_url="http://127.0.0.1:59999", timeout=1.0)
    assert report["ok"] is False
    assert "不可达" in report["summary"]
    assert report["steps"] and report["steps"][0]["ok"] is False


def test_format_report_contains_summary():
    text = S.format_report({"base_url": "x", "steps": [], "ok": False, "summary": "S"})
    assert "烟测" in text and "S" in text
