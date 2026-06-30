"""MOIS LOCALDATA 소스 DB sync (Phase A).

MOIS 인허가 feature 적재는 두 단계다.

- **Phase A** (본 모듈): 행정안전부 LOCALDATA 인허가 파일을 공개 파일 포털
  (``file.localdata.go.kr``)에서 받아 **미리 sync된 SQLite 소스 DB**에 적재한다.
  공개 파일 다운로드라 별도 API key가 필요 없다(provider ``python-mois-api``의
  ``LocalDataFileClient``는 keyless). 네트워크만 있으면 된다.
- **Phase B** (``provider_fetchers.fetch_mois_license_records``): 그 소스 DB를
  **읽기만** 하여 영업중 인허가 record를 feature-load asset에 stream한다.

본 모듈은 Phase A를 ① 단위 테스트 가능한 순수 helper(``sync_mois_source_db``)와
② 운영자가 Dagster UI/API/스케줄로 실행하는 op/job/schedule로 제공한다. provider
패키지(``mois``)는 ADR-044 로컬 체크아웃이며 hard dependency가 아니므로(부재 가능),
``provider_fetchers``와 동일하게 호출 시점에 ``importlib`` + ``cast(Any, ...)``로
lazy resolve한다 — 본 모듈 import만으로 ``mois`` 패키지를 hard-require 하지 않는다.

NOTE: 본 모듈은 ``from __future__ import annotations``를 쓰지 않는다 — Dagster ``@op``는
``context`` 파라미터 타입힌트를 런타임 class 객체로 검증하므로, 문자열화된 annotation
(future import)은 ``DagsterInvalidDefinitionError``를 유발한다(``maintenance.py``와 동일).
"""

import importlib
import logging
import pathlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, cast

from kortravelmap.providers.mois import PROMOTED_SERVICE_SLUGS
from kortravelmap.settings import KorTravelMapSettings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dagster import (
    Array,
    DefaultScheduleStatus,
    Field,
    Int,
    Noneable,
    OpExecutionContext,
    ScheduleDefinition,
    String,
    job,
    op,
)

from .maintenance import MAINTENANCE_RETRY_POLICY
from .provider_fetchers import ProviderCredentialMissing
from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE

__all__ = [
    "MOIS_SOURCE_SYNC_JOBS",
    "MOIS_SOURCE_SYNC_JOB_TAGS",
    "MOIS_SOURCE_SYNC_SCHEDULES",
    "MoisSourceSyncSummary",
    "mois_localdata_source_sync_job",
    "mois_localdata_source_sync_op",
    "sync_mois_source_db",
]

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MoisSourceSyncSummary:
    """Phase A sync 결과 요약(provider 결과를 krtour 경계 dataclass로 복사)."""

    db_path: str
    service_slugs: tuple[str, ...]
    sync_kind: str
    scanned_count: int
    upserted_count: int
    open_count: int
    closed_count: int
    unknown_status_count: int

    def as_metadata(self) -> dict[str, object]:
        """Dagster op output metadata로 노출할 dict."""
        return {
            "db_path": self.db_path,
            "service_slug_count": len(self.service_slugs),
            "sync_kind": self.sync_kind,
            "scanned_count": self.scanned_count,
            "upserted_count": self.upserted_count,
            "open_count": self.open_count,
            "closed_count": self.closed_count,
            "unknown_status_count": self.unknown_status_count,
        }


def _checkpoint_sqlite_wal(engine: Engine) -> None:
    """MOIS source SQLite WAL 파일이 컨테이너 임시 공간에 누적되지 않게 줄인다.

    best-effort: checkpoint 실패는 provider sync의 성공/실패 판단을 바꾸지 않는다
    (예외를 삼키되 경고만 남긴다). ``PRAGMA wal_checkpoint(TRUNCATE)``는 동시 reader가
    lock을 잡고 있으면 ``busy=1``을 반환하며 WAL을 truncate하지 못하므로, 반환행
    ``(busy, log, checkpointed)``을 캡처해 ``busy != 0``일 때 경고를 남긴다 — 조용히
    WAL이 잔존(=다시 디스크를 채울 수 있는 상태)하는 것을 관측 가능하게 한다(#614 후속).

    checkpoint는 명시적 ``AUTOCOMMIT`` 연결에서 실행한다 — ``wal_checkpoint`` 발행의
    canonical 패턴이며, ``engine.begin()``(pysqlite deferred-BEGIN으로 현재는 동작)보다
    isolation_level/eager-BEGIN 변경에 견고하다.
    """
    if engine.dialect.name != "sqlite":
        return
    try:
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            row = connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)")).first()
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup, 절대 sync를 깨지 않는다
        _LOGGER.warning("MOIS source WAL checkpoint 실패(무시): %s", exc)
        return
    if row is not None and int(row[0]) != 0:
        _LOGGER.warning(
            "MOIS source WAL checkpoint가 busy로 truncate되지 않음 "
            "(busy=%s log=%s checkpointed=%s) — 동시 reader 가능성, WAL 잔존",
            row[0],
            row[1],
            row[2],
        )


