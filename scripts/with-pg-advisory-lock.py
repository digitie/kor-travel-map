#!/usr/bin/env python3
"""Run a command while holding a PostgreSQL advisory lock."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import BinaryIO

import psycopg

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kortravelmap.infra.advisory_lock import advisory_lock_key  # noqa: E402

LOCK_BUSY_EXIT_CODE = 3
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
    parser.add_argument("command", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("command is required after --")
    if not args.dsn:
        parser.error("--dsn or KOR_TRAVEL_MAP_PG_DSN_SYNC is required")
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


def _replay_output(source: BinaryIO, destination: BinaryIO) -> None:
    source.seek(0)
    with suppress(BrokenPipeError):
        while chunk := source.read(64 * 1024):
            destination.write(chunk)
        destination.flush()


def _run_locked_child(
    command: Sequence[str],
) -> int:
    """daemon effect와 연결된 child group이 자연 종료한 뒤에만 반환한다.

    Docker CLI의 local process를 죽이면 daemon container/exec가 계속될 수 있다.
    따라서 TERM/INT는 "호출자 detached"로만 기록하고 child에는 전달하지 않는다.
    wrapper는 자체 spool을 사용해 parent pipe 수명과도 분리하며, child group이
    사라질 때까지 PostgreSQL session lock을 유지한다.
    """

    child: subprocess.Popen[bytes] | None = None
    termination_signal: int | None = None

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
        with (
            tempfile.TemporaryFile(mode="w+b") as child_stdout,
            tempfile.TemporaryFile(mode="w+b") as child_stderr,
        ):
            child = subprocess.Popen(
                command,
                stdout=child_stdout,
                stderr=child_stderr,
                start_new_session=True,
            )
            process_group_id = child.pid
            try:
                while (
                    child.poll() is None
                    or _process_group_exists(process_group_id)
                ):
                    time.sleep(PROCESS_GROUP_POLL_SECONDS)
            finally:
                # 예상하지 못한 local 예외도 daemon effect와 lock을 분리하지 않는다.
                while (
                    child.poll() is None
                    or _process_group_exists(process_group_id)
                ):
                    time.sleep(PROCESS_GROUP_POLL_SECONDS)
            _replay_output(child_stdout, sys.stdout.buffer)
            _replay_output(child_stderr, sys.stderr.buffer)
            if termination_signal is not None:
                return 128 + termination_signal
            assert child.returncode is not None
            return child.returncode
    finally:
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
            return _run_locked_child(args.command)
        finally:
            _release_lock(conn, lock_id=lock_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
