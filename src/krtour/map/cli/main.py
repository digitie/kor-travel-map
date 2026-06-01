"""``krtour.map.cli.main`` — ``krtour-map`` CLI entry-point (ADR-022/039).

Sprint 4 §2.8 CLI. read-only ``status`` + mutate ``import``(MOIS Step A bulk 적재)
명령을 제공한다.

명령
----
- ``krtour-map status`` — 운영 현황 카운트 출력 (read-only, mutex 없음).
- ``krtour-map import mois <records-file>`` — provider가 export한 NDJSON snapshot을
  읽어 MOIS 인허가 feature를 적재한다 (Step A bulk). ``run_mois_license_bulk_job``이
  ``import:python-mois-api:<dataset>`` advisory lock으로 단일 워커 직렬화(ADR-039)
  + ``import_jobs`` 추적(ADR-011)을 수행하므로 CLI에서 별도 mutex를 다시 감싸지
  않는다(같은 키). 다른 워커가 적재 중이면 skip(exit 3).

``import``은 ADR-006상 provider 라이브러리를 런타임 import하지 않고, provider가
외부에서 만든 **provider-neutral NDJSON 파일**(``cli.records``)을 record source로
주입받는다. ``--geocoder-url``을 주면 좌표 → bjd_code 보강(kraddr-geo REST)을 켠다.

engine은 ``KrtourMapSettings.pg_dsn``에서 만들고 호출 종료 시 dispose한다
(ADR-004 — 호출자 소유). DSN은 ``--dsn`` 또는 ``KRTOUR_MAP_PG_DSN`` 환경변수.

ADR 참조
--------
- ADR-002 — async-only (CLI는 ``asyncio.run``으로 진입)
- ADR-006 — provider 라이브러리 미import (record source는 NDJSON 주입)
- ADR-011 — ``import_jobs`` 작업 추적
- ADR-022 — CLI 명령 이름 ``krtour-map``
- ADR-039 — CLI mutex (mutate 명령은 advisory lock; status는 read-only)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from krtour.map.cli.records import iter_mois_license_records
from krtour.map.client import AsyncKrtourMapClient
from krtour.map.infra.db import make_async_engine
from krtour.map.mois import DEFAULT_BATCH_SIZE as MOIS_DEFAULT_BATCH_SIZE
from krtour.map.providers.mois import DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK
from krtour.map.settings import KrtourMapSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from krtour.map.geocoding import ReverseGeocoder
    from krtour.map.infra.status_repo import StatusCounts
    from krtour.map.mois import MoisBulkJobResult

__all__ = ["main", "build_parser"]

# import mois가 다른 워커의 적재와 충돌(advisory lock 미획득)해 skip된 경우의
# exit code — 실패(1)와 구분해 운영 스크립트가 재시도/대기 판단에 쓴다.
_EXIT_IMPORT_SKIPPED = 3


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

    import_p = sub.add_parser(
        "import",
        help="provider snapshot(NDJSON)을 읽어 feature 적재 (mutate, advisory lock).",
    )
    import_sub = import_p.add_subparsers(dest="provider", required=True)
    mois_p = import_sub.add_parser(
        "mois",
        help="MOIS 인허가 Step A bulk 적재 (NDJSON snapshot → import_jobs 추적).",
    )
    mois_p.add_argument(
        "records_file",
        help="MOIS 인허가 NDJSON snapshot 파일(한 줄당 JSON object). cli.records 계약.",
    )
    mois_p.add_argument(
        "--dataset-key",
        default=MOIS_DATASET_KEY_BULK,
        help=f"적재 dataset_key (기본 {MOIS_DATASET_KEY_BULK}).",
    )
    mois_p.add_argument(
        "--batch-size",
        type=int,
        default=MOIS_DEFAULT_BATCH_SIZE,
        help=f"streaming 배치 크기 (기본 {MOIS_DEFAULT_BATCH_SIZE}).",
    )
    mois_p.add_argument(
        "--geocoder-url",
        default=None,
        help=(
            "kraddr-geo REST base URL(예: http://127.0.0.1:8888). 주면 좌표 → "
            "bjd_code 역지오코딩 보강을 켠다. 미지정 시 mois legal_dong_code만 사용."
        ),
    )
    mois_p.add_argument(
        "--source-checksum",
        default=None,
        help="snapshot 체크섬(import_jobs.source_checksum 기록용, 선택).",
    )
    mois_p.set_defaults(func=_cmd_import_mois)

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


@asynccontextmanager
async def _reverse_geocoder_for(
    base_url: str | None,
) -> AsyncIterator[ReverseGeocoder | None]:
    """``--geocoder-url`` → kraddr-geo ``ReverseGeocoder`` (없으면 ``None``).

    httpx client 수명은 본 컨텍스트가 소유한다(ADR-002). ``base_url``엔 ``/v2``를
    붙이지 않는다 — ``KraddrGeoRestClient``가 ``base_path``로 붙인다.
    """
    if base_url is None:
        yield None
        return
    import httpx

    from krtour.map.geocoding import (
        KraddrGeoRestClient,
        kraddr_geo_reverse_geocoder,
    )

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        yield kraddr_geo_reverse_geocoder(KraddrGeoRestClient(http))


def _format_bulk_result(result: MoisBulkJobResult) -> str:
    if not result.acquired:
        return (
            "import: skipped — 다른 워커가 이미 적재 중 (import advisory lock 미획득)."
        )
    assert result.sync is not None  # acquired=True면 항상 채워짐
    load = result.sync.load
    job_id = result.job.job_id if result.job is not None else "?"
    return "\n".join(
        [
            f"import: done (job_id={job_id})",
            f"  features: inserted={load.features_inserted} "
            f"updated={load.features_updated}",
            f"  source_records: inserted={load.source_records_inserted}",
            f"  source_links: inserted={load.source_links_inserted} "
            f"updated={load.source_links_updated}",
            f"  deactivated (snapshot prune): {result.sync.deactivated}",
        ]
    )


async def _cmd_import_mois(args: argparse.Namespace) -> int:
    records_path = Path(args.records_file)
    if not records_path.is_file():  # noqa: ASYNC240  # 1회 stat — 진입 검증
        print(f"import: records 파일 없음 — {records_path}", file=sys.stderr)
        return 2
    engine = make_async_engine(_resolve_dsn(args))
    try:
        records = iter_mois_license_records(records_path)
        async with (
            _reverse_geocoder_for(args.geocoder_url) as geocoder,
            AsyncKrtourMapClient(engine) as client,
        ):
            result = await client.run_mois_license_bulk_job(
                records,
                fetched_at=datetime.now(UTC),
                dataset_key=args.dataset_key,
                reverse_geocoder=geocoder,
                source_checksum=args.source_checksum,
                batch_size=args.batch_size,
            )
        print(_format_bulk_result(result))
        return 0 if result.acquired else _EXIT_IMPORT_SKIPPED
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry-point. 반환값은 process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code: int = asyncio.run(args.func(args))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
