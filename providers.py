"""
Provider runtime resolution.

Turns a model string like "gemini:gemini-3-flash" into everything needed to
make a request: base URL, credential, and -- most importantly -- the *API mode*
(wire protocol). Adding a provider is a dict entry here, not a new adapter.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

# Imported for its side effect: loads .env before the profiles below read it.
import paths  # noqa: F401

# --- API modes (wire protocols) ------------------------------------------
# Transports are written per protocol, not per vendor. A dozen providers share
# CHAT_COMPLETIONS; only genuinely different wire formats earn a new mode.
CHAT_COMPLETIONS = "chat_completions"
ANTHROPIC_MESSAGES = "anthropic_messages"


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
    "anthropic": ProviderProfile(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        key_env=("ANTHROPIC_API_KEY",),
        api_mode=ANTHROPIC_MESSAGES,
        default_model="claude-sonnet-4-6",
        headers={"anthropic-version": "2023-06-01"},
    ),
    # Anything OpenAI-shaped: Ollama, LM Studio, vLLM, llama.cpp.
    "local": ProviderProfile(
        name="local",
        base_url=os.getenv("LOCAL_BASE_URL", "http://localhost:11434/v1"),
        key_env=("LOCAL_API_KEY",),
        default_model="qwen3:latest",
    ),
}

DEFAULT_PROVIDER = "openai"


@dataclass
class RuntimeConfig:
    provider: str
    model_id: str
    base_url: str
    api_key: Optional[str]
    api_mode: str
    headers: dict = field(default_factory=dict)
    thinking: Optional[str] = None  # "low" | "medium" | "high"

    def __str__(self):
        return f"{self.provider}:{self.model_id} [{self.api_mode}]"


def split_provider_prefix(model_string: str) -> Tuple[Optional[str], str]:
    """
    Split "provider:model" without mangling model names that legitimately
    contain a colon -- "qwen3:latest", "llama3.1:8b-instruct". A prefix only
    counts if it names a provider we actually know.
    """
    if ":" not in model_string:
        return None, model_string
    head, tail = model_string.split(":", 1)
    if head in PROFILES and tail:
        return head, tail
    return None, model_string


def detect_api_mode(base_url: str, provider: Optional[str]) -> str:
    """
    Infer the wire protocol from the endpoint. URL wins over provider name so
    that custom gateways and proxies route correctly.
    """
    host = (base_url or "").lower()
    if "api.anthropic.com" in host or host.rstrip("/").endswith("/anthropic"):
        return ANTHROPIC_MESSAGES
    if provider and provider in PROFILES:
        return PROFILES[provider].api_mode
    return CHAT_COMPLETIONS


def _first_env(names: Tuple[str, ...]) -> Optional[str]:
    for n in names:
        val = os.getenv(n)
        if val:
            return val
    return None


def resolve_runtime(model_string: str, base_url_override: Optional[str] = None,
                    thinking: Optional[str] = None) -> RuntimeConfig:
    """
    "gemini:gemini-3-flash"  -> gemini profile, compat endpoint, chat_completions
    "anthropic"              -> anthropic profile, its default model
    "gpt-4o-mini"            -> default provider
    """
    provider, model_id = split_provider_prefix(model_string)

    if provider is None and model_string in PROFILES:
        provider, model_id = model_string, ""

    provider = provider or DEFAULT_PROVIDER
    profile = PROFILES[provider]
    model_id = model_id or profile.default_model

    base_url = (base_url_override or os.getenv("HERMES_BASE_URL") or profile.base_url).rstrip("/")

    return RuntimeConfig(
        provider=provider,
        model_id=model_id,
        base_url=base_url,
        api_key=_first_env(profile.key_env),
        api_mode=detect_api_mode(base_url, provider),
        headers=dict(profile.headers),
        thinking=thinking,
    )


def resolve_chain(model_strings, thinking: Optional[str] = None):
    """Primary runtime first, then fallbacks. Unconfigured providers are dropped."""
    chain = []
    for ms in model_strings:
        ms = ms.strip()
        if not ms:
            continue
        rt = resolve_runtime(ms, thinking=thinking)
        if rt.api_key or rt.provider == "local":
            chain.append(rt)
    return chain


# --- Error classification -------------------------------------------------

RETRY = "retry"          # transient, same runtime
FAILOVER = "failover"    # try the next runtime in the chain
FATAL = "fatal"          # stop; the caller's request is wrong


def classify_error(status: int, body: str) -> str:
    text = (body or "").lower()
    if status == 429 or "rate limit" in text or "quota" in text:
        return FAILOVER
    if status in (401, 403) or "invalid api key" in text:
        return FAILOVER
    if status in (402,) or "insufficient" in text or "billing" in text:
        return FAILOVER
    if status >= 500 or "overloaded" in text:
        return RETRY
    if "context length" in text or "too many tokens" in text or "context_length" in text:
        return FATAL  # compression would handle this; we surface it instead
    return FATAL
