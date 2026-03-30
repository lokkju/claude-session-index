from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from claude_session_index.db import get_session, init_db, rebuild_fts
from claude_session_index.indexer import (
    index_all,
    index_history,
    index_sessions_index,
    index_transcripts,
)


class TestIndexSessionsIndex:
    def test_indexes_entries(self, db_conn: sqlite3.Connection, sample_index_path: Path, tmp_path: Path):
        # Create a fake projects dir with the sessions-index.json
        proj_dir = tmp_path / "projects" / "-home-user-projects-myapp"
        proj_dir.mkdir(parents=True)
        import shutil
        shutil.copy(sample_index_path, proj_dir / "sessions-index.json")

        count = index_sessions_index(db_conn, tmp_path / "projects")
        assert count == 2

        s1 = get_session(db_conn, "idx-session-aaaa-bbbb-cccc-ddddeeee0001")
        assert s1 is not None
        assert s1["project_name"] == "myapp"
        assert s1["first_prompt"] == "Add a greeting function to hello.py"
        assert s1["summary"] == "Added greeting function with tests"
        assert s1["source"] == "sessions-index"


class TestIndexTranscripts:
    def test_indexes_jsonl(self, db_conn: sqlite3.Connection, sample_session_path: Path, tmp_path: Path):
        proj_dir = tmp_path / "projects" / "-home-user-projects-myapp"
        proj_dir.mkdir(parents=True)
        import shutil
        shutil.copy(sample_session_path, proj_dir / "deadbeef-1234-5678-9abc-def012345678.jsonl")

        count = index_transcripts(db_conn, tmp_path / "projects")
        assert count == 1

        session = get_session(db_conn, "deadbeef-1234-5678-9abc-def012345678")
        assert session is not None
        assert "greeting function" in session["first_prompt"]

    def test_skips_non_uuid_files(self, db_conn: sqlite3.Connection, tmp_path: Path):
        proj_dir = tmp_path / "projects" / "-home-user-projects-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "sessions-index.jsonl").write_text("{}")
        (proj_dir / "not-a-uuid.jsonl").write_text("{}")

        count = index_transcripts(db_conn, tmp_path / "projects")
        assert count == 0

    def test_skips_subagents(self, db_conn: sqlite3.Connection, sample_session_path: Path, tmp_path: Path):
        proj_dir = tmp_path / "projects" / "-home-user-projects-myapp"
        subagent_dir = proj_dir / "deadbeef-1234-5678-9abc-def012345678" / "subagents"
        subagent_dir.mkdir(parents=True)
        import shutil
        shutil.copy(sample_session_path, subagent_dir / "aaaabbbb-cccc-dddd-eeee-ffffffffffff.jsonl")

        count = index_transcripts(db_conn, tmp_path / "projects")
        assert count == 0

    def test_incremental_skips_unchanged(self, db_conn: sqlite3.Connection, sample_session_path: Path, tmp_path: Path):
        proj_dir = tmp_path / "projects" / "-home-user-projects-myapp"
        proj_dir.mkdir(parents=True)
        import shutil
        dest = proj_dir / "deadbeef-1234-5678-9abc-def012345678.jsonl"
        shutil.copy(sample_session_path, dest)

        # First index
        count1 = index_transcripts(db_conn, tmp_path / "projects")
        assert count1 == 1
        # Second index — same file, same mtime
        count2 = index_transcripts(db_conn, tmp_path / "projects")
        assert count2 == 0


class TestIndexHistory:
    def test_indexes_history(self, db_conn: sqlite3.Connection, tmp_path: Path):
        history_file = tmp_path / "history.jsonl"
        entries = [
            {"display": "fix the auth bug in login.py", "pastedContents": {}, "timestamp": 1710500000000, "project": "/home/user/projects/myapp"},
            {"display": "add dark mode", "pastedContents": {}, "timestamp": 1710600000000, "project": "/home/user/projects/webapp"},
        ]
        history_file.write_text("\n".join(json.dumps(e) for e in entries))

        count = index_history(db_conn, history_file)
        assert count == 2

    def test_skips_already_indexed(self, db_conn: sqlite3.Connection, tmp_path: Path, sample_session_path: Path):
        """History should not overwrite sessions already indexed from transcripts."""
        # First, index a transcript
        proj_dir = tmp_path / "projects" / "-home-user-projects-myapp"
        proj_dir.mkdir(parents=True)
        import shutil
        dest = proj_dir / "deadbeef-1234-5678-9abc-def012345678.jsonl"
        shutil.copy(sample_session_path, dest)
        index_transcripts(db_conn, tmp_path / "projects")

        # Now create history that references the same session
        history_file = tmp_path / "history.jsonl"
        entries = [
            {"display": "some other prompt", "pastedContents": {}, "timestamp": 1710500000000, "project": "/home/user/projects/myapp", "sessionId": "deadbeef-1234-5678-9abc-def012345678"},
        ]
        history_file.write_text("\n".join(json.dumps(e) for e in entries))

        count = index_history(db_conn, history_file)
        assert count == 0

        # Original data should be preserved
        session = get_session(db_conn, "deadbeef-1234-5678-9abc-def012345678")
        assert "greeting function" in session["first_prompt"]


class TestIndexAll:
    def test_full_pipeline(self, tmp_path: Path, sample_session_path: Path, sample_index_path: Path):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)

        # Set up fake project dir
        proj_dir = tmp_path / "projects" / "-home-user-projects-myapp"
        proj_dir.mkdir(parents=True)
        import shutil
        shutil.copy(sample_index_path, proj_dir / "sessions-index.json")
        shutil.copy(sample_session_path, proj_dir / "deadbeef-1234-5678-9abc-def012345678.jsonl")

        # Set up fake history
        history_file = tmp_path / "history.jsonl"
        history_file.write_text(json.dumps({
            "display": "unrelated prompt",
            "pastedContents": {},
            "timestamp": 1710700000000,
            "project": "/home/user/projects/other",
        }))

        stats = index_all(
            conn,
            projects_dir=tmp_path / "projects",
            history_file=history_file,
            full=False,
        )

        assert stats["phase1_count"] == 2  # from sessions-index.json
        assert stats["phase2_count"] == 1  # from transcript
        assert stats["phase3_count"] == 1  # from history
        assert stats["total"] == 4  # unique sessions total

        conn.close()
