"""Slash commands. Everything the Streamlit sidebar does, typed instead."""

import json
import os

from ... import tools, workspace
from ...config import paths
from ...core.session import AgentSession
from ...providers import catalog
from .ink import RISK_INK, RISK_MARK, bold, clip, dim, green, red, rule, wrap
from .state import AUTO_LEVELS, Tui, ceiling_name

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
