"""T-VN-H28B — 행정코드 교차검증 규칙.

실측 근거: ``docs/reports/concierge-address-mismatch-evidence-2026-07-29.md``.
이전 이름-substring 규칙은 1,477 후보 중 380건을 영구 drop했고 **380건 전부 오탐**이었다
(payload 행정코드 == geo 행정코드, 진짜 불일치 0건).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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
            obs_code="2671025300", claim_code="2671025300", claim_kind="bjd"
        )
    )
    result = validate_feature_bundle_address(bundle)
    assert result.issues == ()
    assert not result.has_errors


def test_address_string_naming_a_different_sigungu_is_not_an_issue() -> None:
    """`서울 서대문구 통일로 251`인데 좌표는 종로구 — 실측에서 코드는 둘 다 종로구였다.

    즉 주소 **문자열** 쪽이 틀렸고 코드 쪽이 맞다. 문자열을 근거로 판정하지 않는다.
    """
    bundle = _bundle(
        bjd_code="1111017700",
        sigungu_code="11110",
        sido_code="11",
        sigungu_name="종로구",
        road="서울 서대문구 통일로 251",
        admin_evidence=AdminEvidence(
            obs_code="1111017700", claim_code="1111017700", claim_kind="bjd"
        ),
    )
    assert validate_feature_bundle_address(bundle).issues == ()


# ── 탐지력: 진짜 불일치는 여전히 잡는다 ──────────────────────────────────────


@pytest.mark.parametrize(
    ("obs", "claim", "expected_level"),
    [
        ("1111017700", "2671025300", "sido"),  # 서울 vs 부산
        ("2671025300", "2650010100", "sigungu"),  # 기장군 vs 수영구
        ("2671025300", "2671010200", "emd"),  # 같은 군, 다른 읍면동
    ],
)
def test_code_conflict_is_detected_at_the_right_level(
    obs: str, claim: str, expected_level: str
) -> None:
    bundle = _bundle(
        admin_evidence=AdminEvidence(obs_code=obs, claim_code=claim, claim_kind="bjd")
    )
    issues = validate_feature_bundle_address(bundle).issues
    codes = [i.code for i in issues if i.code.startswith("admin_code_conflict")]
    assert codes == [f"admin_code_conflict_{expected_level}"]


def test_code_conflict_is_never_an_error() -> None:
    """행정코드 불일치는 관측 대상이지 영구 손실 사유가 아니다."""
    bundle = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="1111017700", claim_code="2671025300", claim_kind="bjd"
        )
    )
    result = validate_feature_bundle_address(bundle)
    conflicts = [i for i in result.issues if i.code.startswith("admin_code_conflict")]
    assert conflicts
    assert all(i.severity == "warning" for i in conflicts)
    assert all(i.code not in DROPPABLE_ISSUE_CODES for i in conflicts)


# ── 정밀도 규칙 ──────────────────────────────────────────────────────────────


def test_ri_digits_are_not_compared() -> None:
    """리(8:10)는 ``_bjd_code_from_emd_code``가 합성할 수 있어 판정 근거가 아니다."""
    bundle = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="2671025300", claim_code="2671025399", claim_kind="bjd"
        )
    )
    assert validate_feature_bundle_address(bundle).issues == ()


def test_sigungu_claim_compares_only_five_digits() -> None:
    """5자리 주장을 10자리로 부풀려 비교하지 않는다."""
    same = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="2671025300", claim_code="26710", claim_kind="sigungu"
        )
    )
    assert validate_feature_bundle_address(same).issues == ()

    differ = _bundle(
        admin_evidence=AdminEvidence(
            obs_code="2671025300", claim_code="26500", claim_kind="sigungu"
        )
    )
    codes = [i.code for i in validate_feature_bundle_address(differ).issues]
    assert "admin_code_conflict_sigungu" in codes


# ── 침묵을 통과로 착각하지 않는다 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        AdminEvidence(),
        AdminEvidence(obs_code="2671025300"),
        AdminEvidence(claim_code="2671025300", claim_kind="bjd"),
    ],
)
def test_missing_axis_yields_no_verdict(evidence: AdminEvidence | None) -> None:
    """축이 하나라도 없으면 판정하지 않는다 — 통과가 아니라 증거 없음이다."""
    bundle = _bundle(admin_evidence=evidence)
    issues = validate_feature_bundle_address(bundle).issues
    assert [i for i in issues if i.code.startswith("admin_code_conflict")] == []


def test_summary_reports_evidence_coverage() -> None:
    """커버리지를 집계하지 않으면 '판정 못 함'과 '통과'가 구분되지 않는다."""
    summary = validate_feature_bundles_address(
        [
            _bundle(
                admin_evidence=AdminEvidence(
                    obs_code="2671025300", claim_code="2671025300", claim_kind="bjd"
                )
            ),
            _bundle(admin_evidence=AdminEvidence(obs_code="2671025300")),
            _bundle(admin_evidence=None),
        ]
    )
    assert summary.evidence_grade_counts == {"dual": 1, "obs_only": 1, "unarmed": 1}
    assert summary.as_metadata()["address_validation_evidence_grades"] == {
        "dual": 1,
        "obs_only": 1,
        "unarmed": 1,
    }


def test_retired_string_codes_are_no_longer_emitted() -> None:
    """이름 축 code는 발행 중단됐다 (탐지력 0이 실측으로 확인됨)."""
    summary = validate_feature_bundles_address(
        [
            _bundle(
                road="완전히 다른 문자열",
                admin_evidence=AdminEvidence(
                    obs_code="2671025300", claim_code="2671025300", claim_kind="bjd"
                ),
            )
        ]
    )
    emitted = {issue.code for issue in summary.issues}
    assert "provider_address_mismatch" not in emitted
    assert "provider_address_partial_match" not in emitted
