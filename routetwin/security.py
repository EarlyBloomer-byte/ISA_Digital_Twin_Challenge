"""Ingestion and operator security (aligned with IEC 62443-3-3 foundational requirements).

  * Device/software identification and authentication -> shared-key HMAC per ingest request
  * Communication integrity                         -> signature covers timestamp + body
  * Replay protection                               -> freshness window + signature cache
  * Auditable events                                -> append-only JSONL audit log
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path


def sign(key: str, timestamp: str, body: bytes) -> str:
    return hmac.new(key.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


class IngestVerifier:
    def __init__(self, key: str, max_skew_s: float = 300.0, cache_size: int = 10000):
        self.key = key
        self.max_skew_s = max_skew_s
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    def verify(self, timestamp: str, signature: str, body: bytes, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        try:
            ts = float(timestamp)
        except (TypeError, ValueError):
            return False, "bad_timestamp"
        if abs(now - ts) > self.max_skew_s:
            return False, "stale_timestamp"
        expected = sign(self.key, timestamp, body)
        if not hmac.compare_digest(expected, signature or ""):
            return False, "bad_signature"
        with self._lock:
            if signature in self._seen:
                return False, "replay"
            self._seen[signature] = now
            while len(self._seen) > self._cache_size:
                self._seen.popitem(last=False)
        return True, "ok"


class AuditLog:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.recent: list[dict] = []

    def write(self, event: str, **fields):
        rec = {"t": time.time(), "event": event, **fields}
        with self._lock:
            self.recent.append(rec)
            del self.recent[:-200]
            if self.path:
                with self.path.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
