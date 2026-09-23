"""成本治理（借鉴 OpenMontage tools/cost_tracker.py 思路，独立轻量实现）。

生命周期：estimate（预估）→ reserve（预留额度）→ reconcile（回写实际）。
预算模式：
  - observe : 只记录，不拦截
  - warn    : 超预算记警告，仍放行
  - cap     : 超预算拒绝（默认）

用法：
    ct = CostTracker(budget_usd=10.0, mode="cap")
    eid = ct.estimate("seedance_ark", "i2v 5s", 0.30)
    if ct.reserve(eid):
        ...  # 执行
        ct.reconcile(eid, 0.28)   # 实际花费
    print(ct.summary())
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CostEntry:
    entry_id: str
    tool: str
    operation: str
    estimated_usd: float
    reserved: bool = False
    actual_usd: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    reconciled_at: Optional[float] = None


class CostTracker:
    """总预算治理：estimate → reserve → reconcile。"""

    def __init__(self, budget_usd: float = 10.0, mode: str = "cap",
                 reserve_holdback: float = 0.10, warn_threshold: float = 0.9):
        self.budget_usd = budget_usd
        self.mode = mode                      # observe | warn | cap
        self.reserve_holdback = reserve_holdback  # 预留安全边际比例
        self.warn_threshold = warn_threshold
        self._entries: dict[str, CostEntry] = {}
        self._spent = 0.0
        self._reserved = 0.0
        self.warnings: list[str] = []

    # ─── 生命周期 ────────────────────────────────────────────
    def estimate(self, tool: str, operation: str, estimated_usd: float) -> str:
        eid = uuid.uuid4().hex[:10]
        self._entries[eid] = CostEntry(
            entry_id=eid, tool=tool, operation=operation,
            estimated_usd=float(estimated_usd))
        return eid

    def reserve(self, entry_id: str) -> bool:
        """预留额度。预算不足（含安全边际）时按模式处理。"""
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        usable = self.budget_usd * (1 - self.reserve_holdback)
        if self._spent + self._reserved + entry.estimated_usd > usable:
            msg = (f"预算不足: 已花 {self._spent:.2f}$ + 预留 {self._reserved:.2f}$ "
                   f"+ 预估 {entry.estimated_usd:.2f}$ > 可用 {usable:.2f}$")
            self.warnings.append(msg)
            if self.mode == "cap":
                return False
            if self.mode == "warn":
                print(f"[CostTracker] WARN: {msg}", flush=True)
        entry.reserved = True
        self._reserved += entry.estimated_usd
        return True

    def reconcile(self, entry_id: str, actual_usd: float) -> None:
        entry = self._entries.get(entry_id)
        if not entry or not entry.reserved:
            return
        self._reserved -= entry.estimated_usd
        self._spent += float(actual_usd)
        entry.actual_usd = float(actual_usd)
        entry.reconciled_at = time.time()

    # ─── 查询 ────────────────────────────────────────────────
    def remaining(self) -> float:
        return max(0.0, self.budget_usd - self._spent - self._reserved)

    def spent(self) -> float:
        return self._spent

    def summary(self) -> dict:
        return {
            "budget_usd": self.budget_usd,
            "spent_usd": round(self._spent, 4),
            "reserved_usd": round(self._reserved, 4),
            "remaining_usd": round(self.remaining(), 4),
            "mode": self.mode,
            "entries": len(self._entries),
            "warnings": self.warnings[-5:],
        }
