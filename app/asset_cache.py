"""资产缓存：同参产物命中即复用（叶子模块，仅标准库）。

动机：单镜 ~8min，而"同一提示词 + 同种子 + 同分辨率"重跑一次毫无意义。
按内容哈希索引产物文件，命中则跳过引擎调用。

约定：
- 缓存**默认关闭**（`Queue.cache_enabled=false`），避免影响既有行为；
- 索引为 JSON，写入用临时文件 + 原子替换；
- 命中前校验产物文件仍存在（被清理则自愈：删索引条目并视为未命中）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Optional


def _normalize(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _normalize(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def cache_key(params: dict) -> str:
    """对参数做规范化（键排序、浮点取整）后取 sha256 前 32 位。"""
    if not isinstance(params, dict):
        raise TypeError("cache_key 需要 dict 参数")
    canonical = json.dumps(_normalize(params), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


class AssetCache:
    INDEX_NAME = "index.json"

    def __init__(self, cache_dir, enabled: bool = True):
        self.dir = Path(cache_dir)
        self.enabled = bool(enabled)
        self.index_path = self.dir / self.INDEX_NAME
        self._index: dict = self._load()

    # ── 索引 I/O ────────────────────────────────────────────
    def _load(self) -> dict:
        try:
            if self.index_path.exists():
                return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    # ── 对外接口 ────────────────────────────────────────────
    def path_for(self, key: str, suffix: str = ".mp4") -> Path:
        return self.dir / f"{key}{suffix or '.mp4'}"

    def lookup(self, key: str) -> Optional[Path]:
        """命中返回产物路径；未命中或产物已丢失返回 None（后者顺带自愈索引）。"""
        if not self.enabled or not key:
            return None
        record = self._index.get(key)
        if not record:
            return None
        path = Path(record.get("path", ""))
        try:
            if path.exists() and path.stat().st_size > 0:
                return path
        except Exception:
            pass
        self._index.pop(key, None)  # 自愈：清掉失效条目
        self._save()
        return None

    def store(self, key: str, src) -> Path:
        """把产物复制进缓存并登记索引，返回缓存内路径。"""
        src_path = Path(src)
        dst = self.path_for(key, src_path.suffix)
        if not self.enabled or not key:
            return dst
        self.dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst)
        self._index[key] = {
            "path": str(dst),
            "size": dst.stat().st_size,
            "ts": time.time(),
            "src": str(src_path),
        }
        self._save()
        return dst

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "entries": len(self._index),
            "dir": str(self.dir),
            "total_bytes": sum(int(r.get("size", 0)) for r in self._index.values()),
        }
