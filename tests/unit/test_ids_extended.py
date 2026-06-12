"""``test_ids_extended`` — ``make_source_record_key`` / ``make_payload_hash``.

PR#26 review report P0-4 — ID helper 확장. ``make_feature_id`` 검증은
``test_ids.py``에 별도 (PR#20).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from kortravelmap.core.ids import (
    PAYLOAD_HASH_DEFAULT_LENGTH,
    SOURCE_RECORD_KEY_HASH_LENGTH,
    make_payload_hash,
    make_source_record_key,
)

# -- make_source_record_key --------------------------------------------


def test_source_record_key_format() -> None:
    """포맷: ``sr_{sha1(input)[:20]}``."""
    key = make_source_record_key(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash="abc123def456",
    )
    assert key.startswith("sr_")
    hash_part = key[3:]
    assert len(hash_part) == SOURCE_RECORD_KEY_HASH_LENGTH == 20
    int(hash_part, 16)  # hex check


def test_source_record_key_is_deterministic() -> None:
    """같은 입력 → 같은 key (idempotent upsert)."""
    args = {
        "provider": "python-visitkorea-api",
        "dataset_key": "festival",
        "source_entity_type": "festival_record",
        "source_entity_id": "E001234",
        "raw_payload_hash": "hash1",
    }
    assert make_source_record_key(**args) == make_source_record_key(**args)


@pytest.mark.parametrize(
    ("field", "new_value"),
    [
        ("provider", "python-knps-api"),
        ("dataset_key", "trails"),
        ("source_entity_type", "trail_record"),
        ("source_entity_id", "E999999"),
        ("raw_payload_hash", "hash2"),
    ],
)
def test_source_record_key_changes_with_any_field(field: str, new_value: str) -> None:
    """구성요소 중 하나라도 바뀌면 key가 달라야 한다."""
    base = {
        "provider": "python-visitkorea-api",
        "dataset_key": "festival",
        "source_entity_type": "festival_record",
        "source_entity_id": "E001234",
        "raw_payload_hash": "hash1",
    }
    a = make_source_record_key(**base)
    b = make_source_record_key(**{**base, field: new_value})
    assert a != b, f"{field} 변경에도 key 동일 — 충돌 위험"


@pytest.mark.parametrize(
    "field",
    ["provider", "dataset_key", "source_entity_type", "source_entity_id", "raw_payload_hash"],
)
def test_source_record_key_rejects_empty(field: str) -> None:
    """빈 구성요소 → ValueError."""
    base = {
        "provider": "python-visitkorea-api",
        "dataset_key": "festival",
        "source_entity_type": "festival_record",
        "source_entity_id": "E001234",
        "raw_payload_hash": "hash1",
    }
    with pytest.raises(ValueError, match=field):
        make_source_record_key(**{**base, field: ""})


@pytest.mark.parametrize(
    "field",
    ["provider", "dataset_key", "source_entity_type", "source_entity_id", "raw_payload_hash"],
)
def test_source_record_key_rejects_pipe(field: str) -> None:
    """``|``는 구분자 — 어느 필드에 들어가도 결정성 깨짐."""
    base = {
        "provider": "python-visitkorea-api",
        "dataset_key": "festival",
        "source_entity_type": "festival_record",
        "source_entity_id": "E001234",
        "raw_payload_hash": "hash1",
    }
    with pytest.raises(ValueError, match=r"\|"):
        make_source_record_key(**{**base, field: "bad|value"})


def test_source_record_key_sha1_matches_explicit() -> None:
    """SHA1 결정성 회귀 — input 포맷 변경 감지."""
    args = {
        "provider": "python-visitkorea-api",
        "dataset_key": "festival",
        "source_entity_type": "festival_record",
        "source_entity_id": "E001234",
        "raw_payload_hash": "hash1",
    }
    raw = (
        f"{args['provider']}|{args['dataset_key']}|"
        f"{args['source_entity_type']}|{args['source_entity_id']}|"
        f"{args['raw_payload_hash']}"
    )
    expected = "sr_" + hashlib.sha1(
        raw.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:20]
    assert make_source_record_key(**args) == expected


# -- make_payload_hash -------------------------------------------------


def test_payload_hash_default_length() -> None:
    """기본 길이 32 hex chars (128 bits)."""
    h = make_payload_hash({"a": 1, "b": 2})
    assert len(h) == PAYLOAD_HASH_DEFAULT_LENGTH == 32
    int(h, 16)  # hex check


def test_payload_hash_custom_length() -> None:
    """``length`` 파라미터로 prefix 조정 가능."""
    h_full = make_payload_hash({"a": 1})
    h_half = make_payload_hash({"a": 1}, length=16)
    assert len(h_half) == 16
    # 절반은 전체의 앞 절반
    assert h_full.startswith(h_half)


@pytest.mark.parametrize("length", [0, 65, -1, 100])
def test_payload_hash_invalid_length_raises(length: int) -> None:
    """``length`` 범위 1~64 외는 ValueError."""
    with pytest.raises(ValueError, match="length"):
        make_payload_hash({"a": 1}, length=length)


def test_payload_hash_canonical_dict_key_order() -> None:
    """``sort_keys=True`` — dict 키 순서 무관."""
    h1 = make_payload_hash({"a": 1, "b": 2})
    h2 = make_payload_hash({"b": 2, "a": 1})
    assert h1 == h2, "dict 키 순서 변경에 hash 변동"


def test_payload_hash_canonical_separators_strip_whitespace() -> None:
    """``separators=(",", ":")`` — whitespace 제거."""
    data1 = {"a": 1, "b": [1, 2, 3]}
    data2 = json.loads(json.dumps(data1, indent=4))  # whitespace 추가된 round-trip
    assert make_payload_hash(data1) == make_payload_hash(data2)


def test_payload_hash_unicode_preserved() -> None:
    """``ensure_ascii=False`` — 한글 그대로 UTF-8 인코딩."""
    h1 = make_payload_hash({"name": "북한산"})
    h2 = make_payload_hash({"name": "북한산"})  # 같은 한글
    assert h1 == h2
    # 한글이 escape 되지 않고 UTF-8로 처리되는지 — 동일 dict는 같은 hash면 OK


def test_payload_hash_different_data_different_hash() -> None:
    """다른 payload → 다른 hash (충돌 회피)."""
    h1 = make_payload_hash({"a": 1})
    h2 = make_payload_hash({"a": 2})
    h3 = make_payload_hash({"a": 1, "b": None})
    assert h1 != h2
    assert h1 != h3
    assert h2 != h3


def test_payload_hash_handles_datetime_decimal() -> None:
    """datetime/date/Decimal은 명시적 canonical JSON 값으로 정규화."""
    dt = datetime(2026, 1, 1)
    payload = {"d": dt, "day": date(2026, 1, 2), "n": Decimal("1.5")}
    h1 = make_payload_hash(payload)
    h2 = make_payload_hash(payload)
    assert h1 == h2


def test_payload_hash_handles_list_top_level() -> None:
    """top-level list도 동작 (dict 외 JSON 가능 타입 전체)."""
    h_list = make_payload_hash([1, 2, 3])
    h_str = make_payload_hash("hello")
    h_int = make_payload_hash(42)
    h_none = make_payload_hash(None)
    # 모두 32 hex chars
    for h in (h_list, h_str, h_int, h_none):
        assert len(h) == 32
        int(h, 16)


@pytest.mark.parametrize(
    "payload",
    [
        {"bad": {1, 2, 3}},
        {"bad": b"bytes"},
        {"bad": object()},
    ],
)
def test_payload_hash_rejects_unsupported_values(payload: object) -> None:
    """set/bytes/임의 객체는 str()로 삼키지 않고 거부."""
    with pytest.raises(TypeError):
        make_payload_hash(payload)


def test_payload_hash_rejects_non_string_dict_key() -> None:
    """JSON object key는 문자열만 허용."""
    with pytest.raises(TypeError, match="dict key"):
        make_payload_hash({1: "one"})


def test_payload_hash_sha256_matches_explicit() -> None:
    """SHA256 결정성 회귀 — canonical 직렬화 규칙 변경 감지."""
    data = {"name": "북한산", "lat": 37.6, "lon": 126.9}
    canonical = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    assert make_payload_hash(data) == expected
