import pytest

from usta.core.budget import Budget
from usta.core.run import RunState


@pytest.mark.parametrize(
    ("turns", "active", "cost", "expected"),
    [
        (0, 0.0, 0.0, None),
        (40, 0.0, 0.0, "max_turns"),
        (0, 1200.0, 0.0, "timeout"),
        (0, 0.0, 0.5, "cost"),
        (40, 1200.0, 0.5, "max_turns"),
    ],
)
def test_budget_check(turns: int, active: float, cost: float, expected: str | None) -> None:
    run = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5)
    run.turns, run.active_seconds, run.cost_usd = turns, active, cost
    assert Budget().check(run) == expected
