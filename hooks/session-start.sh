#!/usr/bin/env bash
# Verify claude-session-index is available
if ! command -v claude-session-index &>/dev/null; then
    echo "claude-session-index is not installed."
    echo "Install with: uv tool install --from git+https://github.com/lokkju/claude-session-index claude-session-index"
    exit 0
fi
