"""루틴 DDL이 실행 가능한 롤로 도는지 문장열을 따라가며 검사한다.

## 왜

`CREATE OR REPLACE`와 `DROP`은 소유자만 할 수 있고, 이 저장소의 소유자 롤들은
NOINHERIT다 — 멤버십만으로는 통과하지 못하고 `SET ROLE`이 실제로 걸려 있어야 한다.

그런데 `SET ROLE`은 **문장열 위의 상태**라서, 어떤 파일이 자기 창을 닫으면 그 뒤의
모든 문장이 영향을 받는다. 2026-09-09 T-VN-39 309가 정확히 그렇게 깨졌다: 바깥에서
소유자 롤별로 묶었는데, 그 그룹 안에 자기 `SET ROLE ...; ...; SET ROLE
ktm_feature_schema_owner;` 쌍을 이미 들고 있는 사이드카가 섞여 있었다. 그 파일이
끝나는 순간 롤이 스키마 소유자로 돌아갔고, 뒤따르던 `derive_subtype_public_ready`가
`must be owner of function`으로 죽었다.

읽어서는 안 보인다 — 각 파일은 혼자 보면 옳고, 목록도 혼자 보면 옳다. 깨지는 것은
둘의 **합성**이다. 그래서 합성을 그대로 흉내 내서 본다.

## 연산마다 요구가 다르다

한 덩어리로 "소유자 롤로 돌아야 한다"고 보면 멀쩡한 패턴을 빨갛게 만든다. 실제로
PostgreSQL이 요구하는 것은 셋으로 갈린다:

- `DROP`, `CREATE OR REPLACE` — 그 객체를 **이미 소유**해야 한다. 창이 필수다.
- 새 `CREATE` — 스키마의 CREATE 권한만 있으면 되고, **만든 롤이 소유자가 된다.**
  그래서 스키마 소유자로 만들고 곧바로 `OWNER TO`로 넘기는 형태가 성립한다. 소유자
  롤이 스키마 CREATE를 못 가진 경우(`ops`)에는 이쪽이 유일한 길이다.
- `GRANT`/`REVOKE` — 소유자여야 한다.

그래서 이 검사도 셋으로 나눠 본다. 무엇이 요구되는지를 옮겨 적는 것이지, 어떤
스타일을 강요하는 것이 아니다.

예외는 두지 않는다. `ops.record_curation_import_manual_feature_child`가 유일한
후보였는데 — `ops`에서 소유자 롤이 CREATE를 못 가진다 — 창을 셋으로 쪼개니 예외가
필요 없어졌다. 예외 목록은 늘어나기 시작하면 검사를 갉아먹으므로, 없는 채로 둔다.

## 무엇을 정본으로 삼는가

소유자는 `alembic/head-schema.sql`이 갖는다. 마이그레이션 자신이 적어 둔 `OWNER TO`를
정본으로 삼으면 그 값이 틀렸을 때 검사도 같이 틀린다.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
from typing import Any, Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: 마이그레이션이 문장열을 시작하는 롤. `_UPGRADE_STATEMENTS`의 첫 문장이다.
_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

_SET_ROLE = re.compile(r"^SET\s+ROLE\s+([a-z_]+)\s*;?\s*$", re.IGNORECASE)
_ROUTINE = r"([a-z_]+\.[a-z_0-9]+)\s*\("
_DROP = re.compile(rf"^DROP\s+(?:FUNCTION|PROCEDURE)\s+{_ROUTINE}", re.IGNORECASE)
_REPLACE = re.compile(
    rf"^CREATE\s+OR\s+REPLACE\s+(?:FUNCTION|PROCEDURE)\s+{_ROUTINE}", re.IGNORECASE
)
_CREATE = re.compile(rf"^CREATE\s+(?:FUNCTION|PROCEDURE)\s+{_ROUTINE}", re.IGNORECASE)
_PRIVILEGE = re.compile(
    rf"^(?:GRANT|REVOKE)\s+.*?\s+ON\s+(?:FUNCTION|PROCEDURE)\s+{_ROUTINE}",
    re.IGNORECASE | re.DOTALL,
)
#: `DO` 블록 안의 `EXECUTE 'ALTER ...'`도 잡으려면 문장 어디에서나 찾아야 한다.
_TRANSFER = re.compile(
    r"ALTER\s+(?:FUNCTION|PROCEDURE)\s+([a-z_]+\.[a-z_0-9]+)\s*\(.*?\)\s*OWNER TO ([a-z_]+)",
    re.IGNORECASE | re.DOTALL,
)
_HEAD_OWNER = re.compile(
    r"^ALTER (?:FUNCTION|PROCEDURE) ([a-z_]+\.[a-z_0-9]+)\(.*?\) OWNER TO ([a-z_]+);$",
    re.MULTILINE | re.DOTALL,
)


def _sql_head(statement: str) -> str:
    """앞머리 주석과 빈 줄을 떼고 실제 SQL이 시작하는 자리부터 돌려준다.

    문장 분할기는 `;`만 보고 자르므로 주석이 문장 앞에 붙어 온다. 그 주석을 떼지
    않으면 `^SET ROLE`을 찾는 눈이 창을 통째로 놓친다 — 그리고 그건 "검사는 초록인데
    상태는 틀린" 바로 그 부류다.
    """
    for index, line in enumerate(lines := statement.splitlines()):
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return "\n".join(lines[index:]).strip()
    return ""


def _head_owners() -> dict[str, str]:
    owners: dict[str, str] = {}
    for match in _HEAD_OWNER.finditer(_HEAD_SCHEMA.read_text(encoding="utf-8")):
        owners.setdefault(match.group(1), match.group(2))
    return owners


def _migration(revision_prefix: str) -> Any:
    path = next(_VERSIONS.glob(f"{revision_prefix}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_lint_{path.stem}", path)
    assert spec is not None, path
    assert spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ownership_requiring_ddl_runs_under_the_owner_role() -> None:
    """`DROP`·`CREATE OR REPLACE`·`GRANT`/`REVOKE`는 소유자 롤 창 안에 있어야 한다."""
    owners = _head_owners()
    role = _SCHEMA_OWNER
    wrong: list[str] = []

    for statement in _migration("309")._UPGRADE_STATEMENTS:
        head = _sql_head(statement)
        if (set_role := _SET_ROLE.match(head)) is not None:
            role = set_role.group(1)
            continue
        for pattern, operation in (
            (_DROP, "DROP"),
            (_REPLACE, "CREATE OR REPLACE"),
            (_PRIVILEGE, "GRANT/REVOKE"),
        ):
            match = pattern.match(head)
            if match is None:
                continue
            routine = match.group(1)
            owner = owners.get(routine)
            # head에 없으면 이 마이그레이션이 만든 루틴이다 — 만든 롤이 소유자이고,
            # 그 일관성은 아래 `..._transfers_ownership...`가 따로 본다.
            if owner is not None and role != owner:
                wrong.append(f"{operation} {routine}: {role}로 도는데 소유자는 {owner}")

    assert not wrong, (
        "소유권이 필요한 루틴 DDL이 소유자가 아닌 롤로 실행된다:\n  "
        + "\n  ".join(dict.fromkeys(wrong))
        + "\n\n롤은 NOINHERIT라 이 상태는 실행 시점에 `must be owner of ...`으로 죽는다. "
        "해당 사이드카가 자기 `SET ROLE` 창을 열고 끝에서 "
        f"`SET ROLE {_SCHEMA_OWNER}`로 닫게 하라 — 바깥에서 묶으면 목록 순서에 결박된다."
    )


def test_routines_created_by_another_role_transfer_ownership_back() -> None:
    """스키마 소유자로 만든 루틴은 반드시 head 소유자에게 넘겨야 한다."""
    owners = _head_owners()
    role = _SCHEMA_OWNER
    created_by: dict[str, str] = {}
    transferred: dict[str, str] = {}

    for statement in _migration("309")._UPGRADE_STATEMENTS:
        head = _sql_head(statement)
        if (set_role := _SET_ROLE.match(head)) is not None:
            role = set_role.group(1)
            continue
        if (created := _CREATE.match(head)) is not None:
            created_by[created.group(1)] = role
        for transfer in _TRANSFER.finditer(statement):
            transferred[transfer.group(1)] = transfer.group(2)

    stranded = [
        f"{routine}: {maker}가 만드는데 소유자는 {owners[routine]}, 이전 없음"
        for routine, maker in created_by.items()
        if routine in owners
        and maker != owners[routine]
        and transferred.get(routine) != owners[routine]
    ]

    assert not stranded, (
        "만든 롤과 소유자가 다른데 소유권을 넘기지 않는다:\n  "
        + "\n  ".join(stranded)
        + "\n\n새 `CREATE`는 만든 롤을 소유자로 만든다. head가 기대하는 소유자와 다르면 "
        "런타임 권한이 통째로 어긋나고, 다음 마이그레이션의 `CREATE OR REPLACE`가 죽는다."
    )


def test_the_routine_stage_ends_on_the_schema_owner() -> None:
    """루틴 단계가 롤을 흘리면 뒤의 트리거·뷰 재생성이 엉뚱한 롤로 돈다."""
    role = _SCHEMA_OWNER
    for statement in _migration("309")._ROUTINE_STATEMENTS:
        if (set_role := _SET_ROLE.match(_sql_head(statement))) is not None:
            role = set_role.group(1)

    assert role == _SCHEMA_OWNER, (
        f"루틴 단계가 `{role}`로 끝난다. 뒤따르는 트리거 재생성·뷰 재생성이 그 롤로 "
        f"돌게 되고, 그건 이 마이그레이션이 의도한 적 없는 소유권을 만든다. 마지막 "
        f"사이드카가 `SET ROLE {_SCHEMA_OWNER}`로 창을 닫는지 보라."
    )
