"""provider 적재의 ``feature-curation-write`` 긴 대기(T-LOAD-LOCK-WAIT, 2026-10-22).

Dagster 엔진의 ``lock_timeout=30000``이 다른 적재의 쓰기 단계 뒤에서 30초 만에 55P03을 냈다.
적재 transaction만 **첫 획득 한 문장**의 대기를 늘리고, 직후 두 timeout을 되돌린다. 이 파일은
어디서(무장한 session의 첫 획득) 무엇을(``lock_timeout``·``statement_timeout`` SET LOCAL과 복원)
하는지를 문장 순서로 결박한다. 실제 대기·55P03은 같은 이름의 통합 검사
(``tests/integration/test_feature_load_curation_lock_wait.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

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

    def __init__(self, *, lock_timeout: int = 30_000, statement_timeout: int = 600_000) -> None:
        self.info: dict[str, Any] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._settings = {"lock_timeout": lock_timeout, "statement_timeout": statement_timeout}

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        sql = str(statement)
        self.calls.append((sql, dict(params)))
        if "pg_settings" in sql:
            return _Result([(name, str(value)) for name, value in self._settings.items()])
        if "set_config" in sql:
            self._settings = {
                "lock_timeout": int(params["lock_timeout"]),
                "statement_timeout": int(params["statement_timeout"]),
            }
        return _Result([])

    def kinds(self) -> list[str]:
        out: list[str] = []
        for sql, params in self.calls:
            if "pg_settings" in sql:
                out.append("read")
            elif "set_config" in sql:
                out.append(f"set({params['lock_timeout']},{params['statement_timeout']})")
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
        "set(900000,960000)",
        "lock",
        "set(30000,600000)",
        "lock",
    ]
    assert FEATURE_CURATION_WRITE_WAIT_INFO_KEY not in session.info


@pytest.mark.asyncio
async def test_statement_timeout_already_large_enough_is_kept() -> None:
    session = _Session(lock_timeout=30_000, statement_timeout=7_200_000)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == ["read", "set(900000,7200000)", "lock", "set(30000,7200000)"]


@pytest.mark.asyncio
async def test_unbounded_statement_timeout_stays_unbounded() -> None:
    session = _Session(lock_timeout=30_000, statement_timeout=0)
    arm_feature_curation_write_wait(session, 900_000)  # type: ignore[arg-type]
    await lock_feature_curation_write(session)  # type: ignore[arg-type]
    assert session.kinds() == ["read", "set(900000,0)", "lock", "set(30000,0)"]


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

