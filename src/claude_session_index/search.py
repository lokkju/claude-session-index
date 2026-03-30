from __future__ import annotations

import sqlite3


def search_sessions(
    conn: sqlite3.Connection,
    query: str,
    project: str | None = None,
    since: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Full-text search across indexed sessions using FTS5 with BM25 ranking."""
    conditions: list[str] = []
    params: list[str | int] = []

    # FTS match
    conditions.append("sessions_fts MATCH ?")
    params.append(query)

    fts_where = " AND ".join(conditions)

    # Build optional session-table filters
    session_filters: list[str] = []
    filter_params: list[str | int] = []

    if project:
        session_filters.append("s.project_name = ?")
        filter_params.append(project)
    if since:
        from claude_session_index.config import since_cutoff

        cutoff = since_cutoff(since)
        session_filters.append("s.modified_at >= ?")
        filter_params.append(cutoff.isoformat())

    session_where = " AND ".join(session_filters)
    if session_where:
        session_where = "AND " + session_where

    all_params = params + filter_params + [limit]

    rows = conn.execute(
        f"""
        SELECT
            s.session_id, s.project_path, s.project_name, s.git_branch,
            s.summary, s.first_prompt, s.commit_messages,
            s.created_at, s.modified_at, s.message_count,
            bm25(sessions_fts) as score
        FROM sessions_fts
        JOIN sessions s ON s.session_id = sessions_fts.session_id
        WHERE {fts_where} {session_where}
        ORDER BY score
        LIMIT ?
        """,
        all_params,
    ).fetchall()

    return [
        {
            "session_id": row[0],
            "project_path": row[1],
            "project_name": row[2],
            "git_branch": row[3],
            "summary": row[4],
            "first_prompt": row[5],
            "commit_messages": row[6],
            "created_at": row[7],
            "modified_at": row[8],
            "message_count": row[9],
            "score": row[10],
        }
        for row in rows
    ]
