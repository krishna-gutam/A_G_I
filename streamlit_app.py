"""
frontends/streamlit_app.py
--------------------------
The Streamlit frontend. It renders widgets and calls into `session.AgentSession`;
it holds no agent logic of its own, so swapping it for a TUI means rewriting
this file only.

Run it with:  streamlit run main.py

Everything lives inside `main()` rather than at module level. Streamlit
re-executes its entrypoint on every interaction, and `main.py` reaches this
code through an import - which Python caches, so module-level rendering would
draw the page once and then render nothing at all on the next click.
"""

import os
import json
import uuid

import streamlit as st

try:
    from streamlit_ace import st_ace
except ImportError:
    st_ace = None

import models as catalog
import paths
import tools
import workspace
from session import AgentSession, AWAITING_APPROVAL, BUDGET_EXHAUSTED, ERROR


# --- SESSION WIRING ---------------------------------------------------------


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


# --- MODEL PICKER -----------------------------------------------------------


def render_model_picker(session: AgentSession) -> None:
    """Search across every provider that answered, then switch to one."""
    token = st.session_state.get("catalog_token", 0)
    all_models, fetched_at = load_catalog(token)

    st.caption(
        f"{len(all_models)} models from {len(catalog.providers_present(all_models))} providers"
    )

    query = st.text_input(
        "Search models",
        placeholder="flash 3   ·   claude sonnet   ·   qwen coder",
        key="model_query",
    )

    col1, col2 = st.columns([0.6, 0.4])
    with col1:
        chosen_providers = st.multiselect(
            "Providers",
            catalog.providers_present(all_models),
            default=[],
            key="model_provider_filter",
        )
    with col2:
        free_only = st.checkbox("Free only", key="model_free_only")
        if st.button("Refresh list", use_container_width=True):
            st.session_state.catalog_token = token + 1
            load_catalog.clear()
            st.rerun()

    results = catalog.search(all_models, query, chosen_providers or None, free_only)

    if not results:
        st.info("No models match that search. Clear a filter or refresh the list.")
        return

    picked = st.selectbox(
        f"Results ({len(results)})",
        results,
        format_func=lambda m: m.display(),
        key="model_pick",
    )

    if picked:
        c1, c2, c3 = st.columns(3)
        c1.metric("Provider", picked.provider)
        c2.metric("Context", picked.context_label)
        c3.metric("Input price", picked.price_label)

    thinking = st.select_slider(
        "Thinking",
        options=["off", "low", "medium", "high"],
        value=session.thinking or "off",
        key="thinking_level",
    )

    fallback_text = st.text_input(
        "Fallback chain",
        value=",".join(session.fallbacks),
        placeholder="openrouter:google/gemini-3-flash,anthropic",
        help="Comma-separated. Used in order when a provider is rate-limited or out of credit.",
        key="fallback_chain",
    )

    if st.button("Use this model", type="primary", use_container_width=True):
        session.set_model(
            picked.ref,
            fallbacks=[f for f in fallback_text.split(",") if f.strip()],
            thinking=None if thinking == "off" else thinking,
        )
        if not session.is_ready():
            st.error(
                f"No credential found for {picked.provider}. "
                f"Set {'/'.join(catalog.PROFILES[picked.provider].key_env)} in your .env."
            )
        else:
            st.success(f"Now using {session.active_runtime}")
            st.rerun()


# --- SIDEBAR ----------------------------------------------------------------


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
                options=["nothing", "read-only", "file writes", "everything"],
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


# --- TABS -------------------------------------------------------------------


def render_history_tab(session: AgentSession) -> None:
    st.subheader("Conversation Threads")

    for tid in session.list_threads():
        col1, col2, col3, col4 = st.columns([0.85, 0.05, 0.05, 0.05])
        summary = session.thread_summary(tid)

        with col1:
            with st.expander(f"{tid}  ·  {summary['messages']} messages"):
                st.write(f"**Last from you:** {summary['last_human'] or '—'}")
                st.write(f"**Last from agent:** {summary['last_ai'] or '—'}")

        with col2:
            if st.button("D", key=f"del_thread_{tid}", help="Delete this thread"):
                session.delete_thread(tid)
                st.rerun()
        with col3:
            new_id = st.text_input("New ID", key=f"rename_input_{tid}", label_visibility="collapsed")
        with col4:
            if st.button("R", key=f"rename_btn_{tid}", help="Rename"):
                if new_id and new_id != tid:
                    session.rename_thread(tid, new_id)
                    st.rerun()


