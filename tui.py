#!/usr/bin/env python3
"""
Terminal frontend.

Third frontend after the CLI and Streamlit, and like the Streamlit one it drives
`session.AgentSession` rather than the raw loop in agent.py: the session stops at
the approval boundary and lets the caller decide, which is exactly what a human at
a terminal needs. No agent logic lives here.

Run with:  python tui.py

Deliberately line-oriented rather than full-screen curses. Responses are not
streamed (see the note in README), so there is nothing to animate; a scrolling
transcript keeps shell scrollback, copy-paste, and pipes working, and it survives
a resize without a redraw path. Slash commands cover what the Streamlit sidebar
does. Type anything else to talk to the model.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap
from typing import List, Optional

import paths  # imported first: loads .env before anything reads it  # noqa: F401
import session as session_mod
import tools
import workspace
from conversation import IterationBudget

# ITERATION_BUDGET is honoured by agent.py but session.py constructs a bare
# IterationBudget(), so the .env setting is silently ignored in every UI. Bind the
# configured limit here rather than editing session.py from a frontend.
BUDGET_LIMIT = int(os.getenv("ITERATION_BUDGET", "12"))


class _ConfiguredBudget(IterationBudget):
    def __init__(self, limit: int = BUDGET_LIMIT):
        super().__init__(limit)


session_mod.IterationBudget = _ConfiguredBudget

from session import (  # noqa: E402
    AWAITING_APPROVAL,
    BUDGET_EXHAUSTED,
    ERROR,
    IDLE,
    AgentSession,
)
import models as catalog  # noqa: E402


# --- ink --------------------------------------------------------------------

_COLOR = (
    sys.stdout.isatty()
    and os.getenv("NO_COLOR") is None
    and os.getenv("TERM", "") != "dumb"
)


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _COLOR else text


def dim(s: str) -> str:
    return _c("2", s)


def bold(s: str) -> str:
    return _c("1", s)


def red(s: str) -> str:
    return _c("31", s)


def green(s: str) -> str:
    return _c("32", s)


def yellow(s: str) -> str:
    return _c("33", s)


def blue(s: str) -> str:
    return _c("36", s)


def magenta(s: str) -> str:
    return _c("35", s)


RISK_INK = {tools.Risk.READ: blue, tools.Risk.WRITE: yellow, tools.Risk.EXEC: red}
RISK_MARK = {tools.Risk.READ: "read", tools.Risk.WRITE: "write", tools.Risk.EXEC: "exec"}


def term_width() -> int:
    return max(50, min(shutil.get_terminal_size((88, 24)).columns, 100))


def wrap(text: str, indent: str = "") -> str:
    limit = term_width() - len(indent)
    out: List[str] = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(para, limit) or [""])
    return "\n".join(indent + line for line in out)


def rule(label: str = "") -> str:
    width = term_width()
    if not label:
        return dim("─" * width)
    return dim("── " + label + " " + "─" * max(0, width - len(label) - 4))


def clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- state ------------------------------------------------------------------


class Tui:
    """Everything the transcript loop needs that the session doesn't own."""

    def __init__(self, session: AgentSession):
        self.session = session
        self.printed = 0            # messages already rendered
        self.ceiling: Optional[tools.Risk] = None   # auto-approval risk ceiling
        self.last_search: List = []  # numbered results from /models

    def reset_transcript(self) -> None:
        self.printed = len(self.session.conversation.messages)


AUTO_LEVELS = {
    "none": None,
    "read": tools.Risk.READ,
    "write": tools.Risk.WRITE,
    "all": tools.Risk.EXEC,
}


def ceiling_name(ceiling: Optional[tools.Risk]) -> str:
    for name, level in AUTO_LEVELS.items():
        if level == ceiling:
            return name
    return "none"


# --- rendering --------------------------------------------------------------


