# claude-session-index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python tool that indexes Claude Code session JSONL files into a searchable SQLite FTS5 database and exposes the index as an MCP server.

**Architecture:** Single Python package with CLI entry point. Three-phase indexing pipeline (sessions-index.json → transcript JSONL → history.jsonl) feeds a SQLite FTS5 database. A FastMCP stdio server exposes search/browse tools. An optional Claude Code plugin auto-indexes on session end.

**Tech Stack:** Python 3.11+, hatchling (build), typer (CLI), fastmcp (MCP server), SQLite FTS5 (stdlib), pytest (tests), ruff (lint), pyright (types)

---

## File Structure

```
claude-session-index/
├── pyproject.toml                          # Build config, deps, entry point, tool config
├── LICENSE                                 # Polyform Shield 1.0.0
├── src/
│   └── claude_session_index/
│       ├── __init__.py                     # Package version
│       ├── config.py                       # Paths, constants, duration parsing
│       ├── extractor.py                    # SessionData dataclass + JSONL parser
│       ├── db.py                           # SQLite schema, upsert, file_mtimes, queries
│       ├── search.py                       # FTS5 query builder, BM25 ranking
│       ├── indexer.py                      # 3-phase pipeline, incremental logic
│       ├── server.py                       # FastMCP stdio server with 5 tools
│       └── cli.py                          # Typer CLI (index, search, stats, serve, timer)
├── plugin/
│   ├── plugin.json                         # Claude Code plugin identity
│   └── hooks/
│       ├── hooks.json                      # Stop hook definition
│       └── session-end.sh                  # Runs index --since 1d
├── systemd/
│   ├── claude-session-index.service        # Oneshot unit
│   └── claude-session-index.timer          # 15-minute timer
├── tests/
│   ├── conftest.py                         # Shared fixtures (tmp db, sample data)
│   ├── fixtures/
│   │   ├── sample_session.jsonl            # Realistic session transcript
│   │   └── sample_sessions_index.json      # sessions-index.json format
│   ├── test_config.py                      # Duration parsing tests
│   ├── test_extractor.py                   # JSONL extraction tests
│   ├── test_db.py                          # Schema, upsert, queries tests
│   ├── test_search.py                      # FTS search tests
│   └── test_indexer.py                     # Pipeline integration tests
└── docs/
    └── superpowers/
        ├── specs/
        │   └── 2026-03-30-session-index-design.md
        └── plans/
            └── 2026-03-30-session-index.md
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `LICENSE`
- Create: `src/claude_session_index/__init__.py`
- Create: `src/claude_session_index/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "claude-session-index"
dynamic = ["version"]
description = "Index Claude Code sessions into searchable SQLite FTS5"
requires-python = ">=3.11"
license = "PolyForm-Shield-1.0.0"
dependencies = [
    "typer>=0.9",
    "fastmcp>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
    "pyright>=1.1",
]

[project.scripts]
claude-session-index = "claude_session_index.cli:app"

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.targets.wheel]
packages = ["src/claude_session_index"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pyright]
typeCheckingMode = "basic"
pythonVersion = "3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create LICENSE**

Download the Polyform Shield 1.0.0 text:

```
Copyright (c) 2026 lokkju

This software is licensed under the PolyForm Shield License 1.0.0.
A copy of the license is available at https://polyformproject.org/licenses/shield/1.0.0
```

- [ ] **Step 3: Create `src/claude_session_index/__init__.py`**

```python
try:
    from importlib.metadata import version

    __version__ = version("claude-session-index")
except Exception:
    __version__ = "0.0.0"
```

- [ ] **Step 4: Create `src/claude_session_index/config.py`**

```python
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
    dt = datetime.fromisoformat(since)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
```

- [ ] **Step 5: Write tests for config.py**

Create `tests/test_config.py`:

