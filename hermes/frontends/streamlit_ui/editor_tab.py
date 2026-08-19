"""The Editor tab: open a project file, edit it, save it back."""

import os
import uuid

import streamlit as st

from ... import workspace

try:
    from streamlit_ace import st_ace
except ImportError:
    st_ace = None


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
