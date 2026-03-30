from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"
DB_DIR = Path.home() / ".local" / "share" / "claude-session-index"
DB_PATH = DB_DIR / "sessions.db"

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_LINES_PER_SESSION = 10_000
USER_PROMPTS_CAP = 3072
ASSISTANT_TEXT_CAP = 3072
ASSISTANT_BLOCK_CAP = 500
COMMAND_MAX_LEN = 500
MIN_PROMPT_LEN = 10

_DURATION_RE = re.compile(r"^(\d+)([dhm])$")


def parse_duration(value: str) -> timedelta:
    """Parse a duration string like '7d', '24h', '30m' into a timedelta."""
    m = _DURATION_RE.match(value.strip())
    if not m:
        raise ValueError(f"Invalid duration: {value!r}. Use format like '7d', '24h', '30m'.")
    amount = int(m.group(1))
    unit = m.group(2)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def since_cutoff(since: str) -> datetime:
    """Convert a duration string or ISO date into a UTC datetime cutoff."""
    try:
        delta = parse_duration(since)
        return datetime.now(timezone.utc) - delta
    except ValueError:
        pass
    # Try ISO date
    try:
        dt = datetime.fromisoformat(since)
    except ValueError:
        raise ValueError(
            f"'{since}' is not a valid duration (e.g. '7d', '24h') or ISO date (e.g. '2026-03-01')."
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
