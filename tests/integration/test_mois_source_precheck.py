"""``ensure_mois_source_sync_for_memberships``의 dataset 판정을 **실 DB**로 고정한다.

이 함수는 canonical feature-update write 경계의 fail-closed 관문이다. 그런데 지금까지
유일한 테스트(``packages/kor-travel-map-api/tests/test_ops_pipeline_router.py``)는 이
함수를 **통째로 monkeypatch**해 "항상 통과"로 갈아끼웠다. 그래서 함수 본문의 fail-open
변이가 어느 게이트에도 보이지 않았다(적대 리뷰 H-C).

여기서는 alembic head DB에 대고 세 갈래를 각각 가른다.

* MOIS dataset이 membership에 있으면 Dagster precheck를 **반드시** 태우고,
  선행조건이 미충족이면 ``MoisSourceSyncRequired``로 막는다.
* MOIS가 아닌 dataset만 있으면 Dagster를 **한 번도** 부르지 않는다.
* 카탈로그에 없는 id는 MOIS로 승격되지 않는다(``provider_dataset_id`` 필터가 살아 있다).

Dagster HTTP 경계는 ``httpx.MockTransport``로 세운다 — 모듈을 patch하지 않으므로
``mois_source_precheck`` 본문(DB 조회 + 판정 + 예외)은 전부 실제로 돈다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from kortravelmap.api.mois_source_precheck import (
    MOIS_SOURCE_SYNC_JOB_NAME,
    MoisSourceSyncRequired,
    ensure_mois_source_sync_for_memberships,
)
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.providers.mois import (
    MOIS_SOURCE_SYNC_COVERAGE_TAG,
    MOIS_SOURCE_SYNC_FULL_COVERAGE,
)
from kortravelmap.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)

pytestmark = pytest.mark.integration

#: 시드와 겹치지 않는 non-MOIS probe provider.
_PROBE_OTHER_PROVIDER = "python-mois-precheck-axis-probe-api"

_CAPABILITIES = '{"schema_version": 1, "produces": ["place"], "extensions": {}}'

_INSERT_DATASET_SQL = """
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, is_active, capabilities
) VALUES (
    :provider, :dataset_key, :display_name, 'openapi', true,
    CAST(:capabilities AS jsonb)
)
RETURNING provider_dataset_id
"""


async def _insert_dataset(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> int:
    return int(
        (
            await session.execute(
                text(_INSERT_DATASET_SQL),
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "display_name": f"probe {provider} {dataset_key}",
                    "capabilities": _CAPABILITIES,
                },
            )
        ).scalar_one()
    )


class _DagsterProbe:
    """Dagster GraphQL 경계를 세우고 **호출 여부 자체**를 관측한다.

    호출 횟수가 축이다 — "MOIS가 아니면 Dagster를 안 부른다"와 "MOIS면 반드시
    부른다"는 반환값이 아니라 이 카운터로만 갈린다.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        self.requests.append(body if isinstance(body, dict) else {})
        return httpx.Response(200, json=self.payload)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def _settings() -> ApiSettings:
    return ApiSettings(
        _env_file=None,
        admin_proxy_secret=None,
        dagster_url="http://dagster.example:12302",
        dagster_allowed_hosts=["dagster.example"],
        mois_source_sync_ttl_hours=24,
    )


def _runs_payload(*, status: str, coverage: str | None) -> dict[str, Any]:
    """``endTime``이 없는 run — 완료 시각이 없어 TTL 계산 자체가 성립하지 않는다.

    coverage tag까지 full이 아니면 ``ready``는 두 축 모두에서 거짓이다.
    """

    tags = (
        [{"key": MOIS_SOURCE_SYNC_COVERAGE_TAG, "value": coverage}]
        if coverage is not None
        else []
    )
    return {
        "data": {
            "runsOrError": {
                "__typename": "Runs",
                "results": [
                    {
                        "runId": "source-sync-probe",
                        "jobName": MOIS_SOURCE_SYNC_JOB_NAME,
                        "status": status,
                        "startTime": None,
                        "endTime": None,
                        "updateTime": None,
                        "tags": tags,
                    }
                ],
            }
        }
    }


def _no_runs_payload() -> dict[str, Any]:
    return {
        "data": {
            "runsOrError": {"__typename": "Runs", "results": []},
        }
    }


def _fresh_full_coverage_payload(*, now: float) -> dict[str, Any]:
    return {
        "data": {
            "runsOrError": {
                "__typename": "Runs",
                "results": [
                    {
                        "runId": "source-sync-probe",
                        "jobName": MOIS_SOURCE_SYNC_JOB_NAME,
                        "status": "SUCCESS",
                        "startTime": now - 600,
                        "endTime": now - 60,
                        "updateTime": now - 60,
                        "tags": [
                            {
                                "key": MOIS_SOURCE_SYNC_COVERAGE_TAG,
                                "value": MOIS_SOURCE_SYNC_FULL_COVERAGE,
                            }
                        ],
                    }
                ],
            }
        }
    }


async def test_mois_membership_without_source_sync_is_rejected(
    migrated_session: AsyncSession,
) -> None:
    """MOIS dataset이 membership에 있으면 실행 이력이 없을 때 **막힌다**.

    이 갈래가 fail-open이 되면(예: dataset 조회 결과와 무관하게 즉시 ``return``)
    MOIS canonical write가 full source sync 없이 그대로 실행된다.
    """
    mois_dataset_id = await _insert_dataset(
        migrated_session,
        provider=MOIS_PROVIDER_NAME,
        dataset_key="mois_precheck_probe_dataset",
    )
    probe = _DagsterProbe(_no_runs_payload())

    async with probe.client() as client:
        with pytest.raises(MoisSourceSyncRequired) as excinfo:
            await ensure_mois_source_sync_for_memberships(
                migrated_session,
                frozenset({(mois_dataset_id, "dataset_wide")}),
                settings=_settings(),
                client=client,
            )

    assert excinfo.value.precheck.ready is False
    assert excinfo.value.precheck.job_name == MOIS_SOURCE_SYNC_JOB_NAME
    assert len(probe.requests) == 1
    assert probe.requests[0]["variables"] == {
        "filter": {"pipelineName": MOIS_SOURCE_SYNC_JOB_NAME}
    }


