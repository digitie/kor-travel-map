"""저장값 재사용 변환(ADR-116) — payload·좌표·토큰이 그대로인 행은 geo를 부르지 않는다.

실제 provider 변환기(KNPS 탐방지원센터 — 좌표 하나에 reverse 한 번, 답을 그대로 주소로 쓴다)에 세는
역지오코더를 꽂는다. DB 조회(``lookup``)는 대역이다 — 그 SQL 술어는 통합
검사(``tests/integration/test_geo_reuse_load_path.py``)가 본다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from kortravelmap.dto import Address, Coordinate
from kortravelmap.geocoding import GeoCallStats, ReverseGeocoder
from kortravelmap.infra.feature_geocode_load import address_column_values
from kortravelmap.providers.knps import knps_point_records_to_bundles

from kortravelmap.dagster.geo_reuse import transform_reusing_stored_geo

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kortravelmap.dto import FeatureBundle

from datetime import UTC, datetime

_FETCHED = datetime(2026, 10, 23, tzinfo=UTC)
_DATASET = "knps_visitor_centers"


@dataclass(frozen=True)
class _Point:
    source_id: str
    name: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    raw: dict[str, Any] = field(default_factory=dict)


def _point(source_id: str, lon: str, lat: str, *, note: str = "") -> _Point:
    return _Point(
        source_id=source_id,
        name=f"탐방지원센터 {source_id}",
        longitude=Decimal(lon),
        latitude=Decimal(lat),
        raw={"id": source_id, "lon": lon, "lat": lat, "note": note},
    )


def _answer(coord: Coordinate, *, generation: str = "A") -> Address:
    """좌표의 함수인 결정적 geo 답(같은 토큰이면 같은 좌표에 같은 답)."""
    return Address(
        legal=f"강원특별자치도 인제군 북면 {coord.lon}-{generation}",
        bjd_code="5181036021",
        sigungu_code="51810",
        sido_code="51",
        sido_name="강원특별자치도",
        sigungu_name="인제군",
        zipcode="24600",
    )


class _CountingReverse:
    def __init__(self, *, generation: str = "A") -> None:
        self.calls: list[tuple[str, str]] = []
        self.generation = generation

    async def __call__(self, coord: Coordinate) -> Address | None:
        self.calls.append((str(coord.lon), str(coord.lat)))
        return _answer(coord, generation=self.generation)


def _transform(points: Sequence[_Point]) -> Any:
    async def run(geocoder: ReverseGeocoder) -> list[FeatureBundle]:
        return await knps_point_records_to_bundles(
            points,  # type: ignore[arg-type]
            dataset_key=_DATASET,
            fetched_at=_FETCHED,
            reverse_geocoder=geocoder,
        )

    return run


def _stored_from(bundles: Sequence[FeatureBundle]) -> dict[str, dict[str, Any]]:
    """지난 run이 적재한 저장값 — 적재 경로가 쓰는 열 모양(``address_column_values``)."""
    return {
        bundle.source_record.source_record_key: address_column_values(bundle.feature.address)
        for bundle in bundles
    }


class _Lookup:
    def __init__(self, stored: Mapping[str, Mapping[str, Any]]) -> None:
        self.stored = stored
        self.asked: list[list[str]] = []

    async def __call__(self, bundles: Sequence[FeatureBundle]) -> Mapping[str, Mapping[str, Any]]:
        keys = [bundle.source_record.source_record_key for bundle in bundles]
        self.asked.append(keys)
        return {key: self.stored[key] for key in keys if key in self.stored}


def _dump(bundles: Sequence[FeatureBundle]) -> list[str]:
    return sorted(json.dumps(bundle.model_dump(mode="json"), sort_keys=True) for bundle in bundles)


async def _full(points: Sequence[_Point]) -> list[FeatureBundle]:
    return await _transform(points)(_CountingReverse())


async def test_unchanged_rows_skip_geo_and_equal_a_full_geocode() -> None:
    points = [_point("p1", "128.1", "38.1"), _point("p2", "128.2", "38.2")]
    previous = await _full(points)
    live = _CountingReverse()
    stats = GeoCallStats()

    bundles = await transform_reusing_stored_geo(
        _transform(points), live=live, lookup=_Lookup(_stored_from(previous)), stats=stats
    )

    assert live.calls == []
    assert _dump(bundles) == _dump(await _full(points))
    assert dict(stats.reuse) == {"skipped": 2, "geocoded": 0, "fallback": 0}
    assert "저장값 재사용 skipped=2 geocoded=0 fallback=0" in stats.summary()
    assert stats.as_metadata()["geo_reuse_skipped"] == 2


async def test_changed_payload_still_geocodes() -> None:
    before = [_point("p1", "128.1", "38.1"), _point("p2", "128.2", "38.2")]
    previous = await _full(before)
    after = [_point("p1", "128.1", "38.1"), _point("p2", "128.2", "38.2", note="바뀜")]
    live = _CountingReverse()
    stats = GeoCallStats()

    bundles = await transform_reusing_stored_geo(
        _transform(after), live=live, lookup=_Lookup(_stored_from(previous)), stats=stats
    )

    assert live.calls == [("128.2", "38.2")]
    assert _dump(bundles) == _dump(await _full(after))
    assert dict(stats.reuse) == {"skipped": 1, "geocoded": 1, "fallback": 0}


async def test_changed_coordinate_still_geocodes() -> None:
    previous = await _full([_point("p1", "128.1", "38.1")])
    moved = [_point("p1", "128.3", "38.3")]
    live = _CountingReverse()

    bundles = await transform_reusing_stored_geo(
        _transform(moved), live=live, lookup=_Lookup(_stored_from(previous))
    )

    assert live.calls == [("128.3", "38.3")]
    assert _dump(bundles) == _dump(await _full(moved))


async def test_rows_the_lookup_rejects_still_geocode() -> None:
    """stale 토큰·override·retired 등 DB 조건 밖의 행은 lookup이 돌려주지 않는다 — geo를 부른다."""
    points = [_point("p1", "128.1", "38.1"), _point("p2", "128.2", "38.2")]
    previous = _stored_from(await _full(points))
    stale_key = next(iter(previous))  # 하나만 재사용 가능 — 다른 하나는 stale로 본다
    live = _CountingReverse(generation="B")

    bundles = await transform_reusing_stored_geo(
        _transform(points), live=live, lookup=_Lookup({stale_key: previous[stale_key]})
    )

    assert len(live.calls) == 1
    by_key = {b.source_record.source_record_key: b for b in bundles}
    assert by_key[stale_key].feature.address.legal is not None
    assert by_key[stale_key].feature.address.legal.endswith("-A")
    other = next(key for key in by_key if key != stale_key)
    assert by_key[other].feature.address.legal is not None
    assert by_key[other].feature.address.legal.endswith("-B")


async def test_a_shared_coordinate_with_a_changed_neighbour_geocodes_both() -> None:
    before = [_point("p1", "128.1", "38.1"), _point("p2", "128.1", "38.1")]
    previous = await _full(before)
    after = [_point("p1", "128.1", "38.1"), _point("p2", "128.1", "38.1", note="바뀜")]
    live = _CountingReverse()
    stats = GeoCallStats()

    await transform_reusing_stored_geo(
        _transform(after), live=live, lookup=_Lookup(_stored_from(previous)), stats=stats
    )

    assert live.calls == [("128.1", "38.1")]  # provider 캐시가 같은 좌표를 한 번으로 묶는다
    assert dict(stats.reuse) == {"skipped": 0, "geocoded": 2, "fallback": 1}


async def test_a_shared_coordinate_with_different_stored_values_geocodes() -> None:
    points = [_point("p1", "128.1", "38.1"), _point("p2", "128.1", "38.1")]
    stored = _stored_from(await _full(points))
    first, second = list(stored)
    stored[second] = {**stored[second], "road_name_code": "999999999999"}
    live = _CountingReverse()

    await transform_reusing_stored_geo(_transform(points), live=live, lookup=_Lookup(stored))

    assert live.calls == [("128.1", "38.1")]
    assert first != second


async def test_a_merge_that_is_not_idempotent_falls_back_to_geo() -> None:
    """provider 병합이 저장값에 대해 멱등이 아니면 사후 확인이 잡아 geo로 다시 한다."""
    points = [_point("p1", "128.1", "38.1")]
    inner = _transform(points)

    async def appending(geocoder: ReverseGeocoder) -> list[FeatureBundle]:
        bundles = await inner(geocoder)
        return [
            bundle.model_copy(
                update={
                    "feature": bundle.feature.model_copy(
                        update={
                            "address": bundle.feature.address.model_copy(
                                update={"legal": f"{bundle.feature.address.legal} 덧붙임"}
                            )
                        }
                    )
                }
            )
            for bundle in bundles
        ]

    previous = await appending(_CountingReverse())
    live = _CountingReverse()
    stats = GeoCallStats()

    bundles = await transform_reusing_stored_geo(
        appending, live=live, lookup=_Lookup(_stored_from(previous)), stats=stats
    )

    assert live.calls == [("128.1", "38.1")]
    assert _dump(bundles) == _dump(previous)
    assert dict(stats.reuse) == {"skipped": 0, "geocoded": 1, "fallback": 1}


async def test_stored_values_that_fail_validation_fall_back_to_geo() -> None:
    """저장값에 법정동코드가 없으면(차단 issue) 새 답이 고칠 수 있으므로 geo를 부른다."""
    points = [_point("p1", "128.1", "38.1")]
    stored = _stored_from(await _full(points))
    key = next(iter(stored))
    empty = address_column_values(Address())
    live = _CountingReverse()

    bundles = await transform_reusing_stored_geo(
        _transform(points), live=live, lookup=_Lookup({key: empty})
    )

    assert live.calls == [("128.1", "38.1")]
    assert bundles[0].feature.address.bjd_code == "5181036021"


async def test_requests_outside_the_row_coordinates_disable_reuse() -> None:
    """provider가 행 좌표가 아닌 점을 물으면 어느 행의 답인지 가를 수 없다 — 재사용하지 않는다."""
    points = [_point("p1", "128.1", "38.1")]
    previous = await _full(points)
    inner = _transform(points)
    elsewhere = Coordinate(lon=Decimal("128.9"), lat=Decimal("38.9"))

    async def peeking(geocoder: ReverseGeocoder) -> list[FeatureBundle]:
        await geocoder(elsewhere)
        return await inner(geocoder)

    live = _CountingReverse()
    await transform_reusing_stored_geo(
        peeking, live=live, lookup=_Lookup(_stored_from(previous))
    )

    assert ("128.1", "38.1") in live.calls


async def test_a_transform_that_rejects_empty_answers_runs_the_plain_path() -> None:
    points = [_point("p1", "128.1", "38.1")]
    inner = _transform(points)

    async def strict(geocoder: ReverseGeocoder) -> list[FeatureBundle]:
        bundles = await inner(geocoder)
        if any(bundle.feature.address.bjd_code is None for bundle in bundles):
            raise ValueError("빈 답")
        return bundles

    live = _CountingReverse()
    lookup = _Lookup({})
    bundles = await transform_reusing_stored_geo(strict, live=live, lookup=lookup)

    assert live.calls == [("128.1", "38.1")]
    assert lookup.asked == []
    assert bundles[0].feature.address.bjd_code == "5181036021"


async def test_nothing_reusable_skips_the_lookup_table_and_geocodes_everything() -> None:
    points = [_point("p1", "128.1", "38.1"), _point("p2", "128.2", "38.2")]
    live = _CountingReverse()
    stats = GeoCallStats()

    bundles = await transform_reusing_stored_geo(
        _transform(points), live=live, lookup=_Lookup({}), stats=stats
    )

    assert sorted(live.calls) == [("128.1", "38.1"), ("128.2", "38.2")]
    assert _dump(bundles) == _dump(await _full(points))
    assert dict(stats.reuse) == {"skipped": 0, "geocoded": 2, "fallback": 0}


@pytest.mark.parametrize("token", [None, "dd1-" + "b" * 32])
async def test_asset_helper_reuses_only_with_a_current_token(token: str | None) -> None:
    """``_transform_reusing_geo``는 run 토큰이 있을 때만 조회한다 — 없으면 원래 호출 그대로."""
    from types import SimpleNamespace

    from kortravelmap.dto.geo_dataset import DatasetRef

    from kortravelmap.dagster import assets

    points = [_point("p1", "128.1", "38.1")]
    previous = _stored_from(await _full(points))
    asked: list[str | None] = []

    class _Client:
        async def read_reusable_geo_columns(
            self, bundles: Sequence[FeatureBundle], *, current_data_token: str
        ) -> Mapping[str, Mapping[str, Any]]:
            asked.append(current_data_token)
            return previous

    class _Handle:
        async def current(self) -> DatasetRef | None:
            if token is None:
                return None
            return DatasetRef(version_token="dv1-" + "a" * 32, data_token=token)

    context = SimpleNamespace(
        resources=SimpleNamespace(kor_travel_map_client=_Client(), kor_travel_geo_dataset=_Handle())
    )
    live = _CountingReverse()

    bundles = await assets._transform_reusing_geo(  # noqa: SLF001
        context,  # type: ignore[arg-type]
        knps_point_records_to_bundles,
        points,
        dataset_key=_DATASET,
        fetched_at=_FETCHED,
        reverse_geocoder=live,
    )

    assert len(bundles) == 1
    if token is None:
        assert asked == []
        assert live.calls == [("128.1", "38.1")]
    else:
        assert asked == [token]
        assert live.calls == []


async def test_a_retry_does_not_ask_geo_again() -> None:
    """사후 확인이 어긋나 다시 변환해도 이미 받은 실제 답은 다시 묻지 않는다(설계 리뷰 MED-1)."""
    old = [_point("p1", "128.1", "38.1")]
    now = [_point("p1", "128.1", "38.1"), _point("p2", "128.2", "38.2")]

    def appending(points: Sequence[_Point]) -> Any:
        inner = _transform(points)

        async def run(geocoder: ReverseGeocoder) -> list[FeatureBundle]:
            return [
                bundle.model_copy(
                    update={
                        "feature": bundle.feature.model_copy(
                            update={
                                "address": bundle.feature.address.model_copy(
                                    update={"legal": f"{bundle.feature.address.legal} 덧붙임"}
                                )
                            }
                        )
                    }
                )
                for bundle in await inner(geocoder)
            ]

        return run

    previous = await appending(old)(_CountingReverse())
    live = _CountingReverse()
    stats = GeoCallStats()

    await transform_reusing_stored_geo(
        appending(now), live=live, lookup=_Lookup(_stored_from(previous)), stats=stats
    )

    assert sorted(live.calls) == [("128.1", "38.1"), ("128.2", "38.2")]  # 각 한 번
    assert dict(stats.reuse) == {"skipped": 0, "geocoded": 2, "fallback": 1}


async def test_a_stored_address_the_dto_no_longer_accepts_falls_back() -> None:
    """옛 저장 jsonb가 지금의 ``Address`` 검증에 실패해도 run이 죽지 않고 geo에 묻는다.

    설계 리뷰 MED-2.
    """
    points = [_point("p1", "128.1", "38.1")]
    stored = _stored_from(await _full(points))
    key = next(iter(stored))
    stored[key] = {**stored[key], "address": {**stored[key]["address"], "retired_field": "x"}}
    live = _CountingReverse()
    stats = GeoCallStats()

    bundles = await transform_reusing_stored_geo(
        _transform(points), live=live, lookup=_Lookup(stored), stats=stats
    )

    assert live.calls == [("128.1", "38.1")]
    assert bundles[0].feature.address.bjd_code == "5181036021"
    assert dict(stats.reuse) == {"skipped": 0, "geocoded": 1, "fallback": 1}


async def test_the_safety_net_is_counted_as_disabled_not_as_nothing_to_reuse() -> None:
    points = [_point("p1", "128.1", "38.1")]
    previous = await _full(points)
    inner = _transform(points)
    elsewhere = Coordinate(lon=Decimal("128.9"), lat=Decimal("38.9"))

    async def peeking(geocoder: ReverseGeocoder) -> list[FeatureBundle]:
        await geocoder(elsewhere)
        return await inner(geocoder)

    lookup = _Lookup(_stored_from(previous))
    stats = GeoCallStats()
    await transform_reusing_stored_geo(peeking, live=_CountingReverse(), lookup=lookup, stats=stats)

    assert lookup.asked == []  # 조회조차 하지 않는다
    assert stats.reuse["disabled"] == 1
    assert "disabled=1" in stats.summary()