def render_logs_tab(session: AgentSession) -> None:
    st.subheader("Full Message History")
    st.caption(
        "Each message carries a clean copy and, where the provider sent one, a "
        "wire-faithful sidecar that gets replayed untouched."
    )

    for i, msg in enumerate(session.messages):
        col1, col2 = st.columns([0.9, 0.1])
        with col1:
            label = f"{i}: {msg.role}"
            if msg.tool_calls:
                label += f" ({', '.join(c.name for c in msg.tool_calls)})"
            if msg.api_content:
                label += "  ·  sidecar"
            with st.expander(label):
                st.markdown("**Clean**")
                st.json(msg.clean())
                if msg.api_content:
                    st.markdown("**api_content** (sent verbatim)")
                    st.json(msg.api_content)
        with col2:
            if st.button("🗑️", key=f"del_{i}"):
                session.delete_message(i)
                st.rerun()


def render_editor_tab() -> None:
    st.subheader("File Editor")

    files = workspace.list_project_files()
    if not files:
        st.info("No files here yet. Switch workspaces in the sidebar, or ask the agent to create one.")
        return

    edit_path = st.selectbox("Select a file to edit:", files)

    if st.button("Load File"):
        if edit_path and os.path.exists(edit_path):
            st.session_state.edit_content = workspace.read_file(edit_path)
            # Unique key forces the editor to remount with the new text
            st.session_state.editor_key = str(uuid.uuid4())
        else:
            st.error("That file is gone. Refresh the list and try again.")

    if "edit_content" in st.session_state:
        if "editor_key" not in st.session_state:
            st.session_state.editor_key = "ace_editor_initial"

        if st_ace:
            new_content = st_ace(
                value=st.session_state.edit_content,
                language="python",
                theme="monokai",
                key=st.session_state.editor_key,
            )
        else:
            new_content = st.text_area(
                "Contents", value=st.session_state.edit_content, height=520,
                key=st.session_state.editor_key,
            )

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("💾 Save Changes", use_container_width=True):
                result = workspace.write_file(edit_path, new_content)
                if result.startswith("Error"):
                    st.error(result)
                else:
                    st.success(result)
                    st.session_state.edit_content = new_content
        with col2:
            if st.button("🔄 Reset Unsaved Changes", use_container_width=True):
                if os.path.exists(edit_path):
                    st.session_state.edit_content = workspace.read_file(edit_path)
                    st.session_state.editor_key = str(uuid.uuid4())
                    st.rerun()


# --- CHAT -------------------------------------------------------------------


def render_transcript(session: AgentSession) -> None:
    for msg in session.messages:
        if msg.role == "user":
            with st.chat_message("user"):
                st.markdown(msg.content)
        elif msg.role == "assistant":
            # Skip silent tool-call turns; the call renders as its own block.
            if msg.content.strip():
                with st.chat_message("assistant"):
                    st.markdown(msg.content)
        elif msg.role == "tool":
            with st.chat_message("tool", avatar="🔧"):
                with st.expander(f"Result from {msg.name or 'tool'}", expanded=False):
                    st.code(msg.content, language="json")


def render_tool_approval(session: AgentSession, pending_calls, auto_ceiling) -> None:
    """The gate shown whenever the model asked for a tool and hasn't run it yet."""
    with st.chat_message("assistant"):
        st.warning("⚠️ **The agent wants to run these tools:**")
        for call in pending_calls:
            icon = {tools.Risk.READ: "👁️", tools.Risk.WRITE: "✏️", tools.Risk.EXEC: "⚡"}[call.risk]
            with st.expander(f"{icon} {call.name}  ·  {call.risk_label}", expanded=True):
                if call.summary:
                    st.caption(call.summary)
                for key, value in call.display_args.items():
                    st.markdown(f"**{key}:**")
                    st.code(str(value), language="python")
                if call.justification:
                    st.markdown("**Justification:**")
                    st.code(call.justification)

        if auto_ceiling is not None and session.auto_approvable(pending_calls, auto_ceiling):
            st.info("Auto-approving: everything here is within your risk ceiling.")
            session.approve_tools()
            st.rerun()

        col1, col2, col3 = st.columns([0.4, 0.3, 0.3])

        if col1.button("✅ Run tools"):
            with st.status("Running tools...", expanded=True) as status:
                session.approve_tools()
                status.update(label="Done", state="complete", expanded=False)
            st.rerun()

        if col2.button("❌ Skip tools"):
            session.deny_tools()
            st.rerun()

        with col3:
            with st.popover("💬 Redirect"):
                feedback_text = st.text_area("Tell the agent what to do instead:")
                if st.button("Send"):
                    if feedback_text.strip():
                        st.session_state.pending_feedback = feedback_text
                        st.rerun()
                    else:
                        st.warning("Write something first.")


def run_prompt(session: AgentSession, prompt: str) -> None:
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner(f"{session.active_runtime.model_id} is thinking..."):
            session.send(prompt)

    st.rerun()


# --- ENTRY POINT ------------------------------------------------------------


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


if __name__ == "__main__":
    main()
