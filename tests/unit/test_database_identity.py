"""``h35-db-identity-v1`` framing이 byte 단위로 고정돼 있는지.

이 digest는 `contracts/vnext/recovery-preflight-v1.json`이 요구하는 값이다. framing이
한 바이트라도 달라지면 이미 발급된 identity와 갈리는데, **갈렸다는 사실이 조용히
지나간다** — 양쪽 다 그럴듯한 64자 hex라서다. 그래서 golden vector로 못박는다.

원래 `tests/unit/test_h35_contract.py`에 있었고, 그 모듈이 T-VN-C01로 퇴역하면서 여기로
옮겼다.
"""

from __future__ import annotations

import pytest

from kortravelmap.core.database_identity import (
    DATABASE_IDENTITY_GOLDEN_VECTOR,
    DATABASE_IDENTITY_PREFIX,
    DatabaseIdentityError,
    canonical_json_bytes,
    compute_database_identity,
)

_TRANSACTION_ID = "00000000-0000-0000-0000-000000000001"


def test_golden_vector_is_exact() -> None:
    """framing이 바뀌면 여기서 잡힌다."""
    assert (
        compute_database_identity(
            transaction_id=str(DATABASE_IDENTITY_GOLDEN_VECTOR["transaction_id"]),
            database=str(DATABASE_IDENTITY_GOLDEN_VECTOR["database"]),
            system_identifier=str(DATABASE_IDENTITY_GOLDEN_VECTOR["system_identifier"]),
        )
        == DATABASE_IDENTITY_GOLDEN_VECTOR["digest"]
    )


def test_prefix_is_the_wire_constant() -> None:
    """접두는 wire 상수다. 모듈을 옮겼다고 바꾸면 안 된다."""
    assert DATABASE_IDENTITY_PREFIX == b"h35-db-identity-v1\0"


@pytest.mark.parametrize(
    ("database", "system_identifier"),
    [
        ("kor_travel_map", "１２３"),  # 전각 숫자
        ("kor_travel_map", "1" * 33),  # 32자 상한 초과
        ("kor_travel_map", ""),  # 빈 값
        ("kor_travel_map", "12a"),  # 숫자 아님
        ("Kor_Travel_Map", "123"),  # 대문자 DB명
        ("1invalid", "123"),  # 숫자로 시작
    ],
)
def test_rejects_noncanonical_inputs(database: str, system_identifier: str) -> None:
    with pytest.raises(DatabaseIdentityError):
        compute_database_identity(
            transaction_id=_TRANSACTION_ID,
            database=database,
            system_identifier=system_identifier,
        )


@pytest.mark.parametrize(
    "transaction_id",
    [
        "00000000000000000000000000000001",  # 하이픈 없음
        "{00000000-0000-0000-0000-000000000001}",  # 중괄호
        "00000000-0000-0000-0000-00000000000G",  # 비16진
        "",
    ],
)
def test_rejects_noncanonical_transaction_id(transaction_id: str) -> None:
    """표기가 달라도 같은 UUID면 `UUID()`는 통과시킨다.

    그러면 같은 트랜잭션이 표기에 따라 다른 digest를 낳는다. 표준 표기만 받는다.
    """
    with pytest.raises(DatabaseIdentityError):
        compute_database_identity(
            transaction_id=transaction_id,
            database="kor_travel_map",
            system_identifier="12345678901234567890",
        )


def test_field_boundaries_are_nul_framed() -> None:
    """NUL 경계가 없으면 인접 필드가 붙어 서로 다른 입력이 같은 digest를 낼 수 있다.

    ``database``와 ``system_identifier``의 경계를 옮긴 두 입력이 **다른** digest를
    내는지 본다. 같은 값이 나오면 framing이 깨진 것이다.
    """
    a = compute_database_identity(
        transaction_id=_TRANSACTION_ID,
        database="kor_travel_map",
        system_identifier="12345",
    )
    b = compute_database_identity(
        transaction_id=_TRANSACTION_ID,
        database="kor_travel_ma",
        system_identifier="12345",
    )
    assert a != b


def test_canonical_json_bytes_is_stable_across_key_order() -> None:
    assert canonical_json_bytes({"b": 1, "a": 2}) == canonical_json_bytes({"a": 2, "b": 1})


def test_canonical_json_bytes_preserves_non_ascii() -> None:
    """``ensure_ascii=False``가 계약이다 — 바뀌면 digest가 갈린다."""
    assert canonical_json_bytes({"k": "한글"}) == '{"k":"한글"}'.encode()


def test_canonical_json_bytes_has_no_incidental_whitespace() -> None:
    assert canonical_json_bytes({"a": [1, 2]}) == b'{"a":[1,2]}'
