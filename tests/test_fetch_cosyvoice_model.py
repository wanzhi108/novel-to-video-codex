"""CosyVoice2 模型下载器（scripts/fetch_cosyvoice_model.py）离线测试。

背景：本机 `huggingface.co` 不可达、`hf-mirror.com` 可达，且 **hf-mirror 对默认 python-urllib
UA 直接返回 403**（实测）。下载器要能：只取推理必需文件、已存在则跳过（可重跑续传）、
校验 sha256、失败非零退出。
"""
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _manifest():
    return [
        {"path": "llm.pt", "size": 10, "sha256": ""},
        {"path": "flow.pt", "size": 20, "sha256": ""},
        {"path": "config.json", "size": 3, "sha256": ""},
        {"path": "flow.decoder.estimator.fp32.onnx", "size": 5, "sha256": ""},
        {"path": "speech_tokenizer_v2.batch.onnx", "size": 5, "sha256": ""},
        {"path": "asset/dingding.png", "size": 5, "sha256": ""},
        {"path": ".gitattributes", "size": 1, "sha256": ""},
    ]


def test_module_api():
    import fetch_cosyvoice_model as f

    for name in ("fetch_manifest", "plan_downloads", "download_file", "sha256_of", "main"):
        assert hasattr(f, name), f"缺少 {name}"


def test_browser_like_user_agent_is_set():
    """回归守卫：默认 urllib UA 会被 hf-mirror 403，必须带浏览器型 UA。"""
    import fetch_cosyvoice_model as f

    ua = f._HEADERS.get("User-Agent", "")
    assert "Mozilla" in ua, "缺少浏览器型 User-Agent（hf-mirror 会 403）"


def test_plan_skips_optional_assets_and_dotfiles(tmp_path):
    import fetch_cosyvoice_model as f

    todo, skip = f.plan_downloads(_manifest(), tmp_path)
    todo_paths = {i["path"] for i in todo}
    assert "flow.decoder.estimator.fp32.onnx" not in todo_paths, "TensorRT 文件应默认跳过"
    assert "speech_tokenizer_v2.batch.onnx" not in todo_paths, "batch 分词器应默认跳过"
    assert "asset/dingding.png" not in todo_paths, "文档配图应跳过"
    assert ".gitattributes" not in todo_paths
    assert todo_paths == {"llm.pt", "flow.pt", "config.json"}
    assert skip == []


def test_plan_includes_optional_when_requested(tmp_path):
    import fetch_cosyvoice_model as f

    todo, _ = f.plan_downloads(_manifest(), tmp_path, include_optional=True)
    assert "flow.decoder.estimator.fp32.onnx" in {i["path"] for i in todo}


def test_plan_skips_existing_file_with_matching_size(tmp_path):
    import fetch_cosyvoice_model as f

    (tmp_path / "config.json").write_bytes(b"abc")  # size 3 == 清单
    todo, skip = f.plan_downloads(_manifest(), tmp_path)
    assert {i["path"] for i in skip} == {"config.json"}
    assert "config.json" not in {i["path"] for i in todo}


def test_plan_rechecks_existing_file_when_size_differs(tmp_path):
    import fetch_cosyvoice_model as f

    (tmp_path / "config.json").write_bytes(b"abcdef")  # 大小不符 → 需重下
    todo, skip = f.plan_downloads(_manifest(), tmp_path)
    assert "config.json" in {i["path"] for i in todo}
    assert skip == []


def test_plan_verifies_sha256_when_provided(tmp_path):
    import fetch_cosyvoice_model as f

    body = b"hello-cosyvoice"
    (tmp_path / "llm.pt").write_bytes(body)
    good = hashlib.sha256(body).hexdigest()
    manifest = [{"path": "llm.pt", "size": len(body), "sha256": good}]
    todo, skip = f.plan_downloads(manifest, tmp_path)
    assert skip and not todo, "哈希一致应跳过"

    bad = hashlib.sha256(b"other").hexdigest()
    todo2, _ = f.plan_downloads([{"path": "llm.pt", "size": len(body), "sha256": bad}], tmp_path)
    assert todo2, "哈希不一致应重新下载"


def test_sha256_of_matches_hashlib(tmp_path):
    import fetch_cosyvoice_model as f

    p = tmp_path / "x.bin"
    p.write_bytes(b"x" * 4096)
    assert f.sha256_of(p) == hashlib.sha256(b"x" * 4096).hexdigest()


def test_chunk_ranges_covers_exactly():
    """分块必须无缝覆盖 [0, size)，否则并行下载会缺字节。"""
    import fetch_cosyvoice_model as f

    ranges = f.chunk_ranges(100, 30)
    assert ranges == [(0, 29), (30, 59), (60, 89), (90, 99)]
    assert sum(e - s + 1 for s, e in ranges) == 100
    assert ranges[0][0] == 0 and ranges[-1][1] == 99
    # 边界情况
    assert f.chunk_ranges(0, 10) == []
    assert f.chunk_ranges(5, 10) == [(0, 4)]
    assert f.chunk_ranges(30, 30) == [(0, 29)]
