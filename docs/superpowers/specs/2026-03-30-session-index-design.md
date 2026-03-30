# Design: claude-session-index

**Date:** 2026-03-30
**Status:** Approved

## Purpose

A local-only Python tool that indexes Claude Code session JSONL files into a searchable SQLite FTS5 database and exposes the index as an MCP server. Designed as the foundation for downstream consumers like daily work summaries, Jira ticket matching, and pattern detection.

## Non-goals

- No external API calls — all processing is local
- No LLM-powered enrichment in v1 (can be added later)
- No web UI
- No multi-agent support beyond Claude Code (can be extended later)

## Architecture

Single Python package (`claude-session-index`) with these subcommands:

- `claude-session-index index` — backfill/incremental indexing
- `claude-session-index search <query>` — CLI search for humans
- `claude-session-index serve` — MCP stdio server for agents
- `claude-session-index stats` — index statistics
- `claude-session-index timer install|uninstall` — systemd timer management

An optional Claude Code plugin provides a SessionEnd hook for auto-indexing.

## Schema

```sql
CREATE TABLE sessions (
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

CREATE VIRTUAL TABLE sessions_fts USING fts5(
    session_id, summary, first_prompt, user_prompts,
    assistant_text, files_changed, commands_run,
    commit_messages, project_name, keywords, tags,
    tokenize='porter unicode61 remove_diacritics 1',
    prefix='2 3'
);

CREATE TABLE file_mtimes (
    file_path TEXT PRIMARY KEY,
    mtime     REAL NOT NULL
);
```

- DB location: `~/.local/share/claude-session-index/sessions.db`
- `session_id` is PRIMARY KEY — upserts via `INSERT ... ON CONFLICT DO UPDATE` ensure idempotent re-indexing
- FTS5 uses porter stemming with prefix indexing for fast prefix queries
- `file_mtimes` table tracks which files have been processed and when, enabling incremental indexing

## JSONL Extraction

A `SessionData` dataclass is produced by parsing each session JSONL file:

```python
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
    files_changed: list[str]
    commands_run: list[str]
    commit_messages: list[str]
    message_count: int
```

### Extraction rules

- **User prompts**: Extract `text` from `message.content` where `type == "user"`. Skip messages <10 chars and XML/system preambles. Concatenate, truncate to 3KB.
- **Assistant text**: Extract `text` blocks from `message.content` where `type == "assistant"`. Skip `thinking` blocks, `tool_use` blocks, signatures. First ~500 chars per block, total cap 3KB.
- **Files changed**: From `tool_use` blocks where `name` in (Read, Write, Edit, Glob, Grep) — extract `file_path`/`path`/`pattern`. Also from `file-history-snapshot` entries. Deduplicated.
- **Commands run**: From `tool_use` blocks where `name == "Bash"` — extract `command` field. Skip commands >500 chars.
- **Commit messages**: From Bash `tool_use` where `command` matches `git commit -m` — extract the message text. Handle both inline `-m "msg"` and heredoc patterns (`cat <<'EOF'`).
- **Metadata**: `session_id`, `cwd` (→ `project_path`), `gitBranch`, `timestamp` from the first entry. `modified_at` from the last entry.

### Safety limits

- Skip files >50MB
- Stream line-by-line (no full file load into memory)
- Cap processing at 10,000 lines per session

## Indexing Pipeline

Three data sources processed in priority order:

### Phase 1: `sessions-index.json` (highest quality)

- Scan `~/.claude/projects/*/sessions-index.json`
- Extract: `sessionId`, `firstPrompt`, `messageCount`, `gitBranch`, `projectPath`, `created`, `modified`
- Source field: `"sessions-index"`

### Phase 2: Transcript JSONL files

- Scan `~/.claude/projects/*/*.jsonl` (UUID-named files)
- Skip `subagents/` directories
- Run the extractor to produce `SessionData`
- Merge with Phase 1: transcript fields fill gaps but don't overwrite sessions-index data
- Source field: `"transcript"`

### Phase 3: `history.jsonl` (gap-fill)

- Parse `~/.claude/history.jsonl`
- Only insert sessions not already indexed from Phases 1-2
- Limited data: `display` (first prompt), `project`, `timestamp`, optional `sessionId`
- Source field: `"history"`

### Incremental indexing

- Before processing each file, compare current `mtime` against `file_mtimes` table
- Skip unchanged files
- `--full` flag drops `file_mtimes` and reprocesses everything
- `--since <duration>` filters by file modification time

### FTS synchronization

- Bulk operations: rebuild FTS table after all phases complete
- Single-session upserts (from SessionEnd hook): delete old FTS entry + insert new one inline

