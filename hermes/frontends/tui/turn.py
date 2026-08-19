"""Driving one turn: the approval gate, the budget prompt, and the status loop."""

import sys

from ...core.budget import IterationBudget
from ...core.session import AWAITING_APPROVAL, BUDGET_EXHAUSTED, ERROR, IDLE
from .ink import RISK_INK, bold, dim, red, rule, wrap, yellow
from .render import flush, render_call
from .state import Tui, ceiling_name


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
        session.budget = IterationBudget()
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
