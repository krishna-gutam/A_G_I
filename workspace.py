"""Workspace helpers: project files, notes, recent projects."""

import os
import json
from pathlib import Path

import paths

RECENTS = paths.RECENTS_FILE
NOTES_FILE = paths.NOTES_FILE

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}
MAX_LISTED = 500


def list_project_files(root: str = ".") -> list:
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


def read_notes() -> str:
    p = Path(NOTES_FILE)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write_notes(text: str) -> None:
    Path(NOTES_FILE).write_text(text, encoding="utf-8")


def load_recent_projects() -> list:
    try:
        recents = json.loads(RECENTS.read_text())
        return [p for p in recents if os.path.isdir(p)]
    except Exception:
        return []


def save_recent_project(path: str) -> None:
    recents = load_recent_projects()
    path = os.path.abspath(path)
    recents = [path] + [p for p in recents if p != path]
    try:
        paths.ensure(RECENTS)
        RECENTS.write_text(json.dumps(recents[:12]))
    except Exception:
        pass
