"""``feature_identity`` 신규 행 generator·write 검증 계약 (T-VN-32C, ADR-068).

0083 값 전환 이후의 write 경로 불변식을 DB 없이 고정한다:

- :func:`candidate_feature_uuid` — 신규 행 후보는 **비파생 UUIDv7**이다
  (legacy id 파생과 무관·호출마다 다름).
- :func:`verify_feature_uuid` — 파생 등식 대조는 폐기됐고, 남은 축은
  ① 관측값이 canonical UUID인가(legacy-only/비정규 fail-close),
  ② ``inserted=True``인 신규 insert의 관측값이 우리가 보낸 후보와 같은가
  (generator 이원화 차단). ``inserted=False``(conflict-update)면 기존 저장값이
  정본이므로 후보와 달라도 통과한다.

``expected_feature_uuid``의 파생 등식 자체는 역사 참조로 남는다 —
``tests/unit/test_feature_identity_boundary_refs.py`` 소관.
"""

from __future__ import annotations

import uuid

import pytest

from kortravelmap.core.ids import feature_uuid_from_legacy
from kortravelmap.infra.feature_identity import (
    FeatureIdentityInvariantError,
    candidate_feature_uuid,
    verify_feature_uuid,
)

pytestmark = pytest.mark.unit

_FEATURE_ID = "f_global_e_0123456789abcdef"


# ── candidate_feature_uuid — 비파생 v7 후보 ─────────────────────────────────


def test_candidate_feature_uuid_is_canonical_nonderived_v7() -> None:
    candidate = candidate_feature_uuid()
    parsed = uuid.UUID(candidate)
    assert str(parsed) == candidate  # canonical lowercase hyphenated
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122


def test_candidate_feature_uuid_differs_per_call_and_from_derivation() -> None:
    """후보는 legacy id와 무관하다 — 파생 generator였다면 둘 다 실패한다."""
    first = candidate_feature_uuid()
    second = candidate_feature_uuid()
    assert first != second
    assert first != str(feature_uuid_from_legacy(_FEATURE_ID))


# ── verify_feature_uuid — canonical 축 ──────────────────────────────────────


def test_verify_accepts_canonical_observation_regardless_of_generation() -> None:
    """파생 세대(uuid5)든 신규 세대(v7)든 canonical이면 통과한다 (0083 이후)."""
    derived = str(feature_uuid_from_legacy(_FEATURE_ID))
    nonderived = candidate_feature_uuid()
    assert verify_feature_uuid(_FEATURE_ID, derived) == derived
    assert verify_feature_uuid(_FEATURE_ID, nonderived) == nonderived
    # 다른 feature의 파생값이어도 canonical이면 통과한다 — 파생 등식은 더 이상
    # 계약이 아니다(회귀 방향 고정: 이 단언이 깨지면 파생 검증이 되살아난 것).
    assert verify_feature_uuid(
        _FEATURE_ID, str(feature_uuid_from_legacy("f_global_e_other"))
    ) == str(feature_uuid_from_legacy("f_global_e_other"))


def test_verify_normalizes_uppercase_observation() -> None:
    observed = candidate_feature_uuid()
    assert verify_feature_uuid(_FEATURE_ID, observed.upper()) == observed


def test_verify_accepts_uuid_object_observation() -> None:
    """driver가 ``uuid.UUID``를 돌려주는 경우도 같은 canonical 문자열이 된다."""
    value = uuid.UUID(candidate_feature_uuid())
    assert verify_feature_uuid(_FEATURE_ID, value) == str(value)


@pytest.mark.parametrize(
    "observed",
    [
        None,
        "",
        "not-a-uuid",
        # uuid.UUID는 수용하지만 canonical 형태가 아닌 표기들.
        "01890a5da-c96-774b-bcce-b302099a8057",  # 36자지만 hyphen 위치가 다르다
        "01890a5dac96774bbcceb302099a8057",
        "{01890a5d-ac96-774b-bcce-b302099a8057}",
        "urn:uuid:01890a5d-ac96-774b-bcce-b302099a8057",
        "01890a5d-ac96-774b-bcce-b302099a805",
    ],
)
def test_verify_fail_closes_on_missing_or_non_canonical_observation(
    observed: str | None,
) -> None:
    """legacy-only(결측)·비정규 표기는 즉시 실패한다 (fail-close)."""
    with pytest.raises(FeatureIdentityInvariantError, match="legacy-only"):
        verify_feature_uuid(_FEATURE_ID, observed)


# ── verify_feature_uuid — inserted/sent 축 (generator 이원화 차단) ──────────


def test_verify_rejects_new_insert_whose_observation_differs_from_sent() -> None:
    """``xmax = 0``(신규 insert)인데 관측값이 후보와 다르면 generator 이원화다."""
    sent = candidate_feature_uuid()
    observed = candidate_feature_uuid()
    with pytest.raises(FeatureIdentityInvariantError, match="generator 이원화"):
        verify_feature_uuid(
            _FEATURE_ID, observed, sent_feature_uuid=sent, inserted=True
        )


def test_verify_accepts_new_insert_echoing_the_sent_candidate() -> None:
    sent = candidate_feature_uuid()
    assert (
        verify_feature_uuid(_FEATURE_ID, sent, sent_feature_uuid=sent, inserted=True)
        == sent
    )
    # 대소문자만 다른 echo도 같은 후보로 본다 (driver 표기 자유도 흡수).
    assert (
        verify_feature_uuid(
            _FEATURE_ID, sent.upper(), sent_feature_uuid=sent, inserted=True
        )
        == sent
    )


def test_verify_accepts_conflict_update_keeping_stored_value() -> None:
    """conflict-update(``inserted=False``)면 기존 저장값이 정본 — 후보는 버려진다.

    기존 행은 0080 backfill 파생값을 유지하므로, 후보(v7)와 다른 것이 **정상**
    상태다. 이 축에서 실패하면 재적재가 전부 fail-close된다.
    """
    stored = str(feature_uuid_from_legacy(_FEATURE_ID))
    sent = candidate_feature_uuid()
    assert (
        verify_feature_uuid(
            _FEATURE_ID, stored, sent_feature_uuid=sent, inserted=False
        )
        == stored
    )


def test_verify_with_unknown_insert_state_checks_canonical_only() -> None:
    """``inserted=None``(xmax 미관측 경로 — admin add)은 canonical 축만 본다."""
    stored = str(feature_uuid_from_legacy(_FEATURE_ID))
    sent = candidate_feature_uuid()
    assert verify_feature_uuid(_FEATURE_ID, stored, sent_feature_uuid=sent) == stored
    with pytest.raises(FeatureIdentityInvariantError, match="legacy-only"):
        verify_feature_uuid(_FEATURE_ID, None, sent_feature_uuid=sent)


def test_verify_without_sent_candidate_skips_the_echo_check() -> None:
    """``sent`` 미제공이면 ``inserted=True``라도 echo 축은 검사하지 않는다."""
    observed = candidate_feature_uuid()
    assert verify_feature_uuid(_FEATURE_ID, observed, inserted=True) == observed
