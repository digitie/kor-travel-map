"""provider 적재의 ``feature-curation-write`` 긴 대기(T-LOAD-LOCK-WAIT, 2026-10-22).

Dagster 엔진의 ``lock_timeout=30000``이 다른 적재의 쓰기 단계 뒤에서 30초 만에 55P03을 냈다.
적재 transaction만 **첫 획득 한 문장**의 대기를 늘리고, 직후 두 timeout을 되돌린다. 이 파일은
어디서(무장한 session의 첫 획득) 무엇을(``lock_timeout``·``statement_timeout`` SET LOCAL과 복원)
하는지를 문장 순서로 결박한다. 실제 대기·55P03은 같은 이름의 통합 검사
(``tests/integration/test_feature_load_curation_lock_wait.py``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.feature_repo import (
    FEATURE_CURATION_WRITE_WAIT_INFO_KEY,
    FeatureLoadResult,
    arm_feature_curation_write_wait,
    lock_feature_curation_write,
)
from kortravelmap.settings import FEATURE_LOAD_CURATION_LOCK_WAIT_SECONDS_DEFAULT


class _Result:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _Session:
    """실행한 SQL을 순서대로 적고, ``pg_settings``에는 주어진 현재 값을 돌려준다."""

    def __init__(
        self,
        *,
        lock_timeout: int = 30_000,
        statement_timeout: int = 600_000,
        connection_check: int = 0,
        lock_error: BaseException | None = None,
    ) -> None:
        self.info: dict[str, Any] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._lock_error = lock_error
        self._settings = {
            "lock_timeout": lock_timeout,
            "statement_timeout": statement_timeout,
            "client_connection_check_interval": connection_check,
        }

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        sql = str(statement)
        self.calls.append((sql, dict(params)))
        if "pg_settings" in sql:
            return _Result([(name, str(value)) for name, value in self._settings.items()])
        if "set_config" in sql:
            self._settings = {name: int(params[name]) for name in self._settings}
        if "feature-curation-write" in sql and self._lock_error is not None:
            raise self._lock_error
        return _Result([])

    def kinds(self) -> list[str]:
        out: list[str] = []
        for sql, params in self.calls:
            if "pg_settings" in sql:
                out.append("read")
            elif "set_config" in sql:
                out.append(
                    f"set({params['lock_timeout']},{params['statement_timeout']},"
                    f"{params['client_connection_check_interval']})"
                )
            elif "feature-curation-write" in sql:
                out.append("lock")
            else:  # pragma: no cover - 방어
                out.append(sql)
        return out


@pytest.mark.asyncio
async def test_unarmed_session_takes_the_fence_with_the_engine_timeout() -> None:
    session = _Session()
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == ["lock"]


@pytest.mark.asyncio
async def test_armed_first_acquisition_extends_both_timeouts_then_restores() -> None:
    """lock 한 문장만 늘리고 되돌린다. 같은 transaction의 다음 획득은 그냥 잡는다."""
    session = _Session(lock_timeout=30_000, statement_timeout=600_000)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]

    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]

    # statement_timeout은 대기 + 60초 여유 — lock 대기가 먼저 끝나 종전과 같은 55P03이 된다.
    assert session.kinds() == [
        "read",
        "set(900000,960000,10000)",
        "lock",
        "set(30000,600000,0)",
        "lock",
    ]
    assert FEATURE_CURATION_WRITE_WAIT_INFO_KEY not in session.info


@pytest.mark.asyncio
async def test_statement_timeout_already_large_enough_is_kept() -> None:
    session = _Session(lock_timeout=30_000, statement_timeout=7_200_000)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == [
        "read",
        "set(900000,7200000,10000)",
        "lock",
        "set(30000,7200000,0)",
    ]


@pytest.mark.asyncio
async def test_unbounded_statement_timeout_stays_unbounded() -> None:
    session = _Session(lock_timeout=30_000, statement_timeout=0)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == ["read", "set(900000,0,10000)", "lock", "set(30000,0,0)"]


@pytest.mark.asyncio
async def test_configured_connection_check_is_kept() -> None:
    """``client_connection_check_interval``은 꺼져 있을 때만 10초로 켠다."""
    session = _Session(connection_check=3_000)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == [
        "read",
        "set(900000,960000,3000)",
        "lock",
        "set(30000,600000,3000)",
    ]


@pytest.mark.asyncio
async def test_a_failed_long_wait_is_logged_and_reraised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """15분 뒤의 55P03이 왜 늦었는지 남긴다 — 성공만 로그하면 실패한 긴 대기가 보이지 않는다."""
    error = DBAPIError("SELECT pg_advisory_xact_lock", {}, Exception("55P03"))
    session = _Session(lock_error=error)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]
    with (
        caplog.at_level(logging.WARNING, logger="kortravelmap.infra.feature_repo"),
        pytest.raises(DBAPIError),
    ):
        await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == ["read", "set(900000,960000,10000)", "lock"]
    assert any("기다리다 실패" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("prior_lock_ms", [0, 900_000, 1_800_000])
@pytest.mark.asyncio
async def test_never_shortens_an_engine_wait(prior_lock_ms: int) -> None:
    """늘리기만 한다 — 무한(0)이나 이미 더 긴 상한은 그대로 둔다."""
    session = _Session(lock_timeout=prior_lock_ms)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == ["read", "lock"]


@pytest.mark.asyncio
async def test_zero_wait_disables() -> None:
    session = _Session()
    arm_feature_curation_write_wait(session, 0)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == ["lock"]


def test_negative_wait_is_rejected() -> None:
    with pytest.raises(ValueError, match="wait_ms"):
        arm_feature_curation_write_wait(_Session(), -1)  # type: ignore[arg-type]


# ── client: 어느 transaction이 무장되는가 ─────────────────────────────────────


class _ClientSession:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}

    async def __aenter__(self) -> _ClientSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


@pytest.fixture
def client() -> AsyncKorTravelMapClient:
    instance = AsyncKorTravelMapClient(object())  # type: ignore[arg-type]
    instance._session_factory = _ClientSession  # type: ignore[assignment]  # noqa: SLF001
    return instance


@pytest.mark.asyncio
async def test_load_feature_bundles_arms_its_transaction_with_the_default(
    client: AsyncKorTravelMapClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    async def _fake_load_bundles(session: Any, bundles: Any, *, geo: Any = None) -> Any:
        seen.append(session.info.get(FEATURE_CURATION_WRITE_WAIT_INFO_KEY))
        return FeatureLoadResult()

    monkeypatch.setattr("kortravelmap.client.load_bundles", _fake_load_bundles)
    await client.load_feature_bundles([])
    assert seen == [FEATURE_LOAD_CURATION_LOCK_WAIT_SECONDS_DEFAULT * 1000]


@pytest.mark.asyncio
async def test_settings_value_reaches_the_snapshot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.settings import KorTravelMapSettings

    settings = KorTravelMapSettings(feature_load_curation_lock_wait_seconds=120)
    instance = AsyncKorTravelMapClient(object(), settings=settings)  # type: ignore[arg-type]
    instance._session_factory = _ClientSession  # type: ignore[assignment]  # noqa: SLF001
    seen: list[object] = []

    async def _fake_load_bundles(session: Any, bundles: Any, *, geo: Any = None) -> Any:
        seen.append(session.info.get(FEATURE_CURATION_WRITE_WAIT_INFO_KEY))
        return FeatureLoadResult()

    async def _fake_capture(session: Any, **_kwargs: Any) -> FeatureLoadResult:
        return FeatureLoadResult()

    monkeypatch.setattr("kortravelmap.client.load_bundles", _fake_load_bundles)
    monkeypatch.setattr("kortravelmap.client.capture_provider_curation_input", _fake_capture)
    await instance.load_authoritative_feature_snapshot(
        [], provider="p", dataset_key="d", source_entity_type="t"
    )
    assert seen == [120_000]


@pytest.mark.asyncio
async def test_maintenance_purge_is_not_armed(
    client: AsyncKorTravelMapClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """적재가 아닌 client 쓰기(만료 notice 정리)는 엔진 상한을 그대로 쓴다."""
    seen: list[object] = []

    async def _fake_purge(session: Any, *, retention: str) -> int:
        seen.append(session.info.get(FEATURE_CURATION_WRITE_WAIT_INFO_KEY))
        return 0

    monkeypatch.setattr("kortravelmap.client.repo_purge_expired_notices", _fake_purge)
    await client.purge_expired_notices()
    assert seen == [None]



# ── 어느 client 메서드가 fence에 닿고, 그중 어느 것이 무장되는가 ─────────────────

_ARMED: frozenset[str] = frozenset(
    {
        "load_feature_bundles",
        "load_feature_bundles_reobserving",
        "load_feature_bundle_batches",
        "load_authoritative_feature_snapshot",
        "load_authoritative_notice_snapshot",
        "load_notice_event_bundles",
        "retire_features_by_source",
        "retire_geometryless_area_features_by_source",
        "load_enrichment_links",
        "load_festival_enrichment",
        "refresh_festival_enrichment_reviews",
        "load_price_features",
    }
)
"""provider 적재 쓰기 — 다른 적재 뒤에서 길게 기다린다."""

_UNARMED_BY_DECISION: frozenset[str] = frozenset(
    {
        # 정리(maintenance) job — 하루 한 번, 실패하면 다음 날 다시 한다.
        "reconcile_notice_features",
        "purge_expired_notices",
        # 관리 단건/병합 — 짧게 기다리는 쪽이 맞다.
        "resolve_enrichment_review",
        "merge_dedup_review",
        "enrich_place_phone",
        # offline upload는 fence 앞에서 upload별 advisory·job 행 잠금을 먼저 쥔다 — 길게 기다리면
        # 그것들도 그만큼 쥔다. 적재 경로지만 이번 범위 밖(T-LOAD-LOCK-WAIT 절충).
        "run_offline_upload_load_job",
        # MOIS CLI 경로 — CLI 엔진에는 lock_timeout이 없다(무장해도 아무것도 안 바뀐다).
        "load_mois_license_features_bulk",
        "sync_mois_license_features_bulk",
        "run_mois_license_bulk_job",
        "run_mois_license_incremental_job",
        "run_mois_license_closed_job",
    }
)


def _reaches_fence(fn: object, depth: int, seen: set[object]) -> bool:
    """함수 본문(중첩 code 포함)이 참조하는 전역을 따라가 fence 함수에 닿는가."""
    import inspect
    import types

    from kortravelmap.infra import feature_repo

    target = inspect.unwrap(fn)  # type: ignore[arg-type]
    if not isinstance(target, types.FunctionType) or target in seen:
        return False
    seen.add(target)
    if not target.__module__.startswith("kortravelmap"):
        return False
    names: set[str] = set(target.__code__.co_names)
    for const in target.__code__.co_consts:
        if isinstance(const, types.CodeType):
            names |= set(const.co_names)
    for name in names:
        value = target.__globals__.get(name)
        if value is feature_repo.lock_feature_curation_write:
            return True
        if depth and isinstance(value, types.FunctionType) and _reaches_fence(
            value, depth - 1, seen
        ):
            return True
    return False


def test_every_fence_reaching_client_method_is_classified() -> None:
    """새 메서드가 fence에 닿으면 무장할지 정하게 만든다 — 빠진 무장도, 잘못된 무장도 빨갛다."""
    import inspect

    armed: set[str] = set()
    unarmed: set[str] = set()
    for name, member in vars(AsyncKorTravelMapClient).items():
        if not inspect.isfunction(member) or not _reaches_fence(member, 4, set()):
            continue
        if "_feature_load_transaction" in member.__code__.co_names:
            armed.add(name)
        else:
            unarmed.add(name)
    assert armed == _ARMED
    assert unarmed == _UNARMED_BY_DECISION
