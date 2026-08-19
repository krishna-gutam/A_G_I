"""Shell access. Off by default -- enable the 'shell' toolset to use it."""

import subprocess

from ..registry import Risk, tool
from ..errors import ToolError

TIMEOUT = 120
MAX_OUTPUT = 20_000

# Refused outright regardless of approval. Not a security boundary -- a
# guardrail against the obvious accident. Real isolation needs a container.
BLOCKED = ("rm -rf /", "mkfs", "dd if=", ":(){", "shutdown", "reboot")


@tool(toolset="shell", risk=Risk.EXEC, parallel_safe=False)
def run_command(command: str, timeout: int = TIMEOUT) -> dict:
    """Run a shell command in the workspace directory and capture its output.

    Args:
        command: The command line to run.
        timeout: Seconds to wait before killing it.
    """
    lowered = command.lower()
    if any(bad in lowered for bad in BLOCKED):
        raise ToolError("That command is blocked. Ask the user to run it themselves.")

    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=min(timeout, 600),
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command exceeded {timeout}s and was killed.")

    def clip(s):
        return s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT] + "\n...[truncated]"

    return {
        "exit_code": proc.returncode,
        "stdout": clip(proc.stdout),
        "stderr": clip(proc.stderr),
    }
