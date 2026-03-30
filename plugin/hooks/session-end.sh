#!/usr/bin/env bash
# Index recent sessions on session end (non-blocking)
nohup uv run --project "$(dirname "$(dirname "$CLAUDE_PLUGIN_ROOT")")" claude-session-index index --since 1d >/dev/null 2>&1 &
