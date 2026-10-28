"""AMKernel command-line entry point."""

import argparse
from collections.abc import Sequence

from amkernel import __version__


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
    """Run the current package entry point."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
