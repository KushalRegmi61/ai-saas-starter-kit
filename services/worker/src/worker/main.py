"""Minimal background-worker CLI.

Second consumer of the workspace-shared `ai-saas-shared` package: validates
object keys with the same traversal guard the API enforces, so the two can
never drift apart. Structured JSON logging only (AGENTS.md §4).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from shared.keys import has_path_traversal

logger = logging.getLogger("worker")


def validate_key(key: str) -> int:
    """Exit 0 + OK for a clean key, exit 1 + REJECTED for traversal."""
    if has_path_traversal(key):
        logger.warning(json.dumps({"event": "key_rejected", "key": key}))
        sys.stdout.write("REJECTED\n")
        return 1
    sys.stdout.write("OK\n")
    return 0


def health() -> int:
    """Report worker health as JSON."""
    sys.stdout.write(json.dumps({"status": "ok", "service": "worker"}) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (returns exit code; `cli` raises SystemExit)."""
    parser = argparse.ArgumentParser(prog="worker", description="Background worker CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    key_parser = sub.add_parser("validate-key", help="Validate one object key")
    key_parser.add_argument("key", help="Object key to validate")
    sub.add_parser("health", help="Report worker health")
    args = parser.parse_args(argv)
    if args.command == "validate-key":
        return validate_key(args.key)
    return health()


def cli() -> None:
    """Console-script entry point."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    raise SystemExit(main())
