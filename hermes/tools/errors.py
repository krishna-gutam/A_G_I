"""Errors a tool may raise."""


class ToolError(Exception):
    """Raised inside a tool to return a clean message instead of a traceback."""
