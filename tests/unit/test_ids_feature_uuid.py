"""``test_ids_feature_uuid`` — legacy id → shadow UUID 파생 회귀 고정 (T-VN-32A).

``feature_uuid_from_legacy``는 alembic ``0079_feature_uuid_shadow`` backfill과
DB 트리거의 Python 정본이다. namespace·고정 벡터가 바뀌면 backfill된 전 UUID가
갈라지므로 (영구 약속) 값 자체를 리터럴로 고정한다. DB SQL mirror와의 대조는
``tests/integration/test_feature_uuid_shadow_migration.py`` 소관.
"""

from __future__ import annotations

import uuid

import pytest

from kortravelmap.core.ids import FEATURE_UUID_NAMESPACE, feature_uuid_from_legacy

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
