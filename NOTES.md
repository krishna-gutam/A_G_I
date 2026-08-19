Read it bottom-up along the dependency arrows — each file then only refers to things you've already seen. Roughly four sittings:

**1. The nouns (start here, ~15 min)**
- `hermes/core/messages.py` — the whole design rests on the `api_content` sidecar idea. Nothing else makes sense until this does.
- `hermes/core/conversation.py` — the message list plus `close_interrupted_tool_sequence`, the one invariant providers actually punish you for breaking.
- `hermes/core/budget.py` — tiny, gets it out of the way.

**2. Reaching a provider (~20 min)**
- `hermes/providers/profiles.py` — the table. Note `api_mode`; that field is the pivot the next tier turns on.
- `hermes/providers/runtime.py` — model string → a request you can make.
- `hermes/providers/errors.py` — three constants and a function, but the turn loop reads *nothing* but its verdict.
- `hermes/transports/base.py` then `chat_completions.py`. Skim `anthropic_messages.py` — read it only to see what a genuinely different wire format costs, since it's mostly parallel structure.

**3. What the agent can do (~20 min)**
- `hermes/tools/registry.py` — the `@tool` decorator and `Tool.run`.
- `hermes/tools/schema.py` and `sandbox.py` — self-contained, read in either order.
- `hermes/tools/builtin/files.py` — one concrete toolset makes the previous three click.
- `hermes/tools/runner.py`, then `hermes/tools/__init__.py` as the facade over all of it.

**4. Where it comes together (the payoff)**
- `hermes/core/loop.py` — short, and now every line is familiar.
- `hermes/frontends/cli.py` — read this *before* the session layer. It's the loop with nothing wrapped around it, which sets up the contrast.
- `hermes/core/session.py` — the same loop turned inside out to stop at the approval boundary. This is the densest file in the repo and the one worth slowing down on.
- `hermes/frontends/tui/turn.py` — what a caller does with that boundary.

**Read only when you need them:** `config/paths.py` and `settings.py` (two minutes, whenever you wonder where a knob lives), `providers/catalog.py` (independent — model discovery touches nothing else), `workspace/`, the remaining `tui/` modules, and the `streamlit_ui/` tabs.

If you have twenty minutes rather than ninety: `messages.py` → `transports/base.py` → `tools/registry.py` → `core/session.py`. Those four carry the architecture; the rest is elaboration.

`README.md` first is fine for orientation, but `MIGRATION.md` is only useful if you already knew the old flat layout — skip it otherwise.