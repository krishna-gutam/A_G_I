"""
Streamlit-side caching and wiring.

Streamlit re-executes the whole script on every interaction, so anything that
must survive a click lives behind a cache decorator here rather than in a
module-level variable.
"""

import streamlit as st

from ...core.session import AgentSession
from ...providers import catalog


@st.cache_resource
def get_session(cwd: str) -> AgentSession:
    """One AgentSession per workspace directory, kept across reruns."""
    return AgentSession(cwd=cwd)


@st.cache_data(show_spinner=False)
def load_catalog(refresh_token: int):
    """Cached by token: bump the token to force a live re-probe."""
    return catalog.discover(force=refresh_token > 0)


def switch_workspace_environment() -> None:
    """Re-bind the session after chdir into another project."""
    get_session.clear()
    st.rerun()
