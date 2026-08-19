"""
Error classification.

What a failed request means for the chain: try again here, move to the next
runtime, or stop. Transports raise `TransportError` carrying the verdict, and
the turn loop reads nothing but that verdict -- it never inspects status codes.
"""

RETRY = "retry"          # transient, same runtime
FAILOVER = "failover"    # try the next runtime in the chain
FATAL = "fatal"          # stop; the caller's request is wrong


class TransportError(Exception):
    def __init__(self, status, body, action):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status = status
        self.body = body
        self.action = action  # RETRY | FAILOVER | FATAL


def classify_error(status: int, body: str) -> str:
    text = (body or "").lower()
    if status == 429 or "rate limit" in text or "quota" in text:
        return FAILOVER
    if status in (401, 403) or "invalid api key" in text:
        return FAILOVER
    if status in (402,) or "insufficient" in text or "billing" in text:
        return FAILOVER
    if status >= 500 or "overloaded" in text:
        return RETRY
    if "context length" in text or "too many tokens" in text or "context_length" in text:
        return FATAL  # compression would handle this; we surface it instead
    return FATAL
