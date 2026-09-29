"""MOIS full source sync canonical 선행조건 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from kortravelmap.providers.mois import (
    MOIS_SOURCE_SYNC_COVERAGE_TAG,
    MOIS_SOURCE_SYNC_FULL_COVERAGE,
)

from kortravelmap.api import dagster_graphql, mois_source_precheck
from kortravelmap.api.settings import ApiSettings

pytestmark = pytest.mark.unit

_CHECKED_AT = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _settings() -> ApiSettings:
    return ApiSettings(
        admin_proxy_secret=None,
        dagster_url="http://dagster.example:12302",
        dagster_allowed_hosts=["dagster.example"],
        mois_source_sync_ttl_hours=24,
    )


def _payload(
    *,
    status: str = "SUCCESS",
    end_time: float | None = None,
    update_time: float | None = None,
    coverage: str | None = MOIS_SOURCE_SYNC_FULL_COVERAGE,
    missing_end_time: bool = False,
) -> dict[str, Any]:
    tags = (
        [{"key": MOIS_SOURCE_SYNC_COVERAGE_TAG, "value": coverage}]
        if coverage is not None
        else []
    )
    return {
        "data": {
            "repositoryOrError": {"__typename": "Repository"},
            "runsOrError": {
                "__typename": "Runs",
                "results": [
                    {
                        "runId": "source-sync-1",
                        "jobName": mois_source_precheck.MOIS_SOURCE_SYNC_JOB_NAME,
                        "status": status,
                        "startTime": _CHECKED_AT.timestamp() - 180,
                        "endTime": (
                            None
                            if missing_end_time
                            else (
                                _CHECKED_AT.timestamp() - 60
                                if end_time is None
                                else end_time
                            )
                        ),
                        "updateTime": (
                            _CHECKED_AT.timestamp() - 60
                            if update_time is None
                            else update_time
                        ),
                        "tags": tags,
                    }
                ],
            }
        }
    }


@pytest.mark.asyncio
async def test_fetch_precheck_uses_exact_job_and_accepts_fresh_full_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _post_graphql(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["query"] == mois_source_precheck._QUERY
        assert kwargs["variables"] == {
            "repositorySelector": {
                "repositoryName": "__repository__",
                "repositoryLocationName": "kortravelmap.dagster.definitions",
            },
            "runsFilter": {
                "pipelineName": mois_source_precheck.MOIS_SOURCE_SYNC_JOB_NAME,
                # 공유 webserver에서 다른 프로젝트의 같은 이름 job을 고르지 않는다.
                "tags": [
                    {
                        "key": ".dagster/repository",
                        "value": "__repository__@kortravelmap.dagster.definitions",
                    }
                ],
            }
        }
        return _payload()

    monkeypatch.setattr(dagster_graphql, "post_graphql", _post_graphql)

    async with httpx.AsyncClient() as client:
        result = await mois_source_precheck.fetch_mois_source_sync_precheck(
            settings=_settings(),
            client=client,
            checked_at=_CHECKED_AT,
        )

    assert result.ready is True
    assert result.age_hours == pytest.approx(1 / 60)
    assert result.disabled_reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (_payload(coverage=None), "full sync가 아닙니다"),
        (_payload(coverage="partial"), "full sync가 아닙니다"),
        (
            _payload(
                end_time=_CHECKED_AT.timestamp() + 60,
                update_time=_CHECKED_AT.timestamp() + 60,
            ),
            "미래입니다",
        ),
        (
            _payload(
                update_time=_CHECKED_AT.timestamp() - 60,
                missing_end_time=True,
            ),
            "성공 시각이 없습니다",
        ),
    ],
)
async def test_fetch_precheck_rejects_noncanonical_or_invalid_completion(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    reason: str,
) -> None:
    async def _post_graphql(**_kwargs: Any) -> dict[str, Any]:
        return payload

    monkeypatch.setattr(dagster_graphql, "post_graphql", _post_graphql)

    async with httpx.AsyncClient() as client:
        result = await mois_source_precheck.fetch_mois_source_sync_precheck(
            settings=_settings(),
            client=client,
            checked_at=_CHECKED_AT,
        )

    assert result.ready is False
    assert result.age_hours is None or result.age_hours >= 0
    assert reason in (result.disabled_reason or "")


@pytest.mark.asyncio
async def test_non_mois_plan_does_not_query_dagster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("non-MOIS plan은 Dagster precheck를 호출하면 안 됩니다")

    monkeypatch.setattr(dagster_graphql, "post_graphql", _unexpected)

    async with httpx.AsyncClient() as client:
        await mois_source_precheck.ensure_mois_source_sync_for_plan(
            frozenset({("kma", "short_forecast")}),
            settings=_settings(),
            client=client,
        )


@pytest.mark.asyncio
async def test_fetch_precheck_fails_loudly_when_the_code_location_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """location 이름이 틀리면 tag filter는 0건이다 — "sync 필요"로 오판하지 않는다."""

    async def _post_graphql(**_kwargs: Any) -> dict[str, Any]:
        return {
            "data": {
                "repositoryOrError": {
                    "__typename": "RepositoryNotFoundError",
                    "message": "Could not find Repository nope.__repository__",
                },
                "runsOrError": {"__typename": "Runs", "results": []},
            }
        }

    monkeypatch.setattr(dagster_graphql, "post_graphql", _post_graphql)

    async with httpx.AsyncClient() as client:
        with pytest.raises(mois_source_precheck.MoisSourceSyncPrecheckError) as excinfo:
            await mois_source_precheck.fetch_mois_source_sync_precheck(
                settings=_settings(),
                client=client,
                checked_at=_CHECKED_AT,
            )

    assert excinfo.value.code == "DAGSTER_QUERY_FAILED"
    assert "Could not find Repository" in str(excinfo.value)
