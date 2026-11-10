"""국가유산 행사 asset — 회차 묶음·장소 좌표·옛 키 은퇴 배선(#1468 D).

변환 규칙은 ``tests/unit/test_providers_krheritage.py``가 갖는다. 여기서는 asset이 (1) 장소 해석기를
client 후보 읽기에 잇고, (2) 회차별 옛 자연키만 retired로 내리며, (3) 빈 snapshot에서는 아무것도
내리지 않는다는 배선을 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from dagster import build_asset_context
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.venue_match import VenueCandidate
from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra.feature_repo import FeatureLoadResult

from kortravelmap.dagster.assets import run_feature_event_krheritage_events

_LEGACY_IDS = {"15720::2026-10-17::2026-10-17", "허선구 고가 행사::2026-10-17::허선구고가"}
_CURRENT_PROGRAM_ID = "program::0123456789abcdef0123456789abcdef"


@dataclass(frozen=True)
class _Current:
    source_entity_id: str


@dataclass(frozen=True)
class _Row:
    sn: str | None = None
    title: str | None = None
    starts_on: Any = None
    ends_on: Any = None
    place: str | None = None
    tel_name: str | None = None
    address: str | None = None
    longitude: Any = None
    latitude: Any = None
    main_image: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _row(seq: str, s_date: str) -> _Row:
    return _Row(
        raw={
            "seqNo": seq,
            "subTitle": "진주성 야행",
            "sDate": s_date,
            "eDate": s_date,
            "subDesc": "진주성 일원",
            "subDate": "10월 22일 ~ 24일(총3회)/ 19시 ~ 21시",
            "groupName": "진주문화원",
            "contact": "055-000-0000",
            "sido": "경상남도",
            "gugun": "진주시",
        }
    )


class _FakeClient:
    def __init__(self) -> None:
        self.loaded: list[Any] = []
        self.retired_ids: set[str] | None = None
        self.venue_queries: list[str] = []

    async def read_current_source_records(
        self, *, provider: str, dataset_key: str
    ) -> tuple[list[_Current], int]:
        assert provider == "python-krheritage-api"
        assert dataset_key == "krheritage_event_list"
        ids = [*_LEGACY_IDS, _CURRENT_PROGRAM_ID]
        return [_Current(i) for i in ids], len(ids)

    async def find_venue_candidates(self, name: str) -> list[VenueCandidate]:
        self.venue_queries.append(name)
        if name != "진주성":
            return []
        return [
            VenueCandidate(
                feature_id="00000000-0000-7000-8000-000000000001",
                name="진주성",
                coord=Coordinate(lon=Decimal("128.0817"), lat=Decimal("35.1887")),
                sido_name="경상남도",
                sigungu_name="진주시",
                dataset_key="krheritage_heritage_features",
            )
        ]

    async def load_authoritative_feature_snapshot(
        self,
        bundles: Any,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        retired_source_entity_ids: set[str] | None = None,
        retire_geometryless_areas: bool = False,
        retire_absent_from_snapshot: bool = False,
        geo: Any = None,
    ) -> tuple[FeatureLoadResult, int]:
        assert not retire_geometryless_areas
        assert not retire_absent_from_snapshot
        assert source_entity_type == "heritage_event"
        materialized = list(bundles)
        self.loaded.extend(materialized)
        self.retired_ids = set(retired_source_entity_ids or set())
        return (
            FeatureLoadResult(bundles_total=len(materialized), features_inserted=len(materialized)),
            len(self.retired_ids),
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        recorded = list(findings)  # type: ignore[call-overload]
        return IntegrityFindingSyncResult(len(recorded), len(recorded), len(recorded))


async def _reverse(coord: Coordinate) -> Address:
    return Address(
        legal="경상남도 진주시 본성동",
        bjd_code="4817010100",
        sigungu_code="48170",
        sido_code="48",
        sido_name="경상남도",
        sigungu_name="진주시",
    )


def _context(client: _FakeClient, records: list[_Row]) -> Any:
    return build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": _reverse,
            "fetched_at": None,
            "strict_address": True,
            "krheritage_events": records,
        }
    )


async def test_sessions_collapse_get_venue_coordinate_and_retire_only_legacy_keys() -> None:
    client = _FakeClient()
    rows = [_row("17627", "20261022"), _row("17628", "20261023"), _row("17627", "20261024")]

    result = await run_feature_event_krheritage_events(_context(client, rows))

    assert result.load.bundles_total == 1
    [bundle] = client.loaded
    assert bundle.source_record.source_entity_id.startswith("program::")
    assert bundle.feature.coord == Coordinate(lon=Decimal("128.0817"), lat=Decimal("35.1887"))
    payload = bundle.feature.detail.payload
    assert payload["coordinate_source"] == "venue_feature"
    assert payload["venue_feature_id"] == "00000000-0000-7000-8000-000000000001"
    assert [s["starts_on"] for s in payload["sessions"]] == [
        "2026-10-22",
        "2026-10-23",
        "2026-10-24",
    ]
    # 회차별 옛 키만 내린다 — 이미 묶은 키(``program::``)는 snapshot 부재여도 건드리지 않는다.
    assert client.retired_ids == _LEGACY_IDS
    assert client.venue_queries == ["진주성"]


async def test_empty_snapshot_retires_nothing() -> None:
    client = _FakeClient()

    result = await run_feature_event_krheritage_events(_context(client, []))

    assert result.load.bundles_total == 0
    assert client.retired_ids == set()
