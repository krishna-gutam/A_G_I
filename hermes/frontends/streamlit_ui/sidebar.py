"""The sidebar: model summary, threads, workspace, counters, notes, toolsets."""

import os

import streamlit as st

from ... import tools, workspace
from ...config import paths
from ...core.session import AgentSession
from .state import switch_workspace_environment

AUTO_LEVELS = {
    "nothing": None,
    "read-only": tools.Risk.READ,
    "file writes": tools.Risk.WRITE,
    "everything": tools.Risk.EXEC,
}


def render_toolset_panel(session) -> None:
    """Switch whole toolsets on and off. Shell and web are off by default."""
    with st.container(border=True):
        st.markdown("**🔧 Tools**")

        chosen = st.multiselect(
            "Enabled toolsets",
            tools.REGISTRY.toolsets(),
            default=session.toolsets,
            key="toolset_select",
        )
        if set(chosen) != set(session.toolsets):
            session.set_toolsets(chosen)
            st.rerun()

        active = tools.enabled_tools(session.toolsets)
        if not active:
            st.caption("No tools enabled. The agent can only talk.")
            return

        for t in active:
            icon = {tools.Risk.READ: "👁️", tools.Risk.WRITE: "✏️", tools.Risk.EXEC: "⚡"}[t.risk]
            st.caption(f"{icon} `{t.name}` — {t.description}")


def render_sidebar(session: AgentSession) -> bool:
    """Draw the sidebar. Returns whether tools should be auto-approved."""
    with st.sidebar:
        with st.container(border=True):
            rt = session.active_runtime
            if rt:
                st.markdown(f"**{rt.provider}** · `{rt.model_id}`")
                chain_tail = " → ".join(r.provider for r in session.chain[1:])
                st.caption(f"{rt.api_mode}" + (f"  ·  falls back to {chain_tail}" if chain_tail else ""))
            else:
                st.error("No provider configured. Pick a model in the Models tab.")

        with st.container(border=True):
            all_threads = session.list_threads()
            current_idx = all_threads.index(session.thread_id)

            selected_thread = st.selectbox(
                "Switch Conversation", all_threads, index=current_idx,
                format_func=lambda x: x[:24],
            )
            if selected_thread != session.thread_id:
                session.switch_thread(selected_thread)
                st.rerun()

            if st.button("➕ New Conversation", key="new_conv_btn"):
                st.session_state.show_new_thread_input = True

            if st.session_state.get("show_new_thread_input", False):
                custom_id = st.text_input("Name this conversation:", key="custom_thread_id_input")
                col1, col2 = st.columns(2)
                if col1.button("Create"):
                    st.session_state.show_new_thread_input = False
                    session.new_thread(custom_id or None)
                    st.rerun()
                if col2.button("Cancel"):
                    st.session_state.show_new_thread_input = False
                    st.rerun()

        with st.container(border=True):
            project_opts = ["Current Directory"] + workspace.load_recent_projects()
            selected_proj = st.selectbox("Switch Workspace", project_opts)

            if st.button("➕ Create New Project", key="new_proj_btn"):
                st.session_state.show_new_project_input = True

            if st.session_state.get("show_new_project_input", False):
                new_path = st.text_input("Absolute path for the new project:", key="new_proj_path_input")
                col1, col2 = st.columns(2)
                if col1.button("Create Project"):
                    if new_path and os.path.isdir(os.path.dirname(new_path)):
                        os.makedirs(new_path, exist_ok=True)
                        st.session_state.show_new_project_input = False
                        os.chdir(new_path)
                        workspace.save_recent_project(new_path)
                        switch_workspace_environment()
                    else:
                        st.error("That parent directory doesn't exist. Check the path.")
                if col2.button("Cancel Project"):
                    st.session_state.show_new_project_input = False
                    st.rerun()

            if selected_proj != "Current Directory":
                if os.path.exists(selected_proj) and os.getcwd() != selected_proj:
                    os.chdir(selected_proj)
                    workspace.save_recent_project(selected_proj)
                    switch_workspace_environment()

            st.caption(f"**Active:** `{os.getcwd()}`")
            st.caption(f"**State:** `{paths.describe()}`")

        with st.container(border=True):
            col1, col2 = st.columns(2)
            col1.metric("Tokens", f"{session.token_count:,}")
            col2.metric("Step", f"{session.budget.used}/{session.budget.limit}")

            auto_level = st.select_slider(
                "Auto-approve up to",
                options=list(AUTO_LEVELS),
                value="nothing",
                help="Anything riskier than this still waits for you.",
            )

            if st.button("⏮️ Undo First Turn", use_container_width=True):
                if session.undo_first_turn():
                    st.rerun()

            if st.button("↩️ Undo Last Turn", use_container_width=True):
                if session.undo_last_turn():
                    st.rerun()

            if st.button("🗑️ Clear Chat History", use_container_width=True):
                session.clear_history()
                st.rerun()

        with st.container(border=True):
            sidebar_notes = st.text_area(
                "Quick Notes:", value=workspace.read_notes(), height=200, key="sidebar_notes"
            )
            if st.button("Save Quick Notes"):
                workspace.write_notes(sidebar_notes)
                st.success("Notes saved.")

        render_toolset_panel(session)

    return AUTO_LEVELS[auto_level]