def render_tool_result(msg) -> None:
    name = msg.name or "tool"
    try:
        payload = json.loads(msg.content)
    except (ValueError, TypeError):
        print(f"  {green('✓')} {bold(name)} {dim(clip(msg.content, term_width() - 20))}")
        return

    if isinstance(payload, dict) and "error" in payload:
        detail = payload.get("message") or payload["error"]
        print(f"  {red('✗')} {bold(name)} {red(clip(detail, term_width() - 20))}")
        return

    if isinstance(payload, dict):
        interesting = {k: v for k, v in payload.items() if k not in ("file_path", "path")}
        preview = ", ".join(f"{k}={clip(v, 40)}" for k, v in list(interesting.items())[:3])
    else:
        preview = clip(payload, term_width() - 20)
    print(f"  {green('✓')} {bold(name)} {dim(clip(preview, term_width() - 20))}")


def flush(tui: Tui) -> None:
    """Render every message added since the last flush."""
    messages = tui.session.conversation.messages
    while tui.printed < len(messages):
        msg = messages[tui.printed]
        tui.printed += 1

        if msg.role == "user":
            continue  # the person just typed it, or we echoed it ourselves
        if msg.role == "tool":
            render_tool_result(msg)
            continue
        if msg.content.strip():
            print()
            print(wrap(msg.content))
            print()


def render_call(call) -> None:
    ink = RISK_INK[call.risk]
    print(f"  {ink('▸')} {bold(call.name)}  {dim(RISK_MARK[call.risk] + ' · ' + call.toolset)}")
    if call.summary:
        print(wrap(call.summary, "      "))

    for key, value in call.display_args.items():
        text = value if isinstance(value, str) else json.dumps(value)
        if "\n" in text or len(text) > 70:
            print(f"      {dim(key + ':')}")
            lines = text.split("\n")
            for line in lines[:12]:
                print(dim("      │ ") + clip(line, term_width() - 10))
            if len(lines) > 12:
                print(dim(f"      │ … {len(lines) - 12} more lines"))
        else:
            print(f"      {dim(key + ':')} {text}")

    if call.justification:
        print(wrap(call.justification, "      "))


# --- turn driving -----------------------------------------------------------


def ask_line(prompt: str, on_interrupt: str = "") -> str:
    """One place for every interactive prompt: EOF, Ctrl-C, and piped stdin.

    A piped stdin echoes no newline, so output would otherwise run onto the
    prompt line and make transcripts unreadable.
    """
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return on_interrupt
    if not sys.stdin.isatty():
        print()
    return answer


def safe_approve(tui: Tui) -> str:
    """Ctrl-C during tool execution must not leave tool calls unanswered."""
    try:
        return tui.session.approve_tools()
    except KeyboardInterrupt:
        session = tui.session
        session.pending = []
        n = session.conversation.close_interrupted_tool_sequence(session.transport)
        flush(tui)
        print(yellow(f"\nStopped. {n} tool call(s) marked cancelled."))
        session.status = IDLE
        return IDLE


def approval_gate(tui: Tui) -> str:
    session = tui.session
    calls = session.pending_tool_calls()
    if not calls:
        return session.advance()

    if tui.ceiling is not None and session.auto_approvable(calls, tui.ceiling):
        for call in calls:
            print(f"  {RISK_INK[call.risk]('▸')} {bold(call.name)} {dim('auto-approved')}")
        return safe_approve(tui)

    print(rule("tool request"))
    for call in calls:
        render_call(call)
    print(rule())

    while True:
        choice = ask_line(
            bold("run? ") + dim("[y]es  [n]o  [r]edirect  [a]lways at this level  [q]uit turn "),
            on_interrupt="n",
        ).lower()

        if choice in ("", "y", "yes"):
            return safe_approve(tui)
        if choice in ("n", "no", "s", "skip"):
            print(dim("Skipped."))
            status = session.deny_tools()
            flush(tui)  # show the refusal before the prompt returns
            return status
        if choice in ("q", "quit"):
            print(dim("Turn ended."))
            session.deny_tools()
            flush(tui)
            return IDLE
        if choice in ("a", "always"):
            tui.ceiling = max(c.risk for c in calls)
            print(dim(f"Auto-approving {ceiling_name(tui.ceiling)} and below for this session."))
            return safe_approve(tui)
        if choice in ("r", "redirect"):
            feedback = ask_line(bold("what should it do instead? "))
            if feedback:
                return session.send_tool_feedback(feedback)
            continue
        print(dim("y / n / r / a / q"))


