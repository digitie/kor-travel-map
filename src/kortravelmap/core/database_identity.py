"""live database identity — ``h35-db-identity-v1`` NUL-framed digest.

`contracts/vnext/recovery-preflight-v1.json`이 **살아 있는 계약**으로 이 값을 요구한다:

    "database_identity": "live 재계산 identity — sha256(h35-db-identity-v1 NUL-framed
     transaction_id/role/database/system_identifier). request echo가 아닌 재계산 값만 신뢰"

정의는 원래 `kortravelmap.cli._h35_contract`에 있었다. 그 모듈은 2026-08-13 prod cutover로
사문화된 H35 helper 세트의 일부라 2026-08-18에 퇴역시켰는데(T-VN-C01), **계약이 참조하는
실행 정의까지 같이 지우면 스펙만 남고 그것을 계산하는 코드가 저장소 어디에도 없게 된다.**
소비자인 `T-VN-39`가 아직 열려 있으므로 그 계약을 구현할 사람이 산문에서 framing을 다시
유도해야 한다 — 그건 golden vector 없이 재현하기 어렵다.

그래서 identity 축만 여기로 옮겼다. 이름의 ``h35`` 접두는 **wire 상수**라 바꾸지 않는다 —
바꾸면 이미 발급된 digest와 갈린다.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Final
from uuid import UUID

from kortravelmap.core.exceptions import KorTravelMapError

DATABASE_IDENTITY_ROLE: Final = "map_application"
DATABASE_IDENTITY_PREFIX: Final = b"h35-db-identity-v1\0"

#: 이 값이 바뀌면 framing이 바뀐 것이다. 테스트가 byte 단위로 고정한다.
DATABASE_IDENTITY_GOLDEN_VECTOR: Final = {
    "transaction_id": "00000000-0000-0000-0000-000000000001",
    "database": "kor_travel_map",
    "system_identifier": "12345678901234567890",
    "digest": "9bca9b82ad2304759581ebf16e724461fcfd7c657e2b41ce5ae3ae54847dee5a",
}


class DatabaseIdentityError(KorTravelMapError):
    """identity 입력이 계약을 벗어났다."""


def canonical_json_bytes(value: object) -> bytes:
    """digest 대상이 되는 canonical JSON 직렬화.

    key 정렬 + 공백 제거 + 비ASCII 보존. 이 셋 중 하나라도 다르면 digest가 갈린다.
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _strict_uuid(value: str, *, field: str) -> None:
    """UUID 문자열을 **표준 표기 그대로** 요구한다.

    ``UUID(value)``만 쓰면 중괄호·하이픈 없는 표기도 통과하는데, 그러면 같은 트랜잭션이
    표기에 따라 다른 digest를 낳는다.
    """
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise DatabaseIdentityError(f"{field}_invalid") from exc
    if str(parsed) != value:
        raise DatabaseIdentityError(f"{field}_invalid")


def compute_database_identity(
    *,
    transaction_id: str,
    database: str,
    system_identifier: str,
) -> str:
    """``h35-db-identity-v1`` NUL-framed live database identity를 계산한다.

    framing은 ``prefix \\0`` 뒤에 ``transaction_id \\0 role \\0 database \\0
    system_identifier \\0``를 잇고 SHA-256을 취한다. 각 필드 뒤의 NUL이 **경계**이고,
    그것이 없으면 인접 필드가 붙어 서로 다른 입력이 같은 digest를 낼 수 있다.
    """
    _strict_uuid(transaction_id, field="transaction_id")
    if re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database) is None:
        raise DatabaseIdentityError("database_identity_input_invalid")
    if (
        not system_identifier.isascii()
        or not system_identifier.isdigit()
        or not 1 <= len(system_identifier) <= 32
    ):
        raise DatabaseIdentityError("database_identity_input_invalid")
    framed = b"".join(
        (
            DATABASE_IDENTITY_PREFIX,
            transaction_id.encode("ascii"),
            b"\0",
            DATABASE_IDENTITY_ROLE.encode("ascii"),
            b"\0",
            database.encode("ascii"),
            b"\0",
            system_identifier.encode("ascii"),
            b"\0",
        )
    )
    return hashlib.sha256(framed).hexdigest()


__all__ = [
    "DATABASE_IDENTITY_GOLDEN_VECTOR",
    "DATABASE_IDENTITY_PREFIX",
    "DATABASE_IDENTITY_ROLE",
    "DatabaseIdentityError",
    "canonical_json_bytes",
    "compute_database_identity",
]
