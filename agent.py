"""
CLI agent.

Notice what isn't here: no provider names in the loop, no message formatting,
no protocol quirks. The loop drives conversation + transport and knows nothing
about how either serializes.
"""

import os
import time

import paths  # loads .env before anything reads it
import tools
from providers import resolve_chain, RETRY, FAILOVER
from transports import build_transport, TransportError
from conversation import Conversation, IterationBudget

BUDGET_PER_TURN = int(os.getenv("ITERATION_BUDGET", "12"))
TOOLSETS = tools.default_toolsets()


def generate_with_failover(chain, conversation, tools):
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
                return transport.generate(conversation, tools), transport, runtime
            except TransportError as e:
                last_error = e
                if e.action == RETRY and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if e.action == FAILOVER:
                    print(f"[Failover] {runtime} unavailable ({e.status}); trying next.")
                break
    raise last_error or RuntimeError("No usable provider in chain.")


def run_turn(chain, conversation, transport):
    budget = IterationBudget(BUDGET_PER_TURN)

    while True:
        turn, transport, runtime = generate_with_failover(chain, conversation, tools.schemas(TOOLSETS))
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


def main():
    print("=== Hermes-style Multi-Provider Agent ===")

    model = os.getenv("MODEL") or input("Model [provider:id, e.g. gemini:gemini-3-flash]: ").strip()
    fallbacks = [m for m in os.getenv("FALLBACK_MODELS", "").split(",") if m.strip()]
    thinking = os.getenv("THINKING") or None

    chain = resolve_chain([model] + fallbacks, thinking=thinking)
    if not chain:
        raise SystemExit(f"No credentials found for '{model}'. Check your .env.")

    print("Chain: " + " -> ".join(str(r) for r in chain))
    print("Tools: " + ", ".join(t.name for t in tools.enabled_tools(TOOLSETS)))

    system_prompt = input("System prompt (optional): ").strip() or None
    conversation = Conversation(system_prompt=system_prompt)
    transport = build_transport(chain[0])

    while True:
        try:
            user_input = input(f"[{chain[0].provider}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        # A previous turn may have died mid-tool-call.
        conversation.close_interrupted_tool_sequence(transport)
        conversation.add_user(user_input)

        try:
            transport = run_turn(chain, conversation, transport)
        except TransportError as e:
            print(f"[Error] all providers failed: {e}\n")
        except KeyboardInterrupt:
            conversation.close_interrupted_tool_sequence(transport)
            print("\n[Interrupted]\n")


if __name__ == "__main__":
    main()