async def test_mois_membership_with_partial_coverage_run_is_rejected(
    migrated_session: AsyncSession,
) -> None:
    """전국 full coverage tag가 없는 성공 run은 선행조건을 만족하지 않는다."""
    mois_dataset_id = await _insert_dataset(
        migrated_session,
        provider=MOIS_PROVIDER_NAME,
        dataset_key="mois_precheck_probe_partial",
    )
    probe = _DagsterProbe(_runs_payload(status="SUCCESS", coverage="partial"))

    async with probe.client() as client:
        with pytest.raises(MoisSourceSyncRequired):
            await ensure_mois_source_sync_for_memberships(
                migrated_session,
                frozenset({(mois_dataset_id, "dataset_wide")}),
                settings=_settings(),
                client=client,
            )

    assert len(probe.requests) == 1


async def test_mois_membership_with_fresh_full_sync_passes(
    migrated_session: AsyncSession,
) -> None:
    """선행조건을 만족하면 통과하되, Dagster는 **실제로 조회된다**."""
    mois_dataset_id = await _insert_dataset(
        migrated_session,
        provider=MOIS_PROVIDER_NAME,
        dataset_key="mois_precheck_probe_ready",
    )
    probe = _DagsterProbe(
        _fresh_full_coverage_payload(now=datetime.now(UTC).timestamp())
    )

    async with probe.client() as client:
        await ensure_mois_source_sync_for_memberships(
            migrated_session,
            frozenset({(mois_dataset_id, "dataset_wide")}),
            settings=_settings(),
            client=client,
        )

    assert len(probe.requests) == 1


async def test_mois_membership_mixed_with_other_provider_is_still_checked(
    migrated_session: AsyncSession,
) -> None:
    """membership 하나라도 MOIS면 검사한다 — 다른 provider가 섞여도 희석되지 않는다."""
    mois_dataset_id = await _insert_dataset(
        migrated_session,
        provider=MOIS_PROVIDER_NAME,
        dataset_key="mois_precheck_probe_mixed",
    )
    other_dataset_id = await _insert_dataset(
        migrated_session,
        provider=_PROBE_OTHER_PROVIDER,
        dataset_key="mois_precheck_probe_mixed_sibling",
    )
    probe = _DagsterProbe(_no_runs_payload())

    async with probe.client() as client:
        with pytest.raises(MoisSourceSyncRequired):
            await ensure_mois_source_sync_for_memberships(
                migrated_session,
                frozenset(
                    {
                        (other_dataset_id, "dataset_wide"),
                        (mois_dataset_id, "target_grids"),
                    }
                ),
                settings=_settings(),
                client=client,
            )

    assert len(probe.requests) == 1


async def test_non_mois_membership_never_reaches_dagster(
    migrated_session: AsyncSession,
) -> None:
    """MOIS가 아닌 dataset만 있으면 Dagster를 한 번도 부르지 않는다.

    ``provider`` 필터가 빠지면 여기서 호출이 발생한다(그리고 실행 이력이 없으므로
    통과 대신 409가 된다).
    """
    other_dataset_id = await _insert_dataset(
        migrated_session,
        provider=_PROBE_OTHER_PROVIDER,
        dataset_key="mois_precheck_probe_other",
    )
    probe = _DagsterProbe(_no_runs_payload())

    async with probe.client() as client:
        await ensure_mois_source_sync_for_memberships(
            migrated_session,
            frozenset({(other_dataset_id, "dataset_wide")}),
            settings=_settings(),
            client=client,
        )

    assert probe.requests == []


async def test_membership_id_outside_catalog_never_reaches_dagster(
    migrated_session: AsyncSession,
) -> None:
    """카탈로그에 없는 id는 MOIS로 승격되지 않는다.

    시드에는 MOIS dataset이 실재하므로(``alembic/versions/0089_tvn33_expand_seed.py``),
    ``provider_dataset_id`` 필터가 빠지면 존재하지 않는 id로도 MOIS 행이 걸려
    Dagster 조회가 발생한다.
    """
    unused_dataset_id = int(
        (
            await migrated_session.execute(
                text(
                    "SELECT COALESCE(MAX(provider_dataset_id), 0) + 1000000 "
                    "FROM provider_sync.provider_datasets"
                )
            )
        ).scalar_one()
    )
    probe = _DagsterProbe(_no_runs_payload())

    async with probe.client() as client:
        await ensure_mois_source_sync_for_memberships(
            migrated_session,
            frozenset({(unused_dataset_id, "dataset_wide")}),
            settings=_settings(),
            client=client,
        )

    assert probe.requests == []


async def test_empty_memberships_never_reaches_dagster(
    migrated_session: AsyncSession,
) -> None:
    """membership이 비면 검사 대상 자체가 없다."""
    probe = _DagsterProbe(_no_runs_payload())

    async with probe.client() as client:
        await ensure_mois_source_sync_for_memberships(
            migrated_session,
            frozenset(),
            settings=_settings(),
            client=client,
        )

    assert probe.requests == []
