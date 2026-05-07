"""Determinism helpers — spec §22.

Hashes config dicts so two runs of the same config produce the same
hash, regardless of dict ordering. Used to stamp run JSON outputs.
"""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


def hash_config(config: dict[str, Any]) -> str:
    payload = orjson.dumps(config, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(payload).hexdigest()[:16]


__all__ = ["hash_config"]
