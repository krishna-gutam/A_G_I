"""Two inspection tabs: threads in this workspace, and the raw message log."""

import streamlit as st

from ...core.session import AgentSession


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
