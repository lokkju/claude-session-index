from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from claude_session_index.config import (
    ASSISTANT_BLOCK_CAP,
    ASSISTANT_TEXT_CAP,
    COMMAND_MAX_LEN,
    MAX_FILE_SIZE,
    MAX_LINES_PER_SESSION,
    MIN_PROMPT_LEN,
    USER_PROMPTS_CAP,
)


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
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    commit_messages: list[str] = field(default_factory=list)
    message_count: int = 0
    parent_session_id: str = ""


_COMMIT_INLINE_RE = re.compile(r'git\s+commit\s+.*?-m\s+["\'](.+?)["\']', re.DOTALL)
_COMMIT_HEREDOC_RE = re.compile(r"cat\s+<<\s*'?EOF'?\n(.+?)\nEOF", re.DOTALL)


def extract_session(file_path: Path) -> SessionData | None:
    """Extract session data from a JSONL transcript file."""
    if file_path.stat().st_size > MAX_FILE_SIZE:
        return None

    session_id = ""
    project_path = ""
    project_name = ""
    git_branch = ""
    created_at = ""
    modified_at = ""
    first_prompt = ""
    user_prompts_parts: list[str] = []
    user_prompts_len = 0
    assistant_parts: list[str] = []
    assistant_len = 0
    files_changed: set[str] = set()
    commands_run: list[str] = []
    commit_messages: list[str] = []
    message_count = 0

    with open(file_path) as f:
        for line_num, line in enumerate(f, 1):
            if line_num > MAX_LINES_PER_SESSION:
                break

            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")

            # File history snapshots — extract tracked file paths
            if entry_type == "file-history-snapshot":
                snapshot = entry.get("snapshot", {})
                for fp in snapshot.get("trackedFileBackups", {}).keys():
                    files_changed.add(fp)
                continue

            # Skip non-message types (system, etc.)
            if entry_type not in ("user", "assistant"):
                # Still grab metadata if present
                if not session_id and entry.get("sessionId"):
                    session_id = entry["sessionId"]
                if not project_path and entry.get("cwd"):
                    project_path = entry["cwd"]
                    project_name = Path(project_path).name
                if not git_branch and entry.get("gitBranch"):
                    git_branch = entry["gitBranch"]
                if not created_at and entry.get("timestamp"):
                    created_at = entry["timestamp"]
                if entry.get("timestamp"):
                    modified_at = entry["timestamp"]
                continue

            # Extract metadata from message entries
            if not session_id and entry.get("sessionId"):
                session_id = entry["sessionId"]
            if not project_path and entry.get("cwd"):
                project_path = entry["cwd"]
                project_name = Path(project_path).name
            if not git_branch and entry.get("gitBranch"):
                git_branch = entry["gitBranch"]
            if not created_at and entry.get("timestamp"):
                created_at = entry["timestamp"]
            if entry.get("timestamp"):
                modified_at = entry["timestamp"]

            message_count += 1

            if entry_type == "user":
                msg = entry.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) >= MIN_PROMPT_LEN:
                    if not content.startswith("<"):
                        if not first_prompt:
                            first_prompt = content[:500]
                        if user_prompts_len < USER_PROMPTS_CAP:
                            user_prompts_parts.append(content)
                            user_prompts_len += len(content)

            elif entry_type == "assistant":
                msg = entry.get("message", {})
                content_blocks = msg.get("content", [])
                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type", "")

                        if block_type == "text":
                            text = block.get("text", "")
                            if text and assistant_len < ASSISTANT_TEXT_CAP:
                                chunk = text[:ASSISTANT_BLOCK_CAP]
                                assistant_parts.append(chunk)
                                assistant_len += len(chunk)

                        elif block_type == "tool_use":
                            _extract_tool_use(block, files_changed, commands_run, commit_messages)

    if not session_id:
        session_id = file_path.stem

    if not created_at:
        return None

    return SessionData(
        session_id=session_id,
        project_path=project_path,
        project_name=project_name,
        git_branch=git_branch,
        created_at=created_at,
        modified_at=modified_at or created_at,
        first_prompt=first_prompt,
        user_prompts="\n".join(user_prompts_parts)[:USER_PROMPTS_CAP],
        assistant_text="\n".join(assistant_parts)[:ASSISTANT_TEXT_CAP],
        files_changed=sorted(files_changed),
        commands_run=commands_run,
        commit_messages=commit_messages,
        message_count=message_count,
    )


def _extract_tool_use(
    block: dict,
    files_changed: set[str],
    commands_run: list[str],
    commit_messages: list[str],
) -> None:
    """Extract files, commands, and commit messages from a tool_use block."""
    tool_name = block.get("name", "")
    tool_input = block.get("input", {})

    if tool_name in ("Read", "Write", "Edit"):
        fp = tool_input.get("file_path", "")
        if fp:
            files_changed.add(fp)
    elif tool_name == "Glob":
        path = tool_input.get("path", "")
        if path:
            files_changed.add(path)
    elif tool_name == "Grep":
        path = tool_input.get("path", "")
        if path:
            files_changed.add(path)
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd:
            # Extract commit messages from full command before truncation
            _extract_commit_message(cmd, commit_messages)
            if len(cmd) <= COMMAND_MAX_LEN:
                commands_run.append(cmd)


def _extract_commit_message(cmd: str, messages: list[str]) -> None:
    """Extract commit message from a git commit command string."""
    if "git commit" not in cmd:
        return
    m = _COMMIT_HEREDOC_RE.search(cmd)
    if m:
        messages.append(m.group(1).strip())
        return
    m = _COMMIT_INLINE_RE.search(cmd)
    if m:
        messages.append(m.group(1).strip())
