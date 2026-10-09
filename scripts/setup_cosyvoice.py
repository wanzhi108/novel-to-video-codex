"""CosyVoice 2 一键安装/自检（可复现、可交接）。

本脚本把 2026-10-10 实测得到的全部环境知识固化下来，避免下次重踩：

| 环节 | 实测结论 | 本脚本做法 |
|---|---|---|
| 源码 | `github.com` 直连被墙；需代理 | `git clone --recurse-submodules`（可 `--proxy`） |
| 依赖隔离 | torch 会污染主环境（已钉版） | 独立 venv `cosyvoice2/.venv` |
| torch | `download.pytorch.org` 需代理；CPU 版 ~200MB 且**不抢 8GB 显存** | 装 `torch==2.3.1+cpu` |
| whisper | `openai-whisper` 源码构建报 `No module named 'pkg_resources'`（setuptools>=81 已移除该模块） | 钉 `setuptools<81` 再 `--no-build-isolation` |
| 模型 | HF LFS 走 `cas-bridge.xethub.hf.co` 仅 ~34KB/s；**ModelScope ~2-4MB/s** | 默认 ModelScope 源 |
| 模型文件 | 只需 6 类文件 + `CosyVoice-BlankEN/`；TRT/batch/cache 变体可跳过 | 复用 `fetch_cosyvoice_model.py` |

用法：
    python scripts/setup_cosyvoice.py                 # 全流程（源码+venv+依赖+模型）
    python scripts/setup_cosyvoice.py --dry-run       # 只打印计划
    python scripts/setup_cosyvoice.py --check         # 只做就绪自检

退出码：0 = 全部就绪；1 = 有步骤失败或未就绪。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CV_HOME = ROOT / "cosyvoice2"
CV_SRC = CV_HOME / "CosyVoice"
CV_VENV = CV_HOME / ".venv"
CV_MODEL = CV_HOME / "pretrained_models" / "CosyVoice2-0.5B"
REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"
PIN_TORCH = "2.3.1"
TSINGHUA = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYTORCH_CPU = "https://download.pytorch.org/whl/cpu"

# 推理必需（依据 cosyvoice/cli/cosyvoice.py 的 CosyVoice2 分支）
REQUIRED_MODEL_FILES = (
    "cosyvoice2.yaml", "campplus.onnx", "speech_tokenizer_v2.onnx",
    "llm.pt", "flow.pt", "hift.pt",
    "CosyVoice-BlankEN/model.safetensors", "CosyVoice-BlankEN/vocab.json",
)
# venv 里必须能 import 的包
REQUIRED_MODULES = ("torch", "torchaudio", "whisper", "transformers", "onnxruntime",
                    "librosa", "soundfile", "hyperpyyaml", "hydra", "omegaconf",
                    "conformer", "fastapi", "uvicorn")


def filter_requirements(text: str) -> list[str]:
    """过滤官方 requirements：去掉 index 指令 / linux-only / webui 专用 gradio，torch 换 CPU 版。"""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        if "sys_platform == 'linux'" in line:
            continue
        if line.startswith("gradio=="):
            continue
        if line.startswith(f"torch=={PIN_TORCH}"):
            line = f"torch=={PIN_TORCH}+cpu"
        elif line.startswith(f"torchaudio=={PIN_TORCH}"):
            line = f"torchaudio=={PIN_TORCH}+cpu"
        out.append(line)
    return out


def missing_model_files(model_dir: Path = CV_MODEL) -> list[str]:
    return [f for f in REQUIRED_MODEL_FILES if not (Path(model_dir) / f).exists()]


def missing_modules(python_exe: Path = CV_VENV / "Scripts" / "python.exe") -> list[str]:
    python_exe = Path(python_exe)
    if not python_exe.exists():
        return list(REQUIRED_MODULES)
    code = ("import importlib.util as u,sys;"
            "print(','.join(m for m in sys.argv[1:] if not u.find_spec(m)))")
    try:
        r = subprocess.run([str(python_exe), "-c", code, *REQUIRED_MODULES],
                           capture_output=True, text=True, timeout=120)
        return [m for m in (r.stdout.strip().split(",")) if m]
    except Exception:
        return list(REQUIRED_MODULES)


def readiness(model_dir: Path = CV_MODEL, python_exe: Path = CV_VENV / "Scripts" / "python.exe") -> dict:
    miss_files = missing_model_files(model_dir)
    miss_mods = missing_modules(python_exe)
    return {
        "source": CV_SRC.exists(),
        "venv": Path(python_exe).exists(),
        "model_files_missing": miss_files,
        "modules_missing": miss_mods,
        "ready": CV_SRC.exists() and Path(python_exe).exists() and not miss_files and not miss_mods,
    }


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> int:
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.call([str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=env)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CosyVoice 2 一键安装 / 自检")
    ap.add_argument("--proxy", default=os.environ.get("COSYVOICE_PROXY", "http://127.0.0.1:7897"),
                    help="访问 GitHub 与 PyTorch 源的代理（置空则直连）")
    ap.add_argument("--source", choices=("modelscope", "hf"), default="modelscope")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="只做就绪自检")
    ap.add_argument("--skip-model", action="store_true")
    ap.add_argument("--skip-deps", action="store_true")
    args = ap.parse_args(argv)

    vpy = CV_VENV / "Scripts" / "python.exe"

    if args.check or args.dry_run:
        st = readiness()
        print("[CosyVoice] 就绪状态:")
        print(f"  源码 {CV_SRC}      : {'✓' if st['source'] else '✗'}")
        print(f"  独立 venv         : {'✓' if st['venv'] else '✗'}")
        print(f"  模型缺失文件      : {st['model_files_missing'] or '无'}")
        print(f"  venv 缺失包       : {st['modules_missing'] or '无'}")
        print(f"  结论              : {'✅ 就绪，可用 python cosyvoice2/server.py 启动' if st['ready'] else '❌ 未就绪'}")
        if args.dry_run:
            print("[CosyVoice] 计划执行的步骤：")
            print("  1) git clone --depth 1 --recurse-submodules（需代理）")
            print(f"  2) python -m venv {CV_VENV}")
            print("  3) 依赖：清华源装（去 linux/gradio，torch→+cpu）→ whisper --no-build-isolation → torch+cpu（pytorch 源，走代理）")
            print(f"  4) 模型：scripts/fetch_cosyvoice_model.py --source {args.source}")
        return 0 if (args.check and st["ready"]) or args.dry_run else (0 if st["ready"] else 1)

    ok = True

    # ① 源码
    if not (CV_SRC / "cosyvoice").is_dir():
        CV_HOME.mkdir(parents=True, exist_ok=True)
        cmd = ["git"]
        if args.proxy:
            cmd += ["-c", f"http.proxy={args.proxy}", "-c", f"https.proxy={args.proxy}"]
        cmd += ["clone", "--depth", "1", "--recurse-submodules", "--shallow-submodules", REPO_URL, str(CV_SRC)]
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        ok &= _run(cmd, env=env) == 0
    else:
        print(f"[CosyVoice] 源码已存在: {CV_SRC}")

    # ② 独立 venv
    if not vpy.exists():
        ok &= _run([sys.executable, "-m", "venv", str(CV_VENV)]) == 0
    else:
        print(f"[CosyVoice] venv 已存在: {CV_VENV}")

    # ③ 依赖
    if not args.skip_deps and vpy.exists():
        req_txt = (CV_SRC / "requirements.txt")
        if req_txt.exists():
            lines = filter_requirements(req_txt.read_text(encoding="utf-8"))
            (CV_HOME / "requirements-win-cpu.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            rest = [l for l in lines if not l.startswith(("torch==", "torchaudio==", "openai-whisper=="))]
            rest_f = CV_HOME / "requirements-win-rest2.txt"
            rest_f.write_text("\n".join(rest) + "\n", encoding="utf-8")

            print("[CosyVoice] 安装依赖（清华源）")
            # 注意：openai-whisper 的 setup.py 依赖 pkg_resources，而 setuptools>=81 已将其移除，
            # 因此必须钉 setuptools<81，否则报 metadata-generation-failed（2026-10-10 实测）
            ok &= _run([vpy, "-m", "pip", "install", "-q", "--upgrade", "setuptools<81", "wheel"]) == 0
            ok &= _run([vpy, "-m", "pip", "install", "-r", str(rest_f),
                        "--index-url", TSINGHUA, "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
                        "--timeout", "60", "--retries", "3"]) == 0
            print("[CosyVoice] 安装 openai-whisper（关闭构建隔离，需已装 setuptools）")
            ok &= _run([vpy, "-m", "pip", "install", "openai-whisper==20231117",
                        "--no-build-isolation", "--index-url", TSINGHUA,
                        "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]) == 0
            print("[CosyVoice] 安装 CPU 版 torch（不占显存）")
            torch_cmd = [vpy, "-m", "pip", "install", f"torch=={PIN_TORCH}+cpu",
                         f"torchaudio=={PIN_TORCH}+cpu", "--index-url", PYTORCH_CPU]
            if args.proxy:
                torch_cmd += ["--proxy", args.proxy]
            ok &= _run(torch_cmd) == 0
        else:
            print(f"[CosyVoice] 未找到 {req_txt}，跳过依赖安装", flush=True)
            ok = False

    # ④ 模型
    if not args.skip_model:
        fetch = ROOT / "scripts" / "fetch_cosyvoice_model.py"
        ok &= _run([sys.executable, str(fetch), "--source", args.source, "--dest", str(CV_MODEL)]) == 0

    # ⑤ 就绪自检
    st = readiness()
    print("\n[CosyVoice] 就绪自检:")
    print(f"  源码: {'✓' if st['source'] else '✗'} | venv: {'✓' if st['venv'] else '✗'}")
    print(f"  模型缺失: {st['model_files_missing'] or '无'}")
    print(f"  缺失包: {st['modules_missing'] or '无'}")
    print(f"  结论: {'✅ 就绪' if st['ready'] else '❌ 未就绪'}；启动命令: python cosyvoice2/server.py")
    return 0 if (ok and st["ready"]) else 1


if __name__ == "__main__":
    sys.exit(main())
