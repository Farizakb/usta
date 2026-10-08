from usta.core.base import Frozen
from usta.core.events import Event
from usta.core.messages import ToolResult


class ToolOutcome(Frozen):
    """What the tool pipeline returns to an engine. M2 adds a parked flag for approvals."""

    result: ToolResult
    event: Event | None = None
