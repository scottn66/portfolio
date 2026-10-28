"""Command-line entry point for portfolio-qc."""

from __future__ import annotations

import argparse
from importlib.metadata import version


def main(argv: list[str] | None = None) -> int:
    """Parse arguments. ``--version`` prints the installed version and exits."""
    parser = argparse.ArgumentParser(
        prog="portfolio-qc",
        description="Backend quality control for scottn66.github.io",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('portfolio-qc')}",
    )
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
