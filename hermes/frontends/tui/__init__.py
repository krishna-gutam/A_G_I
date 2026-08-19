"""
Terminal frontend.

    ink       -- colour, wrapping, rules
    state     -- the Tui object and the auto-approval ceiling
    render    -- messages and pending calls -> lines
    turn      -- the approval gate and the status loop
    commands  -- slash commands
    app       -- banner, prompt, main loop
"""

from .app import main

__all__ = ["main"]
