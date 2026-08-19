"""
Transports: one per wire protocol, not one per vendor.

ChatCompletionsTransport serves OpenAI, Gemini (compat endpoint), OpenRouter,
DeepSeek, Ollama, vLLM and anything else OpenAI-shaped. AnthropicMessages
exists because its wire format is genuinely different, not because Anthropic
is a different company.

Every transport obeys the same rule: when a stored message carries an
api_content sidecar, send that verbatim. Reconstruction from clean fields is a
fallback for history that was restored from disk.
"""

import json
import requests

from conversation import Message, ToolCall, Turn
from providers import CHAT_COMPLETIONS, ANTHROPIC_MESSAGES, classify_error

TIMEOUT = 180


class TransportError(Exception):
    def __init__(self, status, body, action):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status = status
        self.body = body
        self.action = action  # RETRY | FAILOVER | FATAL


def _strip_nulls(obj):
    """
    Provider SDKs and our own dict building both like to emit explicit nulls for
    fields the API never returned; several endpoints reject unknown null
    parameters on the way back in. Drop them before replaying.
    """
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(v) for v in obj]
    return obj


class BaseTransport:
    def __init__(self, runtime):
        self.runtime = runtime
        self.session = requests.Session()

    def _post(self, path, payload):
        url = f"{self.runtime.base_url}{path}"
        resp = self.session.post(url, headers=self._headers(), json=payload, timeout=TIMEOUT)
        if resp.status_code != 200:
            raise TransportError(
                resp.status_code, resp.text, classify_error(resp.status_code, resp.text)
            )
        return resp.json()

    # Subclasses implement:
    def _headers(self): raise NotImplementedError
    def generate(self, conversation, tools) -> Turn: raise NotImplementedError
    def tool_result_messages(self, results): raise NotImplementedError


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
            return _strip_nulls(msg.api_content)  # verbatim replay

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

    def tool_result_messages(self, results):
        # One `tool` message per result, correlated by id.
        return [
            Message(
                role="tool",
                content=item["output"],
                tool_call_id=item["call"].id,
                name=item["call"].name,
            )
            for item in results
        ]


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
            return _strip_nulls(msg.api_content)

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

    def tool_result_messages(self, results):
        return [
            Message(
                role="tool",
                content=item["output"],
                tool_call_id=item["call"].id,
                name=item["call"].name,
            )
            for item in results
        ]


TRANSPORTS = {
    CHAT_COMPLETIONS: ChatCompletionsTransport,
    ANTHROPIC_MESSAGES: AnthropicMessagesTransport,
}


def build_transport(runtime):
    return TRANSPORTS[runtime.api_mode](runtime)
