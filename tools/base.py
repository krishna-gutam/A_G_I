"""
Tool registry.

A tool is a decorated Python function. Its JSON schema is derived from the
signature, type hints, and docstring, because a schema maintained by hand
drifts from the code it describes and the model only ever sees the stale half.

    @tool(toolset="files", risk=Risk.READ)
    def read_file(file_path: str, max_bytes: int = 100_000) -> dict:
        '''Read a UTF-8 text file.

        Args:
            file_path: Path relative to the workspace root.
            max_bytes: Truncate above this size.
        '''

Beyond the schema, each tool declares three things the runtime needs and the
model never sees: which toolset it belongs to (so it can be switched off),
how risky it is (so approval can be automatic for reads and manual for writes),
and which argument names a path (so independent calls can run concurrently).
"""

import inspect
import json
import os
import re
import typing
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class Risk(IntEnum):
    READ = 0   # observes the world
    WRITE = 1  # changes files in the workspace
    EXEC = 2   # runs commands, reaches the network


RISK_LABEL = {
    Risk.READ: "read-only",
    Risk.WRITE: "modifies files",
    Risk.EXEC: "runs commands or reaches the network",
}


class ToolError(Exception):
    """Raised inside a tool to return a clean message instead of a traceback."""


# --- schema derivation ----------------------------------------------------

_JSON_TYPES = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    list: "array", dict: "object",
}


def _json_type(annotation) -> dict:
    origin = typing.get_origin(annotation)

    if origin is typing.Union:  # Optional[X] -> X
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _json_type(args[0]) if len(args) == 1 else {"type": "string"}

    if origin in (list, List):
        args = typing.get_args(annotation)
        item = _json_type(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}

    if origin in (dict, Dict):
        return {"type": "object"}

    return {"type": _JSON_TYPES.get(annotation, "string")}


def _parse_docstring(doc: str):
    """Returns (summary, {param: description}) from a Google-style docstring."""
    if not doc:
        return "", {}

    lines = inspect.cleandoc(doc).splitlines()
    summary_lines, params, in_args = [], {}, False
    current = None

    for line in lines:
        stripped = line.strip()
        if re.match(r"^(Args|Arguments|Params|Parameters):$", stripped):
            in_args = True
            continue
        if in_args and re.match(r"^(Returns|Raises|Examples?|Notes?):$", stripped):
            break

        if in_args:
            match = re.match(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$", stripped)
            if match:
                current = match.group(1)
                params[current] = match.group(2).strip()
            elif current and stripped:
                params[current] += " " + stripped
        elif stripped:
            summary_lines.append(stripped)

    return " ".join(summary_lines).strip(), params


def build_parameters(fn: Callable) -> dict:
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    _, param_docs = _parse_docstring(fn.__doc__)

    properties, required = {}, []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        prop = _json_type(hints.get(name, str))
        if name in param_docs:
            prop["description"] = param_docs[name]
        properties[name] = prop
        # A parameter with a default is simply not required. We deliberately
        # omit a "default" key: several providers only accept a subset of
        # JSON Schema and reject it.
        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# --- tool -----------------------------------------------------------------

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
        summary, _ = _parse_docstring(fn.__doc__)
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


# --- workspace confinement ------------------------------------------------

ALLOW_OUTSIDE = os.getenv("HERMES_ALLOW_OUTSIDE_WORKSPACE", "").lower() in ("1", "true", "yes")


def safe_path(path: str) -> Path:
    """
    Resolve a path inside the workspace. Refuses to escape via .. or symlink
    unless HERMES_ALLOW_OUTSIDE_WORKSPACE is set, so a confused model can't
    rewrite files elsewhere on the machine.
    """
    root = Path.cwd().resolve()
    target = (root / os.path.expanduser(path or ".")).resolve()

    if not ALLOW_OUTSIDE and root not in target.parents and target != root:
        raise ToolError(
            f"'{path}' is outside the workspace ({root}). "
            "Set HERMES_ALLOW_OUTSIDE_WORKSPACE=1 to permit this."
        )
    return target
