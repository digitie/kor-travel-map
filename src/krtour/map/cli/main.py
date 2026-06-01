"""``krtour.map.cli.main`` — ``krtour-map`` CLI entry-point (ADR-022/039).

Sprint 4 §2.8 CLI 골격. 본 PR은 read-only ``status`` 명령 + argparse 프레임을
제공한다. mutate 명령(``import``/``dedup-merge``, mutex 적용)은 provider record
source 주입 설계가 정해진 뒤 후속 PR.

명령
----
- ``krtour-map status`` — 운영 현황 카운트 출력 (read-only, mutex 없음).

engine은 ``KrtourMapSettings.pg_dsn``에서 만들고 호출 종료 시 dispose한다
(ADR-004 — 호출자 소유). DSN은 ``--dsn`` 또는 ``KRTOUR_MAP_PG_DSN`` 환경변수.

ADR 참조
--------
- ADR-002 — async-only (CLI는 ``asyncio.run``으로 진입)
- ADR-022 — CLI 명령 이름 ``krtour-map``
- ADR-039 — CLI mutex (mutate 명령은 advisory lock; status는 read-only)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from krtour.map.client import AsyncKrtourMapClient
from krtour.map.infra.db import make_async_engine
from krtour.map.settings import KrtourMapSettings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from krtour.map.infra.status_repo import StatusCounts

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    """``krtour-map`` argparse 파서 구성."""
    parser = argparse.ArgumentParser(
        prog="krtour-map",
        description="python-krtour-map 운영 CLI (지도 feature 적재/조회).",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="PostgreSQL async DSN (미지정 시 KRTOUR_MAP_PG_DSN 환경변수/기본값).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status_p = sub.add_parser(
        "status", help="운영 현황 카운트 출력 (read-only)."
    )
    status_p.set_defaults(func=_cmd_status)

    return parser


def _format_status(counts: StatusCounts) -> str:
    lines = [
        "features:",
        f"  total={counts.features_total} "
        f"active={counts.features_active} inactive={counts.features_inactive}",
    ]
    if counts.features_by_kind:
        kinds = ", ".join(
            f"{k}={v}" for k, v in sorted(counts.features_by_kind.items())
        )
        lines.append(f"  by_kind: {kinds}")
    if counts.source_records_by_provider:
        provs = ", ".join(
            f"{k}={v}"
            for k, v in sorted(counts.source_records_by_provider.items())
        )
        lines.append(f"source_records by_provider: {provs}")
    if counts.import_jobs_by_state:
        jobs = ", ".join(
            f"{k}={v}" for k, v in sorted(counts.import_jobs_by_state.items())
        )
        lines.append(f"import_jobs by_state: {jobs}")
    if counts.dedup_queue_by_status:
        dq = ", ".join(
            f"{k}={v}" for k, v in sorted(counts.dedup_queue_by_status.items())
        )
        lines.append(f"dedup_review_queue by_status: {dq}")
    return "\n".join(lines)


def _resolve_dsn(args: argparse.Namespace) -> str:
    if args.dsn:
        return str(args.dsn)
    return KrtourMapSettings().pg_dsn.get_secret_value()


async def _cmd_status(args: argparse.Namespace) -> int:
    engine = make_async_engine(_resolve_dsn(args))
    try:
        async with AsyncKrtourMapClient(engine) as client:
            counts = await client.status_counts()
        print(_format_status(counts))
    finally:
        await engine.dispose()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry-point. 반환값은 process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code: int = asyncio.run(args.func(args))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
