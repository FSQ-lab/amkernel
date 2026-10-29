"""AMKernel command-line entry point."""

import argparse
import asyncio
from collections.abc import Sequence

from amkernel import __version__
from amkernel.server import serve_stdio


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="amkernel",
        description="Persistent Python execution for agentic automation.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the official MCP stdio server."""
    parser = build_parser()
    parser.parse_args(argv)
    try:
        return asyncio.run(serve_stdio())
    except KeyboardInterrupt:
        return 130
