"""What the transcript loop needs that the session doesn't own."""

from typing import List, Optional

from ... import tools
from ...core.session import AgentSession

AUTO_LEVELS = {
    "none": None,
    "read": tools.Risk.READ,
    "write": tools.Risk.WRITE,
    "all": tools.Risk.EXEC,
}


def ceiling_name(ceiling: Optional[tools.Risk]) -> str:
    for name, level in AUTO_LEVELS.items():
        if level == ceiling:
            return name
    return "none"


class Tui:
    """Everything the transcript loop needs that the session doesn't own."""

    def __init__(self, session: AgentSession):
        self.session = session
        self.printed = 0            # messages already rendered
        self.ceiling: Optional[tools.Risk] = None   # auto-approval risk ceiling
        self.last_search: List = []  # numbered results from /models

    def reset_transcript(self) -> None:
        self.printed = len(self.session.conversation.messages)
