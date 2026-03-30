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
   - If more detail is needed for a session, call `get_session_detail`
     with the `session_id` to get full user prompts, assistant text,
     and commands run
   - Check `subagent_session_ids` — if present, the session used
     subagent-driven development. Drill into subagent sessions
     for the actual implementation details and commits.

5. **Present the data** in whatever format the user needs.
   Do NOT prescribe a fixed format — adapt to the request:
   - **Standup notes** → brief bullets per project
   - **Daily journal** → narrative form
   - **PR summary** → technical detail with files and commits
   - **Status update** → progress-oriented highlights
   - **Weekly recap** → grouped by day or by project
   - If the user didn't specify a format, ask what they want
