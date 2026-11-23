import time
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def monotonic() -> float:
    return time.monotonic()


def now() -> datetime:
    return datetime.now(timezone.utc)