```python
from datetime import timedelta

import pytest

from claude_session_index.config import parse_duration, since_cutoff


class TestParseDuration:
    def test_days(self):
        assert parse_duration("7d") == timedelta(days=7)

    def test_hours(self):
        assert parse_duration("24h") == timedelta(hours=24)

    def test_minutes(self):
        assert parse_duration("30m") == timedelta(minutes=30)

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")

    def test_no_unit_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("7")


class TestSinceCutoff:
    def test_duration_string(self):
        cutoff = since_cutoff("1d")
        # Should be roughly 24 hours ago
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        diff = now - cutoff
        assert 86390 < diff.total_seconds() < 86410

    def test_iso_date(self):
        cutoff = since_cutoff("2026-03-01")
        assert cutoff.year == 2026
        assert cutoff.month == 3
        assert cutoff.day == 1
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_config.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add pyproject.toml LICENSE src/ tests/test_config.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: project scaffolding with config, duration parsing"
```

---

### Task 2: Test Fixtures

**Files:**
- Create: `tests/fixtures/sample_session.jsonl`
- Create: `tests/fixtures/sample_sessions_index.json`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create sample session JSONL fixture**

Create `tests/fixtures/sample_session.jsonl`. Each line is a JSON object. This fixture contains a realistic mini-session with user messages, assistant responses (including tool_use blocks), and a file-history-snapshot:

```jsonl
{"parentUuid":"00000000-0000-0000-0000-000000000000","isSidechain":false,"type":"user","message":{"role":"user","content":"Add a greeting function to hello.py"},"uuid":"aaaa1111-0000-0000-0000-000000000001","timestamp":"2026-03-15T10:00:00.000Z","cwd":"/home/user/projects/myapp","sessionId":"deadbeef-1234-5678-9abc-def012345678","version":"2.1.87","gitBranch":"feat/greetings"}
{"parentUuid":"aaaa1111-0000-0000-0000-000000000001","isSidechain":false,"type":"assistant","message":{"model":"claude-opus-4-6","id":"msg_001","type":"message","role":"assistant","content":[{"type":"thinking","thinking":"Let me create a greeting function.","signature":"sig"},{"type":"text","text":"I'll create a greeting function for you."},{"type":"tool_use","id":"tu_001","name":"Read","input":{"file_path":"/home/user/projects/myapp/hello.py"}},{"type":"tool_use","id":"tu_002","name":"Edit","input":{"file_path":"/home/user/projects/myapp/hello.py","old_string":"pass","new_string":"return f'Hello, {name}!'"}},{"type":"tool_use","id":"tu_003","name":"Bash","input":{"command":"uv run pytest tests/ -v"}}],"stop_reason":"end_turn","usage":{"input_tokens":100,"output_tokens":50}},"type":"assistant","uuid":"aaaa1111-0000-0000-0000-000000000002","timestamp":"2026-03-15T10:01:00.000Z","cwd":"/home/user/projects/myapp","sessionId":"deadbeef-1234-5678-9abc-def012345678","version":"2.1.87","gitBranch":"feat/greetings"}
{"type":"file-history-snapshot","messageId":"aaaa1111-0000-0000-0000-000000000001","snapshot":{"messageId":"aaaa1111-0000-0000-0000-000000000001","trackedFileBackups":{"/home/user/projects/myapp/hello.py":"backup"},"timestamp":"2026-03-15T10:00:00.500Z"},"isSnapshotUpdate":false}
{"parentUuid":"aaaa1111-0000-0000-0000-000000000002","isSidechain":false,"type":"user","message":{"role":"user","content":"Now commit this with a nice message"},"uuid":"aaaa1111-0000-0000-0000-000000000003","timestamp":"2026-03-15T10:02:00.000Z","cwd":"/home/user/projects/myapp","sessionId":"deadbeef-1234-5678-9abc-def012345678","version":"2.1.87","gitBranch":"feat/greetings"}
{"parentUuid":"aaaa1111-0000-0000-0000-000000000003","isSidechain":false,"type":"assistant","message":{"model":"claude-opus-4-6","id":"msg_002","type":"message","role":"assistant","content":[{"type":"text","text":"I'll commit the changes."},{"type":"tool_use","id":"tu_004","name":"Bash","input":{"command":"git add hello.py && git commit -m \"feat: add greeting function\""}}],"stop_reason":"end_turn","usage":{"input_tokens":100,"output_tokens":50}},"type":"assistant","uuid":"aaaa1111-0000-0000-0000-000000000004","timestamp":"2026-03-15T10:03:00.000Z","cwd":"/home/user/projects/myapp","sessionId":"deadbeef-1234-5678-9abc-def012345678","version":"2.1.87","gitBranch":"feat/greetings"}
{"parentUuid":"aaaa1111-0000-0000-0000-000000000004","isSidechain":false,"type":"user","message":{"role":"user","content":"thanks"},"uuid":"aaaa1111-0000-0000-0000-000000000005","timestamp":"2026-03-15T10:04:00.000Z","cwd":"/home/user/projects/myapp","sessionId":"deadbeef-1234-5678-9abc-def012345678","version":"2.1.87","gitBranch":"feat/greetings"}
```