def handle_budget(tui: Tui) -> str:
    session = tui.session
    print(yellow(f"Budget spent: {session.budget.used} model round-trips this turn."))
    choice = ask_line(
        bold("now? ") + dim("[s]ummarize and stop  [c]ontinue with a fresh budget  [d]rop "),
        on_interrupt="d",
    ).lower()

    if choice in ("", "s"):
        return session.finish_after_budget()
    if choice == "c":
        session.budget = _ConfiguredBudget()
        return session.advance()
    session.status = IDLE
    return IDLE


def drive(tui: Tui, status: str) -> None:
    """Render and resolve statuses until the turn comes to rest."""
    while True:
        flush(tui)

        if status == AWAITING_APPROVAL:
            status = approval_gate(tui)
        elif status == BUDGET_EXHAUSTED:
            status = handle_budget(tui)
        elif status == ERROR:
            print(red("Provider error: ") + wrap(tui.session.last_error or "unknown").strip())
            print(dim("Try /model to switch, or /fallbacks to add a backup."))
            return
        else:
            return


def ask(tui: Tui, prompt: str) -> None:
    session = tui.session
    if not session.is_ready():
        print(red("No provider is configured.") + " " + dim("Set a key in .env, then /model."))
        return
    print(dim(f"…{session.active_runtime.model_id}"))
    try:
        status = session.send(prompt)
    except KeyboardInterrupt:
        session.conversation.close_interrupted_tool_sequence(session.transport)
        tui.reset_transcript()
        print(yellow("\nStopped."))
        return
    drive(tui, status)


# --- commands ---------------------------------------------------------------

HELP_SECTIONS = [
    (None, [
        ("/model <ref|n>", "switch model, by ref or by number from the last /models"),
        ("/models [query]", "search the catalog across every provider that answered"),
        ("/fallbacks <a,b>", "chain used when a provider is rate-limited or out of credit"),
        ("/thinking <level>", "off, low, medium, high"),
        ("/auto <level>", "auto-approval ceiling: none, read, write, all"),
        ("/tools [a,b]", "show toolsets, or enable exactly these"),
    ]),
    ("threads", [
        ("/threads", "list threads in this workspace"),
        ("/thread <id>", "switch to a thread"),
        ("/new [id]", "start a thread"),
        ("/rename <old> <new>", "rename a thread"),
        ("/drop <id>", "delete a thread"),
    ]),
    ("history and workspace", [
        ("/undo", "remove the last exchange"),
        ("/clear", "empty this thread"),
        ("/log [n]", "show the api_content sidecar for recent messages"),
        ("/cd <path>", "change workspace"),
        ("/notes [text]", "read NOTES.md, or append a line to it"),
        ("/status", "model chain, tools, budget, state directory"),
        ("/exit", "leave"),
    ]),
]


def print_help() -> None:
    width = max(len(cmd) for _, rows in HELP_SECTIONS for cmd, _ in rows)
    print()
    print(wrap("Type to talk to the model. Commands start with a slash.", "  "))
    for heading, rows in HELP_SECTIONS:
        print()
        if heading:
            print(dim("  " + heading))
        for cmd, description in rows:
            # Pad before colouring: ANSI codes would otherwise count toward width.
            print(f"  {bold(cmd.ljust(width))}  {dim(description)}")
    print()


