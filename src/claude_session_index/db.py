from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from claude_session_index.extractor import SessionData

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    project_path  TEXT NOT NULL,
    project_name  TEXT NOT NULL,
    summary       TEXT DEFAULT '',
    first_prompt  TEXT DEFAULT '',
    user_prompts  TEXT DEFAULT '',
    assistant_text TEXT DEFAULT '',
    files_changed TEXT DEFAULT '',
    commands_run  TEXT DEFAULT '',
    commit_messages TEXT DEFAULT '',
    git_branch    TEXT DEFAULT '',
    created_at    TEXT NOT NULL,
    modified_at   TEXT NOT NULL,
    message_count INTEGER DEFAULT 0,
    keywords      TEXT DEFAULT '',
    tags          TEXT DEFAULT '',
    source        TEXT DEFAULT 'transcript',
    indexed_at    TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    session_id, summary, first_prompt, user_prompts,
    assistant_text, files_changed, commands_run,
    commit_messages, project_name, keywords, tags,
    tokenize='porter unicode61 remove_diacritics 1',
    prefix='2 3'
);

CREATE TABLE IF NOT EXISTS file_mtimes (
    file_path TEXT PRIMARY KEY,
    mtime     REAL NOT NULL
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize the database, creating tables if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def upsert_session(conn: sqlite3.Connection, session: SessionData, source: str) -> None:
    """Insert or update a session record."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO sessions (
            session_id, project_path, project_name, first_prompt,
            user_prompts, assistant_text, files_changed, commands_run,
            commit_messages, git_branch, created_at, modified_at,
            message_count, source, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            project_path = excluded.project_path,
            project_name = excluded.project_name,
            first_prompt = CASE
                WHEN excluded.first_prompt != '' THEN excluded.first_prompt
                ELSE sessions.first_prompt END,
            user_prompts = CASE
                WHEN excluded.user_prompts != '' THEN excluded.user_prompts
                ELSE sessions.user_prompts END,
            assistant_text = CASE
                WHEN excluded.assistant_text != '' THEN excluded.assistant_text
                ELSE sessions.assistant_text END,
            files_changed = CASE
                WHEN excluded.files_changed != '' THEN excluded.files_changed
                ELSE sessions.files_changed END,
            commands_run = CASE
                WHEN excluded.commands_run != '' THEN excluded.commands_run
                ELSE sessions.commands_run END,
            commit_messages = CASE
                WHEN excluded.commit_messages != '' THEN excluded.commit_messages
                ELSE sessions.commit_messages END,
            git_branch = CASE
                WHEN excluded.git_branch != '' THEN excluded.git_branch
                ELSE sessions.git_branch END,
            modified_at = excluded.modified_at,
            message_count = CASE
                WHEN excluded.message_count > sessions.message_count
                THEN excluded.message_count
                ELSE sessions.message_count END,
            source = excluded.source,
            indexed_at = excluded.indexed_at
        """,
        (
            session.session_id,
            session.project_path,
            session.project_name,
            session.first_prompt,
            session.user_prompts,
            session.assistant_text,
            "\n".join(session.files_changed),
            "\n".join(session.commands_run),
            "\n".join(session.commit_messages),
            session.git_branch,
            session.created_at,
            session.modified_at,
            session.message_count,
            source,
            now,
        ),
    )
    conn.commit()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS index from the sessions table."""
    conn.execute("DELETE FROM sessions_fts")
    conn.execute(
        """
        INSERT INTO sessions_fts (
            session_id, summary, first_prompt, user_prompts,
            assistant_text, files_changed, commands_run,
            commit_messages, project_name, keywords, tags
        )
        SELECT
            session_id, summary, first_prompt, user_prompts,
            assistant_text, files_changed, commands_run,
            commit_messages, project_name, keywords, tags
        FROM sessions
        """
    )
    conn.commit()


def upsert_fts(conn: sqlite3.Connection, session_id: str) -> None:
    """Update the FTS entry for a single session."""
    conn.execute("DELETE FROM sessions_fts WHERE session_id = ?", (session_id,))
    conn.execute(
        """
        INSERT INTO sessions_fts (
            session_id, summary, first_prompt, user_prompts,
            assistant_text, files_changed, commands_run,
            commit_messages, project_name, keywords, tags
        )
        SELECT
            session_id, summary, first_prompt, user_prompts,
            assistant_text, files_changed, commands_run,
            commit_messages, project_name, keywords, tags
        FROM sessions WHERE session_id = ?
        """,
        (session_id,),
    )
    conn.commit()


def get_session(conn: sqlite3.Connection, session_id: str) -> dict | None:
    """Get a single session by ID."""
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_sessions(
    conn: sqlite3.Connection,
    project: str | None = None,
    since: str | None = None,
    branch: str | None = None,
    limit: int = 20,
    order_by: str = "modified_at",
) -> list[dict]:
    """List sessions with optional filters."""
    allowed_order = {"modified_at", "created_at", "message_count"}
    if order_by not in allowed_order:
        order_by = "modified_at"

    conditions: list[str] = []
    params: list[str | int] = []

    if project:
        conditions.append("project_name = ?")
        params.append(project)
    if branch:
        conditions.append("git_branch = ?")
        params.append(branch)
    if since:
        from claude_session_index.config import since_cutoff

        cutoff = since_cutoff(since)
        conditions.append("modified_at >= ?")
        params.append(cutoff.isoformat())

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM sessions {where} ORDER BY {order_by} DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats(conn: sqlite3.Connection, since: str | None = None) -> dict:
    """Get index statistics."""
    conditions: list[str] = []
    params: list[str] = []

    if since:
        from claude_session_index.config import since_cutoff

        cutoff = since_cutoff(since)
        conditions.append("modified_at >= ?")
        params.append(cutoff.isoformat())

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    total = conn.execute(f"SELECT count(*) FROM sessions {where}", params).fetchone()[0]
    projects = conn.execute(
        f"SELECT count(DISTINCT project_name) FROM sessions {where}", params
    ).fetchone()[0]

    by_project_rows = conn.execute(
        f"SELECT project_name, count(*) as cnt FROM sessions {where}"
        " GROUP BY project_name ORDER BY cnt DESC",
        params,
    ).fetchall()
    by_project = {row[0]: row[1] for row in by_project_rows}

    by_date_rows = conn.execute(
        f"SELECT substr(created_at, 1, 10) as day, count(*) as cnt FROM sessions {where}"
        " GROUP BY day ORDER BY day DESC LIMIT 30",
        params,
    ).fetchall()
    by_date = {row[0]: row[1] for row in by_date_rows}

    files_rows = conn.execute(
        f"SELECT files_changed FROM sessions {where}", params
    ).fetchall()
    file_counts: dict[str, int] = {}
    for row in files_rows:
        for f in row[0].split("\n"):
            f = f.strip()
            if f:
                file_counts[f] = file_counts.get(f, 0) + 1
    top_files = dict(sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:20])

    return {
        "total_sessions": total,
        "total_projects": projects,
        "sessions_by_project": by_project,
        "sessions_by_date": by_date,
        "top_files_changed": top_files,
    }


def report_sessions(
    conn: sqlite3.Connection,
    since: str | None = None,
    until: str | None = None,
    project_path_prefix: str | None = None,
    limit: int = 100,
) -> dict:
    """Get sessions grouped by project for a date range."""
    from claude_session_index.config import since_cutoff, until_cutoff

    conditions: list[str] = []
    params: list[str | int] = []

    since_iso = None
    until_iso = None

    if since:
        cutoff = since_cutoff(since)
        since_iso = cutoff.isoformat()
        conditions.append("created_at >= ?")
        params.append(since_iso)
    if until:
        cutoff = until_cutoff(until)
        until_iso = cutoff.isoformat()
        conditions.append("created_at <= ?")
        params.append(until_iso)
    if project_path_prefix:
        conditions.append("project_path LIKE ?")
        params.append(project_path_prefix + "%")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    rows = conn.execute(
        f"""
        SELECT session_id, project_path, project_name, git_branch,
               summary, first_prompt, files_changed, commit_messages,
               created_at, modified_at, message_count
        FROM sessions
        {where}
        ORDER BY project_name ASC, created_at ASC
        """,
        params,
    ).fetchall()

    projects: dict[str, list[dict]] = {}
    for row in rows:
        entry = {
            "session_id": row[0],
            "project_path": row[1],
            "project_name": row[2],
            "git_branch": row[3],
            "summary": row[4],
            "first_prompt": row[5],
            "files_changed": [
                f for f in (row[6] or "").split("\n") if f.strip()
            ],
            "commit_messages": [
                m for m in (row[7] or "").split("\n") if m.strip()
            ],
            "created_at": row[8],
            "modified_at": row[9],
            "message_count": row[10],
        }
        proj = entry["project_name"]
        if proj not in projects:
            projects[proj] = []
        if len(projects[proj]) < limit:
            projects[proj].append(entry)

    session_count = sum(len(v) for v in projects.values())

    return {
        "since": since_iso,
        "until": until_iso,
        "project_count": len(projects),
        "session_count": session_count,
        "projects": projects,
    }


def get_file_mtime(conn: sqlite3.Connection, file_path: str) -> float | None:
    """Get the stored mtime for a file."""
    row = conn.execute(
        "SELECT mtime FROM file_mtimes WHERE file_path = ?", (file_path,)
    ).fetchone()
    return row[0] if row else None


def set_file_mtime(conn: sqlite3.Connection, file_path: str, mtime: float) -> None:
    """Store the mtime for a file."""
    conn.execute(
        "INSERT INTO file_mtimes (file_path, mtime) VALUES (?, ?) "
        "ON CONFLICT(file_path) DO UPDATE SET mtime = excluded.mtime",
        (file_path, mtime),
    )
    conn.commit()


def clear_file_mtimes(conn: sqlite3.Connection) -> None:
    """Clear all stored file mtimes (for full reindex)."""
    conn.execute("DELETE FROM file_mtimes")
    conn.commit()
