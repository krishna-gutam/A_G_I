"""
Streamlit entrypoint.  Run with:  streamlit run app.py

Thin on purpose: the frontend lives in hermes/frontends/streamlit_ui/ so it can
be swapped out without touching the agent.

The CLI and TUI have their own entrypoints:

    python -m hermes.frontends.cli
    python -m hermes.frontends.tui
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from hermes.frontends.streamlit_ui import main  # noqa: E402

if __name__ == "__main__":
    main()
else:
    # Streamlit imports rather than executes the entrypoint, so call main() here too.
    main()
