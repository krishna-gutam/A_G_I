"""
The turn loop.

Notice what isn't here: no provider names, no message formatting, no protocol
quirks. The loop drives conversation + transport and knows nothing about how
either serializes.

Two entry points, one shared failover walk:

    generate_with_failover  -- one model round-trip, retrying and failing over
    run_turn                -- the autonomous loop: run tools as they're asked
                               for. The CLI uses this; UIs use AgentSession
                               instead, which stops at the approval boundary.
"""

import time

from .. import tools
from ..providers.errors import FAILOVER, RETRY, TransportError
from ..transports import build_transport
from .budget import IterationBudget


def generate_with_failover(chain, conversation, tool_schemas):
    """
    Walk the runtime chain. Transient faults retry in place; exhausted keys or
    dead providers move to the next runtime. The conversation is untouched by
    all of this, so a failover mid-turn resumes cleanly.
    """
    last_error = None
    for runtime in chain:
        transport = build_transport(runtime)
        for attempt in range(3):
            try:
                return transport.generate(conversation, tool_schemas), transport, runtime
            except TransportError as e:
                last_error = e
                if e.action == RETRY and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if e.action == FAILOVER:
                    print(f"[Failover] {runtime} unavailable ({e.status}); trying next.")
                break
    raise last_error or RuntimeError("No usable provider in chain.")


def run_turn(chain, conversation, transport, toolsets=None):
    """One user turn, run to completion. Tools execute without asking."""
    toolsets = toolsets if toolsets is not None else tools.default_toolsets()
    budget = IterationBudget()

    while True:
        turn, transport, runtime = generate_with_failover(
            chain, conversation, tools.schemas(toolsets)
        )
        budget.consume()
        conversation.add_turn(turn)

        if turn.content:
            print(f"\nAgent: {turn.content}")
        print(f"[{runtime}] {turn.metadata.get('usage') or {}}\n")

        if not turn.tool_calls:
            return transport

        try:
            results = tools.execute_calls(turn.tool_calls)
        except KeyboardInterrupt:
            # Leave no dangling tool calls behind, or the next request 400s.
            n = conversation.close_interrupted_tool_sequence(transport)
            print(f"\n[Interrupted] {n} tool call(s) marked cancelled.\n")
            return transport

        for r in results:
            print(f"[Tool] {r['call'].name} -> {r['output'][:200]}")
        conversation.add_tool_results(transport, results)

        if budget.exhausted:
            conversation.add_user(budget.handoff_prompt())
            final, transport, runtime = generate_with_failover(chain, conversation, [])
            conversation.add_turn(final)
            print(f"\nAgent: {final.content}\n[Budget exhausted after {budget.used} steps]\n")
            return transport
