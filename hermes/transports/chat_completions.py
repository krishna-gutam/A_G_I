"""
OpenAI chat-completions transport.

Serves OpenAI, Gemini's compat endpoint, OpenRouter, Groq, DeepSeek, and any
local OpenAI-shaped server. The per-provider differences that remain are small
enough to live in `_apply_thinking` rather than in separate adapters.
"""

import json

from ..core.messages import Message, ToolCall, Turn
from ..providers.profiles import CHAT_COMPLETIONS
from .base import BaseTransport, strip_nulls


class ChatCompletionsTransport(BaseTransport):
    api_mode = CHAT_COMPLETIONS

    def _headers(self):
        h = {"Content-Type": "application/json", **self.runtime.headers}
        if self.runtime.api_key:
            h["Authorization"] = f"Bearer {self.runtime.api_key}"
        return h

    # --- serialization ----------------------------------------------------

    def _to_wire(self, msg: Message) -> dict:
        if msg.api_content is not None:
            return strip_nulls(msg.api_content)  # verbatim replay

        if msg.role == "tool":
            return {"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content}

        out = {"role": msg.role, "content": msg.content or ""}
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.args)},
                }
                for c in msg.tool_calls
            ]
        return out

    def _apply_thinking(self, payload):
        """
        Thinking config differs per provider even inside one protocol. This is
        the seam where those differences live, rather than in a whole adapter.
        """
        level = self.runtime.thinking
        if not level:
            return
        if self.runtime.provider in ("openai", "openrouter", "gemini"):
            payload["reasoning_effort"] = level
        elif self.runtime.provider == "groq":
            # Groq hosts a mixed fleet: reasoning-capable models accept this,
            # and the plain instruct models reject it outright. Gate on family
            # rather than provider.
            if any(k in self.runtime.model_id.lower()
                   for k in ("gpt-oss", "qwen3", "deepseek-r1", "thinking")):
                payload["reasoning_effort"] = level
        elif self.runtime.provider == "deepseek":
            payload.setdefault("extra_body", {})["thinking"] = {"type": "enabled"}

    def generate(self, conversation, tools) -> Turn:
        wire = []
        if conversation.system_prompt:
            wire.append({"role": "system", "content": conversation.system_prompt})
        wire.extend(self._to_wire(m) for m in conversation.messages)

        payload = {
            "model": self.runtime.model_id,
            "messages": wire,
            "tools": [{"type": "function", "function": t} for t in tools],
            "tool_choice": "auto",
        }
        self._apply_thinking(payload)

        data = self._post("/chat/completions", payload)
        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {"__raw_arguments": fn.get("arguments")}
            tool_calls.append(ToolCall(id=tc.get("id"), name=fn.get("name"), args=args, raw=tc))

        return Turn(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            # The whole assistant message, including any reasoning fields the
            # provider attached. Replayed as-is; never rebuilt.
            api_content=message,
            metadata={
                "usage": data.get("usage"),
                "model": data.get("model", self.runtime.model_id),
                "provider": self.runtime.provider,
            },
            finish_reason=choice.get("finish_reason"),
        )
