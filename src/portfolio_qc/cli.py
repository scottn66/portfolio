"""Command-line entry point for portfolio-qc."""

from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import version
from pathlib import Path

from portfolio_qc.links import (
    DEFAULT_BASE,
    DEFAULT_MAX_PAGES,
    check_links,
    exit_code,
    format_summary,
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-pages must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("max-pages must be at least 1")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="portfolio-qc",
        description="Backend quality control for scottn66.github.io",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('portfolio-qc')}",
    )
    subparsers = parser.add_subparsers(dest="command")
    links = subparsers.add_parser(
        "links",
        help="Crawl a site and check internal and external links",
        description=(
            "Crawl same-origin HTML pages and check href and src links. "
            "Exits 1 when an internal link is not status 200 after redirects."
        ),
    )
    links.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help=f"Page to start from (default: {DEFAULT_BASE})",
    )
    links.add_argument(
        "--max-pages",
        type=_positive_int,
        default=DEFAULT_MAX_PAGES,
        help=f"Maximum same-origin HTML pages to crawl (default: {DEFAULT_MAX_PAGES})",
    )
    links.add_argument(
        "--json",
        dest="json_path",
        default=None,
        help="Write the JSON report to this path",
    )
    return parser


def _cmd_links(base: str, max_pages: int, json_path: str | None) -> int:
    try:
        report = check_links(base, max_pages=max_pages)
    except ValueError as exc:
        print(f"portfolio-qc: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(format_summary(report))
    if json_path is not None:
        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n"
        try:
            Path(json_path).write_text(payload, encoding="utf-8")
        except OSError as exc:
            print(f"portfolio-qc: {exc}", file=sys.stderr)
            return 2
    return exit_code(report)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the selected command.

    With no command, exits 0. ``--version`` prints the installed version.
    ``links`` returns 1 only when an internal link is broken.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "links":
        return _cmd_links(args.base, args.max_pages, args.json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
