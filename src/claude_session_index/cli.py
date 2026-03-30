from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer

from claude_session_index.config import DB_PATH

app = typer.Typer(name="claude-session-index", help="Index and search Claude Code sessions.")


@app.command()
def index(
    full: bool = typer.Option(False, "--full", help="Full rebuild — reprocess all files"),
    since: str | None = typer.Option(
        None, "--since", help="Only process files modified within duration (e.g. 7d, 30d)"
    ),
) -> None:
    """Index Claude Code sessions into the database."""
    from claude_session_index.db import init_db
    from claude_session_index.indexer import index_all

    typer.echo("Indexing sessions...")
    conn = init_db(DB_PATH)
    try:
        stats = index_all(conn, full=full, since=since)
        typer.echo(f"Phase 1 (sessions-index.json): {stats['phase1_count']} sessions")
        typer.echo(f"Phase 2 (transcripts):         {stats['phase2_count']} sessions")
        typer.echo(f"Phase 3 (history):             {stats['phase3_count']} sessions")
        typer.echo(f"Total indexed:                 {stats['total']} sessions")
    finally:
        conn.close()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    project: str | None = typer.Option(None, "--project", help="Filter by project name"),
    since: str | None = typer.Option(None, "--since", help="Filter by date"),
    limit: int = typer.Option(10, "--limit", help="Max results"),
    output_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Search indexed sessions."""
    from claude_session_index.db import init_db
    from claude_session_index.search import search_sessions

    conn = init_db(DB_PATH)
    try:
        results = search_sessions(conn, query, project=project, since=since, limit=limit)
    finally:
        conn.close()

    if output_json:
        typer.echo(json.dumps(results, indent=2))
        return

    if not results:
        typer.echo("No results found.")
        return

    # Formatted table
    typer.echo(f"{'SESSION ID':<40} {'PROJECT':<20} {'PROMPT':<40} {'DATE':<12} {'SCORE':<8}")
    typer.echo("-" * 120)
    for r in results:
        sid = r["session_id"][:36]
        proj = (r["project_name"] or "")[:18]
        prompt = (r["first_prompt"] or "")[:38]
        date = (r["created_at"] or "")[:10]
        score = f"{r['score']:.2f}" if r.get("score") else ""
        typer.echo(f"{sid:<40} {proj:<20} {prompt:<40} {date:<12} {score:<8}")


@app.command()
def show(
    session_id: str = typer.Argument(..., help="Session UUID"),
    output_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show full details for a session, including subagent session IDs."""
    from claude_session_index.db import get_session, init_db

    conn = init_db(DB_PATH)
    try:
        result = get_session(conn, session_id)
    finally:
        conn.close()

    if result is None:
        typer.echo(f"Session {session_id} not found.")
        raise typer.Exit(1)

    if output_json:
        typer.echo(json.dumps(result, indent=2))
        return

    typer.echo(f"Session:  {result['session_id']}")
    typer.echo(f"Project:  {result['project_name']} ({result['project_path']})")
    typer.echo(f"Branch:   {result['git_branch']}")
    typer.echo(f"Created:  {result['created_at']}")
    typer.echo(f"Modified: {result['modified_at']}")
    typer.echo(f"Messages: {result['message_count']}")
    typer.echo(f"Source:   {result['source']}")
    if result.get("parent_session_id"):
        typer.echo(f"Parent:   {result['parent_session_id']}")
    typer.echo()

    if result.get("summary"):
        typer.echo(f"## Summary\n{result['summary']}\n")

    if result["first_prompt"]:
        typer.echo(f"## First Prompt\n{result['first_prompt']}\n")

    if result["commit_messages"]:
        typer.echo("## Commits")
        for cm in result["commit_messages"].split("\n"):
            if cm.strip():
                typer.echo(f"  {cm.strip()}")
        typer.echo()

    if result["files_changed"]:
        typer.echo("## Files Changed")
        for f in result["files_changed"].split("\n"):
            if f.strip():
                typer.echo(f"  {f.strip()}")
        typer.echo()

    if result.get("subagent_session_ids"):
        typer.echo(f"## Subagents ({len(result['subagent_session_ids'])})")
        for sid in result["subagent_session_ids"]:
            typer.echo(f"  {sid}")
        typer.echo()

    if result["user_prompts"]:
        typer.echo("## User Prompts")
        typer.echo(result["user_prompts"][:2000])
        if len(result["user_prompts"]) > 2000:
            typer.echo("  ... (truncated)")
        typer.echo()

    if result["commands_run"]:
        typer.echo("## Commands Run")
        for cmd in result["commands_run"].split("\n"):
            if cmd.strip():
                typer.echo(f"  $ {cmd.strip()}")