def sync_mois_source_db(
    settings: KorTravelMapSettings,
    *,
    service_slugs: Iterable[str] | None = None,
    org_code: str | None = None,
    batch_size: int = 1000,
) -> MoisSourceSyncSummary:
    """LOCALDATA 인허가 파일을 받아 MOIS 소스 SQLite DB에 적재한다(Phase A).

    ``settings.mois_source_db_path``(env ``KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH``)를 대상
    DB로 쓴다. 미설정 시 ``ProviderCredentialMissing``으로 명확히 실패한다(Phase B
    fetcher와 동일 계약). 파일 부모 디렉터리는 필요 시 생성한다.

    provider ``mois``를 lazy import한 뒤 ``create_sqlite_schema(engine)``로 스키마를
    보장하고, keyless ``LocalDataFileClient``로 업종을 받아 적재한다. ``service_slugs``
    미지정 시 krtour ``PROMOTED_SERVICE_SLUGS``(42 업종) 전체를 정렬해 쓴다. 명시적
    빈 목록을 넘기면 ``ValueError``로 즉시 실패한다(op 경로는 빈 설정을 None→PROMOTED로
    fallback하므로 영향 없음).

    적재는 **업종(슬러그)별로 별도 세션·commit**하고 각 슬러그 후 SQLite WAL을
    ``wal_checkpoint(TRUNCATE)``로 줄인다(#614 — 전체 업종 단일 트랜잭션이 WAL을
    무한히 키워 디스크를 채운 사고 대응). 따라서 시맨틱은 **all-or-nothing이 아니라
    업종 단위 incremental**이다: 중간 슬러그에서 실패하면 그 이전 슬러그들은 이미
    소스 DB에 영속되고 함수는 summary 없이 예외를 올린다. upsert는 idempotent이고 op는
    재시도 정책을 갖는다. provider sync 결과 count는 슬러그별로 합산해
    ``MoisSourceSyncSummary``로 반환한다. engine/session/client는 ``finally``에서 정리한다.

    NOTE: 단일 최대 업종(예: ``general_restaurants``)은 provider가 슬러그당 1회만
    commit하므로 그 한 트랜잭션 동안 WAL이 multi-GB까지 커질 수 있다 — provider 측
    batch별 commit이 필요한 별도 후속 과제다(docs/journal.md #614 항목 참조).
    """
    db_path = settings.mois_source_db_path
    if db_path is None:
        raise ProviderCredentialMissing(
            "MOIS Phase A 소스 DB sync에는 대상 SQLite DB 경로가 필요하다. "
            "KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH를 설정하라."
        )

    path = pathlib.Path(db_path)
    parent = path.parent
    if str(parent) and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

    slugs = tuple(
        sorted(service_slugs if service_slugs is not None else PROMOTED_SERVICE_SLUGS)
    )
    if not slugs:
        # 명시적 빈 목록은 fail-fast — provider도 동일 메시지로 거부한다. op 경로는
        # 빈 설정을 None→PROMOTED로 collapse하므로 여기 도달하지 않는다.
        raise ValueError("service_slugs must contain at least one slug")

    # provider record loader/file client/schema 함수는 ADR-044 로컬 체크아웃이며 hard
    # dependency가 아니므로(부재 가능), provider_fetchers와 동일하게 호출 시점에
    # ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    mois = cast(Any, importlib.import_module("mois"))

    engine = create_engine(f"sqlite:///{db_path}")
    scanned_count = 0
    upserted_count = 0
    open_count = 0
    closed_count = 0
    unknown_status_count = 0
    sync_kind = "localdata_full"
    sync_kinds: set[str] = set()
    synced_slugs: list[str] = []
    try:
        mois.create_sqlite_schema(engine)
        client = mois.LocalDataFileClient()
        try:
            for slug in slugs:
                session = Session(engine)
                try:
                    result = mois.sync_localdata_source_db(
                        session,
                        client,
                        service_slugs=(slug,),
                        org_code=org_code,
                        batch_size=batch_size,
                        commit=True,
                    )
                finally:
                    session.close()
                    _checkpoint_sqlite_wal(engine)

                synced_slugs.extend(str(item) for item in result.service_slugs)
                sync_kinds.add(str(result.sync_kind))
                scanned_count += int(result.scanned_count)
                upserted_count += int(result.upserted_count)
                open_count += int(result.open_count)
                closed_count += int(result.closed_count)
                unknown_status_count += int(result.unknown_status_count)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
    finally:
        _checkpoint_sqlite_wal(engine)
        engine.dispose()

    # 슬러그별 sync_kind를 distinct하게 모은다 — 현재 provider는 항상 'localdata_full'을
    # 돌려주지만, 향후 분기 시 마지막 슬러그 값으로 조용히 collapse되지 않게 한다.
    if sync_kinds:
        sync_kind = (
            next(iter(sync_kinds))
            if len(sync_kinds) == 1
            else ",".join(sorted(sync_kinds))
        )

    return MoisSourceSyncSummary(
        db_path=str(db_path),
        service_slugs=tuple(synced_slugs),
        sync_kind=sync_kind,
        scanned_count=scanned_count,
        upserted_count=upserted_count,
        open_count=open_count,
        closed_count=closed_count,
        unknown_status_count=unknown_status_count,
    )


