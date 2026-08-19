"""
Message primitives.

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
