"""
Streamlit frontend.

    state         -- cached session and catalog wiring
    sidebar       -- model summary, threads, workspace, counters, notes, tools
    models_tab    -- the model picker
    editor_tab    -- the file editor
    history_tabs  -- threads and the raw message log
    chat          -- transcript, approval gate, prompt submission
    app           -- main(), which lays the tabs out

Imported by the `app.py` shim at the repo root.
"""

from .app import main

__all__ = ["main"]