@app.command()
def stats(
    since: str | None = typer.Option(None, "--since", help="Filter by date"),
    output_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show index statistics."""
    from claude_session_index.db import get_stats, init_db

    conn = init_db(DB_PATH)
    try:
        result = get_stats(conn, since=since)
    finally:
        conn.close()

    if output_json:
        typer.echo(json.dumps(result, indent=2))
        return

    typer.echo(f"Total sessions: {result['total_sessions']}")
    typer.echo(f"Total projects: {result['total_projects']}")
    typer.echo()
    typer.echo("Sessions by project:")
    for proj, cnt in result["sessions_by_project"].items():
        typer.echo(f"  {proj}: {cnt}")
    if result["sessions_by_date"]:
        typer.echo()
        typer.echo("Recent activity:")
        for date, cnt in list(result["sessions_by_date"].items())[:10]:
            typer.echo(f"  {date}: {cnt}")


@app.command()
def report(
    since: str = typer.Option("1d", "--since", help="Start of range (duration or ISO date)"),
    until: str | None = typer.Option(None, "--until", help="End of range (ISO date)"),
    project_path: str | None = typer.Option(
        None, "--project-path", help="Filter to sessions under this path prefix"
    ),
    limit: int = typer.Option(100, "--limit", help="Max sessions per project"),
    output_json: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Report sessions worked on within a date range, grouped by project."""
    from claude_session_index.db import init_db, report_sessions

    conn = init_db(DB_PATH)
    try:
        result = report_sessions(
            conn, since=since, until=until,
            project_path_prefix=project_path, limit=limit,
        )
    finally:
        conn.close()

    if output_json:
        typer.echo(json.dumps(result, indent=2))
        return

    if not result["projects"]:
        typer.echo("No sessions found for this range.")
        return

    typer.echo(f"# Work Report (since {since})\n")

    for proj_name, sessions in result["projects"].items():
        typer.echo(f"## {proj_name} ({len(sessions)} sessions)\n")
        for s in sessions:
            branch = s["git_branch"] or "unknown"
            start = (s["created_at"] or "")[:16].replace("T", " ")
            end = (s["modified_at"] or "")[:16].replace("T", " ")
            msgs = s["message_count"]
            title = s["summary"] or s["first_prompt"] or "(no prompt)"
            typer.echo(
                f"### {branch} — {start} to {end} ({msgs} messages)"
            )
            typer.echo(title)

            if s["files_changed"]:
                files_str = ", ".join(
                    Path(f).name for f in s["files_changed"][:10]
                )
                typer.echo(f"- Files: {files_str}")

            if s["commit_messages"]:
                for cm in s["commit_messages"]:
                    typer.echo(f"- Commit: {cm}")

            typer.echo()


@app.command()
def serve() -> None:
    """Start the MCP stdio server."""
    from claude_session_index.server import main

    main()


@app.command()
def timer(
    action: str = typer.Argument(..., help="install or uninstall"),
) -> None:
    """Manage systemd user timer for periodic indexing."""
    systemd_dir = Path(__file__).parent.parent.parent / "systemd"
    user_systemd = Path.home() / ".config" / "systemd" / "user"

    service_name = "claude-session-index.service"
    timer_name = "claude-session-index.timer"

    if action == "install":
        user_systemd.mkdir(parents=True, exist_ok=True)
        service_src = systemd_dir / service_name
        timer_src = systemd_dir / timer_name

        if not service_src.exists() or not timer_src.exists():
            typer.echo(f"Error: systemd unit files not found in {systemd_dir}", err=True)
            raise typer.Exit(1)

        service_dst = user_systemd / service_name
        timer_dst = user_systemd / timer_name

        # Symlink unit files
        for src, dst in [(service_src, service_dst), (timer_src, timer_dst)]:
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(src.resolve())

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", timer_name], check=True)
        typer.echo(f"Timer installed and started. Check with: systemctl --user status {timer_name}")

    elif action == "uninstall":
        subprocess.run(["systemctl", "--user", "stop", timer_name], check=False)
        subprocess.run(["systemctl", "--user", "disable", timer_name], check=False)
        for name in [service_name, timer_name]:
            target = user_systemd / name
            if target.exists() or target.is_symlink():
                target.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        typer.echo("Timer uninstalled.")

    else:
        typer.echo("Usage: claude-session-index timer [install|uninstall]", err=True)
        raise typer.Exit(1)
