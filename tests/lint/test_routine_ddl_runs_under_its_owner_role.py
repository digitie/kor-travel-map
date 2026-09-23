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

다만 head 소유자는 **문장열이 끝난 뒤의** 상태다. 한 마이그레이션 안에서 루틴이
만들어지고 소유자가 옮겨 가는 구간에서는 그 시점의 소유자를 따라가야 한다 —
`CREATE`는 만든 롤을, `ALTER ... OWNER TO`는 지정한 롤을 소유자로 만든다.

## 어떤 revision을 보는가

`_UPGRADE_STATEMENTS`를 가진 **전부**다. 2026-09-19까지 세 검사가 모두
`_migration("309")`에 결박돼 있었고, 312가 더한 역할 창 넷을 한 문장도 보지 않았다.
검사가 대상을 번호로 고르면, 새 대상이 생겨도 검사는 자라지 않는다.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
from typing import Any, Final

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: 마이그레이션이 문장열을 시작하는 롤. `_UPGRADE_STATEMENTS`의 첫 문장이다.
_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: 아직 `SET ROLE`을 하지 않은 구간의 실행 주체. 실제 이름은 배포마다 다르고
#: 관리 DSN의 로그인 롤이다 — 이름이 아니라 "어떤 소유자와도 같지 않다"가 요점이다.
_LOGIN_ROLE: Final[str] = "(login role)"

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
#: `CREATE TRIGGER ... EXECUTE FUNCTION f()` — 생성 시점에 `f`의 EXECUTE가 필요하다.
_TRIGGER = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?(?:CONSTRAINT\s+)?TRIGGER\s+[a-z_0-9]+"
    r".*?EXECUTE\s+(?:FUNCTION|PROCEDURE)\s+([a-z_]+\.[a-z_0-9]+)\s*\(",
    re.IGNORECASE | re.DOTALL,
)
#: `GRANT EXECUTE ON FUNCTION f(...) TO role` — `DO` 블록 안의 문자열 이어붙이기도 본다.
_GRANT_EXECUTE = re.compile(
    r"GRANT\s+EXECUTE\s+ON\s+(?:FUNCTION|PROCEDURE)\s+([a-z_]+\.[a-z_0-9]+)"
    r"\s*\([^)]*\)\s*TO\s+([a-z_]+)",
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


def _sql_text(statement: str) -> str:
    """plpgsql `EXECUTE '...' '...'`의 문자열 이어붙이기를 편다.

    조건부 GRANT는 `DO` 블록 안에서 두 문자열로 쪼개져 오므로, 그대로는 하나의
    `GRANT EXECUTE ... TO role`로 읽히지 않는다. 따옴표 사이의 공백·줄바꿈만
    제거해 **한 문장으로 보이게** 만든다.
    """

    return re.sub(r"'\s*'", "", statement)


def _head_owners() -> dict[str, str]:
    owners: dict[str, str] = {}
    for match in _HEAD_OWNER.finditer(_HEAD_SCHEMA.read_text(encoding="utf-8")):
        owners.setdefault(match.group(1), match.group(2))
    return owners


def _migration(revision_prefix: str) -> Any:
    path = next(_VERSIONS.glob(f"{revision_prefix}_*.py"))
    return _load(path)


def _load(path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"_lint_{path.stem}", path)
    assert spec is not None, path
    assert spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statement_groups(attribute: str) -> list[tuple[str, tuple[str, ...]]]:
    """`attribute`를 가진 **모든** 마이그레이션의 (이름, 문장열).

    **번호를 박지 않는다.** 2026-09-19까지 이 모듈의 세 검사는 전부
    `_migration("309")`에 결박돼 있었고, 312가 새 역할 창 넷과 `CREATE OR REPLACE`
    다섯을 더했는데 **한 문장도 보지 않았다**(2026-09-20 적대 리뷰). 검사가 대상을
    이름으로 고르면, 새 대상이 생겨도 검사는 자라지 않는다.
    """

    groups: list[tuple[str, tuple[str, ...]]] = []
    for path in sorted(_VERSIONS.glob("[0-9]*.py")):
        module = _load(path)
        statements = getattr(module, attribute, None)
        if isinstance(statements, tuple | list) and all(
            isinstance(statement, str) for statement in statements
        ):
            groups.append((path.name, tuple(statements)))
    return groups


def test_the_scan_sees_more_than_one_migration_and_many_statements() -> None:
    """**하한을 '본 것'에 건다.** 대상이 줄면 위 검사들이 조용히 항진명제가 된다."""

    groups = _statement_groups("_UPGRADE_STATEMENTS")
    if not groups and len(list(_VERSIONS.glob("[0-9]*.py"))) <= 1:
        pytest.skip(
            "active graph에 baseline root 하나뿐이다 — 그 revision은 덤프를 통째로 "
            "적용하므로 role을 바꿔 가며 DDL을 내는 단계가 없다. migration이 "
            "추가되면 이 검사는 자동으로 다시 활성화된다."
        )
    assert len(groups) >= 2, (
        f"`_UPGRADE_STATEMENTS`를 가진 마이그레이션을 {len(groups)}개만 찾았다 — "
        "상수 이름이 바뀌었거나 import가 깨졌다."
    )
    total = sum(len(statements) for _, statements in groups)
    assert total >= 100, (
        f"문장을 {total}개만 봤다 — 사이드카 해석이 깨지면 이 숫자가 먼저 무너진다."
    )
    windows = sum(
        1
        for _, statements in groups
        for statement in statements
        if _SET_ROLE.match(_sql_head(statement)) is not None
    )
    assert windows >= 10, (
        f"`SET ROLE` 창을 {windows}개만 봤다 — 롤 창 검사가 볼 것이 거의 없다."
    )


def test_ownership_requiring_ddl_runs_under_the_owner_role() -> None:
    """`DROP`·`CREATE OR REPLACE`·`GRANT`/`REVOKE`는 소유자 롤 창 안에 있어야 한다.

    ## 소유자는 문장열 위에서 **움직인다**

    head 소유자와 곧바로 대조하면 멀쩡한 마이그레이션을 빨갛게 만든다. 실제
    PostgreSQL이 보는 것은 **그 문장 시점의** 소유자다:

    - 새 `CREATE`는 **만든 롤을 소유자로 만든다.** 302가 `ops`에 프로시저를
      스키마 소유자로 만들고 곧바로 `REVOKE`/`GRANT`를 내는 것은 정당하다 —
      그 순간 소유자가 스키마 소유자이기 때문이다. head 소유자는 그 뒤의
      `OWNER TO`가 만든 **나중 상태**다.
    - `ALTER ... OWNER TO`는 그 자리에서 소유자를 옮긴다.

    ## `SET ROLE` 이전은 판정하지 않는다

    마이그레이션은 관리 DSN의 로그인 롤로 시작한다. 304처럼 `SET ROLE`을 한 번도
    하지 않는 revision은 처음부터 끝까지 그 롤로 돌고, 그 롤은 소유자 검사를
    지난다. 판정을 시작하는 시점은 마이그레이션이 **스스로 창을 좁힌** 첫
    `SET ROLE`이다.

    2026-09-20에 이 검사를 309 결박에서 전 revision으로 넓히면서 위 둘을 함께
    옮겼다. 넓히기만 하고 모델을 그대로 두면 302·304가 거짓 양성으로 올라온다 —
    그리고 거짓 양성은 다음 사람이 검사를 좁히게 만든다.
    """

    head_owners = _head_owners()
    wrong: list[str] = []

    for name, statements in _statement_groups("_UPGRADE_STATEMENTS"):
        role: str | None = None
        owner_now: dict[str, str] = {}
        for statement in statements:
            head = _sql_head(statement)
            if (set_role := _SET_ROLE.match(head)) is not None:
                role = set_role.group(1)
                continue
            if (created := _CREATE.match(head)) is not None and role is not None:
                owner_now[created.group(1)] = role
            for transfer in _TRANSFER.finditer(statement):
                owner_now[transfer.group(1)] = transfer.group(2)
            if role is None:
                # 아직 로그인(관리) 롤이다 — 소유자 검사를 지난다.
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
                owner = owner_now.get(routine, head_owners.get(routine))
                # 이 마이그레이션이 만들지도 않았고 head에도 없으면 관측 대상이 아니다.
                if owner is not None and role != owner:
                    wrong.append(
                        f"{name}: {operation} {routine}: {role}로 도는데 소유자는 {owner}"
                    )

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
    created_by: dict[str, str] = {}
    transferred: dict[str, str] = {}

    for _name, statements in _statement_groups("_UPGRADE_STATEMENTS"):
        # `SET ROLE` 이전은 관리 DSN의 로그인 롤이다. 그 롤이 만들면 소유자가
        # 로그인 롤이 되므로 head 소유자와 **반드시** 다르고, 이전이 필수다 —
        # 그래서 스키마 소유자로 가정하지 않고 구별되는 이름을 쓴다.
        role = _LOGIN_ROLE
        for statement in statements:
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
    # `_ROUTINE_STATEMENTS`는 309에만 있는 이름이다. 이름이 아니라 **있는 것을**
    # 전부 본다 — 다른 revision이 같은 단계를 두면 자동으로 따라온다.
    groups = _statement_groups("_ROUTINE_STATEMENTS")
    if not groups and len(list(_VERSIONS.glob("[0-9]*.py"))) <= 1:
        pytest.skip(
            "active graph에 baseline root 하나뿐이다 — 그 revision은 덤프를 통째로 "
            "적용하므로 role을 바꿔 가며 DDL을 내는 단계가 없다. migration이 "
            "추가되면 이 검사는 자동으로 다시 활성화된다."
        )
    assert groups, "`_ROUTINE_STATEMENTS` 단계를 가진 마이그레이션이 없다."

    leaking: list[str] = []
    for name, statements in groups:
        role = _SCHEMA_OWNER
        for statement in statements:
            if (set_role := _SET_ROLE.match(_sql_head(statement))) is not None:
                role = set_role.group(1)
        if role != _SCHEMA_OWNER:
            leaking.append(f"{name}: {role}")

    assert not leaking, (
        f"루틴 단계가 스키마 소유자가 아닌 롤로 끝난다: {leaking}. 뒤따르는 트리거 "
        "재생성·뷰 재생성이 그 롤로 돌게 되고, 그건 이 마이그레이션이 의도한 적 없는 "
        f"소유권을 만든다. 마지막 사이드카가 `SET ROLE {_SCHEMA_OWNER}`로 창을 "
        "닫는지 보라."
    )


def test_trigger_creation_can_execute_its_trigger_function() -> None:
    """`CREATE TRIGGER`는 **생성 시점에** 트리거 함수의 EXECUTE를 요구한다.

    갓 만든 DB에서는 이것이 보이지 않는다. 함수의 ACL이 기본값이라
    (`pg_proc.proacl IS NULL`) PUBLIC이 EXECUTE를 갖고 아무 롤이나 통과하기
    때문이다. 그래서 통합 스위트도 fresh 300 경로도 초록을 준다.

    런타임 권한 조정기는 `REVOKE ALL ON FUNCTION ... FROM PUBLIC`을 낸다.
    **조정기가 한 번이라도 돈 DB**(운영·격리 live)는 ACL이 명시 목록으로 굳어
    PUBLIC 경로가 사라지고, 거기서는 같은 문장이 `42501`로 죽는다.

    2026-09-20에 312가 그렇게 막혔다 — 통합 1,173건이 전부 초록인 채로. 격리 live
    스택에 **제자리 업그레이드**로 올려 보고서야 드러났다. (지금의 운영 배포는 DB를
    다시 만들고 올리므로 그 경로에서는 ACL이 기본값이라 걸리지 않는다. 막히는 것은
    제자리 업그레이드이고, 그 경로는 실재한다.) 이 검사가 그 자리를 문장열에서
    미리 본다.

    통과 조건은 둘 중 하나다:

    - 트리거를 만드는 롤이 그 함수의 **소유자**이거나,
    - 같은 마이그레이션이 그 앞에서 **그 롤에게 EXECUTE를 부여**했거나,
    - 그 마이그레이션이 체인에서 그 함수를 **처음 선언했거나**(그 순간 ACL이
      기본값이라 PUBLIC이 EXECUTE를 갖고, 조정기는 아직 돌지 않았다 —
      301·306·307이 이 모양이고 그래서 정당하다).

    세 번째 조건을 "`CREATE OR REPLACE`가 아닌 `CREATE`"로 좁히면 안 된다. 301은
    **없던 함수**를 `CREATE OR REPLACE`로 만든다 — 없던 것을 replace하면 보존할
    ACL도 없으므로 그것도 기본값이다. 반대로 이미 있는 함수를 `CREATE OR REPLACE`
    하면 ACL이 **보존**되므로 좁혀진 채로 남는다. 그 둘을 가르는 것은 문법이 아니라
    **체인에서 처음인가**이고, 그래서 전 마이그레이션을 훑어 최초 선언자를 구한다.
    """

    owners = _head_owners()
    groups = _statement_groups("_UPGRADE_STATEMENTS")

    #: 루틴 → 체인에서 그것을 **처음 선언한** 마이그레이션. 거기서는 ACL이 기본값이다.
    first_declarer: dict[str, str] = {}
    for name, statements in groups:
        for statement in statements:
            head = _sql_head(statement)
            for pattern in (_CREATE, _REPLACE):
                if (declared := pattern.match(head)) is not None:
                    first_declarer.setdefault(declared.group(1), name)

    wrong: list[str] = []
    seen = 0

    for name, statements in groups:
        role: str | None = None
        granted: set[tuple[str, str]] = set()
        for statement in statements:
            expanded = _sql_text(statement)
            head = _sql_head(expanded)
            if (set_role := _SET_ROLE.match(head)) is not None:
                role = set_role.group(1)
                continue
            for grant in _GRANT_EXECUTE.finditer(expanded):
                # **그 부여가 가능한 부여여야 한다.** EXECUTE를 줄 수 있는 것은
                # 함수의 소유자뿐이다. 이 조건이 없으면, 소유자가 아닌 창에서 낸
                # (그래서 42501로 죽을) GRANT를 검사가 곧이곧대로 믿고 뒤따르는
                # `CREATE TRIGGER`에 초록을 준다 — 2026-09-20 돌연변이 실험이 그
                # 구멍을 드러냈다. `DO` 블록 안의 GRANT는 `_PRIVILEGE` 검사의 눈에
                # 띄지 않으므로(문장이 `DO $...$`로 시작한다) 여기서 함께 본다.
                if role is not None and role == owners.get(grant.group(1)):
                    granted.add((grant.group(1), grant.group(2)))
            trigger = _TRIGGER.match(head)
            if trigger is None:
                continue
            seen += 1
            routine = trigger.group(1)
            owner = owners.get(routine)
            if owner is None:
                continue
            effective = role if role is not None else _LOGIN_ROLE
            if (
                effective == owner
                or (routine, effective) in granted
                or first_declarer.get(routine) == name
            ):
                continue
            wrong.append(
                f"{name}: CREATE TRIGGER가 {routine}을 {effective}로 부는데 "
                f"소유자는 {owner}이고 EXECUTE 부여도 없다"
            )

    if seen == 0 and len(list(_VERSIONS.glob("[0-9]*.py"))) <= 1:
        pytest.skip(
            "active graph에 baseline root 하나뿐이다 — 그 revision은 덤프를 통째로 "
            "적용하므로 role을 바꿔 가며 DDL을 내는 단계가 없다. migration이 "
            "추가되면 이 검사는 자동으로 다시 활성화된다."
        )
    assert seen >= 1, (
        "`CREATE TRIGGER ... EXECUTE FUNCTION`을 한 건도 찾지 못했다 — "
        "정규식이 낡았으면 이 검사는 항진명제가 된다."
    )
    assert not wrong, (
        "트리거를 만드는 롤이 그 트리거 함수를 실행할 수 없다: "
        + " / ".join(wrong)
        + " — 갓 만든 DB는 함수 ACL이 기본값이라 통과하지만, 런타임 권한 조정기가 "
        "PUBLIC의 EXECUTE를 걷어낸 DB(운영)에서는 `42501`로 죽는다. 함수 소유자 "
        "창에서 만들거나, 그 창에서 EXECUTE를 빌리고 되돌려 놓을 것."
    )
