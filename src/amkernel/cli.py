"""AMKernel server and distribution command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from amkernel import __version__
from amkernel.distribution import Client, DistributionError, DistributionManager, ProjectStatus
from amkernel.server import serve_stdio


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="amkernel",
        description="Install, verify, and run AMKernel for Coding Agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    for name in ("install", "status", "doctor", "update"):
        command = subparsers.add_parser(name)
        command.add_argument("--client", choices=("auto", "omp", "pi", "codex"), default="auto")
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--json", action="store_true")
        if name in {"install", "update"}:
            command.add_argument("--scope", choices=("project",))
            command.add_argument("--yes", action="store_true")
    uninstall = subparsers.add_parser("uninstall")
    uninstall.add_argument("--client", choices=("auto", "omp", "pi", "codex"), default="auto")
    uninstall.add_argument("--project", type=Path, default=Path.cwd())
    uninstall.add_argument("--scope", choices=("project",))
    uninstall.add_argument("--global", dest="global_scope", action="store_true")
    uninstall.add_argument("--yes", action="store_true")
    uninstall.add_argument("--json", action="store_true")
    return parser


def _confirm(message: str, assumed: bool) -> None:
    if assumed:
        return
    if not sys.stdin.isatty():
        raise DistributionError("confirmation required; rerun with --yes")
    answer = input(f"{message} [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise DistributionError("cancelled")


def _print_status(status: ProjectStatus, as_json: bool) -> None:
    if as_json:
        print(json.dumps(status.to_dict(), indent=2, sort_keys=True))
        return
    print(f"Runtime installed: {'yes' if status.runtime_installed else 'no'}")
    print(f"Skill installed: {'yes' if status.skill_installed else 'no'}")
    print(f"MCP configured: {'yes' if status.mcp_configured else 'no'}")
    print(f"Project: {status.project}")
    if status.client:
        print(f"Client: {status.client}")
    if status.runtime_version:
        print(f"Runtime version: {status.runtime_version}")
    if status.skill_version:
        print(f"Skill version: {status.skill_version}")
    if status.known_project_references:
        print("Known project references:")
        for project in status.known_project_references:
            print(f"- {project}")
        if status.references_truncated:
            print("- additional references omitted")
    if status.detail:
        print(f"Next action: {status.detail}")
    elif status.restart_required:
        print("Next action: restart the Coding Agent to load AMKernel")


def _client(manager: DistributionManager, requested: str) -> Client:
    return manager.select_client(requested)


def _require_automation_contract(args: argparse.Namespace) -> None:
    if not getattr(args, "yes", False):
        return
    if not args.json:
        raise DistributionError("automated mutations require --json")
    if args.command == "uninstall" and args.global_scope:
        return
    if args.client == "auto":
        raise DistributionError("automated project mutations require an explicit --client")
    if args.scope != "project":
        raise DistributionError("automated project mutations require --scope project")


def _print_plan(manager: DistributionManager, client: Client) -> None:
    print("Planned changes:", file=sys.stderr)
    for change in manager.planned_changes(client):
        print(f"- {change}", file=sys.stderr)


def _run_distribution(args: argparse.Namespace) -> int:
    manager = DistributionManager(args.project)
    _require_automation_contract(args)
    if args.command == "install":
        client = _client(manager, args.client)
        _print_plan(manager, client)
        _confirm(
            f"Install AMKernel globally and enable it for {manager.project}?",
            args.yes,
        )
        status = manager.install(client)
    elif args.command == "status":
        status_client = None if args.client == "auto" else _client(manager, args.client)
        status = manager.status(status_client)
    elif args.command == "doctor":
        status = manager.doctor(_client(manager, args.client))
    elif args.command == "update":
        client = _client(manager, args.client)
        _print_plan(manager, client)
        _confirm("Update the global AMKernel Runtime used by every enabled project?", args.yes)
        status = manager.update(client)
    elif args.command == "uninstall":
        if args.global_scope:
            references = sorted(manager.known_projects())
            retained_references = tuple(references[:100])
            reference_note = (
                " No enabled project references are registered."
                if not references
                else " Registered project references will stop working: "
                + ", ".join(references[:20])
            )
            print(reference_note.strip(), file=sys.stderr)
            _confirm("Remove the global AMKernel Runtime?" + reference_note, args.yes)
            manager.uninstall_global()
            status = replace(
                manager.status(None),
                known_project_references=retained_references,
                references_truncated=len(references) > len(retained_references),
            )
        else:
            _confirm(f"Disable AMKernel in {manager.project}?", args.yes)
            status = manager.uninstall_project(_client(manager, args.client))
    else:
        raise AssertionError(f"unexpected command: {args.command}")
    _print_status(status, args.json)
    return 0 if not status.detail or args.command == "uninstall" else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the MCP server by default, or an explicit distribution command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command:
        try:
            return _run_distribution(args)
        except DistributionError as error:
            if getattr(args, "json", False):
                message = str(error)[:4096]
                print(
                    json.dumps(
                        {"ok": False, "error": {"type": "DistributionError", "message": message}}
                    )
                )
            else:
                print(f"amkernel: {error}", file=sys.stderr)
            return 2
    try:
        return asyncio.run(serve_stdio())
    except KeyboardInterrupt:
        return 130
