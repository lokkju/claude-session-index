from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from claude_session_index.config import HISTORY_FILE, MAX_FILE_SIZE, PROJECTS_DIR
from claude_session_index.db import (
    clear_file_mtimes,
    get_file_mtime,
    get_session,
    rebuild_fts,
    set_file_mtime,
    upsert_session,
)
from claude_session_index.extractor import SessionData, extract_session

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def index_sessions_index(
    conn: sqlite3.Connection,
    projects_dir: Path,
    since_cutoff: datetime | None = None,
) -> int:
    """Phase 1: Index sessions from sessions-index.json files."""
    count = 0
    for index_file in projects_dir.rglob("sessions-index.json"):
        try:
            data = json.loads(index_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        project_path = data.get("originalPath", "")
        project_name = Path(project_path).name if project_path else ""

        for entry in data.get("entries", []):
            if entry.get("isSidechain"):
                continue

            created = entry.get("created", "")
            modified = entry.get("modified", created)

            if since_cutoff and modified:
                try:
                    mod_dt = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                    if mod_dt < since_cutoff:
                        continue
                except ValueError:
                    pass

            session = SessionData(
                session_id=entry.get("sessionId", ""),
                project_path=entry.get("projectPath", project_path),
                project_name=project_name,
                git_branch=entry.get("gitBranch", ""),
                created_at=created,
                modified_at=modified,
                first_prompt=entry.get("firstPrompt", ""),
                user_prompts=entry.get("firstPrompt", ""),
                assistant_text="",
                message_count=entry.get("messageCount", 0),
            )

            upsert_session(conn, session, source="sessions-index")
            # Update summary directly since SessionData doesn't have it
            if entry.get("summary"):
                conn.execute(
                    "UPDATE sessions SET summary = ? WHERE session_id = ?",
                    (entry["summary"], session.session_id),
                )
                conn.commit()

            count += 1

    return count


def index_transcripts(
    conn: sqlite3.Connection,
    projects_dir: Path,
    since_cutoff: datetime | None = None,
) -> int:
    """Phase 2: Index session transcript JSONL files."""
    count = 0
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue

        for jsonl_file in proj_dir.glob("*.jsonl"):
            # Only process UUID-named files
            if not _UUID_RE.match(jsonl_file.stem):
                continue

            # Skip files in subagent directories
            if "subagents" in jsonl_file.parts:
                continue

            # Skip oversized files
            try:
                stat = jsonl_file.stat()
            except OSError:
                continue
            if stat.st_size > MAX_FILE_SIZE:
                continue

            # Incremental: skip unchanged files
            file_key = str(jsonl_file)
            stored_mtime = get_file_mtime(conn, file_key)
            current_mtime = stat.st_mtime
            if stored_mtime is not None and stored_mtime >= current_mtime:
                continue

            # Apply since filter
            if since_cutoff:
                mod_dt = datetime.fromtimestamp(current_mtime, tz=UTC)
                if mod_dt < since_cutoff:
                    continue

            session = extract_session(jsonl_file)
            if session is None:
                continue

            upsert_session(conn, session, source="transcript")
            set_file_mtime(conn, file_key, current_mtime)
            count += 1

    return count


def index_history(
    conn: sqlite3.Connection,
    history_file: Path,
    since_cutoff: datetime | None = None,
) -> int:
    """Phase 3: Index sessions from history.jsonl (gap-fill only)."""
    if not history_file.exists():
        return 0

    count = 0
    with open(history_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            display = entry.get("display", "")
            project = entry.get("project", "")
            timestamp_ms = entry.get("timestamp", 0)
            session_id = entry.get("sessionId", "")

            if not display or not project:
                continue

            # Convert timestamp
            ts = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
            created_at = ts.isoformat()

            if since_cutoff and ts < since_cutoff:
                continue

            # Generate a stable session_id from timestamp + project if not provided
            if not session_id:
                import hashlib

                key = f"{timestamp_ms}:{project}:{display[:100]}"
                session_id = hashlib.sha256(key.encode()).hexdigest()[:36]
                # Format as UUID-like
                session_id = (
                    f"{session_id[:8]}-{session_id[8:12]}-{session_id[12:16]}"
                    f"-{session_id[16:20]}-{session_id[20:32]}"
                )

            # Skip if already indexed from phases 1-2
            existing = get_session(conn, session_id)
            if existing is not None:
                continue

            project_name = Path(project).name
            session = SessionData(
                session_id=session_id,
                project_path=project,
                project_name=project_name,
                git_branch="",
                created_at=created_at,
                modified_at=created_at,
                first_prompt=display[:500],
                user_prompts=display,
                assistant_text="",
                message_count=1,
            )

            upsert_session(conn, session, source="history")
            count += 1

    return count


def index_all(
    conn: sqlite3.Connection,
    projects_dir: Path | None = None,
    history_file: Path | None = None,
    full: bool = False,
    since: str | None = None,
) -> dict:
    """Run the full 3-phase indexing pipeline."""
    if projects_dir is None:
        projects_dir = PROJECTS_DIR
    if history_file is None:
        history_file = HISTORY_FILE

    cutoff: datetime | None = None
    if since:
        from claude_session_index.config import since_cutoff as compute_cutoff

        cutoff = compute_cutoff(since)

    if full:
        clear_file_mtimes(conn)

    phase1 = index_sessions_index(conn, projects_dir, since_cutoff=cutoff)
    phase2 = index_transcripts(conn, projects_dir, since_cutoff=cutoff)
    phase3 = index_history(conn, history_file, since_cutoff=cutoff)

    rebuild_fts(conn)

    total = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]

    return {
        "phase1_count": phase1,
        "phase2_count": phase2,
        "phase3_count": phase3,
        "total": total,
    }
