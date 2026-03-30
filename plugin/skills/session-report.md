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
