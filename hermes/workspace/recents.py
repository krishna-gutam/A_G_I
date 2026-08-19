"""Recently opened project directories."""

import json
import os
from typing import List

from ..config import paths

RECENTS = paths.RECENTS_FILE
MAX_RECENTS = 12


def load_recent_projects() -> List[str]:
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
        RECENTS.write_text(json.dumps(recents[:MAX_RECENTS]))
    except Exception:
        pass
