"""The Models tab: search every provider that answered, then switch to one."""

import streamlit as st

from ...core.session import AgentSession
from ...providers import catalog
from ...providers.profiles import PROFILES
from .state import load_catalog


def render_model_picker(session: AgentSession) -> None:
    """Search across every provider that answered, then switch to one."""
    token = st.session_state.get("catalog_token", 0)
    all_models, fetched_at = load_catalog(token)

    st.caption(
        f"{len(all_models)} models from {len(catalog.providers_present(all_models))} providers"
    )

    query = st.text_input(
        "Search models",
        placeholder="flash 3   ·   gpt-4o   ·   qwen coder",
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
        placeholder="openrouter:google/gemini-3-flash,openai",
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
                f"Set {'/'.join(PROFILES[picked.provider].key_env)} in your .env."
            )
        else:
            st.success(f"Now using {session.active_runtime}")
            st.rerun()