- [ ] **Step 2: Create sample sessions-index.json fixture**

Create `tests/fixtures/sample_sessions_index.json`:

```json
{
  "version": 1,
  "entries": [
    {
      "sessionId": "idx-session-aaaa-bbbb-cccc-ddddeeee0001",
      "fullPath": "/home/user/.claude/projects/-home-user-projects-myapp/idx-session-aaaa-bbbb-cccc-ddddeeee0001.jsonl",
      "fileMtime": 1710500000000,
      "firstPrompt": "Add a greeting function to hello.py",
      "summary": "Added greeting function with tests",
      "messageCount": 12,
      "created": "2026-03-15T10:00:00.000Z",
      "modified": "2026-03-15T11:00:00.000Z",
      "gitBranch": "feat/greetings",
      "projectPath": "/home/user/projects/myapp",
      "isSidechain": false
    },
    {
      "sessionId": "idx-session-aaaa-bbbb-cccc-ddddeeee0002",
      "fullPath": "/home/user/.claude/projects/-home-user-projects-myapp/idx-session-aaaa-bbbb-cccc-ddddeeee0002.jsonl",
      "fileMtime": 1710600000000,
      "firstPrompt": "Fix the login bug in auth.py",
      "summary": "Fixed authentication timeout issue",
      "messageCount": 8,
      "created": "2026-03-16T09:00:00.000Z",
      "modified": "2026-03-16T10:30:00.000Z",
      "gitBranch": "fix/auth-timeout",
      "projectPath": "/home/user/projects/myapp",
      "isSidechain": false
    }
  ],
  "originalPath": "/home/user/projects/myapp"
}
```

- [ ] **Step 3: Create conftest.py with shared fixtures**

Create `tests/conftest.py`:

```python
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
```

- [ ] **Step 4: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add tests/
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "test: add fixtures and conftest for session data"
```

---

### Task 3: SessionData Dataclass and Extractor

**Files:**
- Create: `src/claude_session_index/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: Write failing tests for extractor**

Create `tests/test_extractor.py`:

```python
from __future__ import annotations

from pathlib import Path

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
        # But "thanks" still counts as a message even if its text is skipped
        assert result.message_count == 5

    def test_returns_none_for_empty_file(self, tmp_path: Path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert extract_session(empty) is None

    def test_skips_oversized_files(self, tmp_path: Path):
        big = tmp_path / "big.jsonl"
        big.write_text("x")
        # Monkey-patch stat to simulate large file
        import claude_session_index.config as cfg
        original = cfg.MAX_FILE_SIZE
        cfg.MAX_FILE_SIZE = 0
        try:
            assert extract_session(big) is None
        finally:
            cfg.MAX_FILE_SIZE = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_extractor.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_session'`

- [ ] **Step 3: Implement extractor.py**

