"""
Session layer.

Everything the UI needs to drive a turn, with the agent loop turned inside out:
the CLI runs tools the moment the model asks, but a UI has to stop and let a
human look first. So `advance()` returns at the approval boundary and the
caller decides what happens next.

Threads persist BOTH representations (see Conversation.to_dict) so reopening a
thread resumes it faithfully rather than replaying a lossy transcript.
"""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import List, Optional

from .. import tools
from ..config import paths, settings
from ..providers.errors import TransportError
from ..providers.runtime import resolve_chain
from ..transports import build_transport
from .budget import IterationBudget
from .conversation import Conversation
from .loop import generate_with_failover
from .messages import Message, ToolCall

STATE_DIR = paths.THREADS_DIR

DENIED = '{"error": "denied", "message": "The user declined this tool call. Do not retry it; ask what to do instead."}'
REDIRECTED = '{"error": "redirected", "message": "The user interrupted with new instructions. See the next message."}'

# Status values the UI switches on.
IDLE = "idle"
AWAITING_APPROVAL = "awaiting_approval"
BUDGET_EXHAUSTED = "budget_exhausted"
ERROR = "error"


class PendingCall:
    """A tool call dressed for display, with its registry metadata attached."""

    def __init__(self, call: ToolCall):
        self.call = call
        self.name = call.name
        self.args = call.args
        self.tool = tools.describe(call.name)

    @property
    def risk(self):
        return self.tool.risk if self.tool else tools.Risk.EXEC

    @property
    def risk_label(self) -> str:
        return tools.RISK_LABEL[self.risk]

    @property
    def toolset(self) -> str:
        return self.tool.toolset if self.tool else "unknown"

    @property
    def summary(self) -> str:
        return self.tool.description if self.tool else "Unregistered tool."

    @property
    def display_args(self) -> dict:
        return {k: v for k, v in self.args.items() if k != "justification"}

    @property
    def justification(self) -> Optional[str]:
        return self.args.get("justification")


