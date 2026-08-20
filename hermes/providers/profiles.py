"""
Provider profiles.

One dict row per provider: base URL, which env vars hold its credential, and --
most importantly -- the *API mode* it speaks. Adding a provider is an entry
here, not a new adapter.
"""

from dataclasses import dataclass, field
from typing import Tuple

from ..config import settings

# --- API modes (wire protocols) ------------------------------------------
# Transports are written per protocol, not per vendor. A dozen providers share
# CHAT_COMPLETIONS; only genuinely different wire formats earn a new mode.
CHAT_COMPLETIONS = "chat_completions"


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    base_url: str
    key_env: Tuple[str, ...]
    api_mode: str = CHAT_COMPLETIONS
    default_model: str = ""
    headers: dict = field(default_factory=dict)


PROFILES = {
    "openai": ProviderProfile(
        name="openai",
        base_url="https://api.openai.com/v1",
        key_env=("OPENAI_API_KEY",),
        default_model="gpt-4o-mini",
    ),
    # Gemini via Google's OpenAI-compatible surface. This is the whole trick:
    # the native generateContent shape (parts / functionCall / thoughtSignature)
    # never enters this codebase, so it can never be dropped by our own
    # serialization. Cost: only what the compat layer chooses to expose.
    "gemini": ProviderProfile(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_env=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        default_model="gemini-3-flash",
    ),
    "openrouter": ProviderProfile(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_env=("OPENROUTER_API_KEY",),
        default_model="google/gemini-3-flash",
    ),
    # Groq is OpenAI-shaped, so it needs no transport of its own -- just a row.
    "groq": ProviderProfile(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        key_env=("GROQ_API_KEY",),
        default_model="llama-3.3-70b-versatile",
    ),
    "deepseek": ProviderProfile(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        key_env=("DEEPSEEK_API_KEY",),
        default_model="deepseek-chat",
    ),
    # Anything OpenAI-shaped: Ollama, LM Studio, vLLM, llama.cpp.
    "local": ProviderProfile(
        name="local",
        base_url=settings.LOCAL_BASE_URL,
        key_env=("LOCAL_API_KEY",),
        default_model="qwen3:latest",
    ),
}

DEFAULT_PROVIDER = "openai"
