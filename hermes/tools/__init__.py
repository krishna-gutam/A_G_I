"""
Tools.

The public surface callers touch:

    tools.schemas(enabled)        -> what the model is told it can do
    tools.execute_calls(calls)    -> run them, results in call order
    tools.REGISTRY                -> introspection for the UI
    tools.default_toolsets()      -> what's on, per TOOLSETS in .env

Internals, if you need them: `registry` (the @tool decorator and the Tool
record), `schema` (signature -> JSON schema), `runner` (concurrency planning),
`sandbox` (workspace confinement), `builtin/` (the tools themselves).
"""

from typing import List, Optional

from ..config import settings
from .errors import ToolError
from .registry import REGISTRY, RISK_LABEL, Risk, Tool, tool
from .runner import execute, execute_calls, max_risk, plan_batches
from .sandbox import safe_path

# Import for the registration side effect. Must come after `tool` exists.
from . import builtin  # noqa: F401,E402


def default_toolsets() -> List[str]:
    return settings.default_toolsets()


def schemas(toolsets: Optional[List[str]] = None) -> List[dict]:
    return REGISTRY.schemas(toolsets if toolsets is not None else default_toolsets())


def enabled_tools(toolsets: Optional[List[str]] = None) -> List[Tool]:
    return REGISTRY.enabled(toolsets if toolsets is not None else default_toolsets())


def describe(name: str) -> Optional[Tool]:
    return REGISTRY.get(name)


__all__ = [
    "REGISTRY", "Risk", "RISK_LABEL", "Tool", "ToolError", "tool", "safe_path",
    "schemas", "enabled_tools", "default_toolsets", "describe", "max_risk",
    "execute", "execute_calls", "plan_batches",
]
