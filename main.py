"""
Entrypoint.  Run with:  streamlit run main.py

Thin on purpose: the frontend lives in frontends/streamlit_app.py so it can be
swapped out without touching the agent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from streamlit_app import main

if __name__ == "__main__":
    main()
else:
    # Streamlit imports rather than executes the entrypoint, so call main() here too.
    main()
