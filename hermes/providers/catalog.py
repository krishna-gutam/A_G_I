"""
Model catalog.

Discovers what each configured provider actually serves, caches it to disk, and
exposes a search over the union. Sources are probed independently with short
timeouts -- one dead endpoint slows nothing else down and never blocks the UI.

Tiered, in the order tried:
  1. disk cache, if fresh
  2. live probe of every provider that has a credential (plus OpenRouter,
     whose catalog is public, and any local server that answers)
  3. a small static snapshot, so the picker is never empty
"""

import json
import re
import os
import time
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

import requests

from ..config import paths, settings
from .profiles import PROFILES

CACHE_PATH = paths.MODEL_CACHE
CACHE_TTL = 60 * 60 * 12  # 12 hours
PROBE_TIMEOUT = 6


@dataclass
class ModelInfo:
    ref: str                       # "gemini:gemini-3-flash" -- paste straight into resolve_runtime
    provider: str
    model_id: str
    label: str = ""
    context_length: Optional[int] = None
    prompt_price: Optional[float] = None   # USD per 1M input tokens
    source: str = "static"

    @property
    def context_label(self) -> str:
        if not self.context_length:
            return "—"
        if self.context_length >= 1_000_000:
            return f"{self.context_length / 1_000_000:.1f}M"
        return f"{self.context_length // 1000}K"

    @property
    def price_label(self) -> str:
        if self.prompt_price is None:
            return "—"
        if self.prompt_price == 0:
            return "free"
        return f"${self.prompt_price:.2f}/M"

    def display(self) -> str:
        bits = [self.ref]
        if self.context_length:
            bits.append(self.context_label)
        if self.prompt_price is not None:
            bits.append(self.price_label)
        return "  ·  ".join(bits)


# --- static floor ---------------------------------------------------------

STATIC = [
    ("openai", "gpt-4o-mini", 128000), ("openai", "gpt-4o", 128000),
    ("openai", "o4-mini", 200000),
    ("gemini", "gemini-3-flash", 1048576), ("gemini", "gemini-3-pro", 1048576),
    ("gemini", "gemini-2.5-flash", 1048576),
    ("anthropic", "claude-sonnet-4-6", 200000), ("anthropic", "claude-haiku-4-5", 200000),
    ("deepseek", "deepseek-chat", 65536),
    # Groq hosts other people's open models; the live probe is authoritative,
    # these are only a floor for when it can't be reached.
    ("groq", "llama-3.3-70b-versatile", 131072),
    ("groq", "openai/gpt-oss-120b", 131072),
]


def _static() -> List[ModelInfo]:
    return [
        ModelInfo(ref=f"{p}:{m}", provider=p, model_id=m, context_length=ctx, source="static")
        for p, m, ctx in STATIC
    ]


# --- probes ---------------------------------------------------------------
# Each returns [] on any failure. Never raises into the caller.

def _key_for(provider: str) -> Optional[str]:
    for env in PROFILES[provider].key_env:
        if os.getenv(env):
            return os.getenv(env)
    return None


def _probe_openrouter() -> List[ModelInfo]:
    """Public catalog -- no key needed, and by far the widest coverage."""
    try:
        r = requests.get("https://openrouter.ai/api/v1/models", timeout=PROBE_TIMEOUT)
        r.raise_for_status()
        out = []
        for m in r.json().get("data", []):
            pricing = m.get("pricing") or {}
            try:
                price = float(pricing.get("prompt", 0)) * 1_000_000
            except (TypeError, ValueError):
                price = None
            out.append(ModelInfo(
                ref=f"openrouter:{m['id']}",
                provider="openrouter",
                model_id=m["id"],
                label=m.get("name", ""),
                context_length=m.get("context_length"),
                prompt_price=price,
                source="openrouter",
            ))
        return out
    except Exception:
        return []


def _probe_openai_compatible(provider: str) -> List[ModelInfo]:
    """Works for any /v1/models endpoint: OpenAI, Gemini compat, DeepSeek, Ollama."""
    key = _key_for(provider)
    profile = PROFILES[provider]
    if not key and provider != "local":
        return []
    try:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        r = requests.get(f"{profile.base_url.rstrip('/')}/models",
                         headers=headers, timeout=PROBE_TIMEOUT)
        r.raise_for_status()
        out = []
        for m in r.json().get("data", []):
            mid = m.get("id", "")
            mid = mid.split("/")[-1] if mid.startswith("models/") else mid
            if not mid:
                continue
            out.append(ModelInfo(
                ref=f"{provider}:{mid}",
                provider=provider,
                model_id=mid,
                context_length=m.get("context_length") or m.get("context_window"),
                source=provider,
            ))
        return out
    except Exception:
        return []


