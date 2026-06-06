"""``krtour.map.cli.main`` — ``krtour-map`` CLI entry-point (ADR-022/039).

Sprint 4 §2.8 CLI. read-only ``status`` + mutate ``import``(MOIS Step A bulk 적재)
명령을 제공한다.

명령
----
- ``krtour-map status`` — 운영 현황 카운트 출력 (read-only, mutex 없음).
- ``krtour-map consistency-report`` — ADR-033 F1~F8 정합성 dry-run Markdown/JSON
  리포트 출력 (read-only 기본, mutex 없음).
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

from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.cli.consistency_report import (
    ConsistencyReportOptions,
    load_file_object_refs,
    render_consistency_report_json,
    render_consistency_report_markdown,
)
from krtour.map.cli.mutex import dedup_merge_lock_key, try_mutex_lock
from krtour.map.cli.records import iter_mois_license_records
from krtour.map.client import AsyncKrtourMapClient
from krtour.map.core import kst_now
from krtour.map.infra.consistency import (
    DEDUP_PENDING_WARN_THRESHOLD,
    DEDUP_SCORE_REGRESSION_WARN_POINTS,
    PROVIDER_LAST_SUCCESS_WARN_SECONDS,
)
from krtour.map.infra.db import make_async_engine
from krtour.map.infra.merge_repo import MergeError
from krtour.map.infra.status_repo import dedup_fp_stats
from krtour.map.mois import DEFAULT_BATCH_SIZE as MOIS_DEFAULT_BATCH_SIZE
from krtour.map.providers.mois import DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK
from krtour.map.providers.mois import DATASET_KEY_HISTORY as MOIS_DATASET_KEY_HISTORY
from krtour.map.settings import KrtourMapSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from krtour.map.geocoding import AddressResolver, ReverseGeocoder
    from krtour.map.infra.merge_repo import MergeOutcome
    from krtour.map.infra.status_repo import StatusCounts
    from krtour.map.mois import (
        MoisBulkJobResult,
        MoisClosedJobResult,
        MoisIncrementalJobResult,
    )

__all__ = ["main", "build_parser"]

# mutate 명령이 다른 워커와 충돌(advisory lock 미획득)해 skip된 경우의 exit code —
# 실패(1)와 구분해 운영 스크립트가 재시도/대기 판단에 쓴다.
_EXIT_LOCK_SKIPPED = 3
# 입력 오류(파일 없음 / review_key 없음·이미 검토) — 재시도 무의미.
_EXIT_INVALID = 2


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

    consistency_p = sub.add_parser(
        "consistency-report",
        help="ADR-033 F1~F8 정합성 dry-run report 출력 (read-only 기본).",
    )
    consistency_p.add_argument(
        "--batch-id",
        default=None,
        help="리포트 batch_id. 미지정 시 새 UUID 생성.",
    )
    consistency_p.add_argument(
        "--persist",
        action="store_true",
        help="dry-run 대신 ops.feature_consistency_reports에 리포트를 저장한다.",
    )
    consistency_p.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="출력 형식. 기본 markdown.",
    )
    consistency_p.add_argument(
        "--output",
        default=None,
        help="출력 파일 경로. 미지정 시 stdout.",
    )
    consistency_p.add_argument(
        "--sample-limit",
        type=int,
        default=20,
        help="케이스별 sample id 최대 개수. 기본 20.",
    )
    consistency_p.add_argument(
        "--dedup-pending-threshold",
        type=int,
        default=DEDUP_PENDING_WARN_THRESHOLD,
        help=f"F4 pending dedup WARN threshold. 기본 {DEDUP_PENDING_WARN_THRESHOLD}.",
    )
    consistency_p.add_argument(
        "--provider-last-success-sla-seconds",
        type=int,
        default=PROVIDER_LAST_SUCCESS_WARN_SECONDS,
        help=(
            "F5 provider last_success 기본 SLA seconds. "
            f"기본 {PROVIDER_LAST_SUCCESS_WARN_SECONDS}."
        ),
    )
    consistency_p.add_argument(
        "--dedup-score-regression-warn-points",
        type=float,
        default=DEDUP_SCORE_REGRESSION_WARN_POINTS,
        help=f"F7 score regression WARN points. 기본 {DEDUP_SCORE_REGRESSION_WARN_POINTS:g}.",
    )
    consistency_p.add_argument(
        "--known-file-objects",
        default=None,
        help=(
            "F8 객체 저장소 snapshot JSON/JSONL 경로. 각 항목은 storage_backend, bucket, "
            "object_key를 가진다."
        ),
    )
    consistency_p.add_argument(
        "--fail-on-error",
        action="store_true",
        help="severity_max=ERROR이면 report 출력 후 exit 1.",
    )
    consistency_p.set_defaults(func=_cmd_consistency_report)

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
        "--mode",
        choices=["bulk", "incremental", "closed"],
        default="bulk",
        help=(
            "bulk(Step A — 전체 snapshot + 부재분 soft-delete) / "
            "incremental(Step B — 변경분 upsert + cursor 전진, prune 없음) / "
            "closed(Step C — 폐업·취소 record의 대응 feature를 inactive 전환). 기본 bulk."
        ),
    )
    mois_p.add_argument(
        "--dataset-key",
        default=None,
        help=(
            "적재 dataset_key. 미지정 시 모드별 기본 — bulk="
            f"{MOIS_DATASET_KEY_BULK} / incremental={MOIS_DATASET_KEY_HISTORY}."
        ),
    )
    mois_p.add_argument(
        "--cursor",
        default=None,
        help=(
            "incremental 전용(필수) — 이번 적재 후 저장할 cursor 값. "
            "``{\"last_modified_date\": <값>}``로 provider_sync_state에 기록."
        ),
    )
    mois_p.add_argument(
        "--sync-scope",
        default="default",
        help="incremental cursor scope (provider_sync_state.sync_scope, 기본 default).",
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
            "kraddr-geo REST base URL(예: http://127.0.0.1:9001). 주면 좌표 → "
            "bjd_code 역지오코딩 보강을 켠다. 미지정 시 mois legal_dong_code만 사용."
        ),
    )
    mois_p.add_argument(
        "--source-checksum",
        default=None,
        help="snapshot 체크섬(import_jobs.source_checksum 기록용, 선택).",
    )
    mois_p.set_defaults(func=_cmd_import_mois)

    merge_p = sub.add_parser(
        "dedup-merge",
        help="검토 큐 후보 1쌍을 병합 (mutate, advisory lock; ADR-016).",
    )
    merge_p.add_argument(
        "review_key",
        help="ops.dedup_review_queue.review_key (UUID). status로 후보 목록 확인.",
    )
    merge_p.add_argument(
        "--merged-by",
        default=None,
        help="병합 수행자(운영자 ID 등). feature_merge_history.merged_by 기록.",
    )
    merge_p.add_argument(
        "--reason",
        default=None,
        help="병합 사유(선택). history.reason + 큐 decision_reason 기록.",
    )
    merge_p.set_defaults(func=_cmd_dedup_merge)

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
        fp = dedup_fp_stats(counts.dedup_queue_by_status)
        if fp.resolved and fp.precision is not None and fp.fp_rate is not None:
            lines.append(
                f"dedup FP(운영): resolved={fp.resolved} "
                f"confirmed={fp.confirmed} rejected={fp.rejected} "
                f"precision={fp.precision:.3f} fp_rate={fp.fp_rate:.3f}"
            )
        else:
            lines.append(
                f"dedup FP(운영): 검토 완료 후보 없음 "
                f"(pending={fp.pending}, ignored={fp.ignored})"
            )
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


async def _cmd_consistency_report(args: argparse.Namespace) -> int:
    known_file_objects = None
    known_source = None
    known_count = None
    if args.known_file_objects is not None:
        path = Path(args.known_file_objects)
        if not path.is_file():  # noqa: ASYNC240  # CLI 진입 1회 stat
            print(f"consistency-report: snapshot 파일 없음 — {path}", file=sys.stderr)
            return _EXIT_INVALID
        try:
            known_file_objects = load_file_object_refs(path)
        except ValueError as exc:
            print(f"consistency-report: {exc}", file=sys.stderr)
            return _EXIT_INVALID
        known_source = str(path)
        known_count = len(known_file_objects)

    engine = make_async_engine(_resolve_dsn(args))
    try:
        async with AsyncKrtourMapClient(engine) as client:
            report = await client.run_consistency_report(
                batch_id=args.batch_id,
                persist=bool(args.persist),
                sample_limit=args.sample_limit,
                dedup_pending_threshold=args.dedup_pending_threshold,
                provider_last_success_sla_seconds=args.provider_last_success_sla_seconds,
                dedup_score_regression_warn_points=args.dedup_score_regression_warn_points,
                known_file_objects=known_file_objects,
            )
    finally:
        await engine.dispose()

    options = ConsistencyReportOptions(
        generated_at=kst_now(),
        persisted=bool(args.persist),
        sample_limit=args.sample_limit,
        dedup_pending_threshold=args.dedup_pending_threshold,
        provider_last_success_sla_seconds=args.provider_last_success_sla_seconds,
        dedup_score_regression_warn_points=args.dedup_score_regression_warn_points,
        known_file_objects_source=known_source,
        known_file_objects_count=known_count,
    )
    output = (
        render_consistency_report_json(report, options=options)
        if args.format == "json"
        else render_consistency_report_markdown(report, options=options)
    )
    if args.output is None:
        print(output, end="")
    else:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")  # noqa: ASYNC240  # CLI 1회 출력
        print(f"consistency-report: wrote {output_path}")
    return 1 if args.fail_on_error and report.severity_max == "ERROR" else 0


@asynccontextmanager
async def _geocoders_for(
    base_url: str | None,
) -> AsyncIterator[tuple[ReverseGeocoder | None, AddressResolver | None]]:
    """``--geocoder-url`` → kraddr-geo geocoder 콜러블들 (없으면 ``None``).

    httpx client 수명은 본 컨텍스트가 소유한다(ADR-002). ``base_url``엔 ``/v2``를
    붙이지 않는다 — ``KraddrGeoRestClient``가 ``base_path``로 붙인다.
    """
    if base_url is None:
        yield None, None
        return
    import httpx

    from krtour.map.geocoding import (
        KraddrGeoRestClient,
        kraddr_geo_address_resolver,
        kraddr_geo_reverse_geocoder,
    )

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        yield (
            kraddr_geo_reverse_geocoder(client),
            kraddr_geo_address_resolver(client, fallback="api"),
        )


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


def _format_incremental_result(result: MoisIncrementalJobResult) -> str:
    if not result.acquired:
        return (
            "import: skipped — 다른 워커가 이미 적재 중 (import advisory lock 미획득)."
        )
    assert result.load is not None
    assert result.sync_state is not None
    load = result.load
    job_id = result.job.job_id if result.job is not None else "?"
    return "\n".join(
        [
            f"import (incremental): done (job_id={job_id})",
            f"  features: inserted={load.features_inserted} "
            f"updated={load.features_updated}",
            f"  source_records: inserted={load.source_records_inserted}",
            f"  cursor: {result.sync_state.cursor}",
        ]
    )


def _format_closed_result(result: MoisClosedJobResult) -> str:
    if not result.acquired:
        return (
            "import: skipped — 다른 워커가 이미 적재 중 (import advisory lock 미획득)."
        )
    assert result.sync_state is not None
    job_id = result.job.job_id if result.job is not None else "?"
    return "\n".join(
        [
            f"import (closed): done (job_id={job_id})",
            f"  deactivated (inactive 전환): {result.deactivated}",
            f"  cursor: {result.sync_state.cursor}",
        ]
    )


async def _cmd_import_mois(args: argparse.Namespace) -> int:
    records_path = Path(args.records_file)
    if not records_path.is_file():  # noqa: ASYNC240  # 1회 stat — 진입 검증
        print(f"import: records 파일 없음 — {records_path}", file=sys.stderr)
        return _EXIT_INVALID
    incremental = args.mode == "incremental"
    closed = args.mode == "closed"
    if (incremental or closed) and not args.cursor:
        print(
            f"import: --mode {args.mode}은 --cursor 가 필수입니다.", file=sys.stderr
        )
        return _EXIT_INVALID
    dataset_key = args.dataset_key or (
        MOIS_DATASET_KEY_HISTORY if incremental else MOIS_DATASET_KEY_BULK
    )
    engine = make_async_engine(_resolve_dsn(args))
    try:
        records = iter_mois_license_records(records_path)
        async with (
            _geocoders_for(args.geocoder_url) as geocoders,
            AsyncKrtourMapClient(engine) as client,
        ):
            reverse_geocoder, address_resolver = geocoders
            if closed:
                cl = await client.run_mois_license_closed_job(
                    records,
                    new_cursor={"last_modified_date": args.cursor},
                    target_dataset_key=dataset_key,
                    sync_scope=args.sync_scope,
                    source_checksum=args.source_checksum,
                )
                print(_format_closed_result(cl))
                return 0 if cl.acquired else _EXIT_LOCK_SKIPPED
            if incremental:
                inc = await client.run_mois_license_incremental_job(
                    records,
                    fetched_at=datetime.now(UTC),
                    new_cursor={"last_modified_date": args.cursor},
                    dataset_key=dataset_key,
                    sync_scope=args.sync_scope,
                    reverse_geocoder=reverse_geocoder,
                    address_resolver=address_resolver,
                    source_checksum=args.source_checksum,
                    batch_size=args.batch_size,
                )
                print(_format_incremental_result(inc))
                return 0 if inc.acquired else _EXIT_LOCK_SKIPPED
            result = await client.run_mois_license_bulk_job(
                records,
                fetched_at=datetime.now(UTC),
                dataset_key=dataset_key,
                reverse_geocoder=reverse_geocoder,
                address_resolver=address_resolver,
                source_checksum=args.source_checksum,
                batch_size=args.batch_size,
            )
        print(_format_bulk_result(result))
        return 0 if result.acquired else _EXIT_LOCK_SKIPPED
    finally:
        await engine.dispose()


def _format_merge_outcome(o: MergeOutcome) -> str:
    return "\n".join(
        [
            f"dedup-merge: done (merge_id={o.merge_id})",
            f"  master: {o.master_feature_id}",
            f"  loser:  {o.loser_feature_id} (soft-deleted)",
            f"  source_links: moved={o.source_links_moved} "
            f"dropped={o.source_links_dropped}",
            f"  queue: {'merged' if o.queue_updated else 'unchanged'}",
        ]
    )


async def _cmd_dedup_merge(args: argparse.Namespace) -> int:
    engine = make_async_engine(_resolve_dsn(args))
    try:
        # advisory lock으로 같은 review 병합 중복 실행 차단(ADR-039). lock은 별도
        # 세션이 보유하고, 실제 병합은 client가 자체 transaction에서 수행한다.
        async with (
            AsyncSession(engine) as lock_session,
            try_mutex_lock(
                lock_session, dedup_merge_lock_key(args.review_key)
            ) as acquired,
        ):
            if not acquired:
                print(
                    f"dedup-merge: skipped — 같은 review 병합 진행 중 "
                    f"({args.review_key}).",
                )
                return _EXIT_LOCK_SKIPPED
            async with AsyncKrtourMapClient(engine) as client:
                try:
                    outcome = await client.merge_dedup_review(
                        args.review_key,
                        merged_by=args.merged_by,
                        reason=args.reason,
                    )
                except MergeError as exc:
                    print(f"dedup-merge: {exc}", file=sys.stderr)
                    return _EXIT_INVALID
            print(_format_merge_outcome(outcome))
            return 0
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
