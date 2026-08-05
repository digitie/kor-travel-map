"""``test_ids_feature_uuid`` — feature UUID generator 회귀 고정 (T-VN-32A/32C).

두 세대가 공존한다:

- ``feature_uuid_from_legacy`` (0080 backfill 세대) — alembic
  ``0080_feature_uuid_shadow`` backfill과 DB 트리거의 Python 정본. namespace·
  고정 벡터가 바뀌면 backfill된 전 UUID가 갈라지므로 (영구 약속) 값 자체를
  리터럴로 고정한다. **0083 이후에도 기존 731,600행의 역사 계약으로 유지**된다.
- ``make_feature_uuid`` (0083 정본 generator) — 신규 행의 **비파생** UUIDv7.
  값 고정은 불가능하므로(난수) RFC 9562 레이아웃 불변식으로 고정한다.

DB SQL mirror(``feature.feature_uuid_from_legacy`` / ``feature.uuid_generate_v7``)
와의 대조는 ``tests/integration/test_feature_uuid_shadow_migration.py`` 소관.
"""

from __future__ import annotations

import itertools
import uuid

import pytest

from kortravelmap.core.ids import (
    FEATURE_UUID_NAMESPACE,
    feature_uuid_from_legacy,
    make_feature_uuid,
)

# ── namespace 고정 ──────────────────────────────────────────────────────────


def test_namespace_is_pinned_literal_and_derivation() -> None:
    """namespace는 리터럴·파생 규칙 양쪽으로 고정한다 (둘 중 하나만 어겨도 실패)."""
    assert uuid.UUID("75d60e13-2779-5b06-a920-6b1b892a7c84") == FEATURE_UUID_NAMESPACE
    assert uuid.uuid5(uuid.NAMESPACE_URL, "kor-travel-map:feature-uuid:v1") == (
        FEATURE_UUID_NAMESPACE
    )


# ── 고정 벡터 2개 — 회귀 고정 ───────────────────────────────────────────────


def test_fixed_vector_place_feature_id() -> None:
    """ADR-009 문서 예제 id (data-model.md §11)의 파생값 고정."""
    assert feature_uuid_from_legacy("f_1168010100_p_3c0c2820e96d28d3") == uuid.UUID(
        "4232803d-a8a7-57c2-b80b-e13ca8fa1a2a"
    )


def test_fixed_vector_global_event_feature_id() -> None:
    assert feature_uuid_from_legacy("f_global_e_0123456789abcdef") == uuid.UUID(
        "8f30ccfb-3959-55ad-b2a5-323749bd6c39"
    )


# ── 결정성·RFC 4122 속성 ────────────────────────────────────────────────────


def test_same_input_yields_same_uuid_and_differs_by_input() -> None:
    a = feature_uuid_from_legacy("f_global_w_aaaa")
    b = feature_uuid_from_legacy("f_global_w_aaaa")
    c = feature_uuid_from_legacy("f_global_w_aaab")
    assert a == b
    assert a != c


def test_result_is_rfc4122_version_5() -> None:
    derived = feature_uuid_from_legacy("f_1168010100_p_3c0c2820e96d28d3")
    assert derived.version == 5
    assert derived.variant == uuid.RFC_4122


def test_non_ascii_legacy_id_is_utf8_stable() -> None:
    """비-ASCII id도 UTF-8 bytes 기준으로 결정적이다 (DB convert_to UTF8 동일)."""
    a = feature_uuid_from_legacy("feature:레거시-한글-id")
    assert a == feature_uuid_from_legacy("feature:레거시-한글-id")
    assert a.version == 5


def test_empty_feature_id_rejected() -> None:
    with pytest.raises(ValueError, match="비어 있을 수 없음"):
        feature_uuid_from_legacy("")


# ── make_feature_uuid — 0083 비파생 UUIDv7 generator ────────────────────────

_UUID_V7_TIMESTAMP_SHIFT: int = 80
"""128bit 정수에서 상위 48bit(unix-ms) 만 남기는 우시프트 폭."""


def test_make_feature_uuid_is_rfc9562_version_7_with_rfc_variant() -> None:
    """version 7 · variant 0b10 — DB mirror(feature.uuid_generate_v7)와 같은 레이아웃."""
    for _ in range(16):
        value = make_feature_uuid()
        assert value.version == 7
        assert value.variant == uuid.RFC_4122
        # 비트 자체로도 고정한다 (uuid 모듈 해석에 의존하지 않는 축).
        assert (value.int >> 76) & 0xF == 0x7
        assert (value.int >> 62) & 0b11 == 0b10


def test_make_feature_uuid_encodes_injected_timestamp_in_high_48_bits() -> None:
    """상위 48bit == 주입한 unix milliseconds (시간 정렬성의 근거)."""
    for now_ms in (0, 1, 1_754_400_000_000, (1 << 48) - 1):
        value = make_feature_uuid(_now_ms=now_ms)
        assert value.int >> _UUID_V7_TIMESTAMP_SHIFT == now_ms
        assert value.version == 7
        assert value.variant == uuid.RFC_4122


def test_make_feature_uuid_is_not_deterministic() -> None:
    """비파생 — 같은 입력(없음)·같은 밀리초에도 서로 다른 값이 나온다 (74bit 난수)."""
    assert make_feature_uuid() != make_feature_uuid()
    fixed_ms = 1_754_400_000_000
    values = {make_feature_uuid(_now_ms=fixed_ms) for _ in range(64)}
    assert len(values) == 64


def test_make_feature_uuid_is_monotonic_in_timestamp() -> None:
    """``_now_ms`` 단조 증가 → UUID도 정수·canonical 문자열 양쪽에서 단조 증가."""
    timestamps = [1_754_400_000_000 + step for step in (0, 1, 2, 999, 86_400_000)]
    values = [make_feature_uuid(_now_ms=now_ms) for now_ms in timestamps]
    ints = [value.int for value in values]
    texts = [str(value) for value in values]
    assert ints == sorted(ints)
    assert all(earlier < later for earlier, later in itertools.pairwise(ints))
    # canonical lowercase hex + 고정 폭이라 문자열 사전순도 정수순과 같다
    # (keyset 페이지네이션·인덱스 지역성의 실질 근거).
    assert texts == sorted(texts)


@pytest.mark.parametrize("now_ms", [-1, 1 << 48, (1 << 48) + 1, 1 << 64])
def test_make_feature_uuid_rejects_timestamp_outside_48_bits(now_ms: int) -> None:
    with pytest.raises(ValueError, match="48bit"):
        make_feature_uuid(_now_ms=now_ms)