Create `src/claude_session_index/extractor.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from claude_session_index.config import (
    ASSISTANT_BLOCK_CAP,
    ASSISTANT_TEXT_CAP,
    COMMAND_MAX_LEN,
    MAX_FILE_SIZE,
    MAX_LINES_PER_SESSION,
    MIN_PROMPT_LEN,
    USER_PROMPTS_CAP,
)


@dataclass
class SessionData:
    session_id: str
    project_path: str
    project_name: str
    git_branch: str
    created_at: str
    modified_at: str
    first_prompt: str
    user_prompts: str
    assistant_text: str
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    commit_messages: list[str] = field(default_factory=list)
    message_count: int = 0


_COMMIT_INLINE_RE = re.compile(r'git\s+commit\s+.*?-m\s+["\'](.+?)["\']', re.DOTALL)
_COMMIT_HEREDOC_RE = re.compile(r"cat\s+<<\s*'?EOF'?\n(.+?)\nEOF", re.DOTALL)


def extract_session(file_path: Path) -> SessionData | None:
    """Extract session data from a JSONL transcript file."""
    if file_path.stat().st_size > MAX_FILE_SIZE:
        return None

    session_id = ""
    project_path = ""
    project_name = ""
    git_branch = ""
    created_at = ""
    modified_at = ""
    first_prompt = ""
    user_prompts_parts: list[str] = []
    user_prompts_len = 0
    assistant_parts: list[str] = []
    assistant_len = 0
    files_changed: set[str] = set()
    commands_run: list[str] = []
    commit_messages: list[str] = []
    message_count = 0

    with open(file_path) as f:
        for line_num, line in enumerate(f, 1):
            if line_num > MAX_LINES_PER_SESSION:
                break

            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")

            # File history snapshots — extract tracked file paths
            if entry_type == "file-history-snapshot":
                snapshot = entry.get("snapshot", {})
                for fp in snapshot.get("trackedFileBackups", {}).keys():
                    files_changed.add(fp)
                continue

            # Skip non-message types (system, etc.)
            if entry_type not in ("user", "assistant"):
                # Still grab metadata if present
                if not session_id and entry.get("sessionId"):
                    session_id = entry["sessionId"]
                if not project_path and entry.get("cwd"):
                    project_path = entry["cwd"]
                    project_name = Path(project_path).name
                if not git_branch and entry.get("gitBranch"):
                    git_branch = entry["gitBranch"]
                if not created_at and entry.get("timestamp"):
                    created_at = entry["timestamp"]
                if entry.get("timestamp"):
                    modified_at = entry["timestamp"]
                continue

            # Extract metadata from message entries
            if not session_id and entry.get("sessionId"):
                session_id = entry["sessionId"]
            if not project_path and entry.get("cwd"):
                project_path = entry["cwd"]
                project_name = Path(project_path).name
            if not git_branch and entry.get("gitBranch"):
                git_branch = entry["gitBranch"]
            if not created_at and entry.get("timestamp"):
                created_at = entry["timestamp"]
            if entry.get("timestamp"):
                modified_at = entry["timestamp"]

            message_count += 1

            if entry_type == "user":
                msg = entry.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) >= MIN_PROMPT_LEN:
                    if not content.startswith("<"):
                        if not first_prompt:
                            first_prompt = content[:500]
                        if user_prompts_len < USER_PROMPTS_CAP:
                            user_prompts_parts.append(content)
                            user_prompts_len += len(content)

            elif entry_type == "assistant":
                msg = entry.get("message", {})
                content_blocks = msg.get("content", [])
                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type", "")

                        if block_type == "text":
                            text = block.get("text", "")
                            if text and assistant_len < ASSISTANT_TEXT_CAP:
                                chunk = text[:ASSISTANT_BLOCK_CAP]
                                assistant_parts.append(chunk)
                                assistant_len += len(chunk)

                        elif block_type == "tool_use":
                            _extract_tool_use(block, files_changed, commands_run, commit_messages)

    if not session_id:
        session_id = file_path.stem

    if not created_at:
        return None

    return SessionData(
        session_id=session_id,
        project_path=project_path,
        project_name=project_name,
        git_branch=git_branch,
        created_at=created_at,
        modified_at=modified_at or created_at,
        first_prompt=first_prompt,
        user_prompts="\n".join(user_prompts_parts)[:USER_PROMPTS_CAP],
        assistant_text="\n".join(assistant_parts)[:ASSISTANT_TEXT_CAP],
        files_changed=sorted(files_changed),
        commands_run=commands_run,
        commit_messages=commit_messages,
        message_count=message_count,
    )


def _extract_tool_use(
    block: dict,
    files_changed: set[str],
    commands_run: list[str],
    commit_messages: list[str],
) -> None:
    """Extract files, commands, and commit messages from a tool_use block."""
    tool_name = block.get("name", "")
    tool_input = block.get("input", {})

    if tool_name in ("Read", "Write", "Edit"):
        fp = tool_input.get("file_path", "")
        if fp:
            files_changed.add(fp)
    elif tool_name == "Glob":
        path = tool_input.get("path", "")
        if path:
            files_changed.add(path)
    elif tool_name == "Grep":
        path = tool_input.get("path", "")
        if path:
            files_changed.add(path)
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd and len(cmd) <= COMMAND_MAX_LEN:
            commands_run.append(cmd)
            _extract_commit_message(cmd, commit_messages)


def _extract_commit_message(cmd: str, messages: list[str]) -> None:
    """Extract commit message from a git commit command string."""
    if "git commit" not in cmd:
        return
    m = _COMMIT_HEREDOC_RE.search(cmd)
    if m:
        messages.append(m.group(1).strip())
        return
    m = _COMMIT_INLINE_RE.search(cmd)
    if m:
        messages.append(m.group(1).strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_extractor.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/extractor.py tests/test_extractor.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: JSONL extractor with SessionData dataclass"
```

