"""
Transport base.

One transport per wire protocol, not per vendor. Every transport obeys the same
rule: when a stored message carries an `api_content` sidecar, send that
verbatim. Reconstruction from clean fields is a fallback for history restored
from disk.
"""

import requests

from ..config import settings
from ..core.messages import Message, Turn
from ..providers.errors import TransportError, classify_error

TIMEOUT = settings.REQUEST_TIMEOUT


def strip_nulls(obj):
    """
    Provider SDKs and our own dict building both like to emit explicit nulls for
    fields the API never returned; several endpoints reject unknown null
    parameters on the way back in. Drop them before replaying.
    """
    if isinstance(obj, dict):
        return {k: strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [strip_nulls(v) for v in obj]
    return obj


class BaseTransport:
    api_mode = ""

    def __init__(self, runtime):
        self.runtime = runtime
        self.session = requests.Session()

    def _post(self, path, payload):
        url = f"{self.runtime.base_url}{path}"
        resp = self.session.post(url, headers=self._headers(), json=payload, timeout=TIMEOUT)
        if resp.status_code != 200:
            raise TransportError(
                resp.status_code, resp.text, classify_error(resp.status_code, resp.text)
            )
        return resp.json()

    def tool_result_messages(self, results):
        """
        One `tool` message per result, correlated by id. Both protocols agree
        at this layer; they diverge only when the message is serialized.
        """
        return [
            Message(
                role="tool",
                content=item["output"],
                tool_call_id=item["call"].id,
                name=item["call"].name,
            )
            for item in results
        ]

    # Subclasses implement:
    def _headers(self) -> dict: raise NotImplementedError
    def _to_wire(self, msg: Message) -> dict: raise NotImplementedError
    def generate(self, conversation, tools) -> Turn: raise NotImplementedError
