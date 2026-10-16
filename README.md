# claude-session-index

Index Claude Code session transcripts into a searchable SQLite FTS5 database. Search, report, and summarize your work across projects.

## Install

```bash
uv tool install --from git+https://github.com/lokkju/claude-session-index claude-session-index
```

## Quick Start

```bash
# Index all sessions (~10 seconds for a full scan)
claude-session-index index

# Search across all sessions
claude-session-index search "authentication bug"

# Today's work report
claude-session-index report --since 1d

# Full details for a session
claude-session-index show <session-id>

# Index statistics
claude-session-index stats
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `index` | Index sessions into the database. `--full` rebuilds from scratch, `--since 7d` limits to recent files. |
| `search <query>` | Full-text search with BM25 ranking. `--project`, `--since`, `--limit`, `--json` options. |
| `show <session-id>` | Full session detail including subagent IDs. `--json` for structured output. |
| `report` | Sessions grouped by project for a date range. `--since`, `--until`, `--project-path`, `--json`. |
| `stats` | Index overview: session counts, projects, recent activity. `--json`. |
| `serve` | Start MCP stdio server (6 tools: search, get_session_detail, list, stats, report, resume_info). |
| `timer install\|uninstall` | Manage systemd user timer for 15-minute background indexing. |

## Claude Code Plugin

This repo is also a Claude Code plugin, `session-history`, with two skills:

- **session-report** — Query the index for sessions from a time period
- **tps** (Total Project Summary) — Gather session data and present flexible work summaries (standup notes, daily journals, weekly recaps)

### Install as Plugin

Add the `lokkju` marketplace, then install the plugin:

```bash
# Add marketplace (one-time)
claude plugin marketplace add lokkju/skills

# Install plugin
claude plugin install session-history@lokkju
```

Or load it straight from a checkout for one session:

```bash
claude --plugin-dir /path/to/claude-session-index
```

The plugin used to be called `claude-session-index`, a name Claude Code now reserves. If you
installed it under that name, remove it and install it again under the new one:

```bash
claude plugin uninstall claude-session-index@lokkju
claude plugin marketplace update lokkju
claude plugin install session-history@lokkju
```

The CLI and Python package keep the `claude-session-index` name; only the plugin changed.

### Auto-Indexing

The plugin includes hooks that:
- **SessionStart**: Warn if the CLI tool isn't installed
- **Stop**: Automatically index recent sessions when a Claude Code session ends

## How It Works

### Three-Phase Indexing

1. **sessions-index.json** — High-quality metadata (summaries, message counts) from Claude's own index files
2. **Transcript JSONL** — Full session transcripts parsed for user prompts, assistant text, tool usage, files changed, commands run, and commit messages
3. **history.jsonl** — Gap-fill from the global history log

Subagent sessions are indexed with `parent_session_id` linking, so work done by subagents is discoverable and attributable.

### Incremental by Default

File modification times are tracked — only changed files are reprocessed. Use `--full` to force a complete rebuild.

### Data Stored

| Field | Source |
|-------|--------|
| `first_prompt` | First user message |
| `summary` | From sessions-index.json (if available) |
| `user_prompts` | All user messages (capped at 3KB) |
| `assistant_text` | Assistant text blocks, excluding thinking (capped at 3KB) |
| `files_changed` | From Read/Write/Edit/Glob/Grep tool calls + file-history-snapshots |
| `commands_run` | From Bash tool calls (max 500 chars each) |
| `commit_messages` | Extracted from git commit commands (inline -m, heredoc, -F patterns) |
| `git_branch` | Branch at session start |
| `parent_session_id` | Links subagent sessions to their parent |

## MCP Server

The `serve` command starts a stdio MCP server with 6 tools. Register it with:

```bash
claude mcp add session-index -- claude-session-index serve
```

## Systemd Timer

For background indexing every 15 minutes:

```bash
claude-session-index timer install    # symlinks + enables timer
claude-session-index timer uninstall  # stops + removes
```

## Development

```bash
git clone https://github.com/lokkju/claude-session-index
uv sync --dev
uv run pytest tests/ -v        # 64 tests
uv run ruff check src/ tests/  # lint
```

## License

[PolyForm Shield 1.0.0](https://polyformproject.org/licenses/shield/1.0.0/)
