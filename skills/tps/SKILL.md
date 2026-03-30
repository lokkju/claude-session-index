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

2. **Gather the data** via CLI (preferred) or MCP:
   ```bash
   claude-session-index report --since <range> --json
   ```
   If the `session-index` MCP server is available, you can alternatively
   call the `report` MCP tool with the same parameters.

   If the tool is not installed, tell the user:
   ```
   claude-session-index is not installed. Install with:
   uv tool install --from git+https://github.com/lokkju/claude-session-index claude-session-index
   ```

3. **Check for plans and specs.** For each project in the report:
   - Look for plan files matching the date range in:
     - `{project_path}/docs/superpowers/plans/YYYY-MM-DD-*.md`
     - `{project_path}/docs/superpowers/specs/YYYY-MM-DD-*.md`
   - Also check `~/.claude/projects/` for the project's directory
     (path-encoded, e.g. `-home-user-projects-myapp`) for any
     plan or spec files
   - Plans explain the *intent* behind the work — what was being
     built and why. Include this context in summaries.

4. **Review session data.** For each project:
   - Note session count, branches worked on, and commit messages
   - If a session has a `summary`, prefer it over `first_prompt`
   - For more detail on a specific session, run:
     ```bash
     claude-session-index show <session_id> --json
     ```
     Or search by topic:
     ```bash
     claude-session-index search "<topic>" --json
     ```
   - Check `subagent_session_ids` in session data — if present,
     the session used subagent-driven development. The subagent
     sessions contain the actual implementation details and commits.
     Drill into them for a complete picture.

5. **Present the data** in whatever format the user needs.
   Do NOT prescribe a fixed format — adapt to the request:
   - **Standup notes** → brief bullets per project
   - **Daily journal** → narrative form
   - **PR summary** → technical detail with files and commits
   - **Status update** → progress-oriented highlights
   - **Weekly recap** → grouped by day or by project
   - If the user didn't specify a format, ask what they want
