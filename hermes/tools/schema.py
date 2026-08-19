"""
Schema derivation.

A tool's JSON schema comes from its signature, type hints, and docstring,
because a schema maintained by hand drifts from the code it describes and the
model only ever sees the stale half.
"""

import inspect
import re
import typing
from typing import Callable, Dict, List, Tuple

_JSON_TYPES = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    list: "array", dict: "object",
}


def json_type(annotation) -> dict:
    origin = typing.get_origin(annotation)

    if origin is typing.Union:  # Optional[X] -> X
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return json_type(args[0]) if len(args) == 1 else {"type": "string"}

    if origin in (list, List):
        args = typing.get_args(annotation)
        item = json_type(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}

    if origin in (dict, Dict):
        return {"type": "object"}

    return {"type": _JSON_TYPES.get(annotation, "string")}


def parse_docstring(doc: str) -> Tuple[str, dict]:
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
    _, param_docs = parse_docstring(fn.__doc__)

    properties, required = {}, []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        prop = json_type(hints.get(name, str))
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