def _probe_anthropic() -> List[ModelInfo]:
    key = _key_for("anthropic")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            timeout=PROBE_TIMEOUT,
        )
        r.raise_for_status()
        return [
            ModelInfo(ref=f"anthropic:{m['id']}", provider="anthropic", model_id=m["id"],
                      label=m.get("display_name", ""), context_length=200000, source="anthropic")
            for m in r.json().get("data", [])
        ]
    except Exception:
        return []


def _probe_ollama() -> List[ModelInfo]:
    """Native tags endpoint -- some Ollama builds don't serve /v1/models."""
    base = settings.LOCAL_BASE_URL.replace("/v1", "")
    try:
        r = requests.get(f"{base}/api/tags", timeout=2)
        r.raise_for_status()
        return [
            ModelInfo(ref=f"local:{m['name']}", provider="local", model_id=m["name"],
                      source="ollama")
            for m in r.json().get("models", [])
        ]
    except Exception:
        return []


PROBES = [
    _probe_openrouter,
    _probe_anthropic,
    _probe_ollama,
    lambda: _probe_openai_compatible("openai"),
    lambda: _probe_openai_compatible("gemini"),
    lambda: _probe_openai_compatible("groq"),
    lambda: _probe_openai_compatible("deepseek"),
    lambda: _probe_openai_compatible("local"),
]


# --- cache ----------------------------------------------------------------

def _read_cache():
    try:
        raw = json.loads(CACHE_PATH.read_text())
        if time.time() - raw["fetched_at"] > CACHE_TTL:
            return None
        return [ModelInfo(**m) for m in raw["models"]], raw["fetched_at"]
    except Exception:
        return None


def _write_cache(models: List[ModelInfo]) -> float:
    now = time.time()
    try:
        paths.ensure(CACHE_PATH)
        CACHE_PATH.write_text(json.dumps(
            {"fetched_at": now, "models": [asdict(m) for m in models]}
        ))
    except Exception:
        pass
    return now


def discover(force: bool = False):
    """Returns (models, fetched_at). Probes run concurrently."""
    if not force:
        cached = _read_cache()
        if cached:
            return cached

    found: List[ModelInfo] = []
    with ThreadPoolExecutor(max_workers=len(PROBES)) as pool:
        for result in pool.map(lambda fn: fn(), PROBES):
            found.extend(result)

    # Static entries only fill gaps a live probe didn't cover.
    seen = {m.ref for m in found}
    found.extend(m for m in _static() if m.ref not in seen)

    # Dedupe, preferring native provider entries over gateway duplicates.
    by_ref = {}
    for m in sorted(found, key=lambda m: m.provider == "openrouter"):
        by_ref.setdefault(m.ref, m)

    models = sorted(by_ref.values(), key=lambda m: (m.provider, m.model_id))
    return models, _write_cache(models)


# --- search ---------------------------------------------------------------

def search(models: List[ModelInfo], query: str = "",
           providers: Optional[List[str]] = None,
           free_only: bool = False, limit: int = 300) -> List[ModelInfo]:
    """
    Space-separated terms, all of which must match somewhere in the ref or
    label. "flash 3" finds gemini-3-flash without needing the exact order.
    """
    results = models
    if providers:
        results = [m for m in results if m.provider in providers]
    if free_only:
        results = [m for m in results if m.prompt_price == 0]

    for term in query.lower().split():
        results = [m for m in results if term in m.ref.lower() or term in (m.label or "").lower()]

    terms = query.lower().split()

    def rank(m):
        # A term that lands on a token boundary beats one buried inside a word,
        # so "mini" puts gpt-4o-mini above gemini.
        tokens = set(re.split(r"[^a-z0-9]+", m.model_id.lower()))
        boundary = sum(
            1 for t in terms if any(tok == t or tok.startswith(t) for tok in tokens)
        )
        exact = 0 if query and query.lower() in m.model_id.lower() else 1
        return (-boundary, exact, m.provider != "openrouter", m.provider, m.model_id)

    return sorted(results, key=rank)[:limit]


def providers_present(models: List[ModelInfo]) -> List[str]:
    return sorted({m.provider for m in models})
