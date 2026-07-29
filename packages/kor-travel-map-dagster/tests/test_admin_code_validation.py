"""T-VN-H28B — 행정코드 교차검증 규칙.

실측 근거: ``docs/reports/concierge-address-mismatch-evidence-2026-07-29.md``.
이전 이름-substring 규칙은 1,477 후보 중 380건을 영구 drop했고 **380건 전부 오탐**이었다
(payload 행정코드 == geo 행정코드, 진짜 불일치 0건).
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
    validate_feature_bundle_address,
    validate_feature_bundles_address,
)

_FETCHED_AT = "2026-07-29T00:00:00+00:00"


def _bundle(
    *,
    bjd_code: str | None = "2671025300",
    sigungu_code: str | None = "26710",
    sido_code: str | None = "26",
    sigungu_name: str | None = "기장군",
    road: str | None = "부산 기장 해동용궁사",
    coord: Coordinate | None = None,
    admin_evidence: AdminEvidence | None = None,
) -> FeatureBundle:
    if coord is None:
        coord = Coordinate(lon=Decimal("129.223"), lat=Decimal("35.1886"))
    address = Address(
        road=road,
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
        raw_name="해동용궁사",
        raw_address=road,
        fetched_at=datetime.fromisoformat(_FETCHED_AT),
    )
    link = SourceLink(
        feature_id=feature.feature_id,
        source_record_key=record.source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
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
