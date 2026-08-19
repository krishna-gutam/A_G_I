"""
Conversation state: the ordered message list, plus the invariants a provider
will reject if we break them.

The dual-representation scheme each message carries is described in
`hermes.core.messages`.
"""

from typing import List, Optional

from .messages import CANCELLED_RESULT, Message, ToolCall, Turn

__all__ = ["Conversation", "Message", "ToolCall", "Turn", "CANCELLED_RESULT"]


class Conversation:
    def __init__(self, system_prompt: Optional[str] = None):
        self.system_prompt = system_prompt
        self.messages: List[Message] = []

    # --- mutation ---------------------------------------------------------

    def add_user(self, text: str) -> Message:
        msg = Message(role="user", content=text)
        self.messages.append(msg)
        return msg

    def add_turn(self, turn: Turn) -> Message:
        msg = Message(
            role="assistant",
            content=turn.content,
            tool_calls=list(turn.tool_calls),
            api_content=turn.api_content,
        )
        self.messages.append(msg)
        return msg

    def add_tool_results(self, transport, results: List[dict]) -> None:
        """
        results: [{"call": ToolCall, "output": str}, ...] in the SAME order the
        model issued the calls. Parallel execution must reorder its results back
        into call order before getting here -- some protocols pair by position,
        and every protocol pairs better when the order is stable for the cache.
        """
        for msg in transport.tool_result_messages(results):
            self.messages.append(msg)

    # --- invariants -------------------------------------------------------

    def close_interrupted_tool_sequence(self, transport) -> int:
        """
        An assistant message carrying tool calls MUST be followed by a result
        for each one. If the user hit Ctrl-C mid-execution, the sequence is
        left open and the next request 400s on every provider. Backfill the
        missing ones with an explicit cancellation so the model learns the tool
        did not run.

        Returns the number of synthetic results injected.
        """
        last_assistant = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].role == "assistant" and self.messages[i].tool_calls:
                last_assistant = i
                break
        if last_assistant is None:
            return 0

        answered = set()
        for msg in self.messages[last_assistant + 1:]:
            if msg.role == "tool":
                answered.add(msg.tool_call_id or msg.name)

        missing = [
            c for c in self.messages[last_assistant].tool_calls
            if (c.id or c.name) not in answered
        ]
        if not missing:
            return 0

        self.add_tool_results(
            transport, [{"call": c, "output": CANCELLED_RESULT} for c in missing]
        )
        return len(missing)

    # --- views ------------------------------------------------------------

    def durable(self) -> List[dict]:
        """Clean history for transcripts, search, or export. No opaque blobs."""
        return [m.clean() for m in self.messages]

    def to_dict(self) -> dict:
        """
        Session-store form. Keeps BOTH representations: drop api_content here
        and a resumed thread loses its reasoning state, which is the same bug
        as dropping it in memory -- just deferred until the user reopens the tab.
        """
        return {
            "system_prompt": self.system_prompt,
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        conv = cls(system_prompt=d.get("system_prompt"))
        conv.messages = [Message.from_dict(m) for m in d.get("messages", [])]
        return conv

    def __len__(self):
        return len(self.messages)
