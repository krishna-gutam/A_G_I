"""
Frontends.

Three of them, sharing everything below this package:

    cli        -- `hermes.core.loop` directly; tools run as the model asks
    tui        -- terminal, driven by AgentSession with an approval gate
    streamlit  -- browser, same session, same gate

No agent logic lives in here. A frontend renders and collects input; when it
needs a decision made it asks the session.
"""
