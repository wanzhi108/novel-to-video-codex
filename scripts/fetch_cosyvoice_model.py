"""从 HF 镜像下载 CosyVoice2 模型（可复现、可续传、带校验）。

背景：官方模型在 HuggingFace 上，本机 `huggingface.co` 不可达但 **hf-mirror.com 可达**；
`git clone` GitHub 需代理。为了让"装 CosyVoice"这件事可复现、可交接，本脚本只用标准库：

    python scripts/fetch_cosyvoice_model.py \
        --repo FunAudioLLM/CosyVoice2-0.5B \
        --dest cosyvoice2/pretrained_models/CosyVoice2-0.5B

行为：
- 调 `{endpoint}/api/models/{repo}?blobs=true` 取文件清单（含 LFS 文件的 sha256/size）；
- 逐文件下载，**已存在且大小一致（有 sha256 则校验哈希）即跳过** → 中断后可重跑续传；
- 失败文件汇总并以非零退出码报告，便于脚本化判断；
- `--dry-run` 只打印计划（不下载），`--list` 只列文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
DEFAULT_REPO = "FunAudioLLM/CosyVoice2-0.5B"
MS_REPO = "iic/CosyVoice2-0.5B"
MS_ENDPOINT = "https://modelscope.cn"
DEFAULT_DEST = "cosyvoice2/pretrained_models/CosyVoice2-0.5B"

# 两个源（2026-10-10 实测）：hf-mirror 小文件可用但 LFS 走 cas-bridge.xethub.hf.co，
# 直连仅 ~34KB/s（942MB 要 7 小时+）；ModelScope 同文件实测 ~1.4MB/s，快约 40 倍。
SOURCES = {
    "hf": {
        "endpoint": DEFAULT_ENDPOINT,
        "repo": DEFAULT_REPO,
        "list": "{endpoint}/api/models/{repo}?blobs=true",
        "file": "{endpoint}/{repo}/resolve/main/{path}",
    },
    "modelscope": {
        "endpoint": MS_ENDPOINT,
        "repo": MS_REPO,
        "list": "{endpoint}/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true",
        "file": "{endpoint}/models/{repo}/resolve/master/{path}",
    },
}

_SKIP_SUFFIXES = (".gitattributes",)
_SKIP_PREFIXES = ("asset/",)  # 文档配图等与推理无关
# 推理不需要（本服务 load_trt=False、load_jit=False，且用非 batch 分词器）
# 依据 cosyvoice/cli/cosyvoice.py：CosyVoice2 只需 cosyvoice2.yaml + campplus.onnx
# + speech_tokenizer_v2.onnx + llm.pt/flow.pt/hift.pt + CosyVoice-BlankEN/
_OPTIONAL_FILES = (
    "flow.decoder.estimator.fp32.onnx",   # TensorRT 引擎，仅 load_trt=True 时使用
    "flow.encoder.fp32.zip",              # TensorRT 编码器引擎
    "flow.encoder.fp16.zip",              # TensorRT 编码器引擎（fp16）
    "speech_tokenizer_v2.batch.onnx",     # batch 版分词器，本服务用单条版
    "flow.cache.pt",                      # JIT/cache 变体
)

# hf-mirror 对默认 python-urllib UA 直接返回 403，必须带浏览器型 UA
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 LuminaForge-fetch/1.0"),
    "Accept": "*/*",
}


def _open(url: str, timeout: float):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=timeout)


def fetch_manifest(repo: str = "", endpoint: str = "", source: str = "modelscope",
                   timeout: float = 30.0) -> list[dict]:
    """取文件清单：[{path, size, sha256}]（sha256 有则用于校验）。"""
    cfg = SOURCES.get(source, SOURCES["modelscope"])
    repo = repo or cfg["repo"]
    endpoint = (endpoint or cfg["endpoint"]).rstrip("/")
    url = cfg["list"].format(endpoint=endpoint, repo=repo)
    with _open(url, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out: list[dict] = []
    if source == "modelscope":
        for item in (data.get("Data") or {}).get("Files", []):
            if item.get("Type") != "blob":
                continue
            path = item.get("Path") or ""
            if not path:
                continue
            out.append({
                "path": path,
                "size": int(item.get("Size") or 0),
                "sha256": (item.get("Sha256") or "").lower(),
            })
    else:
        for sib in data.get("siblings", []):
            path = sib.get("rfilename") or ""
            if not path:
                continue
            lfs = sib.get("lfs") or {}
            out.append({
                "path": path,
                "size": int(lfs.get("size") or sib.get("size") or 0),
                "sha256": (lfs.get("sha256") or lfs.get("oid") or "") or "",
            })
    return out


def plan_downloads(manifest: list[dict], dest: Path,
                   include_optional: bool = False) -> tuple[list[dict], list[dict]]:
    """按目标目录现状拆分「需要下载」与「已存在可跳过」。"""
    todo, skip = [], []
    for item in manifest:
        path = item["path"]
        if path.endswith(_SKIP_SUFFIXES) or path.startswith(_SKIP_PREFIXES):
            continue
        if not include_optional and path in _OPTIONAL_FILES:
            continue
        target = Path(dest) / path
        if target.exists():
            size = item.get("size") or 0
            if not size or target.stat().st_size == size:
                if not item.get("sha256") or sha256_of(target) == item["sha256"]:
                    skip.append(item)
                    continue
        todo.append(item)
    return todo, skip


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def download_file(item: dict, dest: Path, repo: str = "", endpoint: str = "",
                  source: str = "modelscope", timeout: float = 120.0) -> Path:
    """下载单个文件（先写 .part，校验通过后改名）。"""
    cfg = SOURCES.get(source, SOURCES["modelscope"])
    repo = repo or cfg["repo"]
    endpoint = (endpoint or cfg["endpoint"]).rstrip("/")
    target = Path(dest) / item["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    url = cfg["file"].format(endpoint=endpoint, repo=repo, path=item["path"])
    with _open(url, timeout) as resp, open(tmp, "wb") as out:
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
    if item.get("sha256") and sha256_of(tmp) != item["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"校验失败（sha256 不匹配）: {item['path']}")
    tmp.replace(target)
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="下载 CosyVoice2 模型（ModelScope / HF 镜像）")
    ap.add_argument("--source", choices=sorted(SOURCES), default="modelscope",
                    help="下载源（默认 modelscope：国内速度实测快约 40 倍）")
    ap.add_argument("--repo", default="")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--list", action="store_true", help="只列文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印下载计划")
    ap.add_argument("--all", action="store_true", help="连可选的 TensorRT/batch/cache 文件一起下载")
    args = ap.parse_args(argv)

    dest = Path(args.dest)
    manifest = fetch_manifest(args.repo, args.endpoint, args.source)
    todo, skip = plan_downloads(manifest, dest, include_optional=args.all)
    total_mb = sum(i.get("size") or 0 for i in todo) / (1024 ** 2)
    _cfg = SOURCES[args.source]
    print(f"[CVModel] source={args.source} repo={args.repo or _cfg['repo']} → {dest}")
    print(f"[CVModel] 清单 {len(manifest)} 个文件；需下载 {len(todo)} 个（{total_mb:.1f} MB）；已存在 {len(skip)} 个")
    if args.list:
        for i in manifest:
            print(f"  {i['size']/1048576:8.1f} MB  {i['path']}")
        return 0
    if args.dry_run:
        for i in todo:
            print(f"  ↓ {(i.get('size') or 0)/1048576:8.1f} MB  {i['path']}")
        return 0

    failed: list[str] = []
    for idx, item in enumerate(todo, 1):
        mb = (item.get("size") or 0) / 1048576
        print(f"[{idx}/{len(todo)}] {item['path']} ({mb:.1f} MB)", flush=True)
        try:
            download_file(item, dest, args.repo, args.endpoint, args.source)
        except (urllib.error.URLError, RuntimeError, OSError) as e:
            print(f"  ✗ 失败: {e}", flush=True)
            failed.append(item["path"])

    if failed:
        print(f"[CVModel] ❌ {len(failed)} 个文件失败：{failed}")
        return 1
    print(f"[CVModel] ✅ 模型就绪: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
