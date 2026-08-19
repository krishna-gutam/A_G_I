"""
Providers: who we can talk to, how to reach them, and what a failure means.

    profiles  -- the table of providers and the protocol each one speaks
    runtime   -- "gemini:gemini-3-flash" -> a ready-to-use RuntimeConfig
    errors    -- retry / failover / fatal classification
    catalog   -- live discovery of which models each provider actually serves
"""

from .errors import FAILOVER, FATAL, RETRY, TransportError, classify_error
from .profiles import (
    ANTHROPIC_MESSAGES,
    CHAT_COMPLETIONS,
    DEFAULT_PROVIDER,
    PROFILES,
    ProviderProfile,
)
from .runtime import (
    RuntimeConfig,
    detect_api_mode,
    resolve_chain,
    resolve_runtime,
    split_provider_prefix,
)

__all__ = [
    "ANTHROPIC_MESSAGES", "CHAT_COMPLETIONS", "DEFAULT_PROVIDER", "PROFILES",
    "ProviderProfile", "RuntimeConfig", "detect_api_mode", "resolve_chain",
    "resolve_runtime", "split_provider_prefix",
    "RETRY", "FAILOVER", "FATAL", "TransportError", "classify_error",
]
