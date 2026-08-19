# Multi-provider coding agent

A CLI and Streamlit agent that talks to OpenAI, Gemini, Anthropic, Groq, DeepSeek,
OpenRouter, and any local OpenAI-compatible server — without a per-vendor adapter
for each one.

Two ideas carry the design:

**Transports are per wire protocol, not per vendor.** Six of the seven providers
speak the OpenAI chat-completions format, so they share one transport. Anthropic
gets its own because its format genuinely differs. Adding Groq was one row in a
dict.

**Provider messages are replayed verbatim.** Every message keeps a clean copy for
display and an `api_content` sidecar holding the provider's own object, byte for
byte. Whatever opaque state a vendor requires back — Gemini thought signatures,
OpenAI reasoning items, Anthropic thinking-block signatures — rides in the sidecar
and is never inspected, so it can never be dropped.

---

## Install

```bash
pip install -r requirements.txt
cp .env.example .env      # add at least one API key
```

## Run

```bash
streamlit run main.py     # web UI
python agent.py           # CLI
```

---

## Configuration

Everything is `.env`. One API key is enough to start.

### Credentials

| Variable | Provider |
|---|---|
| `OPENAI_API_KEY` | OpenAI |
| `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Gemini |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GROQ_API_KEY` | Groq |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `OPENROUTER_API_KEY` | OpenRouter |
| — | `local` needs no key |

### Model selection

```bash
MODEL=groq:llama-3.3-70b-versatile
FALLBACK_MODELS=openrouter:google/gemini-3-flash,anthropic
THINKING=medium          # off | low | medium | high
ITERATION_BUDGET=12      # model round-trips per turn
```

Model strings are `provider:model_id`. The prefix only counts if it names a known
provider, so `local:qwen3:latest` and `openrouter:google/gemini-3-flash` both parse
correctly. Bare `gpt-4o-mini` falls back to the default provider; bare `anthropic`
uses that provider's default model.

Fallbacks are tried in order when a provider is rate-limited, out of credit, or
returning auth errors. Providers with no credential are dropped from the chain
silently, so you can list ones you haven't set up yet.

### Tools

```bash
TOOLSETS=files                     # files, shell, web
MAX_PARALLEL_TOOLS=8
HERMES_ALLOW_OUTSIDE_WORKSPACE=0   # let file tools escape the working directory
```

### State location

```bash
HERMES_STATE_DIR=~/.hermes_ui      # or ./.hermes to keep it beside the project
```

Threads, the model cache, and recent projects all live under it. Override
individually with `HERMES_THREADS_DIR`, `HERMES_MODEL_CACHE`, `HERMES_RECENTS_FILE`,
`HERMES_NOTES_FILE`. Paths expand `~` and `$VARS`.

---

## The UI

**Chat** — transcript, plus the approval gate whenever the model asks for a tool.
Approve, skip, or redirect with feedback.

**Models** — search across every provider that answered. Type terms in any order
(`flash 3`, `sonnet 4`, `qwen coder`), filter by provider or free-tier, and switch
without losing the conversation. Context length and input price show where the
source reports them.

**Editor** — load and save any file in the workspace.

**Message Logs** — every message expanded into its clean copy and its `api_content`
sidecar, so you can see exactly what goes over the wire.

**Manage History** — rename, delete, and inspect threads.

The sidebar carries the active runtime and fallback chain, thread and workspace
switching, token count, step count, toolset toggles, undo, and notes.

### Approval

Auto-approval is a risk ceiling, not a checkbox:

| Setting | Runs unattended |
|---|---|
| nothing | — |
| read-only | `read_file`, `list_files`, `search_files` |
| file writes | the above, plus `write_file`, `edit_file` |
| everything | plus `run_command`, `fetch_url` |

Anything above the ceiling still waits for you.

---

## Tools

| Toolset | Tool | Risk |
|---|---|---|
| `files` | `list_files`, `read_file`, `search_files` | read-only |
| `files` | `write_file`, `edit_file` | modifies files |
| `shell` | `run_command` | runs commands |
| `web` | `fetch_url` | network |

Only `files` is on by default. File tools are confined to the working directory
unless `HERMES_ALLOW_OUTSIDE_WORKSPACE=1`.

### Adding a tool

Write a decorated function in `tools/`. The JSON schema comes from the signature,
type hints, and docstring — there is no schema list to update and no dispatch
branch to add.

```python
from .base import tool, Risk, ToolError, safe_path

@tool(toolset="files", risk=Risk.WRITE, path_arg="file_path", parallel_safe=False)
def append_file(file_path: str, text: str) -> dict:
    """Append text to the end of a file.

    Args:
        file_path: Path relative to the workspace root.
        text: Text to append.
    """
    target = safe_path(file_path)
    if not target.is_file():
        raise ToolError(f"'{file_path}' does not exist.")
    with target.open("a", encoding="utf-8") as f:
        f.write(text)
    return {"status": "appended", "file_path": file_path}
```

The three decorator arguments the model never sees:

- `toolset` — which group it belongs to, so it can be switched off
- `risk` — `READ`, `WRITE`, or `EXEC`, driving the approval ceiling
- `path_arg` / `parallel_safe` — which argument names a file, so independent calls
  batch concurrently. Two writes to different paths run together; two writes to the
  same path serialize.

Return a dict, list, or string; it's JSON-encoded for you. Raise `ToolError` for a
clean message. Anything else raised becomes a structured error rather than a crash.

### Adding a provider

If it's OpenAI-shaped, add a row to `PROFILES` in `providers.py`:

```python
"cerebras": ProviderProfile(
    name="cerebras",
    base_url="https://api.cerebras.ai/v1",
    key_env=("CEREBRAS_API_KEY",),
    default_model="llama-3.3-70b",
),
```

It now appears in resolution, the model catalog, search, and fallback chains. A new
transport is only needed for a genuinely different wire format.

---

## Layout

```
main.py                    entrypoint for streamlit
agent.py                   CLI frontend + the model-call loop with failover
frontends/streamlit_app.py web frontend; widgets only, no agent logic

providers.py               model string -> credentials, base URL, API mode
transports.py              one class per wire protocol
conversation.py            Message/Turn, clean + api_content, iteration budget
session.py                 threads, approval gate, persistence, model switching
models.py                  catalog discovery, caching, cross-provider search
tools/                     registry, schema derivation, toolsets
paths.py                   every state path, resolved from .env
workspace.py               project files, notes, recent projects
```

Both frontends drive the same loop. `agent.py` runs tools the moment the model asks;
`session.py` stops at the approval boundary and lets the caller decide. Swapping in a
TUI means writing one file.

---

## Notes

**Gemini goes through the OpenAI-compatible endpoint**
(`generativelanguage.googleapis.com/v1beta/openai`), not native `generateContent`.
That means the native `parts` / `functionCall` / `thoughtSignature` shape never
enters this codebase, so it can't be dropped by our own serialization. The
trade-off is that you get whatever the compat layer exposes; native-only features
would need a third transport.

**Interrupts are handled.** An assistant message carrying tool calls must be
followed by a result for each one. Ctrl-C mid-execution backfills cancellations, so
the next request doesn't 400 on a dangling call.

**Threads persist both representations.** Dropping `api_content` at save time is the
same bug as dropping it in memory, just deferred until someone reopens the tab.

**Responses are not streamed.** Reassembling an assistant message from deltas means
reconstructing `api_content` rather than storing what arrived, which is the exact
fidelity guarantee everything else here depends on.

**`shell.py`'s blocklist is not a security boundary.** It catches obvious accidents.
Real isolation needs a container; the approval gate is doing the actual work.
