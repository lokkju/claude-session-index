# Design: Report Command and TPS Skill

**Date:** 2026-03-30
**Status:** Draft

## Purpose

Add a `report` command to claude-session-index that outputs all sessions worked on within a date range, optionally filtered by project path prefix. Expose the same capability as an MCP tool. Provide a `tps` (total-project-summary) skill that agents can invoke to gather session data and summarize work flexibly.

## Non-goals

- No LLM summarization inside the tool itself — that's the skill's job
- No new dependencies
- No changes to the indexing pipeline or schema

## Components

### 1. Report Query (`db.py`)

New function `report_sessions()` in `db.py`:

```python
def report_sessions(
    conn: sqlite3.Connection,
    since: str | None = None,
    until: str | None = None,
    project_path_prefix: str | None = None,
    limit: int = 100,
) -> dict:
```

**Parameters:**
- `since` — duration string (`1d`, `7d`) or ISO date. Defaults to `1d` when called from CLI/MCP with no value.
- `until` — ISO date string. Defaults to now.
- `project_path_prefix` — filters sessions where `project_path` starts with this prefix (e.g. `/home/lokkju/projects`). Uses `LIKE prefix%` with the `%` escaped.
- `limit` — max sessions per project (default 100)

**Returns:**

```python
{
    "since": "2026-03-30T00:00:00+00:00",
    "until": "2026-03-30T23:59:59+00:00",
    "project_count": 3,
    "session_count": 7,
    "projects": {
        "myapp": [
            {
                "session_id": "deadbeef-...",
                "git_branch": "feat/greetings",
                "first_prompt": "Add a greeting function...",
                "summary": "Added greeting function with tests",
                "files_changed": ["hello.py", "tests/test_hello.py"],
                "commit_messages": ["feat: add greeting function"],
                "created_at": "2026-03-30T10:00:00Z",
                "modified_at": "2026-03-30T11:00:00Z",
                "message_count": 12
            }
        ]
    }
}
```

Sessions are grouped by `project_name`, sorted by `created_at` within each group.

The `files_changed` and `commit_messages` fields are stored as newline-separated strings in the DB — `report_sessions()` splits them into lists before returning.

**Filtering logic (uses `created_at`, not `modified_at`, since we care about when work started):**
- `since`: `created_at >= since_cutoff(since)`
- `until`: `created_at <= until_cutoff` (parse with same logic as `since_cutoff`, but for an upper bound)
- `project_path_prefix`: `project_path LIKE ?` with param `prefix + '%'`
- Results ordered by `project_name ASC, created_at ASC`

### 2. CLI Command

```
claude-session-index report [--since 1d] [--until DATE] [--project-path PREFIX] [--json]
```

- `--since` defaults to `1d`
- `--until` defaults to now (omitted)
- `--project-path` optional prefix filter
- `--json` outputs the raw JSON structure
- Default: markdown report

**Markdown output format:**

```markdown
# Work Report: 2026-03-30

## myapp (3 sessions)

### feat/greetings — 10:00-11:00 (12 messages)
Add a greeting function to hello.py
- Files: hello.py, tests/test_hello.py
- Commits: feat: add greeting function

### fix/auth — 14:00-15:30 (8 messages)
Fix the login bug in auth.py
- Files: auth.py, tests/test_auth.py
- Commits: fix: resolve auth timeout

## infra (1 session)

### main — 16:00-16:30 (4 messages)
Update terraform modules
- Files: modules/vpc/main.tf
- Commits: chore: update vpc module
```

When `summary` is available (from sessions-index.json), show it instead of `first_prompt`.

Time display uses local timezone, showing just `HH:MM` for same-day reports and `YYYY-MM-DD HH:MM` for multi-day ranges.

### 3. MCP Tool

New tool `report` in `server.py`:

```python
@mcp.tool()
def report(
    since: str = "1d",
    until: str | None = None,
    project_path: str | None = None,
    limit: int = 100,
) -> str:
    """Get a structured report of all sessions within a date range.

    Args:
        since: Start of range — duration like '1d', '7d' or ISO date (default: '1d')
        until: End of range — ISO date (default: now)
        project_path: Filter to sessions under this path prefix
        limit: Max sessions per project (default 100)
    """
```

Returns the JSON structure from `report_sessions()`.

### 4. `until` Support in Config

Add `until_cutoff()` to `config.py`:

```python
def until_cutoff(until: str) -> datetime:
    """Convert an ISO date into a UTC datetime upper bound."""
    dt = datetime.fromisoformat(until)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
```

This is simpler than `since_cutoff` — no duration support needed since "until 7d" doesn't make semantic sense. Just ISO dates.

### 5. Consumption Skill Documentation

A skill file at `plugin/skills/session-report.md` that documents how agents should use the report + drill-down pattern:

```markdown
---
name: session-report
description: Use when asked to summarize work, generate standup notes, create daily/weekly reports, or review what was accomplished across sessions
---

## How to Use

1. Call the `report` MCP tool with appropriate date range
2. Review the structured output — sessions grouped by project
3. For sessions needing more detail, call `get_session_detail` with the session_id
4. Use the gathered data to fulfill the user's request

## Available Data Per Session

**From report:** session_id, project, branch, first_prompt/summary, files_changed, commit_messages, timestamps, message_count

**From get_session_detail (drill-down):** All of the above plus: user_prompts (full text), assistant_text, commands_run, keywords, tags
```

### 6. TPS Skill

A skill file at `plugin/skills/tps.md`:

```markdown
---
name: tps
description: >
  Total Project Summary. Use when asked to summarize work done,
  generate standup notes, create daily/weekly reports, review
  accomplishments, or answer "what did I work on today/this week".
  Gathers session data and presents it for flexible summarization.
---

## Workflow

1. Determine the date range from the user's request
   - "today" / "what did I do today" → --since 1d
   - "this week" → --since 7d
   - "yesterday" → --since 2d --until yesterday's date
   - Specific dates → use as-is

2. Run the report command:
   claude-session-index report --since <range> --json

3. Parse the JSON output. For each project:
   - Note the session count, branches, and commit messages
   - If a session has a summary, prefer it over first_prompt
   - If more detail is needed, call get_session_detail via the MCP tool

4. Present the gathered data to fulfill the user's purpose.
   Do NOT prescribe a format — adapt to what the user asked for:
   - Standup notes → brief bullets per project
   - Daily journal → narrative form
   - PR summary → technical detail focus
   - Status update → progress-oriented
   - If the user didn't specify, ask what format they want
```

## Project Structure Changes

```
claude-session-index/
├── src/claude_session_index/
│   ├── config.py            # Add until_cutoff()
│   ├── db.py                # Add report_sessions()
│   ├── cli.py               # Add report command
│   └── server.py            # Add report MCP tool
├── plugin/
│   ├── skills/
│   │   ├── session-report.md  # Consumption documentation skill
│   │   └── tps.md             # Total Project Summary skill
│   └── plugin.json            # Update to include skills
├── tests/
│   ├── test_db.py             # Add report_sessions tests
│   └── test_config.py         # Add until_cutoff tests
└── docs/
    └── superpowers/specs/
        └── 2026-03-30-report-and-tps-design.md
```

## Test Plan

### `test_config.py`
- `until_cutoff` with ISO date
- `until_cutoff` with invalid input raises ValueError

### `test_db.py`
- `report_sessions` returns sessions grouped by project
- `report_sessions` with `since` filter
- `report_sessions` with `until` filter
- `report_sessions` with `project_path_prefix` filter
- `report_sessions` splits newline-separated fields into lists
- `report_sessions` with empty result set
