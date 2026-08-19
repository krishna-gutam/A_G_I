"""
Anthropic Messages transport.

This one exists because its wire format is genuinely different, not because
Anthropic is a different company.
"""

from ..core.messages import Message, ToolCall, Turn
from ..providers.profiles import ANTHROPIC_MESSAGES
from .base import BaseTransport, strip_nulls


class AnthropicMessagesTransport(BaseTransport):
    api_mode = ANTHROPIC_MESSAGES

    def _headers(self):
        h = {"Content-Type": "application/json", **self.runtime.headers}
        if self.runtime.api_key:
            h["x-api-key"] = self.runtime.api_key
        return h

    def _to_wire(self, msg: Message) -> dict:
        if msg.api_content is not None:
            # Content blocks verbatim -- this is what preserves thinking-block
            # signatures across turns.
            return strip_nulls(msg.api_content)

        if msg.role == "tool":
            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                }],
            }

        blocks = []
        if msg.content:
            blocks.append({"type": "text", "text": msg.content})
        for c in msg.tool_calls:
            blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args})
        return {"role": msg.role, "content": blocks or [{"type": "text", "text": ""}]}

    def generate(self, conversation, tools) -> Turn:
        # Adjacent tool results must be merged into a single user message.
        wire = []
        for m in conversation.messages:
            entry = self._to_wire(m)
            if (m.role == "tool" and wire and wire[-1]["role"] == "user"
                    and isinstance(wire[-1].get("content"), list)):
                wire[-1]["content"].extend(entry["content"])
            else:
                wire.append(entry)

        payload = {
            "model": self.runtime.model_id,
            "max_tokens": 8192,
            "messages": wire,
            "tools": [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ],
        }
        if conversation.system_prompt:
            payload["system"] = conversation.system_prompt
        if self.runtime.thinking:
            budget = {"low": 2048, "medium": 8192, "high": 24576}[self.runtime.thinking]
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            payload["max_tokens"] = max(payload["max_tokens"], budget + 4096)

        data = self._post("/messages", payload)
        blocks = data.get("content", [])

        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        tool_calls = [
            ToolCall(id=b.get("id"), name=b.get("name"), args=b.get("input", {}), raw=b)
            for b in blocks if b.get("type") == "tool_use"
        ]

        return Turn(
            content=text,
            tool_calls=tool_calls,
            api_content={"role": "assistant", "content": blocks},
            metadata={
                "usage": data.get("usage"),
                "model": data.get("model", self.runtime.model_id),
                "provider": self.runtime.provider,
            },
            finish_reason=data.get("stop_reason"),
        )