## MCP Server

Stdio transport using the `mcp` Python SDK. Registered via:

```bash
claude mcp add session-index -- uv run --project /path/to/claude-session-index claude-session-index serve
```

### Tools

**`search_sessions`**
- Input: `query` (string, required), `project` (string, optional), `since` (string, optional, e.g. "7d", "2026-03-01"), `limit` (int, optional, default 10)
- FTS5 MATCH query with BM25 ranking
- Returns: list of `{session_id, project_path, project_name, git_branch, summary, first_prompt, commit_messages, score, created_at, modified_at, message_count}`

**`get_session`**
- Input: `session_id` (string, required)
- Returns: full session record with all indexed fields

**`list_sessions`**
- Input: `project` (string, optional), `since` (string, optional), `branch` (string, optional), `limit` (int, optional, default 20), `order_by` (string, optional, default "modified_at")
- Filtered listing, no search query — just browse

**`session_stats`**
- Input: `since` (string, optional)
- Returns: `{total_sessions, total_projects, sessions_by_project, sessions_by_date, top_files_changed}`

**`resume_info`**
- Input: `session_id` (string, required)
- Returns: `{session_id, project_path, resume_command}` where `resume_command` is `["claude", "--resume", "<session_id>"]`

## CLI

```
claude-session-index <command> [options]
```

### `index`

Indexes sessions into the database.

- `--full` — rebuild from scratch (drops file_mtimes, reprocesses everything)
- `--since <duration>` — only process files modified within duration (e.g. `7d`, `30d`)
- Default: incremental (skip unchanged files)
- Output: phase progress, counts, timing

### `search <query>`

Full-text search across indexed sessions.

- `--project <name>` — filter by project name
- `--since <duration>` — filter by date
- `--limit <n>` — max results (default 10)
- `--json` — JSON output
- Default: formatted table (session_id truncated, project, first_prompt truncated, date, score)

### `stats`

Show index statistics.

- `--json` — JSON output
- Default: formatted summary

### `serve`

Start MCP stdio server. No flags. Intended to be invoked by Claude Code's MCP subsystem.

### `timer install|uninstall`

Manage systemd user timer for periodic indexing.

- `install` — symlinks service + timer to `~/.config/systemd/user/`, enables and starts timer
- `uninstall` — stops timer, disables, removes symlinks
- Timer runs every 15 minutes by default

## Optional Plugin

Located in `plugin/` within the project repo:

```
plugin/
  plugin.json
  hooks/
    hooks.json
    session-end.sh
```

- `plugin.json`: plugin identity, no skills or commands
- `hooks.json`: single `Stop` hook
- `session-end.sh`: runs `claude-session-index index --since 1d`, non-blocking

Installation:
```bash
claude plugin add /path/to/claude-session-index/plugin
```

## Systemd Timer

Located in `systemd/` within the project repo:

- `claude-session-index.service` — oneshot unit running `claude-session-index index`
- `claude-session-index.timer` — triggers service every 15 minutes

User-level units (`~/.config/systemd/user/`), no root required.

## Project Structure

```
claude-session-index/
├── pyproject.toml
├── LICENSE                     # Polyform Shield 1.0.0
├── src/
│   └── claude_session_index/
│       ├── __init__.py
│       ├── cli.py              # typer CLI
│       ├── db.py               # SQLite schema, upsert, FTS, queries
│       ├── extractor.py        # JSONL parser → SessionData
│       ├── indexer.py          # 3-phase pipeline, incremental logic
│       ├── search.py           # FTS5 query builder, BM25 ranking
│       ├── server.py           # MCP stdio server
│       └── config.py           # paths, constants
├── plugin/
│   ├── plugin.json
│   └── hooks/
│       ├── hooks.json
│       └── session-end.sh
├── systemd/
│   ├── claude-session-index.service
│   └── claude-session-index.timer
├── tests/
│   ├── test_extractor.py
│   ├── test_db.py
│   ├── test_indexer.py
│   ├── test_search.py
│   └── fixtures/
│       └── sample_session.jsonl
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-30-session-index-design.md
```

## Dependencies

### Runtime
- `typer` — CLI framework
- `mcp` — MCP SDK for stdio server

### Dev
- `pytest`
- `ruff`
- `pyright`

SQLite (including FTS5) is Python stdlib — no additional dependency needed.

## License

Polyform Shield 1.0.0

## Future Extensions (not in v1)

- claude.ai session import (via `claude-to-sqlite` zip export)
- LLM-powered tag/summary enrichment
- Multi-query OR searches for batch consumers
- Additional agent adapters (Codex, Copilot, etc.)
- HTTP transport for the MCP server
