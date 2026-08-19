"""Workspace confinement for path-taking tools."""

import os
from pathlib import Path

from ..config import settings
from .errors import ToolError


def safe_path(path: str) -> Path:
    """
    Resolve a path inside the workspace. Refuses to escape via .. or symlink
    unless HERMES_ALLOW_OUTSIDE_WORKSPACE is set, so a confused model can't
    rewrite files elsewhere on the machine.
    """
    root = Path.cwd().resolve()
    target = (root / os.path.expanduser(path or ".")).resolve()

    if not settings.ALLOW_OUTSIDE_WORKSPACE and root not in target.parents and target != root:
        raise ToolError(
            f"'{path}' is outside the workspace ({root}). "
            "Set HERMES_ALLOW_OUTSIDE_WORKSPACE=1 to permit this."
        )
    return target
