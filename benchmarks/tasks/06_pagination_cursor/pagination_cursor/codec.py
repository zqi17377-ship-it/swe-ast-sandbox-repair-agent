"""URL-safe base64 cursor encoding and integrity verification."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass


class InvalidCursorError(ValueError):
    """Raised when an opaque pagination cursor is malformed or tampered with."""


@dataclass(frozen=True)
class CursorToken:
    """Decoded keyset boundary coordinates."""

    sort_value: int
    item_id: str


def _compute_tag(sort_value: int, item_id: str, secret: str) -> str:
    raw = f"{sort_value}:{item_id}:{secret}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def encode_cursor(sort_value: int, item_id: str, secret: str = "cursor-v1") -> str:
    """Serialize `(sort_value, item_id)` into an opaque tamper-evident token."""
    payload = {
        "sv": int(sort_value),
        "id": str(item_id),
        "sig": _compute_tag(int(sort_value), str(item_id), secret),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    return encoded.decode("ascii")


def decode_cursor(token: str, secret: str = "cursor-v1") -> CursorToken:
    """Decode and verify an opaque cursor token."""
    try:
        padded = token.strip()
        raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw_bytes.decode("utf-8"))
        sv = int(data["sv"])
        iid = str(data["id"])
        sig = str(data["sig"])
    except Exception as exc:
        raise InvalidCursorError(f"Malformed pagination cursor: {token!r}") from exc

    expected = _compute_tag(sv, iid, secret)
    if sig != expected:
        raise InvalidCursorError("Cursor signature verification failed.")
    return CursorToken(sort_value=sv, item_id=iid)
