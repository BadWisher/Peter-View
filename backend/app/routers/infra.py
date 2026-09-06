from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

CHECK_TIMEOUT = 300
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
CHUNK_LINES = 500
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RULES_FILE = DATA_DIR / "rules.json"
PREFS_FILE = DATA_DIR / "user_prefs.json"
RULE_SEVERITIES = {"error", "warning", "suggestion"}

_rules_lock = threading.Lock()
_prefs_lock = threading.Lock()
_check_sem = asyncio.Semaphore(3)

DOCS_ENABLED = os.getenv("PROOFREADER_DOCS", "false").lower() in ("true", "1", "yes")
