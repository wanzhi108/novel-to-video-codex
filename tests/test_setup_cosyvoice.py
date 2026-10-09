"""CosyVoice 一键安装脚本（scripts/setup_cosyvoice.py）离线测试。

固化 2026-10-10 实测得到的环境知识（过滤规则、必需文件清单、就绪判定），
避免"下次装的时候又要重新踩一遍坑"。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import setup_cosyvoice as S  # noqa: E402

SAMPLE_REQ = """\
--extra-index-url https://download.pytorch.org/whl/cu121
# 注释行应被忽略
conformer==0.3.2
deepspeed==0.15.1; sys_platform == 'linux'
gradio==5.4.0
torch==2.3.1
torchaudio==2.3.1
openai-whisper==20231117
onnxruntime==1.18.0; sys_platform == 'darwin' or sys_platform == 'win32'
transformers==4.51.3
"""


def test_filter_requirements_drops_linux_and_gradio():
    lines = S.filter_requirements(SAMPLE_REQ)
    joined = " ".join(lines)
    assert "deepspeed" not in joined, "linux-only 依赖应被过滤"
    assert not any(l.startswith("gradio==") for l in lines), "gradio 仅 webui 需要，应过滤"
    assert not any(l.startswith("--") for l in lines), "index 指令应被过滤"


def test_filter_requirements_switches_torch_to_cpu():
    lines = S.filter_requirements(SAMPLE_REQ)
    assert "torch==2.3.1+cpu" in lines, "torch 应换 CPU 版（不占显存）"
    assert "torchaudio==2.3.1+cpu" in lines
    assert "torch==2.3.1" not in lines


def test_filter_requirements_keeps_windows_and_common():
    lines = S.filter_requirements(SAMPLE_REQ)
    joined = " ".join(lines)
    assert "onnxruntime==1.18.0" in joined, "Windows 分支依赖必须保留"
    assert "openai-whisper==20231117" in joined, "whisper 是模块级必需（frontend.py: import whisper）"
    assert "transformers==4.51.3" in joined


def test_required_model_files_are_the_inference_minimum():
    """必需清单必须与 cosyvoice/cli/cosyvoice.py 的 CosyVoice2 分支一致。"""
    must = set(S.REQUIRED_MODEL_FILES)
    for f in ("cosyvoice2.yaml", "campplus.onnx", "speech_tokenizer_v2.onnx",
              "llm.pt", "flow.pt", "hift.pt"):
        assert f in must, f"缺少推理必需文件: {f}"
    assert "CosyVoice-BlankEN/model.safetensors" in must, "缺 Qwen2 文本编码器权重"
    # 不该把可跳过的变体列为必需
    assert "flow.cache.pt" not in must
    assert "flow.decoder.estimator.fp32.onnx" not in must


def test_missing_model_files_detects_gaps(tmp_path):
    gaps = S.missing_model_files(tmp_path)
    assert len(gaps) == len(S.REQUIRED_MODEL_FILES)
    (tmp_path / "llm.pt").write_bytes(b"x")
    assert "llm.pt" not in S.missing_model_files(tmp_path)


def test_readiness_reports_not_ready_on_empty_layout(tmp_path):
    st = S.readiness(model_dir=tmp_path / "model", python_exe=tmp_path / "nope" / "python.exe")
    assert st["ready"] is False
    assert st["venv"] is False
    assert st["model_files_missing"]


def test_dry_run_cli_exits_zero():
    assert S.main(["--dry-run"]) == 0
