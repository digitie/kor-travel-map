"""``test_h25b_verify_links`` — T-VN-H34 승인 링크 검증 도구의 판정 로직.

이 저장소는 ``scripts/``에 테스트가 없어 감사에서 지적받았고
(``tests/unit/test_curation_audit_scripts.py`` 619줄이 그래서 생겼다), 같은 실수를
반복하지 않으려고 판정 축을 단위로 고정한다.

특히 **개발 중 두 번 틀렸던 지점**을 회귀로 박는다.

1. 동명 feature가 여럿인 것을 *모순*으로 셌다 → 전수 222건 중 30건이 모순으로 잡히고
   그중 20건이 이 축 단독이었다. 동명 다수는 "링크가 틀렸다"가 아니라 **그 축으로
   확정할 수 없다**는 뜻이다.
2. 카테고리 기대를 ``01``(TOURISM)로만 잡았다 → ``장태산자연휴양림``처럼 숙박을 갖춘
   휴양림(``03030000``)이 오탐으로 잡혔다. 축을 "관광이어야 한다"에서 **"명백히 대상일 수
   없는 유형인가"** 로 뒤집었다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "h25b_verify_links.py"
_spec = importlib.util.spec_from_file_location("h25b_verify_links", _MODULE_PATH)
assert _spec is not None
assert _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["h25b_verify_links"] = _mod
_spec.loader.exec_module(_mod)

_judge = _mod._judge


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "collection_key": "korean-tourism-100:2025-2026",
        "external_item_id": "kt100-2025-2026-001",
        "place_name": "어떤 관광지",
        "feature_id": "f_x_p_y",
        "feature_name": "어떤 관광지",
        "region": "충북",
        "feature_category": "01020300",
        "feature_sido_code": "43",
        "feature_sigungu_code": "43150",
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_region_axis_compares_by_code_not_text() -> None:
    """``충북`` vs ``충청북도`` 문자열 비교로는 축이 통째로 깨진다 — 코드로 본다."""
    ok = _judge(_row(region="충북", feature_sido_code="43"), ("f_x_p_y",))
    assert ok["axes"]["region"] == "pass"

    bad = _judge(_row(region="충북", feature_sido_code="11"), ("f_x_p_y",))
    assert bad["axes"]["region"] == "fail"
    assert bad["verdict"] == "contradiction"


@pytest.mark.unit
def test_missing_region_is_not_a_contradiction() -> None:
    """region이 없으면 축을 못 쓰는 것이지 모순이 아니다."""
    result = _judge(_row(region=None), ("f_x_p_y",))
    assert result["axes"]["region"] == "n/a"
    assert result["verdict"] == "no_contradiction"


@pytest.mark.unit
@pytest.mark.parametrize(
    "category",
    [
        "06010000",  # TRANSPORT_PARKING — 관광지의 '주차장' feature를 잡은 경우
        "02020100",  # FOOD_CAFE_COFFEE
        "03050200",  # LODGING_PENSION_RURAL — 호수가 펜션일 수 없다
    ],
)
def test_implausible_category_is_a_contradiction(category: str) -> None:
    result = _judge(_row(feature_category=category), ("f_x_p_y",))
    assert result["axes"]["category"] == "fail"
    assert result["verdict"] == "contradiction"


@pytest.mark.unit
@pytest.mark.parametrize(
    "category",
    [
        "01020300",  # TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND
        "01030101",  # TOURISM_BOTANICAL_GARDEN_NATIONAL
        "03030000",  # LODGING_RECREATION_FOREST — 숙박을 갖춘 휴양림은 정당하다
    ],
)
def test_plausible_category_passes(category: str) -> None:
    """축을 ``01``만 허용으로 좁히면 휴양림이 오탐이 된다 — 그 회귀를 막는다."""
    result = _judge(_row(feature_category=category), ("f_x_p_y",))
    assert result["axes"]["category"] == "pass"
    assert result["verdict"] == "no_contradiction"


@pytest.mark.unit
def test_duplicate_names_never_produce_contradiction() -> None:
    """동명 다수는 **반증이 아니다** — 그 축으로 확정할 수 없다는 뜻이다.

    초안은 이걸 ``fail``로 두어 전수 222건 중 20건을 잘못 모순으로 보고했다.
    """
    result = _judge(
        _row(),
        ("f_x_p_y", "feature:2", "feature:3", "feature:4"),
    )
    assert result["axes"]["linked_exact_name_candidate"] == "n/a"
    assert result["verdict"] == "no_contradiction"
    assert any("확정할 수 없다" in reason for reason in result["reasons"])


@pytest.mark.unit
def test_no_axis_available_is_insufficient_not_confirmation() -> None:
    """모든 축이 n/a면 ``insufficient``다 — ``no_contradiction``으로 승격하지 않는다."""
    result = _judge(
        _row(
            region=None,
            feature_category="",
            feature_name=None,
            collection_key="legacy:whatever:1",
        ),
        (),
    )
    assert set(result["axes"].values()) == {"n/a"}
    assert result["verdict"] == "insufficient"


@pytest.mark.unit
def test_non_tourism_campaign_skips_category_axis() -> None:
    """카테고리 축은 관광 캠페인에만 적용한다 — concierge legacy에는 기대가 없다."""
    result = _judge(
        _row(collection_key="legacy:media-places:abc"),
        ("f_x_p_y",),
    )
    assert result["axes"]["category"] == "n/a"


@pytest.mark.unit
def test_linked_name_mismatch_is_explicit_contradiction() -> None:
    """DB 다른 곳의 유일 동명 후보를 linked feature의 긍정 근거로 쓰지 않는다."""

    result = _judge(
        _row(
            place_name="정답 장소",
            feature_name="완전히 다른 장소",
            feature_id="feature:wrong",
        ),
        ("feature:right",),
    )

    assert result["axes"]["linked_name"] == "fail"
    assert result["axes"]["linked_exact_name_candidate"] == "n/a"
    assert result["verdict"] == "contradiction"
    assert result["evidence"]["exact_name_candidate_feature_ids"] == [
        "feature:right"
    ]
    assert result["evidence"]["linked_feature_is_exact_name_candidate"] is False


@pytest.mark.unit
def test_linked_name_uses_same_nfkc_whitespace_policy_on_both_sides() -> None:
    result = _judge(
        _row(
            place_name="  Ａ 관광지  ",
            feature_name="A   관광지",
        ),
        ("f_x_p_y",),
    )

    assert result["axes"]["linked_name"] == "pass"
    assert result["evidence"]["normalized_place_name"] == "a 관광지"
    assert result["evidence"]["normalized_linked_feature_name"] == "a 관광지"
