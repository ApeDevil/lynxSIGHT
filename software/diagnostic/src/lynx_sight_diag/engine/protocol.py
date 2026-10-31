"""Framing and versioning of the engine protocol (contract version 1)."""

from __future__ import annotations

import json
from typing import IO

PROTOCOL_VERSION = 1  # = ENGINE_PROTOCOL_VERSION in software/desktop/crates/contracts


class EngineError(Exception):
    """A request that cannot be served; becomes an `error` response with this code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def read_message(stream: IO[str]) -> dict | None:
    """The next request, or None at end of input. Raises EngineError on malformed lines."""
    while True:
        line = stream.readline()
        if not line:
            return None
        if line.strip():
            break
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EngineError("invalid_request", f"not JSON: {exc}") from exc
    if not isinstance(message, dict) or "type" not in message or "id" not in message:
        raise EngineError("invalid_request", "a request needs `protocol`, `id` and `type`")
    return message


def envelope(request_id: int, body: dict) -> dict:
    return {"protocol": PROTOCOL_VERSION, "id": request_id, **body}


def write_message(stream: IO[str], message: dict) -> None:
    stream.write(json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n")
    stream.flush()


def error(code: str, message: str) -> dict:
    return {"type": "error", "code": code, "message": message}
