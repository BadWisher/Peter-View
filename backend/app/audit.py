from __future__ import annotations

import json
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUDIT_FILE = DATA_DIR / "audit.jsonl"
_lock = threading.Lock()
KEEP = 2000


def append(action: str, user: str, **fields) -> None:
    record = {"ts": time.time(), "user": user, "action": action, **fields}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with AUDIT_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _trim()


def _trim() -> None:
    if not AUDIT_FILE.exists():
        return
    lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) <= KEEP:
        return
    AUDIT_FILE.write_text("\n".join(lines[-KEEP:]) + "\n", encoding="utf-8")


def recent(limit: int = 100) -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    rows = []
    for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:][::-1]
