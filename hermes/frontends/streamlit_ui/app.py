"""
The Streamlit frontend.

It renders widgets and calls into `AgentSession`; it holds no agent logic of its
own, so swapping it for a TUI means rewriting this package only.

Run it with:  streamlit run app.py   (the shim at the repo root)

Everything lives inside `main()` rather than at module level. Streamlit
re-executes its entrypoint on every interaction, and the root shim reaches this
code through an import - which Python caches, so module-level rendering would
draw the page once and then render nothing at all on the next click.
"""

import os

import streamlit as st

from ...core.session import BUDGET_EXHAUSTED, ERROR
from .chat import render_tool_approval, render_transcript, run_prompt
from .editor_tab import render_editor_tab
from .history_tabs import render_history_tab, render_logs_tab
from .models_tab import render_model_picker
from .sidebar import render_sidebar
from .state import get_session


def main() -> None:
    st.set_page_config(page_title="Agent", layout="wide")

    session = get_session(os.getcwd())
    auto_ceiling = render_sidebar(session)

    pending_calls = session.pending_tool_calls()

    tab_chat, tab_models, tab_edit, tab_logs, tab_history = st.tabs(
        ["💬 Chat", "🧠 Models", "📝 Editor", "📜 Message Logs", "🕒 Manage History"]
    )

    with tab_models:
        render_model_picker(session)

    with tab_history:
        render_history_tab(session)

    with tab_logs:
        render_logs_tab(session)

    with tab_edit:
        render_editor_tab()

    with tab_chat:
        render_transcript(session)

        if pending_calls:
            render_tool_approval(session, pending_calls, auto_ceiling)

        # Feedback is submitted inside a popover; resume on the next run so the
        # popover isn't holding the rerun open.
        if st.session_state.get("pending_feedback"):
            text = st.session_state.pop("pending_feedback")
            with st.chat_message("assistant"):
                with st.spinner("Taking your redirection..."):
                    session.send_tool_feedback(text)
            st.rerun()

        if session.status == BUDGET_EXHAUSTED:
            st.info(f"Hit the {session.budget.limit}-step limit for this turn.")
            if st.button("Ask for a summary and stop"):
                session.finish_after_budget()
                st.rerun()

        if session.status == ERROR and session.last_error:
            st.error(session.last_error)

    if not session.is_ready():
        with tab_chat:
            st.warning(
                "**No model selected.** Open the Models tab, search for one, and pick it. "
                "You'll need the matching API key in your .env."
            )
        st.chat_input("Select a model to start...", disabled=True)
        return

    prompt = st.chat_input("What would you like to do?")
    if prompt:
        with tab_chat:
            run_prompt(session, prompt)
