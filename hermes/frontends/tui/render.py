"""Turning messages and pending calls into lines on a terminal."""

import json

from .ink import RISK_INK, RISK_MARK, bold, dim, green, red, term_width, clip, wrap
from .state import Tui


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
