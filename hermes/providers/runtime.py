"""
Runtime resolution.

Turns a model string like "gemini:gemini-3-flash" into everything needed to
make a request: base URL, credential, and the wire protocol to speak.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..config import settings
from .profiles import CHAT_COMPLETIONS, DEFAULT_PROVIDER, PROFILES


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

    base_url = (
        base_url_override or settings.BASE_URL_OVERRIDE or profile.base_url
    ).rstrip("/")

    return RuntimeConfig(
        provider=provider,
        model_id=model_id,
        base_url=base_url,
        api_key=_first_env(profile.key_env),
        api_mode=detect_api_mode(base_url, provider),
        headers=dict(profile.headers),
        thinking=thinking,
    )


def resolve_chain(model_strings, thinking: Optional[str] = None) -> List[RuntimeConfig]:
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
