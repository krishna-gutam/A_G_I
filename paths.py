"""
Where state lives.

One place resolves every path so the whole app can be relocated with a single
.env line -- onto a synced drive, a scratch disk, or a per-project directory
checked into the repo.

This module also calls load_dotenv() on import, and everything that reads an
environment variable at import time imports it first. Without that ordering,
module-level os.getenv() calls run before .env is parsed and silently fall back
to defaults -- the setting appears to be ignored with no error to explain why.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _resolve(env_var: str, default: str) -> Path:
    """Expands ~ and $VARS, and accepts paths relative to the current project."""
    raw = os.getenv(env_var) or default
    return Path(os.path.expandvars(raw)).expanduser()


# Root for everything below. Set HERMES_STATE_DIR=./.hermes to keep state
# beside the project instead of in the home directory.
STATE_DIR = _resolve("HERMES_STATE_DIR", "~/.hermes_ui")

# Each can be overridden individually; by default they sit under STATE_DIR.
THREADS_DIR = _resolve("HERMES_THREADS_DIR", str(STATE_DIR / "threads"))
MODEL_CACHE = _resolve("HERMES_MODEL_CACHE", str(STATE_DIR / "models.json"))
RECENTS_FILE = _resolve("HERMES_RECENTS_FILE", str(STATE_DIR / "recent_projects.json"))

# Notes are per-project by design, so this one is relative to the working
# directory unless you give it an absolute path.
NOTES_FILE = os.getenv("HERMES_NOTES_FILE", "NOTES.md")


def ensure(path: Path) -> Path:
    """Create a directory (or a file's parent) on demand. Never raises."""
    try:
        target = path if path.suffix == "" else path.parent
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def describe() -> str:
    return str(STATE_DIR)
