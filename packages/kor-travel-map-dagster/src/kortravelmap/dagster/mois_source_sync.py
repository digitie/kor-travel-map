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
    """MOIS source SQLite WAL 파일이 컨테이너 임시 공간에 누적되지 않게 줄인다."""
    if engine.dialect.name != "sqlite":
        return
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    except Exception:
        # provider sync 본 작업의 성공/실패 판단을 checkpoint 실패로 바꾸지는 않는다.
        return


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
    보장하고, keyless ``LocalDataFileClient``로 ``service_slugs`` 업종 파일을 받아
    ``sync_localdata_source_db(session, client, service_slugs=..., commit=True)``로
    upsert한다. ``service_slugs`` 미지정 시 krtour ``PROMOTED_SERVICE_SLUGS``(42 업종)
    전체를 정렬해 쓴다. provider sync 결과를 ``MoisSourceSyncSummary``로 복사해 반환
    한다. engine/session/client는 ``finally``에서 정리한다.
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
                sync_kind = str(result.sync_kind)
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
