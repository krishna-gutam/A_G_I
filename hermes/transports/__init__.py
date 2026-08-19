"""
Transports: one per wire protocol.

ChatCompletionsTransport serves OpenAI, Gemini (compat endpoint), OpenRouter,
DeepSeek, Groq, Ollama, vLLM and anything else OpenAI-shaped. AnthropicMessages
exists because its format genuinely differs.

Adding a protocol means a module here plus a row in TRANSPORTS.
"""

from ..providers.errors import TransportError
from ..providers.profiles import ANTHROPIC_MESSAGES, CHAT_COMPLETIONS
from .anthropic_messages import AnthropicMessagesTransport
from .base import BaseTransport
from .chat_completions import ChatCompletionsTransport

TRANSPORTS = {
    CHAT_COMPLETIONS: ChatCompletionsTransport,
    ANTHROPIC_MESSAGES: AnthropicMessagesTransport,
}


def build_transport(runtime):
    return TRANSPORTS[runtime.api_mode](runtime)


__all__ = [
    "TRANSPORTS", "build_transport", "BaseTransport", "TransportError",
    "ChatCompletionsTransport", "AnthropicMessagesTransport",
]
