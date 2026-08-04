"""``infra/feature_identity`` 순수 함수 계약 (T-VN-32B, ADR-068).

DB 없이 검증 가능한 경계/불변식 계약:

- 참조 형식 검증(빈 문자열/공백 패딩/길이 초과 → ``FeatureIdentityRefError``)
- dual 기간 정본 generator(``expected_feature_uuid`` = uuid5 파생, core 정본과 동일)
- write 경로 fail-close(``verify_feature_uuid`` — 결측/파생 불일치 즉시 실패)
"""

from __future__ import annotations

import pytest

from kortravelmap.core.ids import feature_uuid_from_legacy
from kortravelmap.infra.feature_identity import (
    MAX_FEATURE_REF_LENGTH,
    FeatureIdentityInvariantError,
    FeatureIdentityRefError,
    expected_feature_uuid,
    validate_feature_ref,
    verify_feature_uuid,
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
    """dual 기간 정본 generator는 core uuid5 파생과 동일하다 (32B 결정)."""
    for feature_id in (
        "f_1168010100_p_3c0c2820e96d28d3",
        "f_global_e_0123456789abcdef",
        "feature:레거시-한글-id",
    ):
        assert expected_feature_uuid(feature_id) == str(
            feature_uuid_from_legacy(feature_id)
        )


def test_verify_feature_uuid_accepts_derived_value_case_insensitively() -> None:
    feature_id = "f_global_e_0123456789abcdef"
    derived = expected_feature_uuid(feature_id)
    assert verify_feature_uuid(feature_id, derived) == derived
    assert verify_feature_uuid(feature_id, derived.upper()) == derived


@pytest.mark.parametrize(
    "observed",
    [
        None,
        "",
        "00000000-0000-5000-8000-000000000000",
    ],
)
def test_verify_feature_uuid_fail_closes_on_missing_or_drifted_value(
    observed: str | None,
) -> None:
    """legacy-only(결측) 또는 파생 불일치 관측은 즉시 실패한다 (fail-close)."""
    with pytest.raises(FeatureIdentityInvariantError):
        verify_feature_uuid("f_global_e_0123456789abcdef", observed)
