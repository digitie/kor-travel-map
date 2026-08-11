"""T-VN-H28B — 행정코드 교차검증 규칙.

실측 근거: ``docs/reports/concierge-address-mismatch-evidence-2026-07-29.md``.
이전 이름-substring 규칙은 1,477 후보 중 380건을 영구 drop했다.

**정정** — 초안은 여기에 *"380건 전부 오탐이었다 (payload 행정코드 == geo 행정코드,
진짜 불일치 0건)"* 라고 적었으나 **그 근거는 무효다**. concierge payload의
``legal_dong_code``는 **같은 좌표로 같은 geo ``/v2/reverse``를 호출해 만든 캐시**이므로
둘의 일치는 항상 성립한다 — tautology이고, 좌표가 틀렸을 때도 일치한다.
철회된 축을 이 테스트의 정당화로 쓰지 않는다.

실제로 유효한 근거는 리포트가 독립 축(provider ``Address.sigungu_name`` 텍스트 대조 +
정지오코딩)으로 재수립한 것이다: 기존 규칙으로 **좌표 오류가 성립한 건은 0건**이며,
drop 380건의 분포는 짧은주소 365 / 접미사차 9 / 타시군구 5 / 기타 1이다.
리포트 자신이 "일반적 의미의 좌표 오류 0건은 아니다"라고 한정한다.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from kortravelmap.core.ids import make_source_record_key
from kortravelmap.dto import (
    Address,
    AdminEvidence,
    Coordinate,
    Feature,
    FeatureBundle,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.geocoding import KorTravelGeoRestClient, kor_travel_geo_reverse_geocoder
from kortravelmap.providers.kor_travel_concierge import (
    kor_travel_concierge_items_to_bundles,
)

from kortravelmap.dagster.validation import (
    DROPPABLE_ISSUE_CODES,
    _provider_address,
    validate_feature_bundle_address,
    validate_feature_bundles_address,
)

_FETCHED_AT = "2026-07-29T00:00:00+00:00"

_DEFAULT_COORD = Coordinate(lon=Decimal("129.223"), lat=Decimal("35.1886"))


def _bundle(
    *,
    bjd_code: str | None = "2671025300",
    sigungu_code: str | None = "26710",
    sido_code: str | None = "26",
    sigungu_name: str | None = "기장군",
    road: str | None = "부산 기장 해동용궁사",
    legal: str | None = None,
    admin: str | None = None,
    coord: Coordinate | None = _DEFAULT_COORD,
    admin_evidence: AdminEvidence | None = None,
    raw_data: dict[str, object] | None = None,
) -> FeatureBundle:
    address = Address(
        road=road,
        legal=legal,
        admin=admin,
        bjd_code=bjd_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        sigungu_name=sigungu_name,
        sido_name="부산광역시",
    )
    feature = Feature(
        feature_id="f_place_test_0001",
        kind="place",
        name="해동용궁사",
        category="02020101",
        coord=coord,
        address=address,
        marker_icon="marker",
        marker_color="P-01",
        detail=PlaceDetail(feature_id="f_place_test_0001", place_kind="attraction"),
    )
    record = SourceRecord(
        source_record_key=make_source_record_key(
            provider="kor-travel-concierge",
            dataset_key="kor_travel_concierge_youtube_place_candidates",
            source_entity_type="candidate",
            source_entity_id="cand-1",
            raw_payload_hash="a" * 64,
        ),
        provider="kor-travel-concierge",
        dataset_key="kor_travel_concierge_youtube_place_candidates",
        source_entity_type="candidate",
        source_entity_id="cand-1",
        raw_payload_hash="a" * 64,
        raw_data={"address": road} if raw_data is None else raw_data,
        fetched_at=datetime.fromisoformat(_FETCHED_AT),
    )
    link = SourceLink(
        feature_id=feature.feature_id,
        source_record_key=record.source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
    )
    return FeatureBundle(
        feature=feature,
        source_record=record,
        source_link=link,
        admin_evidence=admin_evidence,
    )


# ── 오탐 회귀: 실측 380건의 지배적 형태 ──────────────────────────────────────


def test_short_provider_address_no_longer_produces_any_issue() -> None:
    """`부산 기장 해동용궁사` — 실측 380건 중 365건이 이 형태였다.

    좌표는 정확하고(reverse 40m) payload 코드도 geo와 같다. 이전 규칙은 geo 시군구명
    '기장군'이 문자열에 없다는 이유로 error → 영구 drop했다.
    """
    bundle = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="2671025300",
            reverse_attempted=True,
            claim_code="2671025300",
            claim_kind="bjd",
        )
    )
    result = validate_feature_bundle_address(bundle)
    assert result.issues == ()
    assert not result.has_errors


def test_address_naming_a_different_sigungu_warns_but_never_drops() -> None:
    """`서울 서대문구 통일로 251`인데 좌표 reverse는 종로구 — 실측 380건 중 유일한 잔여 후보.

    텍스트를 정지오코딩하면 서대문구이고 후보 좌표에서 **143m**다(종로구 경계). 좌표는
    맞았다. 그래도 이 축은 검토할 가치가 있는 신호이므로 **warning으로 남기고**, 절대
    영구 손실로 만들지 않는다.

    reverse 후보집합에 서대문구가 함께 오면 경계로 흡수돼 조용해진다(아래 별도 테스트).
    """
    bundle = _bundle(
        bjd_code="1111017700",
        sigungu_code="11110",
        sido_code="11",
        sigungu_name="종로구",
        road="서울 서대문구 통일로 251",
    )
    issues = validate_feature_bundle_address(bundle).issues
    codes = [i.code for i in issues]
    assert "provider_address_region_disagreement" in codes
    assert all(i.severity == "warning" for i in issues)
    assert all(i.code not in DROPPABLE_ISSUE_CODES for i in issues)


def test_boundary_candidate_set_absorbs_the_disagreement() -> None:
    """reverse 후보에 인접 시군구가 함께 오면 경계 케이스로 보고 판정하지 않는다."""
    bundle = _bundle(
        bjd_code="1111017700",
        sigungu_code="11110",
        sido_code="11",
        sigungu_name="종로구",
        road="서울 서대문구 통일로 251",
        admin_evidence=AdminEvidence(
            obs_code="1111017700",
            obs_sigungu_names=("종로구", "서대문구"),
            reverse_attempted=True,
        ),
    )
    assert validate_feature_bundle_address(bundle).issues == ()


async def test_reverse_http_candidates_reach_concierge_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/reverse"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "candidates": [
                    {
                        "confidence": 1.0,
                        "match_kind": "road",
                        "distance_m": 20,
                        "address": {
                            "full": "서울특별시 종로구 통일로 251",
                            "road_address": "서울특별시 종로구 통일로 251",
                            "legal_dong_code": "1111017700",
                        },
                        "region": {
                            "sig_cd": "11110",
                            "bjd_cd": "1111017700",
                            "sido": "서울특별시",
                            "sigungu": "종로구",
                        },
                    },
                    {
                        "confidence": 0.9,
                        "match_kind": "parcel",
                        "distance_m": 143,
                        "address": {
                            "full": "서울특별시 서대문구 현저동",
                            "parcel_address": "서울특별시 서대문구 현저동",
                            "legal_dong_code": "1141010900",
                        },
                        "region": {
                            "sig_cd": "11410",
                            "bjd_cd": "1141010900",
                            "sido": "서울특별시",
                            "sigungu": "서대문구",
                        },
                    },
                ],
            },
        )

    item = {
        "export_id": "ytpc-boundary",
        "candidate_id": "boundary",
        "operation": "upsert",
        "place": {
            "name": "경계 후보",
            "longitude": 126.956,
            "latitude": 37.574,
            "address": {"road_address": "서울 서대문구 통일로 251"},
        },
        "source_record": {"source_entity_id": "boundary"},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://geo.test",
    ) as http:
        geocoder = kor_travel_geo_reverse_geocoder(
            KorTravelGeoRestClient(http, require_auth=False)
        )
        [bundle] = await kor_travel_concierge_items_to_bundles(
            [item],
            fetched_at=datetime.fromisoformat(_FETCHED_AT),
            reverse_geocoder=geocoder,
        )

    assert bundle.admin_evidence is not None
    assert bundle.admin_evidence.obs_sigungu_names == ("종로구", "서대문구")
    assert "provider_address_region_disagreement" not in (
        validate_feature_bundle_address(bundle).issue_codes
    )


def test_business_name_substring_cannot_hide_real_sigungu_disagreement() -> None:
    bundle = _bundle(
        bjd_code="1111017700",
        sigungu_code="11110",
        sido_code="11",
        sigungu_name="종로구",
        road="서울 강남구 종로김밥",
    )
    codes = [issue.code for issue in validate_feature_bundle_address(bundle).issues]
    assert "provider_address_region_disagreement" in codes


def test_non_admin_word_ending_in_si_is_not_a_region_claim() -> None:
    bundle = _bundle(
        bjd_code="1168010100",
        sigungu_code="11680",
        sido_code="11",
        sigungu_name="강남구",
        road="서울 종로 현대미술전시",
    )
    result = validate_feature_bundle_address(bundle)
    assert "provider_address_region_disagreement" not in result.issue_codes
    summary = validate_feature_bundles_address([bundle])
    assert summary.name_state_counts == {"no_token": 1}


def test_name_axis_is_armed_without_admin_evidence() -> None:
    """``AdminEvidence``를 채우지 않는 provider도 독립 축 검증을 받는다.

    1차 설계는 이 축을 지워 15개 provider 중 14개가 주소 교차검증을 완전히 잃었다.
    이 테스트가 그 회귀를 막는다.
    """
    bundle = _bundle(sigungu_name="종로구", road="부산 해운대구 어딘가", admin_evidence=None)
    codes = [i.code for i in validate_feature_bundle_address(bundle).issues]
    assert "provider_address_region_disagreement" in codes


# ── 탐지력: 진짜 불일치는 여전히 잡는다 ──────────────────────────────────────


@pytest.mark.parametrize(
    ("obs", "claim", "expected_level"),
    [
        ("1111017700", "2671025300", "sido"),  # 서울 vs 부산
        ("2671025300", "2650010100", "sigungu"),  # 기장군 vs 수영구
        ("2671025300", "2671010200", "emd"),  # 같은 군, 다른 읍면동
    ],
)
def test_stale_code_is_detected_at_the_right_level(
    obs: str, claim: str, expected_level: str
) -> None:
    bundle = _bundle(
        admin_evidence=AdminEvidence(
            obs_code=obs,
            reverse_attempted=True,
            claim_code=claim,
            claim_kind="bjd",
        )
    )
    issues = validate_feature_bundle_address(bundle).issues
    codes = [i.code for i in issues if i.code.startswith("admin_code_stale")]
    assert codes == [f"admin_code_stale_{expected_level}"]


def test_stale_code_is_never_an_error() -> None:
    """행정코드 불일치는 관측 대상이지 영구 손실 사유가 아니다."""
    bundle = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="1111017700",
            reverse_attempted=True,
            claim_code="2671025300",
            claim_kind="bjd",
        )
    )
    result = validate_feature_bundle_address(bundle)
    conflicts = [i for i in result.issues if i.code.startswith("admin_code_stale")]
    assert conflicts
    assert all(i.severity == "warning" for i in conflicts)
    assert all(i.code not in DROPPABLE_ISSUE_CODES for i in conflicts)


# ── 정밀도 규칙 ──────────────────────────────────────────────────────────────


def test_ri_digits_are_not_compared() -> None:
    """리(8:10)는 ``_bjd_code_from_emd_code``가 합성할 수 있어 판정 근거가 아니다."""
    bundle = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="2671025300",
            reverse_attempted=True,
            claim_code="2671025399",
            claim_kind="bjd",
        )
    )
    assert validate_feature_bundle_address(bundle).issues == ()


def test_sigungu_claim_compares_only_five_digits() -> None:
    """5자리 주장을 10자리로 부풀려 비교하지 않는다."""
    same = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="2671025300",
            reverse_attempted=True,
            claim_code="26710",
            claim_kind="sigungu",
        )
    )
    assert validate_feature_bundle_address(same).issues == ()

    differ = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="2671025300",
            reverse_attempted=True,
            claim_code="26500",
            claim_kind="sigungu",
        )
    )
    codes = [i.code for i in validate_feature_bundle_address(differ).issues]
    assert "admin_code_stale_sigungu" in codes


# ── 침묵을 통과로 착각하지 않는다 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        AdminEvidence(),
        AdminEvidence(obs_code="2671025300", reverse_attempted=True),
        AdminEvidence(claim_code="2671025300", claim_kind="bjd"),
    ],
)
def test_missing_axis_yields_no_verdict(evidence: AdminEvidence | None) -> None:
    """축이 하나라도 없으면 판정하지 않는다 — 통과가 아니라 증거 없음이다."""
    bundle = _bundle(admin_evidence=evidence)
    issues = validate_feature_bundle_address(bundle).issues
    assert [i for i in issues if i.code.startswith("admin_code_stale")] == []


def test_summary_reports_evidence_coverage() -> None:
    """커버리지를 집계하지 않으면 '판정 못 함'과 '통과'가 구분되지 않는다."""
    summary = validate_feature_bundles_address(
        [
            _bundle(
                admin_evidence=AdminEvidence(
                    obs_code="2671025300",
                    reverse_attempted=True,
                    claim_code="2671025300",
                    claim_kind="bjd",
                )
            ),
            _bundle(
                admin_evidence=AdminEvidence(
                    obs_code="2671025300", reverse_attempted=True
                )
            ),
            _bundle(admin_evidence=None),
        ]
    )
    assert summary.evidence_grade_counts == {"dual": 1, "obs_only": 1, "unarmed": 1}
    assert summary.as_metadata()["address_validation_evidence_grades"] == {
        "dual": 1,
        "obs_only": 1,
        "unarmed": 1,
    }
    assert sum(summary.name_state_counts.values()) == 3
    assert summary.as_metadata()["address_validation_name_states"] == (
        summary.name_state_counts
    )


def test_reverse_not_attempted_is_warning_not_failure() -> None:
    bundle = _bundle(
        bjd_code=None,
        sigungu_code=None,
        sido_code=None,
        sigungu_name=None,
        road="서울 종로 현대미술전시",
        admin_evidence=AdminEvidence(reverse_attempted=False),
    )
    result = validate_feature_bundle_address(bundle)
    assert [(issue.code, issue.severity) for issue in result.issues] == [
        ("reverse_geocode_not_attempted", "warning")
    ]


def test_observation_requires_reverse_attempted() -> None:
    with pytest.raises(ValueError, match="reverse_attempted=True"):
        AdminEvidence(obs_code="2671025300")


def test_reverse_attempted_without_observation_or_claim_is_error() -> None:
    bundle = _bundle(
        bjd_code=None,
        sigungu_code=None,
        sido_code=None,
        sigungu_name=None,
        road=None,
        admin_evidence=AdminEvidence(reverse_attempted=True),
    )
    result = validate_feature_bundle_address(bundle)
    assert ("reverse_geocode_failed", "error") in [
        (issue.code, issue.severity) for issue in result.issues
    ]


def test_retired_string_codes_are_no_longer_emitted() -> None:
    """이름 축 code는 발행 중단됐다 (탐지력 0이 실측으로 확인됨)."""
    summary = validate_feature_bundles_address(
        [
            _bundle(
                road="완전히 다른 문자열",
                admin_evidence=AdminEvidence(
                    obs_code="2671025300",
                    reverse_attempted=True,
                    claim_code="2671025300",
                    claim_kind="bjd",
                ),
            )
        ]
    )
    emitted = {issue.code for issue in summary.issues}
    assert "provider_address_mismatch" not in emitted
    assert "provider_address_partial_match" not in emitted


# ── 주소 주장의 유무 판정 — `None`이 문자열로 새면 축 전체가 죽는다 ──────────
#
# 이전 구현의 `_raw_payload_address`는 세 고속도로 단서를 `if str(part).strip()`으로
# 걸렀다. `str(None) == "None"`은 truthy라 **주소 키 조회가 빈손인 payload가 항상
# `'None ...'` 형태의 문자열을 주장으로 반환**했다. 당시 열거하던 원 철자 주소 키를
# 가진 dataset(standard_data `rdnmadr`, krforest `address`, …)은 그 앞에서 걸러
# 멀쩡했고, 철자가 다르거나(mois `road_address`) 키가 없는 dataset(knps, mcst,
# visitkorea, khoa, krairport)만 다음 피해를 입었다:
#   - `Address.road`/`legal` fallback이 영원히 발동하지 않았고(아래 fallback 테스트),
#   - 독립 이름축은 한글 토큰 없는 문자열만 보게 되어, reverse 관측이 있으면
#     `no_token`, 없으면 `no_observation`으로 집계됐으며,
#   - `no_claim` 집계는 도달 불가능했고,
#   - `missing_address`(droppable error)도 도달 불가능했다.
# 아래 회귀는 전부 그 구현에서 실패한다.


def test_payload_without_address_keys_makes_no_claim() -> None:
    """provider 원 필드명만 실은 payload는 **주소 주장이 없다**(`no_claim`).

    KNPS는 ``raw_data = dict(record.raw)``로 provider 원 필드명을 그대로 싣는다
    (``providers/knps.py``). 알려진 주소 키가 하나도 없으면 주장은 없는 것이지,
    빈 문자열을 조립해 있다고 말할 일이 아니다.
    """
    bundle = _bundle(
        road=None,
        raw_data={"name": "해동용궁사", "roadAddr": "부산 기장군 기장읍"},
    )
    summary = validate_feature_bundles_address([bundle])
    assert _provider_address(bundle) is None
    assert summary.name_state_counts == {"no_claim": 1}
    assert summary.issues == ()


def test_reverse_filled_address_becomes_the_claim_when_payload_has_none() -> None:
    """payload에 주소 키가 없으면 ``Address.road``로 **fallback이 실제로 발동**한다.

    이전 구현에서는 `'None None None'`이 먼저 반환돼 이 경로가 죽어 있었고, reverse가
    채운 도로명/법정동 주소가 통째로 버려졌다.
    """
    bundle = _bundle(
        bjd_code="1111017700",
        sigungu_code="11110",
        sido_code="11",
        sigungu_name="종로구",
        road="서울특별시 서대문구 통일로 251",
        raw_data={"name": "무명", "contentid": "1234"},
    )
    issues = validate_feature_bundle_address(bundle).issues
    assert [i.code for i in issues] == ["provider_address_region_disagreement"]
    assert issues[0].provider_address == "서울특별시 서대문구 통일로 251"


def test_legal_address_is_used_when_road_is_blank() -> None:
    """``road``가 공백뿐이면 ``legal``까지 내려간다 — 공백은 주장이 아니다."""
    bundle = _bundle(
        bjd_code="1111017700",
        sigungu_code="11110",
        sido_code="11",
        sigungu_name="종로구",
        road="   ",
        legal="서울특별시 서대문구 현저동 101",
        raw_data={"name": "무명"},
    )
    assert _provider_address(bundle) == "서울특별시 서대문구 현저동 101"


@pytest.mark.parametrize(
    ("road", "legal", "admin", "expected"),
    [
        (
            "서울특별시 종로구 통일로 251",
            "서울특별시 종로구 신문로2가 1",
            "서울특별시 종로구",
            "서울특별시 종로구 통일로 251",
        ),
        (
            None,
            "서울특별시 종로구 신문로2가 1",
            "서울특별시 종로구",
            "서울특별시 종로구 신문로2가 1",
        ),
        (None, None, "서울특별시 종로구", "서울특별시 종로구"),
    ],
)
def test_address_fallback_keeps_road_legal_admin_precedence(
    road: str | None,
    legal: str | None,
    admin: str | None,
    expected: str,
) -> None:
    """``Address`` fallback은 ``road`` → ``legal`` → ``admin`` 순이다.

    ``_provider_address``의 docstring이 계약으로 진술하는 순서이고
    (``Address.display()``와 같은 순서), 셋 다 채워진 상태에서만 갈린다. 순서가
    뒤집히면 도로명 주소가 있는 row도 시군구까지만 있는 ``admin`` 문자열을 주장으로
    삼아, 행정 토큰 대조축의 판정 대상이 통째로 바뀐다.

    기존 회귀는 세 단계를 **하나씩만** 세웠다(``road``만/``legal``만/``admin``만).
    그래서 두 값이 동시에 있을 때의 우선순위는 어느 테스트도 보지 않았다.
    """
    bundle = _bundle(
        road=road,
        legal=legal,
        admin=admin,
        raw_data={"name": "무명"},
    )
    assert _provider_address(bundle) == expected


def test_standard_data_payload_prefers_rdnmadr_over_lnmadr() -> None:
    """``rdnmadr``(도로명)가 ``lnmadr``(지번)보다 앞선다.

    두 키는 ``providers/standard_data.py``가 raw_data에 그대로 싣는 실측 컬럼명이다
    (``_raw_data`` — 축제/관광지/박물관 등). ``_RAW_ADDRESS_KEYS`` docstring이
    "도로명이 지번보다 앞선다"고 진술하는 성질이며, 조회는 dict 순서가 아니라
    **키 튜플 순서**로 도므로 payload에서 지번이 먼저 와도 결과가 같아야 한다.
    """
    bundle = _bundle(
        road=None,
        raw_data={
            "lnmadr": "서울특별시 영등포구 여의도동 8",
            "rdnmadr": "서울특별시 영등포구 여의공원로 120",
        },
    )
    assert _provider_address(bundle) == "서울특별시 영등포구 여의공원로 120"


def test_folded_view_keeps_the_first_spelling_when_two_keys_fold_alike() -> None:
    """같은 정규화 키로 접히는 철자가 둘이면 **먼저 나온 키가 이긴다**.

    ``_normalized_view`` docstring이 진술하는 성질이다. 중복 방지가 빠지면 뒤에 나온
    철자가 앞선 값을 덮어써, 정규화 패스가 고르는 주소가 payload의 키 나열 순서에
    따라 뒤집힌다. 두 철자 모두 ``_RAW_ADDRESS_KEYS``의 원 철자와는 다르므로
    (``road_address`` ≠ ``Road_Address``/``roadAddress``) 정확 일치 패스는 빈손이고
    정규화 패스만 판정한다.
    """
    bundle = _bundle(
        road=None,
        raw_data={
            "Road_Address": "서울특별시 종로구 통일로 251",
            "roadAddress": "부산광역시 기장군 기장읍 용궁길 86",
        },
    )
    assert _provider_address(bundle) == "서울특별시 종로구 통일로 251"


@pytest.mark.parametrize(
    ("raw_data", "expected"),
    [
        (
            {
                "roadNM": "서해안고속도로",
                "accPointNM": "서산나들목",
                "startEndTypeCode": "부산방향",
            },
            "서해안고속도로 서산나들목 부산방향",
        ),
        ({"routeName": "경부고속도로", "pointName": "안성휴게소"}, "경부고속도로 안성휴게소"),
        ({"roadNM": "서해안고속도로"}, "서해안고속도로"),
        ({"direction": "부산방향"}, "부산방향"),
        ({"roadNM": "   ", "accPointNM": ""}, None),
        ({"name": "무명", "contentid": "1234"}, None),
    ],
)
def test_traffic_clue_joins_only_the_parts_that_exist(
    raw_data: dict[str, object], expected: str | None
) -> None:
    """EX 돌발 단서는 **있는 조각만** 잇는다. 없는 조각이 ``'None'``이 되지 않는다."""
    bundle = _bundle(road=None, raw_data=raw_data)
    assert _provider_address(bundle) == expected


@pytest.mark.parametrize(
    ("raw_data", "expected"),
    [
        # krex traffic notices — 좌표 없는 row가 실측 63/99. 원 payload 철자는
        # dataset마다 다르다(`python-krex-api` `_get`가 다중 철자를 흡수한다).
        ({"routeNo": "0010", "pointName": "양재"}, "0010 양재"),
        ({"route_no": "0010", "point_name": "양재"}, "0010 양재"),
        # mcst kcisa 방언은 대문자 `ADDRESS`로 온다.
        ({"ADDRESS": "서울특별시 종로구 통일로 251"}, "서울특별시 종로구 통일로 251"),
        ({"Address_Road": "서울특별시 종로구 통일로 251"}, "서울특별시 종로구 통일로 251"),
    ],
)
def test_clue_lookup_survives_provider_key_spelling(
    raw_data: dict[str, object], expected: str
) -> None:
    """철자 하나를 놓치면 좌표 없는 row가 통째로 ``missing_address``로 drop된다.

    이전 구현은 원 철자 정확 일치만 봤고, 그 사각은 ``'None None None'``이 항상
    truthy라서 드러나지 않았다.
    """
    bundle = _bundle(road=None, raw_data=raw_data)
    assert _provider_address(bundle) == expected


@pytest.mark.parametrize(
    ("raw_data", "expected"),
    [
        # 진짜 도로명 주소가 정규화 철자로만 오고, 교통 키는 원 철자로 온다.
        (
            {"roadAddress": "서울특별시 종로구 통일로 251", "direction": "부산방향"},
            "서울특별시 종로구 통일로 251",
        ),
        # 지번 주소도 마찬가지 — 주소는 전부 교통 단서보다 앞이다.
        (
            {"Lot_Address": "서울특별시 종로구 신문로2가 1", "startEndTypeCode": "부산방향"},
            "서울특별시 종로구 신문로2가 1",
        ),
        (
            {"ADDRESS": "강원특별자치도 춘천시 1", "roadNM": "중앙고속도로"},
            "강원특별자치도 춘천시 1",
        ),
    ],
)
def test_address_beats_traffic_clue_across_spelling_passes(
    raw_data: dict[str, object], expected: str
) -> None:
    """주소는 철자가 어떻든 교통 단서를 이긴다 — 교통 단서는 주소가 아니다.

    이전 구현은 "(주소+교통) 원 철자" 한 패스를 먼저 돌았기 때문에, 원 철자 교통 키
    하나(``direction``)가 정규화 패스에서만 잡히는 진짜 도로명 주소를 가로챘다.
    그 상태에서 위 세 건은 각각 ``'부산방향'``/``'부산방향'``/``'중앙고속도로'``를
    주장으로 돌려준다.
    """
    bundle = _bundle(road=None, raw_data=raw_data)
    assert _provider_address(bundle) == expected


def test_rest_area_clue_keeps_route_and_direction_together() -> None:
    """krex 휴게소 payload는 typed 속성명(``route_name``)으로 온다 — 노선이 살아야 한다.

    ``providers/krex._rest_area_item_to_bundle``이 직접 조립하는 raw_data 모양이다
    (원 철자 ``roadNM``이 아니라 ``route_name``, 주소 컬럼은 없다). 이전 구현은 원
    철자 패스에서 ``direction`` 하나만 걸려 즉시 반환했고, ``route_name``을 잡을 수
    있는 정규화 패스는 영영 돌지 않아 노선명이 통째로 버려졌다.
    """
    bundle = _bundle(
        road=None,
        raw_data={
            "natural_key": "안성휴게소::경부고속도로::부산방향",
            "name": "안성휴게소",
            "route_name": "경부고속도로",
            "direction": "부산방향",
            "lon": "127.2",
            "lat": "37.0",
            "phone_number": None,
        },
    )
    assert _provider_address(bundle) == "경부고속도로 부산방향"


def test_traffic_clue_still_precedes_reverse_filled_address() -> None:
    """교통 단서는 payload 안에서만 마지막이고, ``Address`` 텍스트보다는 앞이다.

    krex 휴게소/휴게소기상/traffic notice는 셋 다 ``road=None``이고 ``admin``이
    reverse 산물이라, 여기서 ``Address``로 내려가면 이름축이 geo를 geo와 대조해
    **거짓 ``matched``**로 조용해진다. ``no_token``으로 판정 불가를 드러내는 쪽을
    택한 것이므로, 순서가 뒤집히면 이 테스트가 깨져야 한다.
    """
    bundle = _bundle(
        road=None,
        admin="부산광역시 기장군 기장읍",
        raw_data={"route_name": "동해고속도로", "direction": "속초방향"},
    )
    assert _provider_address(bundle) == "동해고속도로 속초방향"
    summary = validate_feature_bundles_address([bundle])
    assert summary.name_state_counts == {"no_token": 1}


@pytest.mark.parametrize(
    ("sigungu_name", "expected_state"),
    [("기장군", "no_token"), (None, "no_observation")],
)
def test_tokenless_claim_splits_by_whether_an_observation_exists(
    sigungu_name: str | None, expected_state: str
) -> None:
    """행정 토큰 없는 주장은 관측 유무로 ``no_token``/``no_observation``이 갈린다.

    판정 순서가 claim → observation → token이므로, 관측이 없으면 토큰을 보기 전에
    ``no_observation``으로 끝난다. ``'None None None'`` 시절 주소 없는 row가 "전부
    ``no_token``"이었다는 서술이 틀린 이유가 이것이다.
    """
    bundle = _bundle(
        sigungu_name=sigungu_name,
        road=None,
        raw_data={"address": "1층 안내데스크 옆"},
    )
    summary = validate_feature_bundles_address([bundle])
    assert summary.name_state_counts == {expected_state: 1}


def test_mois_payload_prefers_road_address_over_lot_address() -> None:
    """mois 실측 payload 키(``providers/mois._raw_data``) — 도로명이 지번보다 앞선다."""
    bundle = _bundle(
        road=None,
        raw_data={
            "lot_address": "서울특별시 종로구 신문로2가 1",
            "road_address": "서울특별시 종로구 통일로 251",
        },
    )
    assert _provider_address(bundle) == "서울특별시 종로구 통일로 251"


def test_admin_only_address_is_still_a_location_clue() -> None:
    """mcst는 좌표 없는 row의 provider 주소를 ``Address.admin``에만 남긴다.

    ``providers/mcst.py`` ``_resolve_address``는 ``road``/``legal``을 채우지 않는다
    (골프장 현황: 좌표 없음 + ``지역``/``소재지`` 합성 주소 → ``admin``). 이 단계를
    fallback에서 빠뜨리면 좌표 없는 dataset 전체가 "단서 없음"이 되어
    ``missing_address``로 **영구 drop**된다 — ``Address.display()``와 같은 순서로 본다.
    """
    bundle = _bundle(
        bjd_code=None,
        sigungu_code=None,
        sido_code=None,
        sigungu_name=None,
        road=None,
        admin="강원특별자치도 춘천시 1",
        coord=None,
        raw_data={"이름": "라데나골프클럽", "소재지": "춘천시 1"},
    )
    assert _provider_address(bundle) == "강원특별자치도 춘천시 1"
    assert validate_feature_bundle_address(bundle).issues == ()


def test_bundle_without_any_location_clue_is_missing_address() -> None:
    """좌표·주소·행정코드가 전부 없으면 ``missing_address``.

    이전 구현에서 ``_provider_address``는 **절대 ``None``을 반환하지 않았으므로** 이
    droppable error는 도달 불가능한 죽은 코드였다.
    """
    bundle = _bundle(
        bjd_code=None,
        sigungu_code=None,
        sido_code=None,
        sigungu_name=None,
        road=None,
        coord=None,
        raw_data={"name": "이름뿐"},
    )
    result = validate_feature_bundle_address(bundle)
    assert [(i.code, i.severity) for i in result.issues] == [
        ("missing_address", "error")
    ]
    assert "missing_address" in DROPPABLE_ISSUE_CODES


def test_name_states_separate_no_claim_from_no_token() -> None:
    """집계에서 '주장 없음'과 '주장은 있으나 행정 토큰 없음'이 실제로 갈린다.

    이전 구현에서 ``no_claim``은 **한 건도 나올 수 없었고**, 주소가 아예 없는 row가
    ``no_token``으로 집계돼 운영 지표가 뒤집혔다.
    """
    summary = validate_feature_bundles_address(
        [
            _bundle(road=None, raw_data={"name": "무명"}),
            _bundle(road="서울 종로 현대미술전시"),
            _bundle(road="부산 기장군 해동용궁사"),
            _bundle(sigungu_name=None, road="부산 기장군 해동용궁사"),
        ]
    )
    assert summary.name_state_counts == {
        "no_claim": 1,
        "no_token": 1,
        "matched": 1,
        "no_observation": 1,
    }
