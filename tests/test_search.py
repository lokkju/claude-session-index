from __future__ import annotations

import sqlite3

from claude_session_index.db import rebuild_fts, upsert_session
from claude_session_index.extractor import SessionData
from claude_session_index.search import search_sessions


def _make_session(session_id: str, project_name: str, first_prompt: str, **kwargs) -> SessionData:
    defaults = dict(
        session_id=session_id,
        project_path=f"/tmp/{project_name}",
        project_name=project_name,
        git_branch="main",
        created_at="2026-03-15T10:00:00Z",
        modified_at="2026-03-15T11:00:00Z",
        first_prompt=first_prompt,
        user_prompts=first_prompt,
        assistant_text="I helped with this task.",
    )
    defaults.update(kwargs)
    return SessionData(**defaults)


class TestSearchSessions:
    def test_basic_search(self, db_conn: sqlite3.Connection):
        upsert_session(db_conn, _make_session("s1", "myapp", "fix the login bug"), source="transcript")
        upsert_session(db_conn, _make_session("s2", "myapp", "add dark mode theme"), source="transcript")
        rebuild_fts(db_conn)

        results = search_sessions(db_conn, "login bug")
        assert len(results) >= 1
        assert results[0]["session_id"] == "s1"

    def test_search_returns_score(self, db_conn: sqlite3.Connection):
        upsert_session(db_conn, _make_session("s1", "myapp", "fix the login bug"), source="transcript")
        rebuild_fts(db_conn)

        results = search_sessions(db_conn, "login")
        assert len(results) == 1
        assert "score" in results[0]

    def test_filter_by_project(self, db_conn: sqlite3.Connection):
        upsert_session(db_conn, _make_session("s1", "app1", "fix login"), source="transcript")
        upsert_session(db_conn, _make_session("s2", "app2", "fix login"), source="transcript")
        rebuild_fts(db_conn)

        results = search_sessions(db_conn, "login", project="app1")
        assert len(results) == 1
        assert results[0]["session_id"] == "s1"

    def test_limit(self, db_conn: sqlite3.Connection):
        for i in range(5):
            upsert_session(
                db_conn,
                _make_session(f"s{i}", "myapp", f"fix bug number {i}"),
                source="transcript",
            )
        rebuild_fts(db_conn)

        results = search_sessions(db_conn, "fix bug", limit=2)
        assert len(results) == 2

    def test_no_results(self, db_conn: sqlite3.Connection):
        upsert_session(db_conn, _make_session("s1", "myapp", "fix login"), source="transcript")
        rebuild_fts(db_conn)

        results = search_sessions(db_conn, "kubernetes deployment")
        assert len(results) == 0

    def test_searches_commit_messages(self, db_conn: sqlite3.Connection):
        upsert_session(
            db_conn,
            _make_session("s1", "myapp", "do some work", commit_messages=["refactor: extract auth middleware"]),
            source="transcript",
        )
        rebuild_fts(db_conn)

        results = search_sessions(db_conn, "auth middleware")
        assert len(results) == 1
