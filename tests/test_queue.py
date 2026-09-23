"""queue 模块测试：CostTracker 预算治理 + TaskQueue 并发/重试/续传。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler.cost import CostTracker  # noqa: E402
from scheduler.tasks import Task, TaskQueue  # noqa: E402


def test_cost_tracker():
    ct = CostTracker(budget_usd=10.0, mode="cap")
    # 预算内
    eid = ct.estimate("seedance_ark", "i2v 5s", 0.30)
    assert ct.reserve(eid) is True
    ct.reconcile(eid, 0.28)
    assert abs(ct.spent() - 0.28) < 1e-6
    # 超预算（cap 拒绝）
    big = ct.estimate("runway", "long clip", 100.0)
    assert ct.reserve(big) is False
    # 观察模式不拦截
    ct2 = CostTracker(budget_usd=1.0, mode="observe")
    b2 = ct2.estimate("x", "y", 5.0)
    assert ct2.reserve(b2) is True
    print("✅ CostTracker: 预算内通过 / 超预算 cap 拒绝 / observe 放行")


async def test_task_queue():
    calls = {"ok": 0, "retry_ok": 0}

    async def ok_task():
        calls["ok"] += 1
        return "done"

    async def retry_then_ok():
        calls["retry_ok"] += 1
        if calls["retry_ok"] < 2:
            raise RuntimeError("第一次失败")
        return "done"

    q = TaskQueue(max_concurrency=2, resume=True)
    q.submit(Task(id="a", run=ok_task))
    q.submit(Task(id="b", run=retry_then_ok, retries=2))
    q.submit(Task(id="c", run=ok_task))
    await q.run()
    prog = q.progress()
    assert prog["done"] == 3, f"期望 3 完成，实际 {prog}"
    assert prog["failed"] == 0

    # 断点续传：再次提交已完成 id → 跳过
    q2 = TaskQueue(max_concurrency=2, resume=True)
    # 先跑一遍 a
    q2.submit(Task(id="a", run=ok_task))
    await q2.run()
    assert q2.progress()["done"] == 1
    q2.submit(Task(id="a", run=ok_task))  # 重复 id
    q2.submit(Task(id="d", run=ok_task))
    await q2.run()
    p2 = q2.progress()
    assert p2["skipped"] == 1, f"期望跳过 1，实际 {p2}"
    assert p2["done"] == 2
    print(f"✅ TaskQueue: 并发2完成3任务 / 失败自动重试 / 断点续传跳过 (进度={prog})")


def test_state_persistence():
    """状态落盘 + 模拟进程重启恢复（断点续传）。"""
    import tempfile
    from pathlib import Path

    async def ok_task():
        return "done"

    tmp = Path(tempfile.mkdtemp(prefix="qstate_"))
    state = tmp / "queue_state.json"

    # 第一批：跑 2 个任务，落盘
    q1 = TaskQueue(max_concurrency=2, resume=True, state_file=state)
    q1.submit(Task(id="a", run=ok_task))
    q1.submit(Task(id="b", run=ok_task))
    asyncio.run(q1.run())
    assert state.exists()
    assert q1.progress()["done"] == 2

    # 模拟进程重启：新队列从磁盘恢复
    q2 = TaskQueue(max_concurrency=2, resume=True, state_file=state)
    loaded = q2.load_state()
    assert loaded is True
    # 重新提交 a（已完成）→ 跳过；提交 c（新）→ 执行
    q2.submit(Task(id="a", run=ok_task))
    q2.submit(Task(id="c", run=ok_task))
    asyncio.run(q2.run())
    p2 = q2.progress()
    assert p2["skipped"] >= 1, f"期望跳过已完成 a: {p2}"
    assert p2["done"] >= 1, f"c 应被执行: {p2}"
    print(f"✅ 队列状态持久化: 落盘→重启→跳过已完成 (progress={p2})")


def main():
    test_cost_tracker()
    asyncio.run(test_task_queue())
    test_state_persistence()
    print("QUEUE TEST OK")


if __name__ == "__main__":
    main()
