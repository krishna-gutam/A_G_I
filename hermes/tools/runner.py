"""
Execution planning.

Decides what may run at the same time, and guarantees results come back in
call order regardless of what finished first.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import List

from ..config import settings
from .registry import REGISTRY, Risk


def max_risk(calls) -> Risk:
    """Highest risk among a batch -- what the approval UI should warn about."""
    risks = [REGISTRY.get(c.name).risk for c in calls if REGISTRY.get(c.name)]
    return max(risks) if risks else Risk.READ


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
            with ThreadPoolExecutor(max_workers=settings.MAX_PARALLEL_TOOLS) as pool:
                for call, result in zip(
                    batch, pool.map(lambda c: REGISTRY.execute(c.name, c.args), batch)
                ):
                    outputs[id(call)] = result
    return [{"call": c, "output": outputs[id(c)]} for c in calls]


def execute(name: str, args: dict) -> str:
    """Single call. Kept for scripts and tests."""
    return REGISTRY.execute(name, args)
