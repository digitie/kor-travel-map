"""주소 검증 finding batch의 DB 진입 전 불변식."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from kortravelmap.core.ids import make_integrity_finding_key
from kortravelmap.infra.integrity_violation_repo import sync_integrity_findings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class _ScalarResult:
    def __init__(self, size: int) -> None:
        self._size = size

    def all(self) -> list[str]:
        return [str(index) for index in range(self._size)]


class _ExecuteResult:
    def __init__(self, size: int) -> None:
        self._size = size

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._size)


class _CapturingSession:
    def __init__(self) -> None:
        self.params: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any]) -> _ExecuteResult:
        del statement
        self.params = params
        return _ExecuteResult(len(params["payloads"]))


def _finding(entity_id: str) -> dict[str, Any]:
    provider = "test-provider"
    dataset = "places"
    return {
        "provider": provider,
        "dataset_key": dataset,
        "source_record_key": None,
        "feature_id": None,
        "violation_type": "missing_address",
        "severity": "warning",
        "message": entity_id,
        "payload": {
            "dedupe_key": make_integrity_finding_key(
                provider=provider,
                dataset_key=dataset,
                source_entity_type="place",
                source_entity_id=entity_id,
                violation_type="missing_address",
            ),
            "occurrence_count": 1,
        },
    }


async def test_sync_orders_every_array_by_dedupe_key_before_upsert() -> None:
    session = _CapturingSession()
    findings = [_finding("z"), _finding("a"), _finding("m")]

    upserted = await sync_integrity_findings(
        cast("AsyncSession", session),
        provider="test-provider",
        dataset_key="places",
        findings=findings,
    )

    assert upserted == 3
    assert session.params is not None
    payloads = [json.loads(value) for value in session.params["payloads"]]
    keys = [payload["dedupe_key"] for payload in payloads]
    assert keys == sorted(keys)


async def test_sync_rejects_unbounded_legacy_dedupe_key() -> None:
    session = _CapturingSession()
    finding = _finding("entity")
    finding["payload"]["dedupe_key"] = "address_validation:" + "x" * 20_000

    with pytest.raises(ValueError, match="av2_<sha256>"):
        await sync_integrity_findings(
            cast("AsyncSession", session),
            provider="test-provider",
            dataset_key="places",
            findings=[finding],
        )
