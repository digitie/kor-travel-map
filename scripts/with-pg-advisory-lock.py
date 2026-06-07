#!/usr/bin/env python3
"""Run a command while holding a PostgreSQL advisory lock."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from krtour.map.infra.advisory_lock import advisory_lock_key  # noqa: E402

LOCK_BUSY_EXIT_CODE = 3


def _psycopg_dsn(dsn: str) -> str:
    """Convert SQLAlchemy-flavored PostgreSQL URLs to psycopg URLs."""

    replacements = {
        "postgresql+asyncpg://": "postgresql://",
        "postgresql+psycopg://": "postgresql://",
        "postgresql+psycopg2://": "postgresql://",
    }
    for prefix, replacement in replacements.items():
        if dsn.startswith(prefix):
            return replacement + dsn.removeprefix(prefix)
    return dsn


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, help="Logical lock key.")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("KRTOUR_MAP_PG_DSN_SYNC") or os.environ.get("KRTOUR_MAP_PG_DSN"),
        help="PostgreSQL DSN used to hold the advisory lock.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for the lock instead of failing fast when it is busy.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("command is required after --")
    if not args.dsn:
        parser.error("--dsn or KRTOUR_MAP_PG_DSN_SYNC is required")
    return args


def _acquire_lock(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    lock_id: int,
    wait: bool,
) -> bool:
    with conn.cursor() as cur:
        if wait:
            cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
            return True
        cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
        row = cur.fetchone()
        return bool(row and row[0])


def _release_lock(conn: psycopg.Connection[tuple[object, ...]], *, lock_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    lock_id = advisory_lock_key(args.key)
    dsn = _psycopg_dsn(args.dsn)

    with psycopg.connect(dsn, autocommit=True) as conn:
        acquired = _acquire_lock(conn, lock_id=lock_id, wait=args.wait)
        if not acquired:
            print(
                f"advisory lock is already held: key={args.key!r}",
                file=sys.stderr,
            )
            return LOCK_BUSY_EXIT_CODE

        env = os.environ.copy()
        env["KRTOUR_MAP_MAINTENANCE_LOCK_HELD"] = "1"
        try:
            completed = subprocess.run(args.command, env=env, check=False)
            return completed.returncode
        finally:
            _release_lock(conn, lock_id=lock_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
