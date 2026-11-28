"""등산 코스 asset — 구간 은퇴를 코스 적재와 한 호출(한 transaction)로 넘긴다(ADR-128 개정).

#1569는 코스 적재 뒤 ``load_authoritative_feature_snapshot([], retired_source_entity_ids=...)``를
**따로** 불러 구간을 은퇴시키고, 첫 호출의 seal 값(은퇴 전)을 결과로 돌려줬다. 그 값으로 child 완료
seal을 잡으면 은퇴가 있는 run마다 어긋났다. 여기서는 asset이 (1) snapshot 호출을 한 번만 하고,
(2) 그 호출에 코스가 덮은 구간을 ``superseded``로 넘기며, (3) 그 호출의 seal 값을 그대로 돌려주고,
(4) sync 성공은 그 적재가 끝난 뒤에 은퇴 수와 함께 남긴다는 배선을 고정한다. 실제 seal 왕복은
``tests/integration/test_course_segment_retire_seal.py``가 본다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from dagster import build_asset_context
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra.feature_repo import FeatureLoadResult, SupersededSourceEntities
from kortravelmap.providers.krforest import (
    MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE,
    MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE,
)

from kortravelmap.dagster.assets import run_feature_route_krforest_mountain_trails


@dataclass(frozen=True)
class _Trail:
    name: str | None
    source_id: str | None
    source_file: str | None
    layer_name: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    bbox: tuple[float, float, float, float] | None
    raw: Any = field(default_factory=dict)


def _trail(
    serial: int, coords: list[tuple[float, float]], *, segment_name: str, length_km: float = 0.88
) -> _Trail:
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return _Trail(
        name=f"시험산 {segment_name}",
        source_id=f"unit-course:{serial}",
        source_file="mountain/unit.zip/PMNTN.shp",
        layer_name="PMNTN",
        geometry_type="LineString",
        geometry={"type": "LineString", "coordinates": [list(c) for c in coords]},
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        raw={
            "MNTN_CODE": "999900001",
            "MNTN_NM": "시험산",
            "PMNTN_NM": segment_name,
            "PMNTN_SN": serial,
            "PMNTN_LT": length_km,
            "PMNTN_UPPL": 16,
            "PMNTN_GODN": 11,
            "PMNTN_DFFL": "중간",
        },
    )


_RECORDS = [
    _trail(1, [(127.000, 37.5), (127.010, 37.5)], segment_name="서쪽구간"),
    _trail(2, [(127.020, 37.5), (127.010, 37.5)], segment_name="서쪽구간"),
    _trail(3, [(127.100, 37.5), (127.140, 37.5)], segment_name="동쪽구간", length_km=3.53),
]
_MEMBERSHIP = ProviderDatasetOperationMembership(
    provider_dataset_id=41,
    sync_scope="dataset_wide",
    operation_key="feature_route_krforest_mountain_trails_job",
)


class _FakeClient:
    def __init__(self, *, fail_snapshot: bool = False) -> None:
        self.events: list[str] = []
        self.snapshot_calls: list[dict[str, Any]] = []
        self.sync_cursors: list[dict[str, Any]] = []
        self.fail_snapshot = fail_snapshot

    async def load_authoritative_feature_snapshot(
        self, bundles: Any, **kwargs: Any
    ) -> tuple[FeatureLoadResult, int]:
        self.events.append("snapshot")
        materialized = list(bundles)
        self.snapshot_calls.append({"bundles": materialized, **kwargs})
        if self.fail_snapshot:
            raise RuntimeError("snapshot transaction rolled back")
        superseded = kwargs.get("superseded")
        return (
            FeatureLoadResult(
                bundles_total=len(materialized),
                features_inserted=len(materialized),
                superseded_retired=len(superseded.source_entity_ids) if superseded else 0,
                curation_input_member_count=7,
                curation_input_set_hash="sealed-after-retirement",
            ),
            0,
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        recorded = list(findings)  # type: ignore[call-overload]
        return IntegrityFindingSyncResult(len(recorded), len(recorded), len(recorded))

    def record_sync_success(self) -> None:  # 존재만 본다(_record_feature_sync_success).
        raise AssertionError("membership 경로를 써야 한다")

    async def record_sync_success_for_operation_membership(
        self, *, membership: ProviderDatasetOperationMembership, cursor: dict[str, Any]
    ) -> None:
        assert membership == _MEMBERSHIP
        self.events.append("sync")
        self.sync_cursors.append(cursor)


async def _reverse(coord: Coordinate) -> Address:
    return Address(
        legal="강원특별자치도 춘천시 신북읍",
        bjd_code="5111025000",
        sigungu_code="51110",
        sido_code="51",
        sido_name="강원특별자치도",
        sigungu_name="춘천시",
    )


def _context(client: _FakeClient) -> Any:
    return build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": _reverse,
            "fetched_at": None,
            "strict_address": True,
            "krforest_mountain_trails": list(_RECORDS),
            "feature_update_membership": _MEMBERSHIP,
        }
    )


async def test_course_load_retires_covered_segments_in_the_same_snapshot_call() -> None:
    client = _FakeClient()

    result = await run_feature_route_krforest_mountain_trails(_context(client))

    # 한 번의 snapshot 호출 = 한 transaction. 은퇴만 하는 두 번째 호출이 없다.
    assert client.events == ["snapshot", "sync"]
    [call] = client.snapshot_calls
    assert call["source_entity_type"] == MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE
    assert call["retire_absent_from_snapshot"] is True
    assert call["superseded"] == SupersededSourceEntities(
        source_entity_type=MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE,
        source_entity_ids=frozenset({"unit-course:1", "unit-course:2", "unit-course:3"}),
    )
    assert len(call["bundles"]) == 2
    # run이 child 완료 seal에 넘기는 값은 은퇴까지 끝난 그 호출의 seal이다.
    assert result.load.curation_input_member_count == 7
    assert result.load.curation_input_set_hash == "sealed-after-retirement"
    assert result.load.superseded_retired == 3
    [cursor] = client.sync_cursors
    assert cursor["segment_routes_retired"] == 3
    assert cursor["course_segments_covered"] == 3
    assert cursor["course_segments_source"] == 3


async def test_failed_snapshot_records_no_sync_success() -> None:
    """적재(=은퇴) transaction이 실패하면 sync 성공을 남기지 않는다.

    은퇴가 적재와 한 transaction이라 코스만 commit되고 구간이 공개로 남는 중간 상태도 없다.
    """
    client = _FakeClient(fail_snapshot=True)

    with pytest.raises(RuntimeError, match="rolled back"):
        await run_feature_route_krforest_mountain_trails(_context(client))

    assert client.events == ["snapshot"]
    assert client.sync_cursors == []
