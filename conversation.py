"""
Conversation state.

The central idea is the `api_content` sidecar: every message keeps two
representations.

  content      -- clean text. What you print, log, search, summarize, export.
  api_content  -- the provider's own message object, byte-faithful.

Whatever opaque state the vendor requires back -- Gemini thought signatures,
OpenAI reasoning items, Anthropic thinking-block signatures -- rides in
api_content and is replayed untouched. Nothing here inspects it, so nothing
here can drop it. The clean copy stays readable regardless.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CANCELLED_RESULT = '{"error": "cancelled", "message": "Tool execution interrupted by user."}'


@dataclass
class ToolCall:
    id: Optional[str]
    name: str
    args: dict
    raw: Any = None  # provider-native call object, if the protocol needs it back


@dataclass
class Message:
    role: str                                    # user | assistant | tool
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    api_content: Optional[Dict] = None           # wire-faithful sidecar

    def to_dict(self) -> dict:
        """Full persistence form: clean fields AND the wire-faithful sidecar."""
        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in self.tool_calls],
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "api_content": self.api_content,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            role=d["role"],
            content=d.get("content", ""),
            tool_calls=[ToolCall(c.get("id"), c["name"], c.get("args", {})) for c in d.get("tool_calls") or []],
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
            api_content=d.get("api_content"),
        )

    def clean(self) -> dict:
        """Durable/display form. Never sent to a provider."""
        out = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [{"name": c.name, "args": c.args} for c in self.tool_calls]
        if self.name:
            out["name"] = self.name
        return out


@dataclass
class Turn:
    """One assistant response, normalized for the caller to read."""
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    api_content: Optional[Dict] = None
    metadata: dict = field(default_factory=dict)
    finish_reason: Optional[str] = None


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


class IterationBudget:
    """
    Bounds one turn. Consumed per model round-trip, not per tool call, so a
    single response with five parallel calls costs one unit.

    On exhaustion the turn ends with a handoff instruction rather than a bare
    error, so the model gets a chance to summarize where it got to.
    """

    def __init__(self, limit: int = 12):
        self.limit = limit
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
