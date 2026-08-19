"""Terminal ink: colour, wrapping, rules. No agent concepts."""

import os
import shutil
import sys
import textwrap
from typing import List

from ... import tools

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