def show_status(tui: Tui) -> None:
    session = tui.session
    chain = " → ".join(str(r) for r in session.chain) if session.chain else red("none configured")
    active = tools.enabled_tools(session.toolsets)
    print(rule("status"))
    print(f"  {dim('chain    ')} {chain}")
    print(f"  {dim('thinking ')} {session.thinking or 'off'}")
    print(f"  {dim('tools    ')} {', '.join(t.name for t in active) or 'none'}")
    print(f"  {dim('auto     ')} {ceiling_name(tui.ceiling)}")
    print(f"  {dim('thread   ')} {session.thread_id}  ({len(session.conversation.messages)} messages)")
    print(f"  {dim('tokens   ')} {session.token_count:,}")
    print(f"  {dim('budget   ')} {session.budget.used}/{session.budget.limit} per turn")
    print(f"  {dim('workspace')} {os.getcwd()}")
    print(f"  {dim('state    ')} {paths.describe()}")
    print(rule())


def cmd_models(tui: Tui, query: str) -> None:
    print(dim("probing providers…"))
    try:
        found, _ = catalog.discover()
    except Exception as e:  # discovery must never take the UI down
        print(red(f"Catalog unavailable: {e}"))
        return

    results = catalog.search(found, query)[:25]
    if not results:
        print(dim("Nothing matched. Try fewer terms."))
        return

    tui.last_search = results
    print(rule(f"{len(results)} of {len(found)} models"))
    for i, m in enumerate(results, 1):
        print(f"  {dim(str(i).rjust(3))}  {m.ref}  {dim(m.context_label + '  ' + m.price_label)}")
    print(rule())
    print(dim("Switch with /model <number> or /model <ref>."))


def cmd_model(tui: Tui, arg: str) -> None:
    session = tui.session
    if not arg:
        print(dim("Usage: /model gemini:gemini-3-flash   or   /model 4"))
        return
    ref = arg
    if arg.isdigit():
        index = int(arg) - 1
        if not (0 <= index < len(tui.last_search)):
            print(red("No such number.") + dim(" Run /models first."))
            return
        ref = tui.last_search[index].ref

    session.set_model(ref, thinking=session.thinking)
    if session.is_ready():
        print(dim(f"Now on {session.active_runtime}."))
    else:
        print(red(f"No credential for {ref}.") + dim(" The chain is empty; add a key to .env."))


def cmd_tools(tui: Tui, arg: str) -> None:
    session = tui.session
    if arg:
        chosen = [t.strip() for t in arg.replace(",", " ").split() if t.strip()]
        unknown = [t for t in chosen if t not in tools.REGISTRY.toolsets()]
        if unknown:
            print(red(f"Unknown toolset: {', '.join(unknown)}.")
                  + dim(f" Available: {', '.join(tools.REGISTRY.toolsets())}."))
            return
        session.set_toolsets(chosen)

    print(rule("tools"))
    for name in tools.REGISTRY.toolsets():
        on = name in session.toolsets
        print(f"  {green('on ') if on else dim('off')} {bold(name)}")
    for t in tools.enabled_tools(session.toolsets):
        print(f"       {RISK_INK[t.risk]('▸')} {t.name} {dim('· ' + RISK_MARK[t.risk])}")
    print(rule())


def cmd_log(tui: Tui, arg: str) -> None:
    count = int(arg) if arg.isdigit() else 3
    messages = tui.session.conversation.messages[-count:]
    if not messages:
        print(dim("Nothing to show yet."))
        return
    for msg in messages:
        print(rule(msg.role))
        print(dim("clean:"))
        print(wrap(json.dumps(msg.clean(), indent=1)[:1500], "  "))
        print(dim("api_content:"))
        body = json.dumps(msg.api_content, indent=1)[:2000] if msg.api_content else "none"
        print(wrap(body, "  "))
    print(rule())


def cmd_notes(tui: Tui, arg: str) -> None:
    if arg:
        existing = workspace.read_notes()
        workspace.write_notes((existing + "\n" if existing else "") + arg)
        print(dim("Added to NOTES.md."))
        return
    body = workspace.read_notes()
    print(wrap(body, "  ") if body.strip() else dim("NOTES.md is empty."))


