from __future__ import annotations

import sqlite3
from pathlib import Path

from claude_session_index.db import (
    clear_file_mtimes,
    get_file_mtime,
    get_session,
    get_stats,
    init_db,
    list_sessions,
    set_file_mtime,
    upsert_session,
)
from claude_session_index.extractor import SessionData


class TestInitDb:
    def test_creates_tables(self, db_conn: sqlite3.Connection):
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "sessions" in tables
        assert "sessions_fts" in tables
        assert "file_mtimes" in tables

    def test_sessions_columns(self, db_conn: sqlite3.Connection):
        cursor = db_conn.execute("PRAGMA table_info(sessions)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "session_id", "project_path", "project_name", "summary",
            "first_prompt", "user_prompts", "assistant_text", "files_changed",
            "commands_run", "commit_messages", "git_branch", "created_at",
            "modified_at", "message_count", "keywords", "tags", "source",
            "indexed_at",
        }
        assert expected == columns

    def test_idempotent_init(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        cursor = conn2.execute("SELECT count(*) FROM sessions")
        assert cursor.fetchone()[0] == 0
        conn2.close()


class TestUpsertSession:
    def test_insert_new(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        upsert_session(db_conn, sample_session_data, source="transcript")
        row = db_conn.execute(
            "SELECT session_id, project_name, source FROM sessions WHERE session_id = ?",
            (sample_session_data.session_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == sample_session_data.session_id
        assert row[1] == "myapp"
        assert row[2] == "transcript"

    def test_upsert_updates(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        upsert_session(db_conn, sample_session_data, source="transcript")
        updated = SessionData(
            session_id=sample_session_data.session_id,
            project_path=sample_session_data.project_path,
            project_name=sample_session_data.project_name,
            git_branch="main",
            created_at=sample_session_data.created_at,
            modified_at="2026-03-15T12:00:00.000Z",
            first_prompt=sample_session_data.first_prompt,
            user_prompts=sample_session_data.user_prompts,
            assistant_text=sample_session_data.assistant_text,
            message_count=10,
        )
        upsert_session(db_conn, updated, source="transcript")
        count = db_conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        assert count == 1
        row = db_conn.execute(
            "SELECT message_count, git_branch FROM sessions WHERE session_id = ?",
            (sample_session_data.session_id,),
        ).fetchone()
        assert row[0] == 10
        assert row[1] == "main"

    def test_lists_as_newline_separated(
        self, db_conn: sqlite3.Connection, sample_session_data: SessionData
    ):
        upsert_session(db_conn, sample_session_data, source="transcript")
        row = db_conn.execute(
            "SELECT files_changed, commit_messages FROM sessions WHERE session_id = ?",
            (sample_session_data.session_id,),
        ).fetchone()
        assert "/home/user/projects/myapp/hello.py" in row[0]
        assert "feat: add greeting function" in row[1]


class TestFileMtimes:
    def test_get_set(self, db_conn: sqlite3.Connection):
        assert get_file_mtime(db_conn, "/tmp/test.jsonl") is None
        set_file_mtime(db_conn, "/tmp/test.jsonl", 1234567890.0)
        assert get_file_mtime(db_conn, "/tmp/test.jsonl") == 1234567890.0

    def test_update(self, db_conn: sqlite3.Connection):
        set_file_mtime(db_conn, "/tmp/test.jsonl", 1000.0)
        set_file_mtime(db_conn, "/tmp/test.jsonl", 2000.0)
        assert get_file_mtime(db_conn, "/tmp/test.jsonl") == 2000.0

    def test_clear(self, db_conn: sqlite3.Connection):
        set_file_mtime(db_conn, "/tmp/a.jsonl", 1000.0)
        set_file_mtime(db_conn, "/tmp/b.jsonl", 2000.0)
        clear_file_mtimes(db_conn)
        assert get_file_mtime(db_conn, "/tmp/a.jsonl") is None
        assert get_file_mtime(db_conn, "/tmp/b.jsonl") is None


class TestGetSession:
    def test_existing(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        upsert_session(db_conn, sample_session_data, source="transcript")
        result = get_session(db_conn, sample_session_data.session_id)
        assert result is not None
        assert result["session_id"] == sample_session_data.session_id
        assert result["project_name"] == "myapp"

    def test_missing(self, db_conn: sqlite3.Connection):
        assert get_session(db_conn, "nonexistent") is None


class TestListSessions:
    def test_list_all(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        upsert_session(db_conn, sample_session_data, source="transcript")
        results = list_sessions(db_conn)
        assert len(results) == 1
        assert results[0]["session_id"] == sample_session_data.session_id

    def test_filter_by_project(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        upsert_session(db_conn, sample_session_data, source="transcript")
        assert len(list_sessions(db_conn, project="myapp")) == 1
        assert len(list_sessions(db_conn, project="other")) == 0

    def test_filter_by_branch(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        upsert_session(db_conn, sample_session_data, source="transcript")
        assert len(list_sessions(db_conn, branch="feat/greetings")) == 1
        assert len(list_sessions(db_conn, branch="main")) == 0

    def test_limit(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        for i in range(5):
            sd = SessionData(
                session_id=f"session-{i}",
                project_path="/tmp/proj",
                project_name="proj",
                git_branch="main",
                created_at=f"2026-03-{15+i:02d}T10:00:00Z",
                modified_at=f"2026-03-{15+i:02d}T11:00:00Z",
                first_prompt=f"prompt {i}",
                user_prompts=f"prompt {i}",
                assistant_text=f"response {i}",
            )
            upsert_session(db_conn, sd, source="transcript")
        assert len(list_sessions(db_conn, limit=3)) == 3


class TestGetStats:
    def test_stats(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
        upsert_session(db_conn, sample_session_data, source="transcript")
        stats = get_stats(db_conn)
        assert stats["total_sessions"] == 1
        assert stats["total_projects"] == 1
        assert "myapp" in stats["sessions_by_project"]