---

### Task 4: Database Schema and Upsert

**Files:**
- Create: `src/claude_session_index/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for db schema and upsert**

Create `tests/test_db.py`:

```python
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
    rebuild_fts,
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
        # Update and re-upsert
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

    def test_lists_as_newline_separated(self, db_conn: sqlite3.Connection, sample_session_data: SessionData):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'init_db'`

- [ ] **Step 3: Implement db.py**

Create `src/claude_session_index/db.py`:

```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
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
    now = datetime.now(timezone.utc).isoformat()
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
            first_prompt = CASE WHEN excluded.first_prompt != '' THEN excluded.first_prompt ELSE sessions.first_prompt END,
            user_prompts = CASE WHEN excluded.user_prompts != '' THEN excluded.user_prompts ELSE sessions.user_prompts END,
            assistant_text = CASE WHEN excluded.assistant_text != '' THEN excluded.assistant_text ELSE sessions.assistant_text END,
            files_changed = CASE WHEN excluded.files_changed != '' THEN excluded.files_changed ELSE sessions.files_changed END,
            commands_run = CASE WHEN excluded.commands_run != '' THEN excluded.commands_run ELSE sessions.commands_run END,
            commit_messages = CASE WHEN excluded.commit_messages != '' THEN excluded.commit_messages ELSE sessions.commit_messages END,
            git_branch = CASE WHEN excluded.git_branch != '' THEN excluded.git_branch ELSE sessions.git_branch END,
            modified_at = excluded.modified_at,
            message_count = CASE WHEN excluded.message_count > sessions.message_count THEN excluded.message_count ELSE sessions.message_count END,
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
        f"SELECT project_name, count(*) as cnt FROM sessions {where} GROUP BY project_name ORDER BY cnt DESC",
        params,
    ).fetchall()
    by_project = {row[0]: row[1] for row in by_project_rows}

    by_date_rows = conn.execute(
        f"SELECT substr(created_at, 1, 10) as day, count(*) as cnt FROM sessions {where} GROUP BY day ORDER BY day DESC LIMIT 30",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_db.py -v`
Expected: All 15 tests PASS

- [ ] **Step 5: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/db.py tests/test_db.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: database schema, upsert, queries, and file_mtimes tracking"
```

---

### Task 5: FTS Search

**Files:**
- Create: `src/claude_session_index/search.py`
- Create: `tests/test_search.py`

- [ ] **Step 1: Write failing tests for search**

Create `tests/test_search.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_search.py -v`
Expected: FAIL — `ImportError: cannot import name 'search_sessions'`

- [ ] **Step 3: Implement search.py**

Create `src/claude_session_index/search.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_search.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/search.py tests/test_search.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: FTS5 search with BM25 ranking and project/date filters"
```

---

### Task 6: Indexer Pipeline

**Files:**
- Create: `src/claude_session_index/indexer.py`
- Create: `tests/test_indexer.py`

- [ ] **Step 1: Write failing tests for indexer**

Create `tests/test_indexer.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_indexer.py -v`
Expected: FAIL — `ImportError: cannot import name 'index_all'`

- [ ] **Step 3: Implement indexer.py**

Create `src/claude_session_index/indexer.py`:

```python
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

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
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
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

            # Store summary separately since SessionData doesn't have it
            upsert_session(conn, session, source="sessions-index")
            # Update summary directly
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
                mod_dt = datetime.fromtimestamp(current_mtime, tz=timezone.utc)
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
            ts = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            created_at = ts.isoformat()

            if since_cutoff and ts < since_cutoff:
                continue

            # Generate a stable session_id from timestamp + project if not provided
            if not session_id:
                import hashlib

                key = f"{timestamp_ms}:{project}:{display[:100]}"
                session_id = hashlib.sha256(key.encode()).hexdigest()[:36]
                # Format as UUID-like
                session_id = f"{session_id[:8]}-{session_id[8:12]}-{session_id[12:16]}-{session_id[16:20]}-{session_id[20:32]}"

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_indexer.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/indexer.py tests/test_indexer.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: 3-phase indexing pipeline with incremental support"
```

---

### Task 7: MCP Server

**Files:**
- Create: `src/claude_session_index/server.py`

- [ ] **Step 1: Implement server.py**

Create `src/claude_session_index/server.py`:

```python
from __future__ import annotations

import json

from fastmcp import FastMCP

from claude_session_index.config import DB_PATH
from claude_session_index.db import get_session, get_stats, init_db, list_sessions
from claude_session_index.search import search_sessions


def create_server() -> FastMCP:
    """Create the MCP server with all tools registered."""
    mcp = FastMCP(
        "claude-session-index",
        instructions="Search and browse indexed Claude Code sessions.",
    )

    @mcp.tool()
    def search(
        query: str,
        project: str | None = None,
        since: str | None = None,
        limit: int = 10,
    ) -> str:
        """Search indexed sessions using full-text search with BM25 ranking.

        Args:
            query: Search query string (FTS5 syntax supported)
            project: Filter by project name
            since: Filter by date — duration like '7d' or ISO date like '2026-03-01'
            limit: Maximum results to return (default 10)
        """
        conn = init_db(DB_PATH)
        try:
            results = search_sessions(conn, query, project=project, since=since, limit=limit)
            return json.dumps(results, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def get_session_detail(session_id: str) -> str:
        """Get full details for a specific session.

        Args:
            session_id: The session UUID
        """
        conn = init_db(DB_PATH)
        try:
            result = get_session(conn, session_id)
            if result is None:
                return json.dumps({"error": f"Session {session_id} not found"})
            return json.dumps(result, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def list_indexed_sessions(
        project: str | None = None,
        since: str | None = None,
        branch: str | None = None,
        limit: int = 20,
        order_by: str = "modified_at",
    ) -> str:
        """List sessions with optional filters, no search query needed.

        Args:
            project: Filter by project name
            since: Filter by date — duration like '7d' or ISO date
            branch: Filter by git branch name
            limit: Maximum results (default 20)
            order_by: Sort field — 'modified_at', 'created_at', or 'message_count'
        """
        conn = init_db(DB_PATH)
        try:
            results = list_sessions(
                conn, project=project, since=since, branch=branch, limit=limit, order_by=order_by
            )
            return json.dumps(results, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def session_stats(since: str | None = None) -> str:
        """Get index statistics — total sessions, projects, activity by date.

        Args:
            since: Filter stats to sessions modified within this window
        """
        conn = init_db(DB_PATH)
        try:
            stats = get_stats(conn, since=since)
            return json.dumps(stats, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def resume_info(session_id: str) -> str:
        """Get resume command for a session.

        Args:
            session_id: The session UUID
        """
        conn = init_db(DB_PATH)
        try:
            result = get_session(conn, session_id)
            if result is None:
                return json.dumps({"error": f"Session {session_id} not found"})
            return json.dumps({
                "session_id": session_id,
                "project_path": result["project_path"],
                "resume_command": ["claude", "--resume", session_id],
            }, indent=2)
        finally:
            conn.close()

    return mcp


def main() -> None:
    """Entry point for the MCP stdio server."""
    server = create_server()
    server.run(transport="stdio")
```

- [ ] **Step 2: Verify server module imports without errors**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index python -c "from claude_session_index.server import create_server; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/server.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: FastMCP stdio server with search, browse, and stats tools"
```

---

### Task 8: CLI

**Files:**
- Create: `src/claude_session_index/cli.py`

- [ ] **Step 1: Implement cli.py**

Create `src/claude_session_index/cli.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from claude_session_index.config import DB_PATH

app = typer.Typer(name="claude-session-index", help="Index and search Claude Code sessions.")


@app.command()
def index(
    full: bool = typer.Option(False, "--full", help="Full rebuild — reprocess all files"),
    since: str | None = typer.Option(None, "--since", help="Only process files modified within duration (e.g. 7d, 30d)"),
) -> None:
    """Index Claude Code sessions into the database."""
    from claude_session_index.db import init_db
    from claude_session_index.indexer import index_all

    typer.echo("Indexing sessions...")
    conn = init_db(DB_PATH)
    try:
        stats = index_all(conn, full=full, since=since)
        typer.echo(f"Phase 1 (sessions-index.json): {stats['phase1_count']} sessions")
        typer.echo(f"Phase 2 (transcripts):         {stats['phase2_count']} sessions")
        typer.echo(f"Phase 3 (history):             {stats['phase3_count']} sessions")
        typer.echo(f"Total indexed:                 {stats['total']} sessions")
    finally:
        conn.close()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    project: str | None = typer.Option(None, "--project", help="Filter by project name"),
    since: str | None = typer.Option(None, "--since", help="Filter by date"),
    limit: int = typer.Option(10, "--limit", help="Max results"),
    output_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Search indexed sessions."""
    from claude_session_index.db import init_db
    from claude_session_index.search import search_sessions

    conn = init_db(DB_PATH)
    try:
        results = search_sessions(conn, query, project=project, since=since, limit=limit)
    finally:
        conn.close()

    if output_json:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        typer.echo("No results found.")
        return

    # Formatted table
    typer.echo(f"{'SESSION ID':<40} {'PROJECT':<20} {'PROMPT':<40} {'DATE':<12} {'SCORE':<8}")
    typer.echo("-" * 120)
    for r in results:
        sid = r["session_id"][:36]
        proj = (r["project_name"] or "")[:18]
        prompt = (r["first_prompt"] or "")[:38]
        date = (r["created_at"] or "")[:10]
        score = f"{r['score']:.2f}" if r.get("score") else ""
        typer.echo(f"{sid:<40} {proj:<20} {prompt:<40} {date:<12} {score:<8}")


@app.command()
def stats(
    since: str | None = typer.Option(None, "--since", help="Filter by date"),
    output_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show index statistics."""
    from claude_session_index.db import get_stats, init_db

    conn = init_db(DB_PATH)
    try:
        result = get_stats(conn, since=since)
    finally:
        conn.close()

    if output_json:
        typer.echo(json.dumps(result, indent=2))
        return

    typer.echo(f"Total sessions: {result['total_sessions']}")
    typer.echo(f"Total projects: {result['total_projects']}")
    typer.echo()
    typer.echo("Sessions by project:")
    for proj, cnt in result["sessions_by_project"].items():
        typer.echo(f"  {proj}: {cnt}")
    if result["sessions_by_date"]:
        typer.echo()
        typer.echo("Recent activity:")
        for date, cnt in list(result["sessions_by_date"].items())[:10]:
            typer.echo(f"  {date}: {cnt}")


@app.command()
def serve() -> None:
    """Start the MCP stdio server."""
    from claude_session_index.server import main

    main()


@app.command()
def timer(
    action: str = typer.Argument(..., help="install or uninstall"),
) -> None:
    """Manage systemd user timer for periodic indexing."""
    systemd_dir = Path(__file__).parent.parent.parent / "systemd"
    user_systemd = Path.home() / ".config" / "systemd" / "user"

    service_name = "claude-session-index.service"
    timer_name = "claude-session-index.timer"

    if action == "install":
        user_systemd.mkdir(parents=True, exist_ok=True)
        service_src = systemd_dir / service_name
        timer_src = systemd_dir / timer_name

        if not service_src.exists() or not timer_src.exists():
            typer.echo(f"Error: systemd unit files not found in {systemd_dir}", err=True)
            raise typer.Exit(1)

        service_dst = user_systemd / service_name
        timer_dst = user_systemd / timer_name

        # Symlink unit files
        for src, dst in [(service_src, service_dst), (timer_src, timer_dst)]:
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(src.resolve())

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", timer_name], check=True)
        typer.echo(f"Timer installed and started. Check with: systemctl --user status {timer_name}")

    elif action == "uninstall":
        subprocess.run(["systemctl", "--user", "stop", timer_name], check=False)
        subprocess.run(["systemctl", "--user", "disable", timer_name], check=False)
        for name in [service_name, timer_name]:
            target = user_systemd / name
            if target.exists() or target.is_symlink():
                target.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        typer.echo("Timer uninstalled.")

    else:
        typer.echo("Usage: claude-session-index timer [install|uninstall]", err=True)
        raise typer.Exit(1)
```

- [ ] **Step 2: Verify CLI help works**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index --help`
Expected: Shows help with `index`, `search`, `stats`, `serve`, `timer` commands

- [ ] **Step 3: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/cli.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: Typer CLI with index, search, stats, serve, and timer commands"
```

---

### Task 9: Plugin and Systemd Units

**Files:**
- Create: `plugin/plugin.json`
- Create: `plugin/hooks/hooks.json`
- Create: `plugin/hooks/session-end.sh`
- Create: `systemd/claude-session-index.service`
- Create: `systemd/claude-session-index.timer`

- [ ] **Step 1: Create plugin.json**

Create `plugin/plugin.json`:

```json
{
  "name": "claude-session-index",
  "description": "Auto-indexes Claude Code sessions on session end",
  "version": "0.1.0"
}
```

- [ ] **Step 2: Create hooks/hooks.json**

Create `plugin/hooks/hooks.json`:

```json
[
  {
    "event": "Stop",
    "hooks": [
      {
        "type": "command",
        "command": "bash $CLAUDE_PLUGIN_ROOT/hooks/session-end.sh"
      }
    ]
  }
]
```

- [ ] **Step 3: Create hooks/session-end.sh**

Create `plugin/hooks/session-end.sh`:

```bash
#!/usr/bin/env bash
# Index recent sessions on session end (non-blocking)
nohup uv run --project "$(dirname "$(dirname "$CLAUDE_PLUGIN_ROOT")")" claude-session-index index --since 1d >/dev/null 2>&1 &
```

- [ ] **Step 4: Make session-end.sh executable**

Run: `chmod +x /home/lokkju/projects/lokkju/claude-session-index/plugin/hooks/session-end.sh`

- [ ] **Step 5: Create systemd service unit**

Create `systemd/claude-session-index.service`:

```ini
[Unit]
Description=Index Claude Code sessions

[Service]
Type=oneshot
ExecStart=uv run --project %h/projects/lokkju/claude-session-index claude-session-index index
```

- [ ] **Step 6: Create systemd timer unit**

Create `systemd/claude-session-index.timer`:

```ini
[Unit]
Description=Index Claude Code sessions every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

- [ ] **Step 7: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add plugin/ systemd/
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: Claude Code plugin with Stop hook and systemd timer units"
```

---

### Task 10: Run Full Test Suite and Lint

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run ruff check**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index ruff check src/ tests/`
Expected: No errors

- [ ] **Step 3: Run ruff format check**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index ruff format --check src/ tests/`
Expected: All files formatted correctly (or fix and recommit)

- [ ] **Step 4: Run pyright**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pyright src/`
Expected: No errors (or minimal expected ones from sqlite3.Row)

- [ ] **Step 5: Fix any issues found and commit**

If any lint/type issues were found:
```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add -u
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "fix: resolve lint and type check issues"
```

---

### Task 11: Integration Test — End to End

**Files:**
- No new files — uses real `~/.claude` data

- [ ] **Step 1: Run a real index**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index index`
Expected: Output showing session counts per phase

- [ ] **Step 2: Run a search**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index search "greeting"`
Expected: Table of matching sessions (or "No results" if no matches)

- [ ] **Step 3: Check stats**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index stats`
Expected: Summary showing total sessions, projects, recent activity

- [ ] **Step 4: Register as MCP server**

Run: `claude mcp add session-index -- uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index serve`
Expected: MCP server registered successfully

- [ ] **Step 5: Fix any issues found and commit**

If any integration issues were found:
```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add -u
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "fix: resolve integration issues from end-to-end testing"
```
