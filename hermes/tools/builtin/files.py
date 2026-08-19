"""File tools. The toolset a coding agent can't work without."""

import os
from pathlib import Path

from ..registry import Risk, tool
from ..errors import ToolError
from ..sandbox import safe_path

MAX_READ_BYTES = 200_000
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache"}


@tool(toolset="files", risk=Risk.READ, path_arg="path")
def list_files(path: str = ".", recursive: bool = False) -> dict:
    """List files and directories.

    Args:
        path: Directory to list, relative to the workspace root.
        recursive: Walk subdirectories instead of listing one level.
    """
    target = safe_path(path)
    if not target.is_dir():
        raise ToolError(f"'{path}' is not a directory.")

    if not recursive:
        entries = sorted(
            f"{p.name}/" if p.is_dir() else p.name for p in target.iterdir()
        )
        return {"path": str(target.relative_to(Path.cwd())) or ".", "entries": entries}

    found = []
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            found.append(os.path.relpath(os.path.join(dirpath, f), target))
            if len(found) >= 1000:
                return {"entries": sorted(found), "truncated": True}
    return {"entries": sorted(found)}


@tool(toolset="files", risk=Risk.READ, path_arg="file_path")
def read_file(file_path: str, start_line: int = 1, end_line: int = 0) -> dict:
    """Read a UTF-8 text file, optionally a line range.

    Args:
        file_path: Path to the file, relative to the workspace root.
        start_line: First line to return, 1-indexed.
        end_line: Last line to return. 0 means read to the end.
    """
    target = safe_path(file_path)
    if not target.is_file():
        raise ToolError(f"'{file_path}' does not exist.")
    if target.stat().st_size > MAX_READ_BYTES:
        raise ToolError(
            f"'{file_path}' is {target.stat().st_size} bytes; "
            f"read a line range instead (limit {MAX_READ_BYTES})."
        )

    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        raise ToolError(f"'{file_path}' is not UTF-8 text.")

    total = len(lines)
    sliced = lines[max(0, start_line - 1): (end_line or total)]
    return {
        "file_path": file_path,
        "total_lines": total,
        "start_line": start_line,
        "content": "\n".join(sliced),
    }


@tool(toolset="files", risk=Risk.WRITE, path_arg="file_path", parallel_safe=False)
def write_file(file_path: str, content: str) -> dict:
    """Create or overwrite a file with the given content.

    Args:
        file_path: Path to write, relative to the workspace root.
        content: Full new contents of the file.
    """
    target = safe_path(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    return {
        "status": "overwritten" if existed else "created",
        "file_path": file_path,
        "bytes": len(content.encode("utf-8")),
    }


@tool(toolset="files", risk=Risk.WRITE, path_arg="file_path", parallel_safe=False)
def edit_file(file_path: str, old_text: str, new_text: str) -> dict:
    """Replace one exact occurrence of a string in a file.

    Prefer this over write_file for small changes: it fails loudly when the
    text is missing or ambiguous, rather than silently discarding the rest.

    Args:
        file_path: Path to the file, relative to the workspace root.
        old_text: Exact text to find. Must appear exactly once.
        new_text: Replacement text.
    """
    target = safe_path(file_path)
    if not target.is_file():
        raise ToolError(f"'{file_path}' does not exist.")

    original = target.read_text(encoding="utf-8")
    count = original.count(old_text)
    if count == 0:
        raise ToolError(f"old_text not found in '{file_path}'.")
    if count > 1:
        raise ToolError(f"old_text appears {count} times in '{file_path}'; make it unique.")

    target.write_text(original.replace(old_text, new_text, 1), encoding="utf-8")
    line = original[: original.index(old_text)].count("\n") + 1
    return {"status": "edited", "file_path": file_path, "line": line}


@tool(toolset="files", risk=Risk.READ)
def search_files(pattern: str, path: str = ".", max_results: int = 50) -> dict:
    """Find lines matching a substring across the workspace.

    Args:
        pattern: Text to look for. Case-insensitive.
        path: Directory to search under.
        max_results: Stop after this many matches.
    """
    root = safe_path(path)
    needle = pattern.lower()
    matches = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                for i, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
                    if needle in line.lower():
                        matches.append({
                            "file": os.path.relpath(fp, Path.cwd()),
                            "line": i,
                            "text": line.strip()[:200],
                        })
                        if len(matches) >= max_results:
                            return {"matches": matches, "truncated": True}
            except (UnicodeDecodeError, OSError):
                continue

    return {"matches": matches, "count": len(matches)}
