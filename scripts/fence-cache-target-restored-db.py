#!/usr/bin/env python3
"""Restore swap env를 쓰기 전에 복원 DB cache-target stream을 fence한다."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Sequence

from sqlalchemy.engine import make_url

from kortravelmap.infra.cache_target_restore import (
    fence_restored_cache_target_streams,
    list_cache_target_restore_references,
)
from kortravelmap.infra.db import (
    make_async_engine,
    make_async_session_factory,
    normalize_async_dsn,
)

_DATABASE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def restored_dsn(live_dsn: str, restored_database: str) -> str:
    """인증·host는 유지하고 database만 검증된 복원 이름으로 바꾼다."""

    if not _DATABASE.fullmatch(restored_database):
        raise ValueError("restore app database 식별자가 유효하지 않습니다.")
    url = make_url(normalize_async_dsn(live_dsn))
    if url.database == restored_database:
        raise ValueError("live DB와 restore app DB는 달라야 합니다.")
    return url.set(database=restored_database).render_as_string(
        hide_password=False
    )


async def _run(
    *,
    live_dsn: str,
    restored_database: str,
    command_id: int,
    input_digest: str,
) -> int:
    restore_dsn = restored_dsn(live_dsn, restored_database)
    live_engine = make_async_engine(live_dsn, pool_size=1, max_overflow=0)
    restore_engine = make_async_engine(restore_dsn, pool_size=1, max_overflow=0)
    live_factory = make_async_session_factory(live_engine)
    restore_factory = make_async_session_factory(restore_engine)
    try:
        async with live_factory() as live_session:
            live_references = await list_cache_target_restore_references(
                live_session
            )
        async with restore_factory.begin() as restore_session:
            results = await fence_restored_cache_target_streams(
                restore_session,
                live_references=live_references,
                host_command_id=command_id,
                host_input_digest=input_digest,
            )
    finally:
        await restore_engine.dispose()
        await live_engine.dispose()
    print(f"cache_target_restore_fences={len(results)}")
    return os.EX_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restored-database", required=True)
    parser.add_argument("--command-id", type=int, required=True)
    parser.add_argument("--input-digest", required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command_id <= 0:
        parser.error("--command-id는 양의 정수여야 합니다.")
    if not _HEX64.fullmatch(args.input_digest):
        parser.error("--input-digest는 lowercase SHA-256 hex여야 합니다.")
    live_dsn = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    if not live_dsn:
        parser.error("KOR_TRAVEL_MAP_PG_DSN이 필요합니다.")
    return asyncio.run(
        _run(
            live_dsn=live_dsn,
            restored_database=args.restored_database,
            command_id=args.command_id,
            input_digest=args.input_digest,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
