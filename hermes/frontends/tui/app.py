"""
Terminal frontend.

Drives `AgentSession` rather than the raw loop in `hermes.core.loop`: the
session stops at the approval boundary and lets the caller decide, which is
exactly what a human at a terminal needs. No agent logic lives here.

Run with:  python -m hermes.frontends.tui

Deliberately line-oriented rather than full-screen curses. Responses are not
streamed (see the note in README), so there is nothing to animate; a scrolling
transcript keeps shell scrollback, copy-paste, and pipes working, and it survives
a resize without a redraw path. Slash commands cover what the Streamlit sidebar
does. Type anything else to talk to the model.
"""

from __future__ import annotations

import os

from ... import tools
from ...core.session import AgentSession
from .commands import handle_command
from .ink import bold, clip, dim, red, yellow
from .state import Tui
from .turn import ask


def banner(tui: Tui) -> None:
    session = tui.session
    print()
    print(bold("  multi-provider agent") + dim("  ·  /help for commands"))
    if session.chain:
        print(dim("  " + " → ".join(str(r) for r in session.chain)))
    else:
        print(red("  No provider configured.") + dim(" Add a key to .env, then /model."))
    active = ", ".join(t.name for t in tools.enabled_tools(session.toolsets)) or "none"
    print(dim(f"  {os.getcwd()}"))
    print(dim(f"  tools: {active}"))
    if any(t.risk == tools.Risk.EXEC for t in tools.enabled_tools(session.toolsets)):
        print(yellow("  shell and network tools are on. Every call still asks first."))
    print()


def prompt_text(tui: Tui) -> str:
    session = tui.session
    model = session.active_runtime.model_id if session.chain else "no model"
    return f"\n{dim(clip(model, 28))} {dim(session.thread_id)} {bold('›')} "


def main() -> None:
    try:
        import readline  # noqa: F401  line editing and history, when available
    except ImportError:
        pass

    session = AgentSession(cwd=os.getcwd())
    tui = Tui(session)
    tui.reset_transcript()  # a resumed thread starts folded, not replayed
    banner(tui)

    if len(session.conversation.messages):
        print(dim(f"  Resumed thread '{session.thread_id}' with "
                  f"{len(session.conversation.messages)} messages. /log to inspect."))

    while True:
        try:
            line = input(prompt_text(tui)).strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print(dim("  (/exit to leave)"))
            continue

        if not line:
            continue
        if line.startswith("/"):
            if not handle_command(tui, line):
                break
            continue

        ask(tui, line)


if __name__ == "__main__":
    main()
