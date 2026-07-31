#!/usr/bin/env python3
"""Run a command while holding a PostgreSQL advisory lock."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from types import FrameType

import psycopg

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kortravelmap.infra.advisory_lock import advisory_lock_key  # noqa: E402

LOCK_BUSY_EXIT_CODE = 3
DEFAULT_TERMINATE_GRACE_SECONDS = 5.0
PROCESS_GROUP_POLL_SECONDS = 0.05


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
        default=os.environ.get("KOR_TRAVEL_MAP_PG_DSN_SYNC")
        or os.environ.get("KOR_TRAVEL_MAP_PG_DSN"),
        help="PostgreSQL DSN used to hold the advisory lock.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for the lock instead of failing fast when it is busy.",
    )
    parser.add_argument(
        "--terminate-grace-seconds",
        type=float,
        default=DEFAULT_TERMINATE_GRACE_SECONDS,
        help="Seconds to wait after TERM/INT before killing the child process group.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("command is required after --")
    if not args.dsn:
        parser.error("--dsn or KOR_TRAVEL_MAP_PG_DSN_SYNC is required")
    if args.terminate_grace_seconds <= 0:
        parser.error("--terminate-grace-seconds must be greater than 0")
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


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_process_group(process_group_id: int, signal_number: int) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process_group_id, signal_number)


def _run_locked_child(
    command: Sequence[str],
    *,
    terminate_grace_seconds: float,
) -> int:
    """신호 뒤 child group을 완전히 종료한 뒤에만 반환한다."""

    child: subprocess.Popen[bytes] | None = None
    termination_signal: int | None = None
    termination_deadline: float | None = None
    kill_sent = False

    def _capture_signal(
        signal_number: int,
        _frame: FrameType | None,
    ) -> None:
        nonlocal termination_signal
        if termination_signal is None:
            termination_signal = signal_number

    previous_handlers = {
        signal_number: signal.signal(signal_number, _capture_signal)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        child = subprocess.Popen(command, start_new_session=True)
        process_group_id = child.pid
        while True:
            child_returncode = child.poll()
            group_exists = _process_group_exists(process_group_id)
            if termination_signal is None:
                if child_returncode is not None and not group_exists:
                    return child_returncode
            else:
                if termination_deadline is None:
                    _signal_process_group(process_group_id, termination_signal)
                    termination_deadline = (
                        time.monotonic() + terminate_grace_seconds
                    )
                elif (
                    not kill_sent
                    and group_exists
                    and time.monotonic() >= termination_deadline
                ):
                    _signal_process_group(process_group_id, signal.SIGKILL)
                    kill_sent = True
                if child_returncode is not None and not group_exists:
                    return 128 + termination_signal
            time.sleep(PROCESS_GROUP_POLL_SECONDS)
    finally:
        if child is not None:
            if _process_group_exists(child.pid):
                _signal_process_group(child.pid, signal.SIGKILL)
            if child.poll() is None:
                child.wait()
        for signal_number, previous_handler in previous_handlers.items():
            signal.signal(signal_number, previous_handler)


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

        try:
            return _run_locked_child(
                args.command,
                terminate_grace_seconds=args.terminate_grace_seconds,
            )
        finally:
            _release_lock(conn, lock_id=lock_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
