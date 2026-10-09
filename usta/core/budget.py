"""Run budgets shared by both engines (SPEC §15.2, ADR-035)."""

from typing import Literal

from usta.core.base import Frozen
from usta.core.run import RunState

BudgetLimit = Literal["max_turns", "timeout", "cost"]


class Budget(Frozen):
    max_turns: int = 40
    cost_step_usd: float = 0.50
    max_active_seconds: float = 1200.0

    def check(self, run: RunState) -> BudgetLimit | None:
        if run.turns >= self.max_turns:
            return "max_turns"
        if run.active_seconds >= self.max_active_seconds:
            return "timeout"
        if run.cost_usd >= run.cost_cap_usd:
            return "cost"
        return None
