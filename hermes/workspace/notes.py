"""The per-project scratchpad, NOTES.md by default."""

from pathlib import Path

from ..config import paths

NOTES_FILE = paths.NOTES_FILE


def read_notes() -> str:
    p = Path(NOTES_FILE)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write_notes(text: str) -> None:
    Path(NOTES_FILE).write_text(text, encoding="utf-8")
