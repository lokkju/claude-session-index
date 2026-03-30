# Report Command and TPS Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `report` command/MCP tool that outputs sessions for a date range grouped by project, plus a `tps` skill for flexible work summarization.

**Architecture:** New `report_sessions()` query in db.py groups sessions by project with date range and path prefix filters. CLI `report` command renders markdown or JSON. MCP `report` tool mirrors it. Two skill files document consumption patterns.

**Tech Stack:** Same as existing — Python 3.11+, typer, fastmcp, SQLite, pytest

---

## File Structure

```
claude-session-index/
├── src/claude_session_index/
│   ├── config.py              # Add until_cutoff()
│   ├── db.py                  # Add report_sessions()
│   ├── cli.py                 # Add report command
│   └── server.py              # Add report MCP tool
├── plugin/
│   ├── plugin.json            # Add skills reference
│   └── skills/
│       ├── session-report.md  # Consumption documentation
│       └── tps.md             # Total Project Summary skill
└── tests/
    ├── test_config.py         # Add until_cutoff tests
    └── test_db.py             # Add report_sessions tests
```

---

### Task 1: Add `until_cutoff` to Config

**Files:**
- Modify: `src/claude_session_index/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for until_cutoff**

Add to `tests/test_config.py`:

```python
from claude_session_index.config import parse_duration, since_cutoff, until_cutoff


class TestUntilCutoff:
    def test_iso_date(self):
        cutoff = until_cutoff("2026-03-30")
        assert cutoff.year == 2026
        assert cutoff.month == 3
        assert cutoff.day == 30

    def test_iso_datetime(self):
        cutoff = until_cutoff("2026-03-30T18:00:00")
        assert cutoff.hour == 18

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="not a valid ISO date"):
            until_cutoff("garbage")
