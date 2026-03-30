from __future__ import annotations

from pathlib import Path

import pytest

from claude_session_index.extractor import SessionData, extract_session


class TestSessionData:
    def test_dataclass_fields(self):
        sd = SessionData(
            session_id="test-id",
            project_path="/tmp/proj",
            project_name="proj",
            git_branch="main",
            created_at="2026-01-01T00:00:00Z",
            modified_at="2026-01-01T01:00:00Z",
            first_prompt="hello",
            user_prompts="hello",
            assistant_text="hi there",
        )
        assert sd.session_id == "test-id"
        assert sd.files_changed == []
        assert sd.commands_run == []
        assert sd.commit_messages == []
        assert sd.message_count == 0


class TestExtractSession:
    def test_extracts_metadata(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        assert result.session_id == "deadbeef-1234-5678-9abc-def012345678"
        assert result.project_path == "/home/user/projects/myapp"
        assert result.project_name == "myapp"
        assert result.git_branch == "feat/greetings"

    def test_extracts_timestamps(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        assert result.created_at == "2026-03-15T10:00:00.000Z"
        assert result.modified_at == "2026-03-15T10:04:00.000Z"

    def test_extracts_user_prompts(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        assert "Add a greeting function" in result.first_prompt
        assert "Add a greeting function" in result.user_prompts
        assert "Now commit this" in result.user_prompts
        # "thanks" is <10 chars, should be skipped
        assert "thanks" not in result.user_prompts

    def test_extracts_assistant_text(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        assert "greeting function" in result.assistant_text
        assert "commit the changes" in result.assistant_text
        # Thinking blocks should be excluded
        assert "Let me create" not in result.assistant_text

    def test_extracts_files_changed(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        assert "/home/user/projects/myapp/hello.py" in result.files_changed

    def test_extracts_commands(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        assert "uv run pytest tests/ -v" in result.commands_run

    def test_extracts_commit_messages(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        assert "feat: add greeting function" in result.commit_messages

    def test_message_count(self, sample_session_path: Path):
        result = extract_session(sample_session_path)
        assert result is not None
        # 3 user messages + 2 assistant messages = 5
        assert result.message_count == 5

    def test_returns_none_for_empty_file(self, tmp_path: Path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert extract_session(empty) is None

    def test_skips_oversized_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        big = tmp_path / "big.jsonl"
        big.write_text("x")
        monkeypatch.setattr("claude_session_index.config.MAX_FILE_SIZE", 0)
        assert extract_session(big) is None
