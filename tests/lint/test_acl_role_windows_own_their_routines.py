"""ACL 인벤토리의 역할 창이 자기가 권한을 거는 루틴을 소유하는지 검사한다.

## 왜

PostgreSQL에서 `GRANT`/`REVOKE ON FUNCTION`은 **소유자만** 할 수 있다. 인벤토리는
문장을 역할 창(`_ACL_ROLE_WINDOWS`)으로 묶어 `SET ROLE` 뒤에 실행하는데, 어떤 루틴의
문장을 **다른 롤의 창**에 넣으면 조정기가 그 자리에서 선다:

    asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied for function resolve_provider_feature_id

그리고 이 실패는 조정기 안에서 나므로 **DB 픽스처 자체가 죽는다** — 그 픽스처를 쓰는
통합 테스트 전량이 setup error가 되고, 오류 메시지는 어느 창이 잘못됐는지 말하지
않는다. 2026-09-10에 정확히 그렇게 됐다: 새 함수의 문장을 `_AUDIT_WRITER_FUNCTION_ACL`
(창은 `ktm_feature_audit_writer`)에 넣었는데 소유자는 `ktm_feature_state_procedure_owner`
였다.

같은 부류를 마이그레이션 쪽에서는 `test_routine_ddl_runs_under_its_owner_role.py`가
이미 막는다. 인벤토리에는 그 눈이 없었다 — 그래서 여기 만든다.

## 정본

소유자는 `alembic/head-schema.sql`이 갖는다. 인벤토리가 스스로 적어 둔 창 이름을
정본으로 삼으면, 그 배치가 틀렸을 때 검사도 같이 틀린다.
"""

from __future__ import annotations

import pathlib
import re

from kortravelmap.infra import runtime_privileges

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: pg_dump가 한 줄로 뱉는 소유권 선언.
_HEAD_OWNER = re.compile(
    r"^ALTER (?:FUNCTION|PROCEDURE) ([a-z_]+\.[a-z_0-9]+)\(.*?\) OWNER TO ([a-z_]+);$",
    re.MULTILINE | re.DOTALL,
)
#: 루틴에 권한을 거는 문장만 본다. 표·시퀀스·스키마 문장은 소유자 규칙이 다르다.
_ROUTINE_ACL = re.compile(
    r"(?:GRANT|REVOKE)\s+.*?\s+ON\s+(?:FUNCTION|PROCEDURE)\s+"
    r"((?:feature|ops|provider_sync)\.[a-z_0-9]+)",
    re.IGNORECASE | re.DOTALL,
)


def _head_owners() -> dict[str, str]:
    owners: dict[str, str] = {}
    for match in _HEAD_OWNER.finditer(_HEAD_SCHEMA.read_text(encoding="utf-8")):
        owners.setdefault(match.group(1), match.group(2))
    return owners


def test_every_routine_acl_runs_inside_its_owner_window() -> None:
    owners = _head_owners()
    assert owners, "head 오라클에서 소유자를 하나도 읽지 못했다 — 이 검사가 공허해졌다"

    wrong: list[str] = []
    seen = 0
    for window_role, statements in runtime_privileges._ACL_ROLE_WINDOWS:
        for statement in statements:
            for routine in _ROUTINE_ACL.findall(statement):
                owner = owners.get(routine)
                if owner is None:
                    # head에 없는 루틴은 `_OPTIONAL_ROUTINES` 검사가 따로 본다.
                    continue
                seen += 1
                if owner != window_role:
                    wrong.append(f"{routine}: 창은 {window_role}인데 소유자는 {owner}")

    assert seen >= 20, (
        f"루틴 ACL 문장을 {seen}개만 봤다 — 인벤토리 형태가 바뀌어 이 검사가 대상을 "
        "잃었을 수 있다. `_ROUTINE_ACL` 패턴을 현행 문장에 맞춰라."
    )
    assert not wrong, (
        "ACL 문장이 소유자가 아닌 창에서 실행된다:\n  "
        + "\n  ".join(dict.fromkeys(wrong))
        + "\n\n`GRANT`/`REVOKE ON FUNCTION`은 소유자만 할 수 있다. 조정기가 그 자리에서 "
        "서고, 그 실패는 DB 픽스처를 죽여 통합 테스트 **전량**을 setup error로 만든다. "
        "문장을 소유자의 창으로 옮겨라."
    )
