"""공개 목록·상세의 ``route`` 요약 부착 (ADR-128)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest
from kortravelmap.infra import route_summary_repo
from kortravelmap.infra.route_summary_repo import PublicRouteSummary

from kortravelmap.api.routers import features as features_router
from kortravelmap.api.routers.features import FeatureSummary, NearbyFeatureSummary


def _summary(feature_id: str, **overrides: Any) -> PublicRouteSummary:
    values: dict[str, Any] = {
        "feature_id": feature_id,
        "route_type": "hiking_course",
        "length_m": 4210.5,
        "duration_minutes": 150,
        "duration_basis": "estimated",
        "difficulty": "moderate",
        "shape": "path",
        "start": (127.0, 37.5),
        "start_name": "노고단고개",
        "end": (127.03, 37.5),
        "end_name": "천왕봉",
    }
    values.update(overrides)
    return PublicRouteSummary(**values)


@pytest.mark.unit
def test_attach_route_summaries_only_queries_route_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    async def _fake(session: Any, feature_ids: Sequence[str]) -> dict[str, PublicRouteSummary]:
        seen.append(list(feature_ids))
        return {"r1": _summary("r1")}

    monkeypatch.setattr(route_summary_repo, "list_public_route_summaries", _fake)
    items = [
        FeatureSummary(feature_id="p1", kind="place", name="카페", category="05010100",
                       lon=127.0, lat=37.5),
        FeatureSummary(feature_id="r1", kind="route", name="코스", category="01080500",
                       lon=127.0, lat=37.5),
    ]
    out = asyncio.run(features_router._attach_route_summaries(object(), items))  # type: ignore[arg-type]

    assert seen == [["r1"]]
    assert out[0].route is None
    route = out[1].route
    assert route is not None
    assert route.route_type == "hiking_course"
    assert route.duration_basis == "estimated"
    assert route.start is not None
    assert route.start.name == "노고단고개"
    assert route.end is not None
    assert route.end.lon == pytest.approx(127.03)


@pytest.mark.unit
def test_attach_route_summaries_skips_query_without_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail(session: Any, feature_ids: Sequence[str]) -> dict[str, PublicRouteSummary]:
        raise AssertionError("route가 없으면 조회하지 않는다")

    monkeypatch.setattr(route_summary_repo, "list_public_route_summaries", _fail)
    items = [
        NearbyFeatureSummary(feature_id="p1", kind="place", name="카페", category="05010100",
                             lon=127.0, lat=37.5, distance_m=10.0),
    ]
    assert asyncio.run(features_router._attach_route_summaries(object(), items)) == items  # type: ignore[arg-type]


@pytest.mark.unit
def test_route_out_drops_unknown_enums_and_missing_points() -> None:
    route = features_router._route_out(
        _summary("r1", duration_basis="weird", shape=None, start=None, end=None)
    )
    assert route.duration_basis is None
    assert route.shape is None
    assert route.start is None
    assert route.end is None


@pytest.mark.unit
def test_batch_trip_card_carries_route_only_for_found_items() -> None:
    found = features_router.FeatureBatchFoundItem(
        state="found",
        feature_id="r1",
        row_revision=3,
        trip_card=features_router.FeatureTripCard(
            feature_id="r1", kind="route", name="코스", category="01080500", lon=127.0,
            lat=37.5, address={}, marker_icon="park", marker_color="P-06",
        ),
    )
    with_route = features_router._with_trip_card_route(found, _summary("r1"))
    assert isinstance(with_route, features_router.FeatureBatchFoundItem)
    assert with_route.trip_card.route is not None
    assert with_route.trip_card.route.length_m == pytest.approx(4210.5)

    missing = features_router.FeatureBatchMissingItem(state="missing", feature_id="x")
    assert features_router._with_trip_card_route(missing, _summary("x")) is missing
    assert features_router._with_trip_card_route(found, None) is found
