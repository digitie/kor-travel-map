"""geo 데이터셋 토큰 파싱·``dataset_version()``·빈 답 계수·outcome 판정 (ADR-109 결정 1~3, T-GR-01).

효과에 결박한다 — ``dataset_version()``은 가짜 transport가 **실제로 받은** 요청(경로·본문)과
대조하고,
빈 답 계수는 응답 픽스처의 bjd 유무로 정한 분자와 대조한다(파생값에 맞추지 않는다).
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from kortravelmap.core.exceptions import GeoRequestError
from kortravelmap.dto import Coordinate
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoAttemptEvidence
from kortravelmap.geocoding import (
    GeoCallStats,
    KorTravelGeoRestClient,
    kor_travel_geo_reverse_geocoder,
)
from kortravelmap.infra.feature_geocode_stamp_repo import decide_outcome

pytestmark = pytest.mark.unit

_API_KEY = SecretStr("test-key")
VERSION = "dv1-" + "a" * 32
DATA = "dd1-" + "b" * 32
OTHER_DATA = "dd1-" + "c" * 32

_CANDIDATE_WITH_BJD: dict[str, Any] = {
    "point": {"lon": 127.0, "lat": 37.0},
    "distance_m": 1.0,
    "confidence": 0.9,
    "match_kind": "road",
    "address": {
        "full": "서울특별시 영등포구 여의공원로 120",
        "road_address": "서울특별시 영등포구 여의공원로 120",
        "legal_dong_code": "1156010100",
    },
    "region": {
        "sig_cd": "11560",
        "bjd_cd": "1156010100",
        "sido": "서울특별시",
        "sigungu": "영등포구",
    },
}


def _reverse_payload(*, bjd: bool, dataset: object = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "OK" if bjd else "ZERO_RESULTS",
        "candidates": [_CANDIDATE_WITH_BJD] if bjd else [],
    }
    if dataset is not None:
        payload["dataset"] = dataset
    return payload


class _Transport(httpx.AsyncBaseTransport):
    """경로별 응답을 차례로 내고, 받은 요청(경로·본문)을 기록한다."""

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.seen: list[tuple[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.url.path, body))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json=item, request=request)


def _client(
    transport: _Transport, stats: GeoCallStats | None = None
) -> tuple[KorTravelGeoRestClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(base_url="http://geo.test", transport=transport)
    return KorTravelGeoRestClient(http, api_key=_API_KEY, stats=stats), http


# -- 응답 dataset 선택 파싱 ----------------------------------------------------------


async def test_reverse_without_dataset_field_parses_to_none() -> None:
    client, http = _client(_Transport([_reverse_payload(bjd=True)]))
    try:
        response = await client.reverse(127.0, 37.0)
    finally:
        await http.aclose()
    assert response.dataset is None
    assert response.candidates  # 옛 응답은 그대로 읽힌다


async def test_reverse_with_dataset_field_parses_to_dataset_ref() -> None:
    dataset = {"version_token": VERSION, "data_token": DATA}
    client, http = _client(_Transport([_reverse_payload(bjd=True, dataset=dataset)]))
    try:
        response = await client.reverse(127.0, 37.0)
    finally:
        await http.aclose()
    assert response.dataset == DatasetRef(version_token=VERSION, data_token=DATA)


@pytest.mark.parametrize(
    "dataset",
    [
        {"version_token": "dv1-short", "data_token": DATA},
        {"version_token": VERSION, "data_token": "dd1-" + "Z" * 32},
        "not-an-object",
    ],
)
async def test_malformed_response_dataset_is_dropped_not_fatal(dataset: object) -> None:
    client, http = _client(_Transport([_reverse_payload(bjd=True, dataset=dataset)]))
    try:
        response = await client.reverse(127.0, 37.0)
    finally:
        await http.aclose()
    assert response.dataset is None
    assert response.candidates


async def test_dataset_without_data_token_keeps_version_only() -> None:
    client, http = _client(
        _Transport([_reverse_payload(bjd=True, dataset={"version_token": VERSION})])
    )
    try:
        response = await client.reverse(127.0, 37.0)
    finally:
        await http.aclose()
    assert response.dataset == DatasetRef(version_token=VERSION, data_token=None)


# -- dataset_version() -----------------------------------------------------------------


async def test_dataset_version_posts_empty_body_and_returns_current_ref() -> None:
    transport = _Transport(
        [
            {
                "status": "OK",
                "available": True,
                "current": {
                    "version_token": VERSION,
                    "activated_at": "2026-10-15T00:00:00Z",
                    "change_type": "full",
                    "data_token": DATA,
                },
            }
        ]
    )
    client, http = _client(transport)
    try:
        ref = await client.dataset_version()
    finally:
        await http.aclose()
    assert transport.seen == [("/v2/dataset/version", {})]
    assert ref == DatasetRef(
        version_token=VERSION,
        data_token=DATA,
        activated_at=datetime(2026, 10, 15, tzinfo=UTC),
    )


async def test_dataset_version_carries_observation_fields_and_drops_malformed_ones() -> None:
    """``activated_at``·``reference_months``는 관측용 선택 필드다(T-GR-04 계획 표가 기록) —
    형식이 틀리면 버리고 토큰 판정은 그대로다."""
    current = {
        "version_token": VERSION,
        "data_token": DATA,
        "activated_at": "2026-08-20T03:12:45+09:00",
        "reference_months": {"juso": "202607", "navi": "202606"},
    }
    broken = {
        "version_token": VERSION,
        "data_token": DATA,
        "activated_at": "어제",
        "reference_months": {"juso": 202607},
    }
    client, http = _client(
        _Transport(
            [
                {"status": "OK", "available": True, "current": current},
                {"status": "OK", "available": True, "current": broken},
            ]
        )
    )
    try:
        good = await client.dataset_version()
        dropped = await client.dataset_version()
    finally:
        await http.aclose()
    assert good is not None
    assert good.reference_months == {"juso": "202607", "navi": "202606"}
    assert good.activated_at is not None
    assert good.activated_at.utcoffset() is not None
    assert dropped == DatasetRef(version_token=VERSION, data_token=DATA)


async def test_dataset_version_unavailable_is_none() -> None:
    client, http = _client(_Transport([{"status": "OK", "available": False}]))
    try:
        assert await client.dataset_version() is None
    finally:
        await http.aclose()


async def test_dataset_version_release_without_fingerprint_has_none_data_token() -> None:
    client, http = _client(
        _Transport(
            [{"status": "OK", "available": True, "current": {"version_token": VERSION}}]
        )
    )
    try:
        ref = await client.dataset_version()
    finally:
        await http.aclose()
    assert ref == DatasetRef(version_token=VERSION, data_token=None)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "OK"},  # available 없음
        {"status": "OK", "available": True},  # current 없음
        {"status": "OK", "available": True, "current": {"version_token": "dv1-x"}},
        {
            "status": "OK",
            "available": True,
            "current": {"version_token": VERSION, "data_token": "dd1-" + "0" * 31},
        },
    ],
)
async def test_dataset_version_contract_violation_is_a_typed_error(
    payload: dict[str, Any],
) -> None:
    """현재 토큰은 스탬프의 비교 키다 — 틀린 값을 받아들이면 모든 행이 영구 stale이다."""
    client, http = _client(_Transport([payload]))
    try:
        with pytest.raises(GeoRequestError, match="응답 계약 오류"):
            await client.dataset_version()
    finally:
        await http.aclose()


# -- GeoCallStats.empty / observed_data_tokens ----------------------------------------


async def test_empty_answers_are_counted_apart_from_failures() -> None:
    """reverse 6건: 정상 3·bjd 없음 2·전송 실패 1 → calls 6, failures 1, empty 2."""
    dataset = {"version_token": VERSION, "data_token": DATA}
    responses: list[dict[str, Any] | Exception] = [
        _reverse_payload(bjd=True, dataset=dataset),
        _reverse_payload(bjd=False, dataset=dataset),
        _reverse_payload(bjd=True, dataset={"version_token": VERSION, "data_token": OTHER_DATA}),
        httpx.ConnectError("refused"),
        _reverse_payload(bjd=False),
        _reverse_payload(bjd=True),
    ]
    expected_empty = sum(
        1 for item in responses if isinstance(item, dict) and not item["candidates"]
    )
    stats = GeoCallStats()
    client, http = _client(_Transport(responses), stats)
    geocoder = kor_travel_geo_reverse_geocoder(client)
    try:
        for index in range(len(responses)):
            coord = Coordinate(lon=127.0 + index * 0.001, lat=37.0)
            with suppress(GeoRequestError):
                await geocoder(coord)
    finally:
        await http.aclose()

    assert stats.calls["reverse"] == 6
    assert stats.failures["reverse"] == 1
    assert stats.empty["reverse"] == expected_empty == 2
    assert stats.observed_data_tokens == {DATA, OTHER_DATA}
    metadata = stats.as_metadata()
    assert metadata["geo_empty_reverse"] == 2
    # 행 단위 최종 빈 답(region fallback 없음 — endpoint 빈 답과 같다, T-GR-03 run 가드의 분자).
    assert metadata["geo_empty_reverse_result"] == 2


# -- DTO ---------------------------------------------------------------------------------


def test_dataset_ref_rejects_malformed_tokens() -> None:
    with pytest.raises(ValidationError):
        DatasetRef(version_token="dv1-" + "a" * 31)
    with pytest.raises(ValidationError):
        DatasetRef(version_token=VERSION, data_token="dv1-" + "b" * 32)


# -- decide_outcome: address-geocoding.md §2 판정 표 전 행 ------------------------------

_BOTH = GeoApplied(reverse=True, geocode=True)
_REVERSE_ONLY = GeoApplied(reverse=True, geocode=False)
_NONE = GeoApplied(reverse=False, geocode=False)


@pytest.mark.parametrize(
    ("label", "kwargs", "expected"),
    [
        # ① price/notice — 스탬프 없음(좌표가 있어도)
        ("1-no-geo", {"geo_applied": _NONE, "has_coord": True}, None),
        # ①이 ②보다 먼저 — geo를 넘기지 않은 run이면 행 evidence가 있어도 스탬프 없음
        (
            "1-before-2",
            {
                "geo_applied": _NONE,
                "has_coord": True,
                "evidence": GeoAttemptEvidence(reverse_attempted=True),
            },
            None,
        ),
        # ② MOIS evidence — reverse 시도 → called(좌표 없음 신호와 무관)
        (
            "2-mois-reverse",
            {
                "geo_applied": _REVERSE_ONLY,
                "has_coord": True,
                "provider_code_present": False,
                "evidence": GeoAttemptEvidence(reverse_attempted=True),
            },
            "called",
        ),
        # ② MOIS evidence — geocode로 코드를 받음 → geocoded
        (
            "2-mois-geocoded",
            {
                "geo_applied": _BOTH,
                "has_coord": False,
                "evidence": GeoAttemptEvidence(
                    reverse_attempted=False, geocode_obtained_code=True
                ),
            },
            "geocoded",
        ),
        # ② MOIS evidence — geocode 시도했지만 코드 없음 → not_called
        (
            "2-mois-geocode-failed",
            {
                "geo_applied": _BOTH,
                "has_coord": False,
                "legal_dong_code_present": True,
                "evidence": GeoAttemptEvidence(reverse_attempted=False),
            },
            "not_called",
        ),
        # ② MOIS evidence — payload bjd 행(아무것도 시도 안 함) → not_called
        #   (좌표·reverse 신호가 있어도)
        (
            "2-mois-payload-bjd",
            {
                "geo_applied": _REVERSE_ONLY,
                "has_coord": True,
                "provider_code_present": True,
                "evidence": GeoAttemptEvidence(reverse_attempted=False),
            },
            "not_called",
        ),
        # ③ reverse + 좌표 → called(payload 코드가 있어도)
        (
            "3-called-with-provider-code",
            {"geo_applied": _REVERSE_ONLY, "has_coord": True, "provider_code_present": True},
            "called",
        ),
        # ③ — 좌표가 있으면 reverse가 비어 geocode가 코드를 채운 행도 called(③과 ④는 좌표
        #   유무로 서로소라 둘 사이 순서는 의미가 없다; 규칙의 이름이 이 행을 정한다)
        (
            "3-coord-row-even-if-geocode-filled",
            {"geo_applied": _BOTH, "has_coord": True, "legal_dong_code_present": True},
            "called",
        ),
        # ④ geocode + 좌표 없음 + 코드 생김 + provider 코드 없음 → geocoded
        (
            "4-geocoded",
            {"geo_applied": _BOTH, "has_coord": False, "legal_dong_code_present": True},
            "geocoded",
        ),
        # ⑤ 좌표 없는 payload 코드 행 → not_called
        (
            "5-provider-code-no-coord",
            {
                "geo_applied": _BOTH,
                "has_coord": False,
                "legal_dong_code_present": True,
                "provider_code_present": True,
            },
            "not_called",
        ),
        # ⑤ 좌표·코드 둘 다 없음 → not_called
        ("5-nothing", {"geo_applied": _BOTH, "has_coord": False}, "not_called"),
        # ④는 geocode를 넘긴 run에서만 — reverse만 넘긴 run이면 좌표 없이 코드가 있어도 not_called
        (
            "4-requires-geocode-run",
            {"geo_applied": _REVERSE_ONLY, "has_coord": False, "legal_dong_code_present": True},
            "not_called",
        ),
        # ⑤ reverse만 넘긴 run의 좌표 없는 행 → not_called
        (
            "5-reverse-run-no-coord",
            {"geo_applied": _REVERSE_ONLY, "has_coord": False},
            "not_called",
        ),
    ],
)
def test_decide_outcome_table(label: str, kwargs: dict[str, Any], expected: str | None) -> None:
    arguments: dict[str, Any] = {
        "has_coord": False,
        "provider_code_present": False,
        "legal_dong_code_present": False,
        "evidence": None,
    }
    arguments.update(kwargs)
    geo_applied = arguments.pop("geo_applied")
    assert decide_outcome(geo_applied, **arguments) == expected, label


# -- GeoLoadContext.effective_token (T-GR-03) ---------------------------------------------


def test_effective_token_is_none_when_the_run_crossed_a_dataset_switch() -> None:
    from kortravelmap.dto.geo_dataset import GeoLoadContext

    current = DatasetRef(version_token=VERSION, data_token=DATA)
    applied = GeoApplied(reverse=True, geocode=False)
    observed: set[str] = set()
    assert (
        GeoLoadContext(
            geo_applied=applied, current_dataset=current, observed_data_tokens=observed
        ).effective_token()
        == DATA
    )
    observed.add(DATA)
    context = GeoLoadContext(
        geo_applied=applied, current_dataset=current, observed_data_tokens=observed
    )
    assert context.effective_token() == DATA
    observed.add(OTHER_DATA)  # 살아 있는 참조 — 적재 시점의 관측이 반영된다
    assert context.effective_token() is None
    assert GeoLoadContext(geo_applied=applied).effective_token() is None
    assert (
        GeoLoadContext(
            geo_applied=applied, current_dataset=DatasetRef(version_token=VERSION)
        ).effective_token()
        is None
    )


def test_effective_token_fails_closed_without_a_live_observation_set() -> None:
    """geo를 쓰는 run이 관측 집합을 넘기지 않으면 전환을 볼 수 없다 — 토큰을 쓰지 않는다."""
    from kortravelmap.dto.geo_dataset import GeoLoadContext

    current = DatasetRef(version_token=VERSION, data_token=DATA)
    for applied in (
        GeoApplied(reverse=True, geocode=False),
        GeoApplied(reverse=False, geocode=True),
    ):
        context = GeoLoadContext(geo_applied=applied, current_dataset=current)
        assert context.effective_token() is None
    # geo를 전혀 쓰지 않는 run은 관측할 것이 없다 — 없는 집합이 빈 집합과 같다.
    unused = GeoApplied(reverse=False, geocode=False)
    assert GeoLoadContext(geo_applied=unused, current_dataset=current).effective_token() == DATA


# -- 부분 퇴행 유지(#1328 M2) ------------------------------------------------------------------


def _stored(address: dict[str, object], *, overrides: dict[str, object] | None = None) -> object:
    from kortravelmap.infra.feature_geocode_load import StoredGeoColumns

    return StoredGeoColumns(
        values={"address": address, "legal_dong_code": address.get("bjd_code")},
        overrides=overrides or {},
    )


def test_partial_regression_keeps_only_geo_only_fields_under_the_same_legal_dong() -> None:
    from kortravelmap.dto import Address
    from kortravelmap.infra.feature_geocode_load import keep_partially_regressed_fields

    stored = _stored(
        {
            "bjd_code": "1156011000",
            "road_name_code": "115603118001",
            "admin_dong_code": "1156054000",
            "zipcode": "07237",
            "sido_name": "서울특별시",
        }
    )
    new = Address(bjd_code="1156011000", sido_name=None)
    kept, fields = keep_partially_regressed_fields(stored, new)  # type: ignore[arg-type]
    # 도로명 텍스트도 관리번호도 없는 답 — 도로명코드는 짝을 확인할 수 없어 지키지 않는다.
    assert fields == ("admin_dong_code", "zipcode")
    assert (kept.road_name_code, kept.admin_dong_code, kept.zipcode) == (
        None,
        "1156054000",
        "07237",
    )
    assert kept.sido_name is None  # 대상 밖 필드는 새 답 그대로

    moved, moved_fields = keep_partially_regressed_fields(  # type: ignore[arg-type]
        stored, Address(bjd_code="1156011100")
    )
    assert moved_fields == ()
    assert moved.road_name_code is None

    overridden = _stored(
        {"bjd_code": "1156011000", "road_name_code": "115603118001"},
        overrides={"core.road_name_code": "115603118001"},
    )
    _, override_fields = keep_partially_regressed_fields(  # type: ignore[arg-type]
        overridden, Address(bjd_code="1156011000")
    )
    assert override_fields == ()


def test_road_name_code_is_kept_only_with_its_road_text_or_its_management_number() -> None:
    """도로명코드는 도로명주소와 짝 — 서로 다른 릴리스의 코드를 섞지 않는다(#1328 3차 리뷰)."""
    from kortravelmap.dto import Address
    from kortravelmap.infra.feature_geocode_load import keep_partially_regressed_fields

    road = "서울특별시 영등포구 여의공원로 120"
    mgmt = "11560110100100008000000001"[:25]
    stored = _stored(
        {
            "bjd_code": "1156011000",
            "road": road,
            "road_name_code": "115603118001",
            "road_address_management_no": mgmt,
        }
    )

    # 같은 도로명 텍스트 — 코드만 지킨다.
    same_road, fields = keep_partially_regressed_fields(  # type: ignore[arg-type]
        stored, Address(bjd_code="1156011000", road=road, road_address_management_no=mgmt)
    )
    assert fields == ("road_name_code",)
    assert same_road.road_name_code == "115603118001"

    # 도로명 텍스트가 다르고 관리번호도 함께 사라졌다 — 둘을 짝으로 지킨다.
    pair, fields = keep_partially_regressed_fields(  # type: ignore[arg-type]
        stored, Address(bjd_code="1156011000", road="서울특별시 영등포구 다른로 1")
    )
    assert fields == ("road_address_management_no", "road_name_code")
    assert (pair.road_name_code, pair.road_address_management_no) == ("115603118001", mgmt)

    # 도로명 텍스트가 다르고 새 답이 자기 관리번호를 냈다 — 옛 코드를 섞지 않는다.
    mixed, fields = keep_partially_regressed_fields(  # type: ignore[arg-type]
        stored,
        Address(
            bjd_code="1156011000",
            road="서울특별시 영등포구 다른로 1",
            road_address_management_no="1156011010010000900000000",
        ),
    )
    assert fields == ()
    assert mixed.road_name_code is None
