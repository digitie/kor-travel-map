"""``infra/feature_identity`` 순수 함수 계약 (T-VN-32B, ADR-068).

DB 없이 검증 가능한 경계 계약:

- 참조 형식 검증(빈 문자열/공백 패딩/길이 초과 → ``FeatureIdentityRefError``)
- ``expected_feature_uuid`` = uuid5 파생, core 정본과 동일 — 0083 이후에는
  **backfill 세대 참조 전용**이다(신규 행 generator가 아님).

신규 행 generator(``candidate_feature_uuid``)와 write 경로 fail-close
(``verify_feature_uuid``)는 ``tests/unit/test_feature_identity_verify.py`` 소관.
"""

from __future__ import annotations

import pytest

from kortravelmap.core.ids import feature_uuid_from_legacy
from kortravelmap.infra.feature_identity import (
    MAX_FEATURE_REF_LENGTH,
    FeatureIdentityRefError,
    candidate_feature_uuid,
    expected_feature_uuid,
    validate_feature_ref,
)

pytestmark = pytest.mark.unit


def test_validate_feature_ref_accepts_legacy_and_uuid_shapes() -> None:
    assert validate_feature_ref("f_1168010100_p_3c0c2820e96d28d3") == (
        "f_1168010100_p_3c0c2820e96d28d3"
    )
    assert validate_feature_ref("feature:레거시-한글-id") == "feature:레거시-한글-id"
    canonical = str(feature_uuid_from_legacy("f_global_e_x"))
    assert validate_feature_ref(canonical) == canonical


@pytest.mark.parametrize(
    "ref",
    [
        "",
        " f_1",
        "f_1 ",
        "\tf_1",
        "x" * (MAX_FEATURE_REF_LENGTH + 1),
    ],
)
def test_validate_feature_ref_rejects_malformed(ref: str) -> None:
    with pytest.raises(FeatureIdentityRefError):
        validate_feature_ref(ref)


def test_expected_feature_uuid_matches_core_derivation() -> None:
    """backfill 세대 참조는 core uuid5 파생과 동일하다 (0080 각인값 재현)."""
    for feature_id in (
        "f_1168010100_p_3c0c2820e96d28d3",
        "f_global_e_0123456789abcdef",
        "feature:레거시-한글-id",
    ):
        assert expected_feature_uuid(feature_id) == str(
            feature_uuid_from_legacy(feature_id)
        )


def test_candidate_feature_uuid_is_not_the_derived_value() -> None:
    """0083 값 전환 — 신규 행 후보는 파생 참조와 분리된 축이다.

    두 함수가 다시 같은 값을 내면 32C 값 전환이 되돌아간 것이다(회귀 방향 고정).
    """
    feature_id = "f_global_e_0123456789abcdef"
    assert candidate_feature_uuid() != expected_feature_uuid(feature_id)
