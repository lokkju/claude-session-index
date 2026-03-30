---
name: session-report
description: >
  Use when asked to look up what was worked on, find sessions from a
  time period, get a work activity overview, or prepare data for
  summarization. Queries the claude-session-index CLI or MCP tool.
---

## How to Use

1. **Run the report command** (CLI is the primary path):
   ```bash
   claude-session-index report --since <range> --json
   ```
   Options:
   - `--since`: duration like `1d`, `7d` or ISO date (default: `1d`)
   - `--until`: optional ISO date for end of range
   - `--project-path`: optional prefix to filter by project location
   - `--limit`: max sessions per project (default: 100)
   - `--json`: structured JSON output (always use this for programmatic consumption)

   If the `session-index` MCP server is available, you can alternatively
   call the `report` MCP tool with the same parameters.

2. **Parse the JSON output.** Sessions are grouped by project. Each includes:
   - `session_id` — unique identifier for drill-down
   - `project_name`, `project_path`, `git_branch`
   - `first_prompt` — what the user asked
   - `summary` — AI-generated summary (if available)
   - `files_changed` — list of files touched
   - `commit_messages` — list of commits made
   - `created_at`, `modified_at` — time range
   - `message_count` — conversation length

3. **Drill into sessions** that need more detail:
   ```bash
   claude-session-index show <session_id> --json
   ```
   Returns full session content: user prompts, assistant text, commands
   run, files changed, commit messages, and subagent session IDs.

   To search by topic instead of ID:
   ```bash
   claude-session-index search "<query>" --json
   ```

   If the `session-index` MCP server is available, you can alternatively
   use `get_session_detail(session_id="...")`.

   If the tool is not installed, tell the user:
   ```
   claude-session-index is not installed. Install with:
   uv tool install --from git+https://github.com/lokkju/claude-session-index claude-session-index
   ```

## Examples

Today's work:
```bash
claude-session-index report --since 1d --json
```

All work under a project tree last week:
```bash
claude-session-index report --since 7d --project-path /home/user/projects --json
```

Search for sessions about a topic:
```bash
claude-session-index search "authentication" --json
```
