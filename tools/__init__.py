"""
Tools package.

Importing this registers every toolset. Callers touch four things:

    tools.schemas(enabled)        -> what the model is told it can do
    tools.execute_calls(calls)    -> run them, results in call order
    tools.REGISTRY                -> introspection for the UI
    tools.default_toolsets()      -> what's on, per TOOLSETS in .env

Adding a tool means writing a decorated function in one of the modules below.
Nothing else changes: no schema list to update, no dispatch branch to add.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from .base import REGISTRY, Risk, RISK_LABEL, Tool, ToolError, safe_path, tool

# Import for the registration side effect.
from . import files    # noqa: F401,E402
from . import shell    # noqa: F401,E402
from . import web      # noqa: F401,E402

MAX_PARALLEL = int(os.getenv("MAX_PARALLEL_TOOLS", "8"))

# Read/write files are on by default; shell and network are opt-in, because
# a default that can run arbitrary commands is a decision the user should make
# on purpose rather than discover afterwards.
SAFE_DEFAULTS = ["files","shell","web"]


def default_toolsets() -> List[str]:
    configured = [t.strip() for t in os.getenv("TOOLSETS", "").split(",") if t.strip()]
    return configured or list(SAFE_DEFAULTS)


def schemas(toolsets: Optional[List[str]] = None) -> List[dict]:
    return REGISTRY.schemas(toolsets if toolsets is not None else default_toolsets())


def enabled_tools(toolsets: Optional[List[str]] = None) -> List[Tool]:
    return REGISTRY.enabled(toolsets if toolsets is not None else default_toolsets())


def describe(name: str) -> Optional[Tool]:
    return REGISTRY.get(name)


def max_risk(calls) -> Risk:
    """Highest risk among a batch -- what the approval UI should warn about."""
    risks = [REGISTRY.get(c.name).risk for c in calls if REGISTRY.get(c.name)]
    return max(risks) if risks else Risk.READ


# --- execution planning ---------------------------------------------------

def _independent(a, b) -> bool:
    """
    Two calls can share a batch when neither is marked unsafe for parallel use,
    or when both are path-scoped and touch different files. Read/read is always
    fine; two writes to the same path never are.
    """
    ta, tb = REGISTRY.get(a.name), REGISTRY.get(b.name)
    if ta is None or tb is None:
        return False
    if ta.parallel_safe and tb.parallel_safe:
        return True
    if ta.path_arg and tb.path_arg:
        pa, pb = a.args.get(ta.path_arg), b.args.get(tb.path_arg)
        return bool(pa and pb and pa != pb)
    return False


def plan_batches(calls) -> List[list]:
    """Group calls into batches that may run concurrently, preserving order."""
    batches: List[list] = []
    for call in calls:
        if batches and all(_independent(call, other) for other in batches[-1]):
            batches[-1].append(call)
        else:
            batches.append([call])
    return batches


def execute_calls(calls) -> List[dict]:
    """
    Run tool calls and return [{"call": ..., "output": json str}] in CALL order.
    Wall-clock order is an implementation detail; history order is a protocol
    requirement.
    """
    outputs = {}
    for batch in plan_batches(calls):
        if len(batch) == 1:
            outputs[id(batch[0])] = REGISTRY.execute(batch[0].name, batch[0].args)
        else:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
                for call, result in zip(
                    batch, pool.map(lambda c: REGISTRY.execute(c.name, c.args), batch)
                ):
                    outputs[id(call)] = result
    return [{"call": c, "output": outputs[id(c)]} for c in calls]


def execute(name: str, args: dict) -> str:
    """Single call. Kept for scripts and tests."""
    return REGISTRY.execute(name, args)


__all__ = [
    "REGISTRY", "Risk", "RISK_LABEL", "Tool", "ToolError", "tool", "safe_path",
    "schemas", "enabled_tools", "default_toolsets", "describe", "max_risk",
    "execute", "execute_calls", "plan_batches",
]
