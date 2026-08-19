# Restructure notes

Everything that was a flat module at the repo root now lives in a `hermes`
package. No agent logic changed; this is a move, a split, and a rewiring of
imports. The three behavioural deltas are listed at the bottom.

## Where things went

| Was | Now |
|---|---|
| `main.py` | `app.py` |
| `agent.py` | `hermes/core/loop.py` (the loop) + `hermes/frontends/cli.py` (the CLI) |
| `session.py` | `hermes/core/session.py` |
| `conversation.py` | `hermes/core/messages.py` + `hermes/core/conversation.py` + `hermes/core/budget.py` |
| `providers.py` | `hermes/providers/profiles.py` + `runtime.py` + `errors.py` |
| `models.py` | `hermes/providers/catalog.py` |
| `transports.py` | `hermes/transports/base.py` + `chat_completions.py` + `anthropic_messages.py` |
| `tools/base.py` | `hermes/tools/registry.py` + `schema.py` + `sandbox.py` + `errors.py` |
| `tools/__init__.py` | `hermes/tools/__init__.py` (facade) + `runner.py` (execution planning) |
| `tools/{files,shell,web}.py` | `hermes/tools/builtin/` |
| `workspace.py` | `hermes/workspace/{files,notes,recents}.py` |
| `paths.py` | `hermes/config/paths.py` |
| scattered `os.getenv` calls | `hermes/config/settings.py` |
| `tui.py` | `hermes/frontends/tui/` (6 modules) |
| `streamlit_app.py` | `hermes/frontends/streamlit_ui/` (7 modules) |
| `env.example` | `.env.example` (the name the README already told you to copy) |

Moves were made with `git mv`, so `git log --follow` still works on every file.

## Running it

```bash
streamlit run app.py                  # web UI          (was: streamlit run main.py)
python -m hermes.frontends.tui        # terminal UI     (was: python tui.py)
python -m hermes.frontends.cli        # plain CLI       (was: python agent.py)
```

`pip install -e .` additionally installs `hermes` and `hermes-tui` as commands.

## Why the splits

**`providers.py` held three unrelated jobs.** The table of who exists, the
resolution of a model string into a request, and the classification of HTTP
errors. The last of those is imported by transports, which meant transports
depended on the whole provider table to read three string constants.

**`tools/__init__.py` had a scheduler in it.** Batch planning and thread-pool
execution are not package glue; they now live in `runner.py`, leaving the
`__init__` as the four-function facade its docstring already described.

**`tools/base.py` was three files.** Schema derivation from signatures, the
registry itself, and workspace path confinement have nothing to say to each
other and change for different reasons.

**The frontends were the two largest files in the repo** (671 and 529 lines) and
were the only ones a new contributor is likely to touch first.

## Dependency direction

```
frontends → core → transports → providers → config
                 ↘  tools  ↗
```

Nothing below `frontends` imports a frontend, so adding a fourth UI touches no
existing file.

## Three behavioural changes

These were bugs the restructure made hard to leave alone. Each is small, and each
is easy to revert if you disagree.

1. **`.env` now loads once, in `hermes/__init__.py`.** Before, `paths.py` called
   `load_dotenv()` as an import side effect and every module that read an env var
   at import time had to remember to `import paths` first. Missing that import
   made a `.env` setting look silently ignored. Any import of anything under
   `hermes` now guarantees the ordering.

2. **`ITERATION_BUDGET` is honoured everywhere.** `IterationBudget()` defaulted to
   a hardcoded 12; only `agent.py` read the setting. `tui.py` worked around this
   by subclassing `IterationBudget` and monkey-patching the class object into the
   `session` module at import time. The default now comes from settings, and the
   monkey-patch is gone. **If you run with `ITERATION_BUDGET` set to something
   other than 12, the Streamlit UI's per-turn limit changes to match.**

3. **`AgentSession(fallbacks=[])` now means "no fallbacks".** It used to mean
   "read `FALLBACK_MODELS` from the environment", because the check was
   `fallbacks or [...]`. That made `/cd` in the TUI silently resurrect env
   fallbacks a user had cleared. It now matches the `toolsets` parameter beside
   it: `None` means default, `[]` means empty.

## One thing left alone

With no `TOOLSETS` line in `.env`, the default is `files, shell, web` — the README
and `.env.example` both say only `files`. That is a real disagreement about
whether shell access is on by default, and it deserves a decision rather than a
quiet change during a refactor. The constant is flagged with a comment in
`hermes/config/settings.py`.