def cmd_cd(tui: Tui, arg: str) -> None:
    target = os.path.abspath(os.path.expanduser(arg or "."))
    if not os.path.isdir(target):
        print(red(f"{target} is not a directory."))
        return
    os.chdir(target)
    workspace.save_recent_project(target)
    old = tui.session
    tui.session = AgentSession(
        cwd=target,
        model_ref=old.model_ref,
        fallbacks=old.fallbacks,
        thinking=old.thinking,
        system_prompt=old.system_prompt,
        toolsets=old.toolsets,
    )
    tui.reset_transcript()
    print(dim(f"Workspace is now {target} · thread {tui.session.thread_id}."))


def handle_command(tui: Tui, line: str) -> bool:
    """Returns False when the person wants out."""
    session = tui.session
    parts = line[1:].split(None, 1)
    name = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name in ("exit", "quit", "q"):
        return False
    elif name in ("help", "h", "?"):
        print_help()
    elif name == "status":
        show_status(tui)
    elif name == "models":
        cmd_models(tui, arg)
    elif name == "model":
        cmd_model(tui, arg)
    elif name == "fallbacks":
        session.set_model(
            session.model_ref,
            fallbacks=[m.strip() for m in arg.split(",") if m.strip()],
            thinking=session.thinking,
        )
        print(dim("Chain: " + " → ".join(str(r) for r in session.chain)))
    elif name == "thinking":
        level = arg.lower()
        if level not in ("off", "low", "medium", "high", ""):
            print(dim("Levels: off, low, medium, high."))
        else:
            session.set_model(session.model_ref, thinking=None if level in ("off", "") else level)
            print(dim(f"Thinking {session.thinking or 'off'}."))
    elif name == "auto":
        if arg.lower() not in AUTO_LEVELS:
            print(dim("Levels: none, read, write, all."))
        else:
            tui.ceiling = AUTO_LEVELS[arg.lower()]
            print(dim(f"Auto-approving {ceiling_name(tui.ceiling)} and below."))
    elif name in ("tools", "toolsets"):
        cmd_tools(tui, arg)
    elif name == "threads":
        for tid in session.list_threads():
            summary = session.thread_summary(tid)
            mark = green("●") if tid == session.thread_id else dim("○")
            print(f"  {mark} {bold(tid.ljust(12))} {dim(str(summary['messages']) + ' msgs')}  "
                  f"{dim(clip(summary['last_human'], 40))}")
    elif name == "thread":
        if not arg:
            print(dim("Usage: /thread <id>"))
        else:
            session.switch_thread(arg)
            tui.reset_transcript()
            print(dim(f"On thread {arg} ({len(session.conversation.messages)} messages)."))
    elif name == "new":
        tid = session.new_thread(arg or None)
        tui.reset_transcript()
        print(dim(f"Started thread {tid}."))
    elif name == "rename":
        names = arg.split()
        if len(names) != 2:
            print(dim("Usage: /rename <old> <new>"))
        else:
            session.rename_thread(*names)
            print(dim(f"Renamed to {names[1]}."))
    elif name in ("drop", "delete"):
        if not arg:
            print(dim("Usage: /drop <id>"))
        else:
            session.delete_thread(arg)
            tui.reset_transcript()
            print(dim(f"Deleted {arg}. Now on {session.thread_id}."))
    elif name == "undo":
        print(dim("Removed the last exchange.") if session.undo_last_turn()
              else dim("Nothing to undo."))
        tui.reset_transcript()
    elif name == "clear":
        session.clear_history()
        tui.reset_transcript()
        print(dim("Thread emptied."))
    elif name == "log":
        cmd_log(tui, arg)
    elif name == "cd":
        cmd_cd(tui, arg)
    elif name == "notes":
        cmd_notes(tui, arg)
    else:
        print(dim(f"No command /{name}. Try /help."))
    return True


# --- entry point ------------------------------------------------------------


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
