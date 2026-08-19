"""
Plain CLI.

The thinnest of the three frontends: it drives `run_turn` directly, so tools
execute the moment the model asks for them. If you want an approval gate, use
the TUI (`python -m hermes.frontends.tui`).

Run with:  python -m hermes.frontends.cli
"""

from .. import tools
from ..config import settings
from ..core.conversation import Conversation
from ..core.loop import run_turn
from ..providers.errors import TransportError
from ..providers.runtime import resolve_chain
from ..transports import build_transport


def main() -> None:
    print("=== Hermes-style Multi-Provider Agent ===")

    toolsets = tools.default_toolsets()
    model = settings.default_model() or input(
        "Model [provider:id, e.g. gemini:gemini-3-flash]: "
    ).strip()

    chain = resolve_chain([model] + settings.default_fallbacks(),
                          thinking=settings.default_thinking())
    if not chain:
        raise SystemExit(f"No credentials found for '{model}'. Check your .env.")

    print("Chain: " + " -> ".join(str(r) for r in chain))
    print("Tools: " + ", ".join(t.name for t in tools.enabled_tools(toolsets)))

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
            transport = run_turn(chain, conversation, transport, toolsets)
        except TransportError as e:
            print(f"[Error] all providers failed: {e}\n")
        except KeyboardInterrupt:
            conversation.close_interrupted_tool_sequence(transport)
            print("\n[Interrupted]\n")


if __name__ == "__main__":
    main()
