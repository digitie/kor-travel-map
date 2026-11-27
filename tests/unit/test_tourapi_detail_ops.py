"""``test_tourapi_detail_ops`` — TourAPI 상세 op 점진 백필(ADR-126).

op마다 예산이 따로고, 우선 점수 → 낡음 → 관광타입 → contentid 순으로 받는다. 받은 op 묶음은
``raw_data``에 남고 방문 안내(``facility_info.visitor_info``)로 바뀐다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.providers.visitkorea_attractions import (
    TOURAPI_DETAIL_RAW_KEY,
    TourApiDetailOpsPlan,
    merge_tourapi_detail_ops,
    plan_tourapi_detail_ops,
    tourapi_attractions_to_bundles,
    tourapi_visitor_info,
)

pytestmark = pytest.mark.unit

KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 11, 27, 4, 0, tzinfo=KST)
_MODIFIED = datetime(2026, 3, 2, 10, 0, 1, tzinfo=KST)
_MODIFIED_ISO = _MODIFIED.isoformat()
_BUDGETS: dict[Any, int] = {"intro": 2, "images": 2, "pet": 2, "accessibility": 2}



@dataclass(frozen=True)
class _Item:
    content_id: str | None
    title: str | None = "부산타워"
    content_type_id: str | None = "12"
    addr1: str | None = "부산광역시 중구 용두산길 37-30"
    addr2: str | None = None
    zipcode: str | None = None
    tel: str | None = None
    first_image: str | None = None
    first_image2: str | None = None
    map_x: float | None = 129.0324096
    map_y: float | None = 35.1011207
    lcls_systm1: str | None = "VE"
    lcls_systm2: str | None = "VE01"
    lcls_systm3: str | None = "VE010200"
    l_dong_regn_cd: str | None = "26"
    l_dong_signgu_cd: str | None = "110"
    created_time: datetime | None = None
    modified_time: datetime | None = _MODIFIED
    copyright_division_code: str | None = "Type1"
    overview: str | None = None
    homepage: str | None = None


def _ops(**data: Any) -> dict[str, Any]:
    return {op: {"modified_time": _MODIFIED_ISO, "data": value} for op, value in data.items()}


def test_plan_orders_by_priority_then_staleness_then_content_type() -> None:
    items = [
        _Item("300", content_type_id="28"),
        _Item("200", content_type_id="14"),
        _Item("100", content_type_id="12"),
        _Item("400", content_type_id="12"),
        _Item("500", lcls_systm2="VE11", lcls_systm3="VE110100"),  # 교통시설은 적재하지 않는다
    ]
    stored = {
        # 400: intro는 최신, images는 낡았다(옛 수정 시각).
        "400": {
            TOURAPI_DETAIL_RAW_KEY: {
                "intro": {"modified_time": _MODIFIED_ISO, "data": {}},
                "images": {"modified_time": "2020-01-01T00:00:00+09:00", "data": []},
            }
        }
    }
    plan = plan_tourapi_detail_ops(items, stored, budgets=_BUDGETS, priority={"300": 15})
    assert [r.content_id for r in plan.fetch["intro"]] == ["300", "100"]
    assert plan.deferred["intro"] == 1  # 200(14)
    # images: 우선 300 → 낡은 400 → 없는 100(12) → 200(14)
    assert [r.content_id for r in plan.fetch["images"]] == ["300", "400"]
    assert plan.deferred["images"] == 2
    assert "500" not in {r.content_id for reqs in plan.fetch.values() for r in reqs}
    assert set(plan.stored) == {"400"}


def test_plan_with_zero_budget_fetches_nothing_and_keeps_stored() -> None:
    stored = {"100": {TOURAPI_DETAIL_RAW_KEY: _ops(intro={"usetime": "09:00~18:00"})}}
    plan = plan_tourapi_detail_ops(
        [_Item("100")], stored, budgets=dict.fromkeys(_BUDGETS, 0)
    )
    assert all(not requests for requests in plan.fetch.values())
    assert plan.stored["100"]["intro"]["data"] == {"usetime": "09:00~18:00"}


def test_plan_skips_intro_without_content_type() -> None:
    plan = plan_tourapi_detail_ops([_Item("100", content_type_id=None)], {}, budgets=_BUDGETS)
    assert plan.fetch["intro"] == ()
    assert [r.content_id for r in plan.fetch["images"]] == ["100"]


def test_merge_overlays_fetched_with_current_modified_time() -> None:
    plan = TourApiDetailOpsPlan(
        stored={"100": _ops(intro={"usetime": "old"})}, fetch={}, deferred={}
    )
    merged = merge_tourapi_detail_ops(
        plan,
        {"intro": {"100": {"usetime": "new"}}, "pet": {"200": {}}},
        {"100": "2026-11-01T00:00:00+09:00", "200": None},
    )
    assert merged["100"]["intro"] == {
        "modified_time": "2026-11-01T00:00:00+09:00",
        "data": {"usetime": "new"},
    }
    assert merged["200"] == {"pet": {"modified_time": None, "data": {}}}


def test_visitor_info_from_ops_keeps_source_text_and_licensed_images() -> None:
    ops = _ops(
        intro={
            "usetimeculture": "09:00~18:00<br>(입장마감 17:30)",
            "restdateculture": "매주 월요일",
            "parkingculture": "가능",
            "parkingfee": "무료",
            "usefee": "성인 3,000원",
            "chkpetculture": "불가",
        },
        images=[
            {
                "originimgurl": "http://tong.visitkorea.or.kr/a.jpg",
                "smallimageurl": "http://tong.visitkorea.or.kr/a_s.jpg",
                "imgname": "전경",
                "cpyrhtDivCd": "Type3",
            },
            {"originimgurl": "http://tong.visitkorea.or.kr/b.jpg", "cpyrhtDivCd": ""},
            {"originimgurl": "javascript:alert(1)", "cpyrhtDivCd": "Type1"},
        ],
        pet={"acmpyTypeCd": "일부구역 동반가능", "acmpyPsblCpam": "소형견"},
        accessibility={"wheelchair": "대여 가능(2대)", "stroller": "", "helpdog": "동반 가능"},
    )
    info = tourapi_visitor_info(ops)
    assert info is not None
    dumped = info.model_dump(mode="json", exclude_defaults=True)
    assert dumped["usage_hours"] == "09:00~18:00\n(입장마감 17:30)"
    assert dumped["rest_days"] == "매주 월요일"
    assert dumped["parking"] == "가능"
    assert dumped["parking_fee"] == "무료"
    assert dumped["fee_text"] == "성인 3,000원"
    assert dumped["pet_note"] == "불가"
    # 공공누리 유형을 모르는 이미지·http(s)가 아닌 URL은 담지 않는다.
    assert dumped["images"] == [
        {
            "url": "http://tong.visitkorea.or.kr/a.jpg",
            "thumbnail_url": "http://tong.visitkorea.or.kr/a_s.jpg",
            "caption": "전경",
            "license": {
                "attribution": "한국관광공사",
                "kogl_type": 3,
                "label": "공공누리 제3유형(출처표시·변경금지)",
                "derivatives_allowed": False,
                "commercial_allowed": True,
            },
        }
    ]
    assert dumped["pet_policy"] == {"companion_type": "일부구역 동반가능", "allowed_pets": "소형견"}
    assert [(n["group"], n["facility"]) for n in dumped["accessibility"]] == [
        ("physical", "wheelchair"),
        ("visual", "helpdog"),
    ]


def test_visitor_info_none_when_ops_are_all_empty() -> None:
    assert tourapi_visitor_info(_ops(intro={}, images=[], pet={})) is None
    assert tourapi_visitor_info(None) is None


def test_overview_and_primary_image_join_visitor_info_first() -> None:
    ops = _ops(
        images=[
            {"originimgurl": "http://tong.visitkorea.or.kr/p.jpg", "cpyrhtDivCd": "Type1"},
            {"originimgurl": "http://tong.visitkorea.or.kr/g.jpg", "cpyrhtDivCd": "Type1"},
        ]
    )
    info = tourapi_visitor_info(
        ops,
        overview="부산 원도심<br>전망대",
        primary_image="http://tong.visitkorea.or.kr/p.jpg",
        primary_thumbnail="http://tong.visitkorea.or.kr/p_s.jpg",
        license_code="Type3",
    )
    assert info is not None
    assert info.description == "부산 원도심\n전망대"
    # 대표 이미지가 먼저, 같은 URL은 한 번만(대표 이미지의 라이선스는 목록 유형).
    assert [(i.url, i.license.kogl_type) for i in info.images] == [
        ("http://tong.visitkorea.or.kr/p.jpg", 3),
        ("http://tong.visitkorea.or.kr/g.jpg", 1),
    ]
    assert info.images[0].caption is None


def test_primary_image_with_unknown_license_is_dropped() -> None:
    info = tourapi_visitor_info(
        None, primary_image="http://tong.visitkorea.or.kr/p.jpg", license_code=None
    )
    assert info is None


def test_plan_asks_member_ops_only_for_listed_content() -> None:
    items = [_Item("100"), _Item("200")]
    plan = plan_tourapi_detail_ops(
        items,
        {},
        budgets=_BUDGETS,
        members={"accessibility": frozenset({"200"}), "pet": frozenset()},
    )
    assert [r.content_id for r in plan.fetch["accessibility"]] == ["200"]
    assert plan.fetch["pet"] == ()
    assert [r.content_id for r in plan.fetch["intro"]] == ["100", "200"]


def test_attraction_bundle_carries_ops_in_raw_and_visitor_info() -> None:
    ops = _ops(intro={"usetime": "상시"}, images=[])
    with_details = asyncio.run(
        tourapi_attractions_to_bundles([_Item("100")], fetched_at=_FETCHED, details={"100": ops})
    )[0]
    plain = asyncio.run(tourapi_attractions_to_bundles([_Item("100")], fetched_at=_FETCHED))[0]
    assert with_details.source_record.raw_data[TOURAPI_DETAIL_RAW_KEY] == ops
    info = with_details.feature.detail.facility_info["visitor_info"]  # type: ignore[union-attr]
    assert info == {"source": "tourapi", "attribution": "한국관광공사", "usage_hours": "상시"}
    # 상세 없는 행은 raw_data·facility_info가 이 기능 전과 같다(payload hash 불변).
    assert TOURAPI_DETAIL_RAW_KEY not in plain.source_record.raw_data
    assert "visitor_info" not in plain.feature.detail.facility_info  # type: ignore[union-attr]
