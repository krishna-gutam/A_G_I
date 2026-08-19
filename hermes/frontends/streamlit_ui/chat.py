"""The Chat tab: transcript, the tool approval gate, and prompt submission."""

import streamlit as st

from ... import tools
from ...core.session import AgentSession


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
