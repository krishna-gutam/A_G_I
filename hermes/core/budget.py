"""Per-turn iteration budget."""

from typing import Optional

from ..config import settings


class IterationBudget:
    """
    Bounds one turn. Consumed per model round-trip, not per tool call, so a
    single response with five parallel calls costs one unit.

    On exhaustion the turn ends with a handoff instruction rather than a bare
    error, so the model gets a chance to summarize where it got to.

    `limit=None` means "whatever ITERATION_BUDGET says". Frontends used to have
    to monkey-patch this class to make the .env setting apply to them.
    """

    def __init__(self, limit: Optional[int] = None):
        self.limit = settings.ITERATION_BUDGET if limit is None else limit
        self.used = 0

    def consume(self) -> None:
        self.used += 1

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    @property
    def near_limit(self) -> bool:
        return self.used >= self.limit - 2

    def handoff_prompt(self) -> str:
        return (
            f"You have used your {self.limit}-step budget for this turn. Stop calling "
            "tools. Summarize what you accomplished, what remains, and the exact next "
            "step you would take."
        )
