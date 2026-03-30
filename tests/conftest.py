from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from claude_session_index.db import init_db
from claude_session_index.extractor import SessionData

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_session_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample_session.jsonl"


@pytest.fixture
def sample_index_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample_sessions_index.json"


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def sample_session_data() -> SessionData:
    return SessionData(
        session_id="deadbeef-1234-5678-9abc-def012345678",
        project_path="/home/user/projects/myapp",
        project_name="myapp",
        git_branch="feat/greetings",
        created_at="2026-03-15T10:00:00.000Z",
        modified_at="2026-03-15T10:04:00.000Z",
        first_prompt="Add a greeting function to hello.py",
        user_prompts="Add a greeting function to hello.py\nNow commit this with a nice message",
        assistant_text="I'll create a greeting function for you.\nI'll commit the changes.",
        files_changed=["/home/user/projects/myapp/hello.py"],
        commands_run=["uv run pytest tests/ -v", 'git add hello.py && git commit -m "feat: add greeting function"'],
        commit_messages=["feat: add greeting function"],
        message_count=4,
    )