MOIS_SOURCE_SYNC_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "maintenance",
    "kor_travel_map.job_kind": "mois_localdata_source_sync",
    "kor_travel_map.provider": "python-mois-api",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""MOIS Phase A source sync Dagster job 공통 tag."""

_MOIS_SOURCE_SYNC_CONFIG_SCHEMA: Final[dict[str, object]] = {
    "service_slugs": Field(
        Array(String),
        default_value=[],
        description=(
            "적재할 LOCALDATA 업종 slug 목록. 빈 목록이면 krtour "
            "PROMOTED_SERVICE_SLUGS(42 업종) 전체를 쓴다."
        ),
    ),
    "org_code": Field(
        Noneable(String),
        default_value=None,
        description="지역 필터 org_code. None이면 전국 파일을 받는다.",
    ),
    "batch_size": Field(
        Int,
        default_value=1000,
        description="소스 DB upsert batch 크기.",
    ),
}


@op(
    # NOTE: job 이름(`mois_localdata_source_sync`)과 달라야 한다 — Dagster job은
    # 동명 graph를 만들므로 op가 같은 이름이면 repository 전체 로드가
    # DagsterInvalidDefinitionError로 실패한다 (#384, T-212e에서 발견).
    name="sync_mois_localdata_source_db",
    config_schema=_MOIS_SOURCE_SYNC_CONFIG_SCHEMA,
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
def mois_localdata_source_sync_op(context: OpExecutionContext) -> dict[str, object]:
    """LOCALDATA 인허가 파일을 받아 MOIS 소스 DB를 갱신한다(Phase A)."""
    settings = KorTravelMapSettings()
    config = cast(Mapping[str, object], context.op_config)

    raw_slugs = config.get("service_slugs") or ()
    service_slugs: tuple[str, ...] | None = (
        tuple(str(slug) for slug in cast("Iterable[object]", raw_slugs)) or None
    )
    org_code_value = config.get("org_code")
    org_code = str(org_code_value) if org_code_value else None
    batch_size = int(cast("int", config.get("batch_size") or 1000))

    summary = sync_mois_source_db(
        settings,
        service_slugs=service_slugs,
        org_code=org_code,
        batch_size=batch_size,
    )
    metadata = summary.as_metadata()
    context.add_output_metadata(metadata)
    return metadata


@job(
    name="mois_localdata_source_sync",
    tags=MOIS_SOURCE_SYNC_JOB_TAGS,
    description=(
        "LOCALDATA 인허가 파일을 받아 MOIS 소스 SQLite DB(Phase A)를 갱신한다. "
        "Phase B feature-load fetcher가 이 DB를 읽는다."
    ),
)
def mois_localdata_source_sync_job() -> None:
    """운영자가 Dagster UI/API/스케줄에서 실행하는 MOIS Phase A sync job."""
    mois_localdata_source_sync_op()


MOIS_SOURCE_SYNC_SCHEDULES: Final = [
    ScheduleDefinition(
        name="mois_localdata_source_sync_weekly_schedule",
        job=mois_localdata_source_sync_job,
        cron_schedule=cron_for_schedule(
            "mois_localdata_source_sync_weekly_schedule",
            "0 4 * * 1",
        ),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags=MOIS_SOURCE_SYNC_JOB_TAGS,
        description=(
            "MOIS LOCALDATA 소스 DB를 주 1회(월 04:00 KST) 갱신한다. 운영 enable "
            "전까지 STOPPED."
        ),
    )
]
"""MOIS Phase A source sync schedule. 운영 enable 전까지 STOPPED."""

MOIS_SOURCE_SYNC_JOBS: Final = [mois_localdata_source_sync_job]