```

Also update the existing import line at the top of the file from:
```python
from claude_session_index.config import parse_duration, since_cutoff
```
to:
```python
from claude_session_index.config import parse_duration, since_cutoff, until_cutoff
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_config.py::TestUntilCutoff -v`
Expected: FAIL — `ImportError: cannot import name 'until_cutoff'`

- [ ] **Step 3: Implement until_cutoff**

Add to the end of `src/claude_session_index/config.py`:

```python
def until_cutoff(until: str) -> datetime:
    """Convert an ISO date string into a UTC datetime upper bound."""
    try:
        dt = datetime.fromisoformat(until)
    except ValueError:
        raise ValueError(
            f"'{until}' is not a valid ISO date (e.g. '2026-03-30')."
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_config.py -v`
Expected: All tests PASS (including existing ones)

- [ ] **Step 5: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/config.py tests/test_config.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: add until_cutoff for date range upper bounds"
```

---

### Task 2: Add `report_sessions` to DB

**Files:**
- Modify: `src/claude_session_index/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for report_sessions**

Add to `tests/test_db.py` — add `report_sessions` to the import block and add a new test class at the end:

Update the import at the top of `tests/test_db.py` from:
```python
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
```
to:
```python
from claude_session_index.db import (
    clear_file_mtimes,
    get_file_mtime,
    get_session,
    get_stats,
    init_db,
    list_sessions,
    rebuild_fts,
    report_sessions,
    set_file_mtime,
    upsert_session,
)
```

Then add the test class:

```python
class TestReportSessions:
    def _insert_sessions(self, db_conn: sqlite3.Connection):
        """Insert multiple sessions across projects for report testing."""
        sessions = [
            SessionData(
                session_id="s1",
                project_path="/home/user/projects/myapp",
                project_name="myapp",
                git_branch="feat/login",
                created_at="2026-03-30T09:00:00+00:00",
                modified_at="2026-03-30T10:00:00+00:00",
                first_prompt="Add login page",
                user_prompts="Add login page",
                assistant_text="I'll create the login page.",
                files_changed=["src/login.py", "tests/test_login.py"],
                commit_messages=["feat: add login page"],
                message_count=8,
            ),
            SessionData(
                session_id="s2",
                project_path="/home/user/projects/myapp",
                project_name="myapp",
                git_branch="feat/login",
                created_at="2026-03-30T14:00:00+00:00",
                modified_at="2026-03-30T15:00:00+00:00",
                first_prompt="Fix login validation",
                user_prompts="Fix login validation",
                assistant_text="I'll fix the validation.",
                files_changed=["src/login.py"],
                commit_messages=["fix: login validation"],
                message_count=5,
            ),
            SessionData(
                session_id="s3",
                project_path="/home/user/projects/infra",
                project_name="infra",
                git_branch="main",
                created_at="2026-03-30T11:00:00+00:00",
                modified_at="2026-03-30T12:00:00+00:00",
                first_prompt="Update terraform modules",
                user_prompts="Update terraform modules",
                assistant_text="I'll update the modules.",
                files_changed=["modules/vpc/main.tf"],
                commit_messages=["chore: update vpc module"],
                message_count=4,
            ),
            SessionData(
                session_id="s4",
                project_path="/home/other/work/tool",
                project_name="tool",
                git_branch="main",
                created_at="2026-03-29T10:00:00+00:00",
                modified_at="2026-03-29T11:00:00+00:00",
                first_prompt="Old session from yesterday",
                user_prompts="Old session",
                assistant_text="Done.",
                message_count=2,
            ),
        ]
        for s in sessions:
            upsert_session(db_conn, s, source="transcript")

    def test_groups_by_project(self, db_conn: sqlite3.Connection):
        self._insert_sessions(db_conn)
        result = report_sessions(db_conn)
        assert "myapp" in result["projects"]
        assert "infra" in result["projects"]
        assert len(result["projects"]["myapp"]) == 2
        assert len(result["projects"]["infra"]) == 1

    def test_sorted_by_created_at(self, db_conn: sqlite3.Connection):
        self._insert_sessions(db_conn)
        result = report_sessions(db_conn)
        myapp = result["projects"]["myapp"]
        assert myapp[0]["session_id"] == "s1"
        assert myapp[1]["session_id"] == "s2"

    def test_since_filter(self, db_conn: sqlite3.Connection):
        self._insert_sessions(db_conn)
        result = report_sessions(db_conn, since="2026-03-30")
        assert "tool" not in result["projects"]
        assert "myapp" in result["projects"]

    def test_until_filter(self, db_conn: sqlite3.Connection):
        self._insert_sessions(db_conn)
        result = report_sessions(
            db_conn, until="2026-03-29T23:59:59"
        )
        assert "myapp" not in result["projects"]
        assert "tool" in result["projects"]

    def test_project_path_prefix(self, db_conn: sqlite3.Connection):
        self._insert_sessions(db_conn)
        result = report_sessions(
            db_conn, project_path_prefix="/home/user/projects"
        )
        assert "myapp" in result["projects"]
        assert "infra" in result["projects"]
        assert "tool" not in result["projects"]

    def test_splits_newline_fields(self, db_conn: sqlite3.Connection):
        self._insert_sessions(db_conn)
        result = report_sessions(db_conn)
        s1 = result["projects"]["myapp"][0]
        assert isinstance(s1["files_changed"], list)
        assert "src/login.py" in s1["files_changed"]
        assert isinstance(s1["commit_messages"], list)
        assert "feat: add login page" in s1["commit_messages"]

    def test_counts(self, db_conn: sqlite3.Connection):
        self._insert_sessions(db_conn)
        result = report_sessions(db_conn)
        assert result["project_count"] >= 2
        assert result["session_count"] >= 3

    def test_empty_result(self, db_conn: sqlite3.Connection):
        result = report_sessions(db_conn, since="2099-01-01")
        assert result["projects"] == {}
        assert result["session_count"] == 0
        assert result["project_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_db.py::TestReportSessions -v`
Expected: FAIL — `ImportError: cannot import name 'report_sessions'`

- [ ] **Step 3: Implement report_sessions**

Add to `src/claude_session_index/db.py`, before the `get_file_mtime` function:

```python
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

    if since:
        cutoff = since_cutoff(since)
        conditions.append("created_at >= ?")
        params.append(cutoff.isoformat())
    if until:
        cutoff = until_cutoff(until)
        conditions.append("created_at <= ?")
        params.append(cutoff.isoformat())
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

    since_iso = since_cutoff(since).isoformat() if since else None
    until_iso = until_cutoff(until).isoformat() if until else None

    return {
        "since": since_iso,
        "until": until_iso,
        "project_count": len(projects),
        "session_count": session_count,
        "projects": projects,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/test_db.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/db.py tests/test_db.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: add report_sessions query with date range and path prefix filters"
```

---

### Task 3: Add `report` CLI Command

**Files:**
- Modify: `src/claude_session_index/cli.py`

- [ ] **Step 1: Add report command to cli.py**

Add the following command to `src/claude_session_index/cli.py`, after the `stats` command and before the `serve` command:

```python
@app.command()
def report(
    since: str = typer.Option("1d", "--since", help="Start of range (duration or ISO date)"),
    until: str | None = typer.Option(None, "--until", help="End of range (ISO date)"),
    project_path: str | None = typer.Option(
        None, "--project-path", help="Filter to sessions under this path prefix"
    ),
    limit: int = typer.Option(100, "--limit", help="Max sessions per project"),
    output_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Report sessions worked on within a date range, grouped by project."""
    from claude_session_index.db import init_db, report_sessions

    conn = init_db(DB_PATH)
    try:
        result = report_sessions(
            conn, since=since, until=until,
            project_path_prefix=project_path, limit=limit,
        )
    finally:
        conn.close()

    if output_json:
        typer.echo(json.dumps(result, indent=2))
        return

    if not result["projects"]:
        typer.echo("No sessions found for this range.")
        return

    # Determine date display from since value
    typer.echo(f"# Work Report (since {since})\n")

    for proj_name, sessions in result["projects"].items():
        typer.echo(f"## {proj_name} ({len(sessions)} sessions)\n")
        for s in sessions:
            branch = s["git_branch"] or "unknown"
            start = (s["created_at"] or "")[:16].replace("T", " ")
            end = (s["modified_at"] or "")[:16].replace("T", " ")
            msgs = s["message_count"]
            title = s["summary"] or s["first_prompt"] or "(no prompt)"
            typer.echo(f"### {branch} — {start} to {end} ({msgs} messages)")
            typer.echo(title)

            if s["files_changed"]:
                files_str = ", ".join(
                    Path(f).name for f in s["files_changed"][:10]
                )
                typer.echo(f"- Files: {files_str}")

            if s["commit_messages"]:
                for cm in s["commit_messages"]:
                    typer.echo(f"- Commit: {cm}")

            typer.echo()
```

- [ ] **Step 2: Verify CLI help shows the report command**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index --help`
Expected: `report` listed among commands

- [ ] **Step 3: Test report command against real data**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index report --since 1d`
Expected: Markdown-formatted report of today's sessions

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index report --since 7d --json | head -20`
Expected: JSON output with `projects` key

- [ ] **Step 4: Run full test suite**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/cli.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: add report CLI command with markdown and JSON output"
```

---

### Task 4: Add `report` MCP Tool

**Files:**
- Modify: `src/claude_session_index/server.py`

- [ ] **Step 1: Add report tool to server.py**

Add the following tool inside `create_server()`, after the `resume_info` tool:

```python
    @mcp.tool()
    def report(
        since: str = "1d",
        until: str | None = None,
        project_path: str | None = None,
        limit: int = 100,
    ) -> str:
        """Get a structured report of all sessions within a date range,
        grouped by project.

        Use this to understand what was worked on during a time period.
        For detailed session content, follow up with get_session_detail.

        Args:
            since: Start of range — duration like '1d', '7d' or ISO date (default: '1d')
            until: End of range — ISO date (default: now)
            project_path: Filter to sessions under this path prefix
            limit: Max sessions per project (default 100)
        """
        from claude_session_index.db import report_sessions

        conn = init_db(DB_PATH)
        try:
            result = report_sessions(
                conn, since=since, until=until,
                project_path_prefix=project_path, limit=limit,
            )
            return json.dumps(result, indent=2)
        finally:
            conn.close()
```

Also add `report_sessions` to the import from `db` at the top of the file:

Update line 8 from:
```python
from claude_session_index.db import get_session, get_stats, init_db, list_sessions
```
to:
```python
from claude_session_index.db import get_session, get_stats, init_db, list_sessions, report_sessions
```

And remove the lazy import inside the tool since it's now at module level.

Wait — the other tools use module-level imports for db functions. But `report_sessions` uses `since_cutoff` and `until_cutoff` internally, which are fine since they're lazy within `report_sessions` itself. So use the module-level import pattern:

```python
    @mcp.tool()
    def report(
        since: str = "1d",
        until: str | None = None,
        project_path: str | None = None,
        limit: int = 100,
    ) -> str:
        """Get a structured report of all sessions within a date range,
        grouped by project.

        Use this to understand what was worked on during a time period.
        For detailed session content, follow up with get_session_detail.

        Args:
            since: Start of range — duration like '1d', '7d' or ISO date (default: '1d')
            until: End of range — ISO date (default: now)
            project_path: Filter to sessions under this path prefix
            limit: Max sessions per project (default 100)
        """
        conn = init_db(DB_PATH)
        try:
            result = report_sessions(
                conn, since=since, until=until,
                project_path_prefix=project_path, limit=limit,
            )
            return json.dumps(result, indent=2)
        finally:
            conn.close()
```

- [ ] **Step 2: Verify server module imports**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index python -c "from claude_session_index.server import create_server; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run full test suite**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add src/claude_session_index/server.py
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: add report MCP tool for date-range session reports"
```

---

### Task 5: Create Skills and Update Plugin

**Files:**
- Create: `plugin/skills/session-report.md`
- Create: `plugin/skills/tps.md`
- Modify: `plugin/plugin.json`

- [ ] **Step 1: Create session-report skill**

Create `plugin/skills/session-report.md`:

```markdown
---
name: session-report
description: >
  Use when asked to look up what was worked on, find sessions from a
  time period, get a work activity overview, or prepare data for
  summarization. Queries the claude-session-index report tool.
---

## How to Use

1. Call the `report` MCP tool with the appropriate date range:
   - `since`: duration like '1d', '7d' or ISO date
   - `until`: optional ISO date for end of range
   - `project_path`: optional prefix to filter by project location

2. The response contains sessions grouped by project. Each session includes:
   - `session_id` — unique identifier for drill-down
   - `project_name`, `project_path`, `git_branch`
   - `first_prompt` — what the user asked
   - `summary` — AI-generated summary (if available)
   - `files_changed` — list of files touched
   - `commit_messages` — list of commits made
   - `created_at`, `modified_at` — time range
   - `message_count` — conversation length

3. For full session content (user prompts, assistant responses, all commands),
   call `get_session_detail` with the `session_id`.

## Example

To find what was worked on today:
```
report(since="1d")
```

To find all work under a project tree last week:
```
report(since="7d", project_path="/home/user/projects")
```

Then drill into a specific session:
```
get_session_detail(session_id="deadbeef-1234-...")
```
```

- [ ] **Step 2: Create tps skill**

Create `plugin/skills/tps.md`:

```markdown
---
name: tps
description: >
  Total Project Summary. Use when asked to summarize work done,
  generate standup notes, create daily or weekly reports, review
  accomplishments, or answer questions like "what did I work on
  today" or "what happened this week". Gathers session data and
  presents it for flexible summarization.
---

## Workflow

1. **Determine the date range** from the user's request:
   - "today" / "what did I do today" → `--since 1d`
   - "this week" → `--since 7d`
   - "yesterday" → `--since 2d --until <yesterday's date>`
   - Specific dates → use as-is

2. **Gather the data** by running the report command:
   ```
   claude-session-index report --since <range> --json
   ```
   Or call the `report` MCP tool with the same parameters.

3. **Review the output.** For each project:
   - Note session count, branches worked on, and commit messages
   - If a session has a `summary`, prefer it over `first_prompt`
   - If more detail is needed for a session, call `get_session_detail`
     with the `session_id` to get full user prompts, assistant text,
     and commands run

4. **Present the data** in whatever format the user needs.
   Do NOT prescribe a fixed format — adapt to the request:
   - **Standup notes** → brief bullets per project
   - **Daily journal** → narrative form
   - **PR summary** → technical detail with files and commits
   - **Status update** → progress-oriented highlights
   - **Weekly recap** → grouped by day or by project
   - If the user didn't specify a format, ask what they want
```

- [ ] **Step 3: Update plugin.json to declare skills**

Update `plugin/plugin.json` to:

```json
{
  "name": "claude-session-index",
  "description": "Auto-indexes Claude Code sessions on session end",
  "version": "0.2.0"
}
```

Note: Claude Code auto-discovers skills from the `skills/` directory within the plugin — no explicit listing needed in `plugin.json`. The version bump reflects the new feature.

- [ ] **Step 4: Commit**

```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add plugin/
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "feat: add session-report and tps skills for work summarization"
```

---

### Task 6: Lint, Test, and Verify

**Files:**
- No new files

- [ ] **Step 1: Run ruff check**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index ruff check src/ tests/`
Expected: No errors

- [ ] **Step 2: Run ruff format**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index ruff format --check src/ tests/`
Expected: All files formatted

- [ ] **Step 3: Run full test suite**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Test report CLI end-to-end**

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index report --since 1d`
Expected: Markdown report of today's sessions

Run: `uv run --project /home/lokkju/projects/lokkju/claude-session-index claude-session-index report --since 7d --json | python3 -m json.tool | head -10`
Expected: Valid JSON with `projects` key

- [ ] **Step 5: Fix any issues and commit**

If any lint/test issues found:
```bash
git -C /home/lokkju/projects/lokkju/claude-session-index add -u
git -C /home/lokkju/projects/lokkju/claude-session-index commit -m "fix: resolve lint and test issues for report feature"
```
