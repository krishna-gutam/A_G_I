"""
Tool registry.

A tool is a decorated Python function:

    @tool(toolset="files", risk=Risk.READ)
    def read_file(file_path: str, max_bytes: int = 100_000) -> dict:
        '''Read a UTF-8 text file.

        Args:
            file_path: Path relative to the workspace root.
            max_bytes: Truncate above this size.
        '''

Its schema is derived from the signature (see `schema.py`). Beyond that, each
tool declares three things the runtime needs and the model never sees: which
toolset it belongs to (so it can be switched off), how risky it is (so approval
can be automatic for reads and manual for writes), and which argument names a
path (so independent calls can run concurrently).
"""

import inspect
import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Dict, List, Optional

from .errors import ToolError
from .schema import build_parameters, parse_docstring


class Risk(IntEnum):
    READ = 0   # observes the world
    WRITE = 1  # changes files in the workspace
    EXEC = 2   # runs commands, reaches the network


RISK_LABEL = {
    Risk.READ: "read-only",
    Risk.WRITE: "modifies files",
    Risk.EXEC: "runs commands or reaches the network",
}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable
    toolset: str = "core"
    risk: Risk = Risk.READ
    path_arg: Optional[str] = None   # argument naming the file this call touches
    parallel_safe: bool = True

    def schema(self) -> dict:
        """Provider-agnostic. Transports wrap this into their own envelope."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def run(self, args: dict) -> str:
        """Always returns a JSON string. Never raises into the agent loop."""
        try:
            filtered = {
                k: v for k, v in (args or {}).items()
                if k in inspect.signature(self.fn).parameters
            }
            result = self.fn(**filtered)
        except ToolError as e:
            return json.dumps({"error": str(e)})
        except TypeError as e:
            return json.dumps({"error": f"Bad arguments for {self.name}: {e}"})
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

        if isinstance(result, str):
            return result if result.startswith(("{", "[")) else json.dumps({"result": result})
        try:
            return json.dumps(result)
        except TypeError:
            return json.dumps({"result": str(result)})


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return sorted(self._tools.values(), key=lambda t: (t.toolset, t.name))

    def toolsets(self) -> List[str]:
        return sorted({t.toolset for t in self._tools.values()})

    def enabled(self, toolsets: Optional[List[str]] = None) -> List[Tool]:
        if toolsets is None:
            return self.all()
        return [t for t in self.all() if t.toolset in toolsets]

    def schemas(self, toolsets: Optional[List[str]] = None) -> List[dict]:
        return [t.schema() for t in self.enabled(toolsets)]

    def execute(self, name: str, args: dict) -> str:
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        return tool.run(args)


REGISTRY = ToolRegistry()


def tool(toolset: str = "core", risk: Risk = Risk.READ,
         path_arg: Optional[str] = None, parallel_safe: bool = True,
         name: Optional[str] = None):
    def decorator(fn: Callable) -> Callable:
        summary, _ = parse_docstring(fn.__doc__)
        REGISTRY.add(Tool(
            name=name or fn.__name__,
            description=summary,
            parameters=build_parameters(fn),
            fn=fn,
            toolset=toolset,
            risk=risk,
            path_arg=path_arg,
            parallel_safe=parallel_safe,
        ))
        return fn
    return decorator
