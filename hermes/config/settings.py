"""
Every environment knob, in one place.

Previously these `os.getenv` calls were scattered across eight modules, so the
only way to learn what `.env` accepted was to grep for `getenv`. Two of them had
also drifted: `ITERATION_BUDGET` was read in the CLI but not in the session
layer, which meant the setting worked in the terminal and was silently ignored
in every UI.

Values that are fixed for the life of the process are constants. Values a user
can change between turns stay functions, so they are re-read on each call.
"""

import os
from typing import List, Optional

# --- values read once, at import -----------------------------------------

#: Model round-trips allowed per turn before the agent is asked to summarize.
ITERATION_BUDGET = int(os.getenv("ITERATION_BUDGET", "12"))

#: Ceiling on concurrently executing tool calls within one batch.
MAX_PARALLEL_TOOLS = int(os.getenv("MAX_PARALLEL_TOOLS", "8"))

#: Let file tools resolve paths outside the working directory.
ALLOW_OUTSIDE_WORKSPACE = os.getenv(
    "HERMES_ALLOW_OUTSIDE_WORKSPACE", ""
).lower() in ("1", "true", "yes")

#: Base URL for the `local` provider: Ollama, LM Studio, vLLM, llama.cpp.
LOCAL_BASE_URL = os.getenv("LOCAL_BASE_URL", "http://localhost:11434/v1")

#: Overrides the base URL of whichever provider is resolved. Rarely set.
BASE_URL_OVERRIDE = os.getenv("HERMES_BASE_URL") or None

#: Seconds to wait on a provider response.
REQUEST_TIMEOUT = int(os.getenv("HERMES_REQUEST_TIMEOUT", "180"))

#: Toolsets enabled when TOOLSETS is unset and a session doesn't name its own.
#:
#: NOTE: behaviour preserved from before the restructure, but it disagrees with
#: both the README and .env.example, which say only `files` is on by default.
#: With no TOOLSETS line, shell and network tools are live -- gated by the
#: approval prompt, but live. Decide which one is right and make them match:
#: either drop this to ["files"], or correct the docs.
SAFE_DEFAULT_TOOLSETS = ["files", "shell", "web"]


# --- values re-read on each call -----------------------------------------


def default_model() -> str:
    return os.getenv("MODEL", "gemini:gemini-3-flash")


def default_fallbacks() -> List[str]:
    return [m.strip() for m in os.getenv("FALLBACK_MODELS", "").split(",") if m.strip()]


def default_thinking() -> Optional[str]:
    return os.getenv("THINKING") or None


def default_toolsets() -> List[str]:
    configured = [t.strip() for t in os.getenv("TOOLSETS", "").split(",") if t.strip()]
    return configured or list(SAFE_DEFAULT_TOOLSETS)
