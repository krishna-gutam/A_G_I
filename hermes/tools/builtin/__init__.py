"""
Built-in toolsets.

Importing this package registers every tool below. Adding a tool means writing
a decorated function in one of these modules -- there is no schema list to
update and no dispatch branch to add.
"""

from . import files, shell, web  # noqa: F401  imported for the side effect

__all__ = ["files", "shell", "web"]
