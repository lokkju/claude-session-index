from __future__ import annotations

import json

from fastmcp import FastMCP

from claude_session_index.config import DB_PATH
from claude_session_index.db import get_session, get_stats, init_db, list_sessions
from claude_session_index.search import search_sessions


def create_server() -> FastMCP:
    """Create the MCP server with all tools registered."""
    mcp = FastMCP(
        "claude-session-index",
        instructions="Search and browse indexed Claude Code sessions.",
    )

    @mcp.tool()
    def search(
        query: str,
        project: str | None = None,
        since: str | None = None,
        limit: int = 10,
    ) -> str:
        """Search indexed sessions using full-text search with BM25 ranking.

        Args:
            query: Search query string (FTS5 syntax supported)
            project: Filter by project name
            since: Filter by date — duration like '7d' or ISO date like '2026-03-01'
            limit: Maximum results to return (default 10)
        """
        conn = init_db(DB_PATH)
        try:
            results = search_sessions(conn, query, project=project, since=since, limit=limit)
            return json.dumps(results, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def get_session_detail(session_id: str) -> str:
        """Get full details for a specific session.

        Args:
            session_id: The session UUID
        """
        conn = init_db(DB_PATH)
        try:
            result = get_session(conn, session_id)
            if result is None:
                return json.dumps({"error": f"Session {session_id} not found"})
            return json.dumps(result, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def list_indexed_sessions(
        project: str | None = None,
        since: str | None = None,
        branch: str | None = None,
        limit: int = 20,
        order_by: str = "modified_at",
    ) -> str:
        """List sessions with optional filters, no search query needed.

        Args:
            project: Filter by project name
            since: Filter by date — duration like '7d' or ISO date
            branch: Filter by git branch name
            limit: Maximum results (default 20)
            order_by: Sort field — 'modified_at', 'created_at', or 'message_count'
        """
        conn = init_db(DB_PATH)
        try:
            results = list_sessions(
                conn, project=project, since=since, branch=branch, limit=limit, order_by=order_by
            )
            return json.dumps(results, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def session_stats(since: str | None = None) -> str:
        """Get index statistics — total sessions, projects, activity by date.

        Args:
            since: Filter stats to sessions modified within this window
        """
        conn = init_db(DB_PATH)
        try:
            stats = get_stats(conn, since=since)
            return json.dumps(stats, indent=2)
        finally:
            conn.close()

    @mcp.tool()
    def resume_info(session_id: str) -> str:
        """Get resume command for a session.

        Args:
            session_id: The session UUID
        """
        conn = init_db(DB_PATH)
        try:
            result = get_session(conn, session_id)
            if result is None:
                return json.dumps({"error": f"Session {session_id} not found"})
            return json.dumps({
                "session_id": session_id,
                "project_path": result["project_path"],
                "resume_command": ["claude", "--resume", session_id],
            }, indent=2)
        finally:
            conn.close()

    return mcp


def main() -> None:
    """Entry point for the MCP stdio server."""
    server = create_server()
    server.run(transport="stdio")
