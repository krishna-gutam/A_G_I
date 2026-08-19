"""Project file listing and flat read/write for the editor UI.

These are the *unguarded* helpers the frontends use for a file the human picked
themselves. Tools that the model drives go through `hermes.tools.builtin.files`,
which confines every path to the workspace.
"""

import os
from pathlib import Path
from typing import List

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache",
}
MAX_LISTED = 500


def list_project_files(root: str = ".") -> List[str]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            if f.startswith("."):
                continue
            files.append(os.path.relpath(os.path.join(dirpath, f), root))
            if len(files) >= MAX_LISTED:
                return sorted(files)
    return sorted(files)


def read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading {path}: {e}"


def write_file(path: str, content: str) -> str:
    try:
        Path(path).write_text(content, encoding="utf-8")
        return f"Saved {path}"
    except Exception as e:
        return f"Error saving {path}: {e}"
