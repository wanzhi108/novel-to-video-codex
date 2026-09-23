"""
SQLite 存储引擎 — 替换 JSON 文件存储
提供 ACID 事务、索引查询、并发安全。
自动迁移现有 JSON 文件数据。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import sqlite3
import time
from pathlib import Path
from typing import Optional

from app.models import JobState, Scene, Character

logger = logging.getLogger("novel2vid.storage")

# 数据库路径：源码模式放仓库根 output，打包模式放 exe 同级 output
if getattr(sys, "frozen", False):
    _DEFAULT_OUT = Path(sys.executable).parent / "output"
else:
    _DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output"
_DB_DIR = Path(os.environ.get("OUTPUT_DIR", _DEFAULT_OUT))
_DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DB_DIR / "luminaforge.db"

# JSON 旧存储目录（用于迁移）
JSON_STORAGE_DIR = _DB_DIR / "jobs"

# 全局数据库连接（延迟初始化）
_db: Optional["Storage"] = None


class Storage:
    """SQLite 异步存储引擎"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """初始化数据库连接和表结构"""
        def _init():
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None,  # 自动提交模式
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")      # WAL 模式，并发读写不阻塞
            conn.execute("PRAGMA synchronous=NORMAL")     # 平衡安全性和性能
            conn.execute("PRAGMA busy_timeout=5000")      # 5秒锁等待
            # 创建表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id        TEXT PRIMARY KEY,
                    data          TEXT NOT NULL,
                    novel_title   TEXT DEFAULT '',
                    current_step  TEXT DEFAULT 'upload',
                    scenes_count  INTEGER DEFAULT 0,
                    done_count    INTEGER DEFAULT 0,
                    created_at    REAL DEFAULT 0,
                    updated_at    REAL DEFAULT 0
                )
            """)
            # 索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(novel_title)")
            # v12.1: 归档表（长期未操作的任务）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS archive (
                    job_id        TEXT PRIMARY KEY,
                    data          TEXT NOT NULL,
                    novel_title   TEXT DEFAULT '',
                    archived_at   REAL DEFAULT 0
                )
            """)
            return conn

        self._conn = await asyncio.to_thread(_init)
        logger.info(f"[Storage] SQLite 初始化完成: {self.db_path}")

    async def close(self):
        """关闭数据库连接"""
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def save(self, job: JobState):
        """保存/更新任务到数据库"""
        data = job.model_dump()
        title = data.get("novel_title", "Untitled")
        step = data.get("current_step", "upload")
        scenes = data.get("scenes", [])
        done = sum(1 for s in scenes if isinstance(s, dict) and s.get("status") == "done") if scenes else 0
        now = time.time()

        def _write():
            self._conn.execute(
                """INSERT INTO jobs (job_id, data, novel_title, current_step, scenes_count, done_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id) DO UPDATE SET
                     data=excluded.data,
                     novel_title=excluded.novel_title,
                     current_step=excluded.current_step,
                     scenes_count=excluded.scenes_count,
                     done_count=excluded.done_count,
                     updated_at=excluded.updated_at
                """,
                (job.id, json.dumps(data, ensure_ascii=False, default=str), title, step,
                 len(scenes), done, now, now)
            )

        async with self._lock:
            await asyncio.to_thread(_write)

    async def load_all(self) -> dict[str, JobState]:
        """加载所有任务到内存"""
        def _load():
            rows = self._conn.execute("SELECT data FROM jobs ORDER BY updated_at DESC").fetchall()
            result = {}
            for row in rows:
                try:
                    data = json.loads(row["data"])
                    data = self._rebuild_models(data)
                    job = JobState(**data)
                    result[job.id] = job
                except Exception as e:
                    logger.warning(f"[Storage] 加载任务失败: {str(e)[:100]}")
            return result

        return await asyncio.to_thread(_load)

    async def load_one(self, job_id: str) -> Optional[JobState]:
        """加载单个任务"""
        def _load():
            row = self._conn.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["data"])
                data = self._rebuild_models(data)
                return JobState(**data)
            except Exception as e:
                logger.warning(f"[Storage] 加载任务 {job_id} 失败: {str(e)[:100]}")
                return None

        return await asyncio.to_thread(_load)

    async def delete(self, job_id: str):
        """删除任务"""
        def _del():
            self._conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        async with self._lock:
            await asyncio.to_thread(_del)

    async def list_jobs(self) -> list[dict]:
        """返回任务列表摘要（不加载完整数据，快速查询）。

        输出字段与前端 web/src/lib/types.ts 的 JobSummary 对齐：
        id / title / status / scene_count / completed_scenes / created_at。
        current_step 映射为 status；novel_title 映射为 title。
        """
        def _list():
            rows = self._conn.execute(
                """SELECT job_id, novel_title, current_step, scenes_count, done_count, updated_at
                   FROM jobs ORDER BY updated_at DESC"""
            ).fetchall()
            return [{
                "id": r["job_id"],
                "title": r["novel_title"] or "Untitled",
                "status": r["current_step"] or "upload",
                "scene_count": r["scenes_count"] or 0,
                "completed_scenes": r["done_count"] or 0,
                "created_at": r["updated_at"] or 0,
            } for r in rows]
        return await asyncio.to_thread(_list)

    async def export_job(self, job_id: str) -> Optional[dict]:
        """v12.1: 导出单个任务为可序列化字典"""
        def _export():
            row = self._conn.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["data"])
            except Exception:
                return None
        return await asyncio.to_thread(_export)

    async def import_job(self, data: dict) -> Optional[JobState]:
        """v12.1: 导入任务字典并持久化"""
        job_id = data.get("id")
        if not job_id:
            return None
        try:
            data = self._rebuild_models(data)
            job = JobState(**data)
            await self.save(job)
            return job
        except Exception as e:
            logger.warning(f"[Storage] 导入任务失败: {str(e)[:100]}")
            return None

    async def archive_old_jobs(self, days: int = 30) -> list[str]:
        """v12.1: 归档指定天数未更新的任务，返回已归档 job_id 列表"""
        cutoff = time.time() - days * 86400
        archived: list[str] = []

        def _archive():
            rows = self._conn.execute(
                "SELECT job_id, data, novel_title FROM jobs WHERE updated_at < ?",
                (cutoff,)
            ).fetchall()
            for r in rows:
                try:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO archive (job_id, data, novel_title, archived_at) VALUES (?, ?, ?, ?)",
                        (r["job_id"], r["data"], r["novel_title"] or "", time.time())
                    )
                    self._conn.execute("DELETE FROM jobs WHERE job_id = ?", (r["job_id"],))
                    archived.append(r["job_id"])
                except Exception as e:
                    logger.warning(f"[Storage] 归档 {r['job_id']} 失败: {e}")
            return archived

        async with self._lock:
            return await asyncio.to_thread(_archive)

    async def list_archived(self) -> list[dict]:
        """v12.1: 列出已归档任务"""
        def _list():
            rows = self._conn.execute(
                "SELECT job_id, novel_title, archived_at FROM archive ORDER BY archived_at DESC"
            ).fetchall()
            return [{
                "job_id": r["job_id"],
                "novel_title": r["novel_title"] or "Untitled",
                "archived_at": r["archived_at"] or 0,
            } for r in rows]
        return await asyncio.to_thread(_list)

    async def restore_archived(self, job_id: str) -> Optional[JobState]:
        """v12.1: 从归档恢复任务"""
        def _load():
            row = self._conn.execute("SELECT data FROM archive WHERE job_id = ?", (job_id,)).fetchone()
            return row

        async with self._lock:
            row = await asyncio.to_thread(_load)
        if not row:
            return None
        try:
            data = json.loads(row["data"])
            data = self._rebuild_models(data)
            job = JobState(**data)
            await self.save(job)
            def _del_arch():
                self._conn.execute("DELETE FROM archive WHERE job_id = ?", (job_id,))
            await asyncio.to_thread(_del_arch)
            return job
        except Exception as e:
            logger.warning(f"[Storage] 恢复归档失败 {job_id}: {e}")
            return None

    async def count(self) -> int:
        """返回任务总数"""
        def _count():
            row = self._conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()
            return row["c"]
        return await asyncio.to_thread(_count)

    @staticmethod
    def _rebuild_models(data: dict) -> dict:
        """从 JSON dict 重建 Pydantic 模型对象"""
        raw_scenes = data.get("scenes", [])
        cleaned = []
        for s in raw_scenes:
            if isinstance(s, dict):
                if "emotional_intensity" in s:
                    try:
                        s["emotional_intensity"] = int(float(s["emotional_intensity"]))
                    except (ValueError, TypeError):
                        s["emotional_intensity"] = 5
            cleaned.append(s)
        data["scenes"] = [Scene(**s) if isinstance(s, dict) else s for s in cleaned]
        data["characters"] = [Character(**c) if isinstance(c, dict) else c
                              for c in data.get("characters", [])]
        return data

    async def migrate_from_json(self):
        """从旧 JSON 文件迁移数据到 SQLite"""
        if not JSON_STORAGE_DIR.exists():
            return

        migrated = 0
        for path in JSON_STORAGE_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                job_id = data.get("id", path.stem)
                # 检查是否已存在
                existing = await self.load_one(job_id)
                if existing:
                    continue  # 已迁移过
                data = self._rebuild_models(data)
                job = JobState(**data)
                await self.save(job)
                migrated += 1
                logger.info(f"[Storage] 迁移 JSON → SQLite: {job_id} ({job.novel_title[:30]})")
            except Exception as e:
                logger.warning(f"[Storage] 迁移失败 {path.name}: {str(e)[:100]}")

        if migrated > 0:
            logger.info(f"[Storage] JSON → SQLite 迁移完成: {migrated} 个任务")
            # 迁移成功后重命名旧目录（不删除，保留备份）
            backup_dir = JSON_STORAGE_DIR.parent / "jobs_json_backup"
            try:
                if backup_dir.exists():
                    import shutil
                    shutil.rmtree(backup_dir)
                JSON_STORAGE_DIR.rename(backup_dir)
                logger.info(f"[Storage] 旧 JSON 文件已备份到 {backup_dir}")
            except Exception as e:
                logger.warning(f"[Storage] 备份旧 JSON 目录失败: {e}")


async def get_storage() -> Storage:
    """获取全局存储实例（单例）"""
    global _db
    if _db is None:
        _db = Storage(DB_PATH)
        await _db.initialize()
        await _db.migrate_from_json()
    return _db


async def sync_save(job: JobState):
    """便捷方法：保存任务"""
    db = await get_storage()
    await db.save(job)


async def sync_load_all() -> dict[str, JobState]:
    """便捷方法：加载所有任务"""
    db = await get_storage()
    return await db.load_all()


async def sync_delete(job_id: str):
    """便捷方法：删除任务"""
    db = await get_storage()
    await db.delete(job_id)


async def sync_list_jobs() -> list[dict]:
    """便捷方法：列出任务"""
    db = await get_storage()
    return await db.list_jobs()


async def sync_export_job(job_id: str) -> Optional[dict]:
    """v12.1: 导出任务"""
    db = await get_storage()
    return await db.export_job(job_id)


async def sync_import_job(data: dict) -> Optional[JobState]:
    """v12.1: 导入任务"""
    db = await get_storage()
    return await db.import_job(data)


async def sync_archive_old_jobs(days: int = 30) -> list[str]:
    """v12.1: 归档旧任务"""
    db = await get_storage()
    return await db.archive_old_jobs(days)


async def sync_list_archived() -> list[dict]:
    """v12.1: 列出归档任务"""
    db = await get_storage()
    return await db.list_archived()


async def sync_restore_archived(job_id: str) -> Optional[JobState]:
    """v12.1: 恢复归档任务"""
    db = await get_storage()
    return await db.restore_archived(job_id)
