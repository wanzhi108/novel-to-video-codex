"""批量任务队列 —— 并发控制 + 自动重试 + 断点续传 + 进度回调。

适用：批量生成场景视频段（每段一个任务），云端/本地引擎统一排队。
并发由 max_concurrency 控制（本地受 VRAM 限制，云端受 API 配额限制）。

用法：
    q = TaskQueue(max_concurrency=2)
    for scene in scenes:
        q.submit(Task(id=f"scene-{scene.id}", run=partial(engine.generate, req)))
    await q.run()          # 消费全部任务
    print(q.summary())     # {done, failed, skipped, duration, ...}

断点续传：任务 id 具有幂等性——submit 时若 same id 已完成则跳过（resume 模式）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("novel2vid.queue")


@dataclass
class Task:
    id: str
    run: Callable[[], Awaitable[object]]   # 实际执行（通常闭包捕获引擎调用）
    retries: int = 2                        # 失败重试次数（0=不重试）
    cost_entry_id: Optional[str] = None     # CostTracker 预留条目
    metadata: dict = field(default_factory=dict)


class TaskQueue:
    """asyncio 批量队列（支持状态落盘断点续传）。"""

    def __init__(self, max_concurrency: int = 2, resume: bool = True,
                 on_progress: Optional[Callable[[dict], None]] = None,
                 state_file: Optional[Path] = None):
        self.max_concurrency = max_concurrency
        self.resume = resume
        self.on_progress = on_progress
        self.state_file = state_file
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._done: set[str] = set()          # 已完成任务 id（供断点续传）
        self._failed: set[str] = set()
        self._stats: dict = {"done": 0, "failed": 0, "skipped": 0}
        self._started = 0.0
        if state_file is not None:
            self.load_state(state_file)

    # ─── 状态持久化（断点续传落盘）──────────────────────────
    def save_state(self, path: Optional[Path] = None) -> Path:
        """把 done/failed 集合落盘（进程重启后可恢复）。"""
        p = Path(path) if path else self.state_file
        if p is None:
            raise ValueError("未指定 state_file")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "done": sorted(self._done),
            "failed": sorted(self._failed),
            "stats": self._stats,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def load_state(self, path: Optional[Path] = None) -> bool:
        """从磁盘恢复 done/failed（resume 语义）。返回是否有状态可恢复。"""
        p = Path(path) if path else self.state_file
        if p is None or not p.exists():
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self._done = set(data.get("done", []))
            self._failed = set(data.get("failed", []))
            stats = data.get("stats", {"done": 0, "failed": 0, "skipped": 0})
            stats["skipped"] = stats.get("skipped", 0) + len(self._done)
            self._stats = stats
            return bool(self._done or self._failed)
        except Exception:
            return False

    def submit(self, task: Task) -> bool:
        """入队。resume 模式下已完成的 id 跳过。返回是否实际入队。"""
        if self.resume and task.id in self._done:
            self._stats["skipped"] += 1
            logger.info(f"[Queue] 跳过已完成任务 {task.id}")
            return False
        self._queue.put_nowait(task)
        return True

    async def _run_one(self, task: Task) -> None:
        for attempt in range(task.retries + 1):
            try:
                await task.run()
                self._done.add(task.id)
                self._stats["done"] += 1
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[Queue] {task.id} 第 {attempt+1}/{task.retries+1} 次失败: {exc}")
                if attempt < task.retries:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
        self._failed.add(task.id)
        self._stats["failed"] += 1

    async def run(self) -> None:
        """消费队列直到空。"""
        self._started = time.time()
        semaphore = asyncio.Semaphore(self.max_concurrency)
        workers = []

        async def worker():
            while True:
                try:
                    task = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                async with semaphore:
                    await self._run_one(task)
                self._queue.task_done()
                if self.on_progress:
                    self.on_progress(self.progress())

        while not self._queue.empty():
            workers = [asyncio.create_task(worker()) for _ in range(self.max_concurrency)]
            await asyncio.gather(*workers, return_exceptions=True)
            # 若 run() 期间有新任务入队，继续下一轮 worker 消费

        # 完成后自动落盘状态（配置了 state_file 时）
        if self.state_file is not None:
            try:
                self.save_state(self.state_file)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[Queue] 状态落盘失败: {exc}")

    async def wait_empty(self) -> None:
        await self._queue.join()

    def progress(self) -> dict:
        total = self._stats["done"] + self._stats["failed"] + self._stats["skipped"]
        pending = self._queue.qsize()
        return {
            "done": self._stats["done"],
            "failed": self._stats["failed"],
            "skipped": self._stats["skipped"],
            "pending": pending,
            "total": total + pending,
        }

    def summary(self) -> dict:
        return {
            **self.progress(),
            "duration_seconds": round(time.time() - self._started, 2) if self._started else 0.0,
        }