class AgentSession:
    def __init__(self, cwd: str, model_ref: str = "", fallbacks: Optional[List[str]] = None,
                 thinking: Optional[str] = None, system_prompt: Optional[str] = None,
                 toolsets: Optional[List[str]] = None):
        self.cwd = cwd
        self.model_ref = model_ref or settings.default_model()
        self.fallbacks = fallbacks if fallbacks is not None else settings.default_fallbacks()
        self.thinking = thinking
        self.system_prompt = system_prompt
        self.toolsets = toolsets if toolsets is not None else tools.default_toolsets()

        self.thread_id = "main"
        self.conversation = Conversation(system_prompt=system_prompt)
        self.status = IDLE
        self.pending: List[ToolCall] = []
        self.last_error: Optional[str] = None
        self.token_count = 0
        self.budget = IterationBudget()

        self._rebuild_chain()
        self._load_thread(self.thread_id)

    # --- model wiring -----------------------------------------------------

    def _rebuild_chain(self) -> None:
        self.chain = resolve_chain([self.model_ref] + self.fallbacks, thinking=self.thinking)
        self.transport = build_transport(self.chain[0]) if self.chain else None

    def set_toolsets(self, toolsets: List[str]) -> None:
        self.toolsets = list(toolsets)
        self._save_thread()

    def auto_approvable(self, calls, ceiling) -> bool:
        """True when every pending call sits at or below the user's risk ceiling."""
        return all(c.risk <= ceiling for c in calls)

    def set_model(self, model_ref: str, fallbacks=None, thinking=None) -> None:
        """
        Switch models mid-conversation. History is kept: api_content sidecars
        from the old provider stay in place, which is right when the protocol
        is shared and merely tolerated when it isn't.
        """
        self.model_ref = model_ref
        if fallbacks is not None:
            self.fallbacks = fallbacks
        self.thinking = thinking
        self._rebuild_chain()
        self._save_thread()

    def is_ready(self) -> bool:
        return bool(self.chain)

    @property
    def active_runtime(self):
        return self.chain[0] if self.chain else None

    @property
    def messages(self) -> List[Message]:
        return self.conversation.messages

    def pending_tool_calls(self) -> List[PendingCall]:
        return [PendingCall(c) for c in self.pending]

    # --- turn driving -----------------------------------------------------

    def send(self, prompt: str) -> str:
        if self.transport:
            self.conversation.close_interrupted_tool_sequence(self.transport)
        self.conversation.add_user(prompt)
        self.budget = IterationBudget()
        return self.advance()

    def advance(self) -> str:
        """One model round-trip. Stops at the approval boundary."""
        if not self.chain:
            self.status, self.last_error = ERROR, "No provider is configured."
            return self.status
        if self.budget.exhausted:
            self.status = BUDGET_EXHAUSTED
            return self.status

        try:
            turn, transport, runtime = generate_with_failover(
                self.chain, self.conversation, tools.schemas(self.toolsets)
            )
        except (TransportError, RuntimeError) as e:
            self.status, self.last_error = ERROR, str(e)
            return self.status

        self.transport = transport
        self.budget.consume()
        self.conversation.add_turn(turn)

        usage = turn.metadata.get("usage") or {}
        self.token_count += (
            usage.get("total_tokens")
            or (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            or 0
        )

        self.pending = list(turn.tool_calls)
        self.last_error = None
        self.status = AWAITING_APPROVAL if self.pending else IDLE
        self._save_thread()
        return self.status

    def approve_tools(self) -> str:
        calls = self.pending
        self.pending = []
        if not calls:
            return self.status

        # The registry decides what may run concurrently and hands results
        # back in call order.
        self.conversation.add_tool_results(self.transport, tools.execute_calls(calls))
        self._save_thread()
        return self.advance()

    def deny_tools(self) -> str:
        """
        Answer the calls with a refusal rather than deleting them. Deleting an
        assistant message that carries tool calls also deletes whatever reasoning
        item was paired with it, which several providers reject on the next turn.
        """
        calls, self.pending = self.pending, []
        if calls:
            self.conversation.add_tool_results(
                self.transport, [{"call": c, "output": DENIED} for c in calls]
            )
        self.status = IDLE
        self._save_thread()
        return self.status

    def send_tool_feedback(self, feedback: str) -> str:
        calls, self.pending = self.pending, []
        if calls:
            self.conversation.add_tool_results(
                self.transport, [{"call": c, "output": REDIRECTED} for c in calls]
            )
        self.conversation.add_user(feedback)
        self._save_thread()
        return self.advance()

    def finish_after_budget(self) -> str:
        self.conversation.add_user(self.budget.handoff_prompt())
        self.budget = IterationBudget()
        return self.advance()

    # --- history editing --------------------------------------------------

    def _repair(self) -> None:
        self.pending = []
        if self.transport:
            self.conversation.close_interrupted_tool_sequence(self.transport)
        self.status = IDLE
        self._save_thread()

    def undo_last_turn(self) -> bool:
        msgs = self.conversation.messages
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].role == "user":
                del msgs[i:]
                self._repair()
                return True
        return False

    def undo_first_turn(self) -> bool:
        msgs = self.conversation.messages
        starts = [i for i, m in enumerate(msgs) if m.role == "user"]
        if len(starts) < 2:
            return False
        del msgs[starts[0]:starts[1]]
        self._repair()
        return True

    def delete_message(self, index: int) -> bool:
        if 0 <= index < len(self.conversation.messages):
            del self.conversation.messages[index]
            self._repair()
            return True
        return False

    def clear_history(self) -> None:
        self.conversation = Conversation(system_prompt=self.system_prompt)
        self.token_count = 0
        self._repair()

    # --- threads ----------------------------------------------------------

    def _thread_dir(self) -> Path:
        key = hashlib.sha1(os.path.abspath(self.cwd).encode()).hexdigest()[:12]
        d = STATE_DIR / key
        paths.ensure(d)
        return d

    def _thread_path(self, tid: str) -> Path:
        return self._thread_dir() / f"{tid}.json"

    def _save_thread(self) -> None:
        try:
            self._thread_path(self.thread_id).write_text(json.dumps({
                "thread_id": self.thread_id,
                "updated_at": time.time(),
                "model_ref": self.model_ref,
                "fallbacks": self.fallbacks,
                "thinking": self.thinking,
                "toolsets": self.toolsets,
                "token_count": self.token_count,
                "conversation": self.conversation.to_dict(),
            }, indent=1))
        except Exception:
            pass

    def _load_thread(self, tid: str) -> None:
        path = self._thread_path(tid)
        if not path.exists():
            self.conversation = Conversation(system_prompt=self.system_prompt)
            self.token_count = 0
            return
        try:
            raw = json.loads(path.read_text())
            self.conversation = Conversation.from_dict(raw["conversation"])
            self.token_count = raw.get("token_count", 0)
            self.toolsets = raw.get("toolsets", self.toolsets)
            if raw.get("model_ref"):
                self.model_ref = raw["model_ref"]
                self.fallbacks = raw.get("fallbacks", [])
                self.thinking = raw.get("thinking")
                self._rebuild_chain()
        except Exception:
            self.conversation = Conversation(system_prompt=self.system_prompt)

    def list_threads(self) -> List[str]:
        found = sorted(p.stem for p in self._thread_dir().glob("*.json"))
        if self.thread_id not in found:
            found.append(self.thread_id)
        return found

    def switch_thread(self, tid: str) -> None:
        self._save_thread()
        self.thread_id = tid
        self.pending = []
        self.status = IDLE
        self._load_thread(tid)

    def new_thread(self, tid: Optional[str] = None) -> str:
        self._save_thread()
        self.thread_id = tid or uuid.uuid4().hex[:8]
        self.conversation = Conversation(system_prompt=self.system_prompt)
        self.token_count = 0
        self.pending = []
        self.status = IDLE
        self._save_thread()
        return self.thread_id

    def delete_thread(self, tid: str) -> None:
        self._thread_path(tid).unlink(missing_ok=True)
        if tid == self.thread_id:
            remaining = [t for t in self.list_threads() if t != tid]
            self.switch_thread(remaining[0] if remaining else "main")

    def rename_thread(self, old: str, new: str) -> None:
        src = self._thread_path(old)
        if src.exists():
            src.rename(self._thread_path(new))
        if self.thread_id == old:
            self.thread_id = new

    def thread_summary(self, tid: str) -> dict:
        try:
            raw = json.loads(self._thread_path(tid).read_text())
            msgs = raw["conversation"]["messages"]
        except Exception:
            msgs = []
        last_human = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
        last_ai = next(
            (m["content"] for m in reversed(msgs) if m["role"] == "assistant" and m["content"]), ""
        )
        return {
            "last_human": last_human[:300],
            "last_ai": last_ai[:300],
            "messages": len(msgs),
        }
