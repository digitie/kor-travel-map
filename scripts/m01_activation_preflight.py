#!/usr/bin/env python3
"""`T-VN-M01` 활성화 전 ACL preflight를 **실측**한다 (설계 문서 §8.3).

`KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true`로 바꾸기 전에, 배포
런타임의 role·membership·relation ACL·routine EXECUTE 분리가 닫힌 manifest와 정확히
같은지 확인한다. 설계 문서
`docs/reports/t-vn-m00-manual-feature-create-design-2026-08-19.md` §8.1~8.3이 정본이다.

## 왜 스크립트인가

§8.2가 **"restore 뒤 동일"**을 요구한다. 즉 이 확인은 활성화 전 한 번이 아니라
restore·rebuild 때마다 다시 돌아야 하는 것이고, 한 번 손으로 세고 마는 것은 계약을
지키지 못한다.

## 무엇을 하지 않는가

권한 probe는 catalog `has_*_privilege`/`pg_has_role`만 쓴다 — **Feature를 만들지 않고
아무것도 쓰지 않는다**(§8.3). 그래서 프로덕션에서 활성화 전에 돌릴 수 있다.

## 사용

    python3 scripts/m01_activation_preflight.py            # 사람이 읽는 표
    python3 scripts/m01_activation_preflight.py --json     # 기계가 읽는 결과

DSN은 `KOR_TRAVEL_MAP_PG_DSN`에서 읽는다. 실패가 하나라도 있으면 exit 1이다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from kortravelmap.infra.db import make_async_engine
from kortravelmap.settings import KorTravelMapSettings

#: 닫힌 manifest의 role 이름. 설계 §8.1.
# ADR-100: 세 LOGIN이 하나로 합쳐졌다. 갈라지는 축은 이제 executor 층뿐이다.
SERVICE_LOGIN = "ktm_feature_service"
SCHEMA_OWNER = "ktm_feature_schema_owner"
MANUAL_PROCEDURE_OWNER = "ktm_manual_feature_procedure_owner"
ADMIN_EXECUTOR = "ktm_manual_feature_admin_executor"
PROVIDER_EXECUTOR = "ktm_feature_create_provider_executor"

#: claim/origin — `_PROTECTED_FEATURE_TABLES`. runtime login은 direct 접근이 없다.
PROTECTED_RELATIONS = (
    "feature.manual_feature_identity_claims",
    "feature.feature_creation_origins",
)
#: wrapper는 API만, generic은 Dagster만 실행한다(§8.1).
WRAPPER_ROUTINE = "create_admin_manual_feature_with_initial_state"
GENERIC_ROUTINE = "create_feature_with_initial_state"


@dataclass(frozen=True)
class Check:
    name: str
    observed: str | None
    expected: str

    @property
    def ok(self) -> bool:
        return self.observed == self.expected


async def _scalar(connection: AsyncConnection, sql: str) -> str | None:
    value = (await connection.execute(text(sql))).scalar_one_or_none()
    return None if value is None else str(value)


async def _role_checks(connection: AsyncConnection) -> list[Check]:
    checks: list[Check] = []
    for role in (MANUAL_PROCEDURE_OWNER, ADMIN_EXECUTOR, PROVIDER_EXECUTOR):
        observed = await _scalar(
            connection,
            "SELECT (NOT rolcanlogin AND NOT rolinherit)::text "
            f"FROM pg_roles WHERE rolname = '{role}'",
        )
        checks.append(Check(f"role.{role}.nologin_noinherit", observed, "true"))
    # membership의 exact option까지 본다 — 옵션이 다르면 우회 경로가 생긴다(§8.1).
    for group, member, admin, inherit, set_option in (
        (MANUAL_PROCEDURE_OWNER, SCHEMA_OWNER, False, False, True),
        (ADMIN_EXECUTOR, SERVICE_LOGIN, False, True, False),
        (PROVIDER_EXECUTOR, SERVICE_LOGIN, False, True, False),
    ):
        observed = await _scalar(
            connection,
            "SELECT (m.admin_option = {admin} AND m.inherit_option = {inherit} "
            "AND m.set_option = {set_option})::text "
            "FROM pg_auth_members m "
            "JOIN pg_roles g ON g.oid = m.roleid "
            "JOIN pg_roles b ON b.oid = m.member "
            f"WHERE g.rolname = '{group}' AND b.rolname = '{member}'".format(
                admin=str(admin).lower(),
                inherit=str(inherit).lower(),
                set_option=str(set_option).lower(),
            ),
        )
        checks.append(Check(f"member.{group}<-{member}.exact_options", observed, "true"))
    # ADR-100: 교차 멤버십 검사는 여기서 사라진다. 통합된 LOGIN은 두 executor 모두의
    # member여야 하므로 "A는 B의 member가 아니다"가 구조적으로 성립할 수 없다. 두
    # executor를 갈라 두는 일은 이제 **grant 층**이 하고, 아래 _routine_checks가 잰다.
    #
    # SET ROLE 검사도 schema owner 쪽 arm만 빠진다: 통합 LOGIN이 migration을 돌려야
    # 하므로 bootstrap이 `ktm_feature_schema_owner`를 `SET TRUE`로 준다. procedure
    # owner로는 여전히 SET ROLE 할 수 없어야 하고, 그 arm은 그대로 힘을 가진다(§8.3).
    for owner in (MANUAL_PROCEDURE_OWNER,):
        observed = await _scalar(
            connection, f"SELECT (NOT pg_has_role('{SERVICE_LOGIN}', '{owner}', 'USAGE'))::text"
        )
        checks.append(Check(f"{SERVICE_LOGIN}.cannot_set_role.{owner}", observed, "true"))
    return checks


async def _relation_checks(connection: AsyncConnection) -> list[Check]:
    """claim/origin의 owner와 direct 접근 부재를 본다.

    `'feature.x'::regclass` 캐스트는 schema USAGE를 요구한다. 이 스크립트는
    `rolinherit=false`인 LOGIN role로도 돌아야 하므로(§8.3이 "두 runtime login을 실제
    DSN으로 접속해" 확인하라고 한다) 캐스트 대신 catalog를 직접 조인해 oid를 얻고,
    oid를 받는 `has_table_privilege` 오버로드를 쓴다. `pg_class`/`pg_namespace`는
    schema 권한과 무관하게 읽힌다.
    """

    checks: list[Check] = []
    for relation in PROTECTED_RELATIONS:
        schema_name, _, relation_name = relation.partition(".")
        locate = (
            "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = '{schema_name}' AND c.relname = '{relation_name}'"
        )
        oid = await _scalar(connection, locate)
        checks.append(Check(f"exists.{relation}", "found" if oid else None, "found"))
        if oid is None:
            continue
        observed = await _scalar(
            connection, f"SELECT relowner::regrole::text FROM pg_class WHERE oid = {oid}"
        )
        checks.append(Check(f"owner.{relation}", observed, SCHEMA_OWNER))
        for grantee in (SERVICE_LOGIN, "public"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                observed = await _scalar(
                    connection,
                    "SELECT (NOT has_table_privilege("
                    f"'{grantee}', {oid}, '{privilege}'))::text",
                )
                checks.append(
                    Check(f"{grantee}.no_{privilege.lower()}.{relation}", observed, "true")
                )
    return checks


async def _routine_checks(connection: AsyncConnection) -> list[Check]:
    """wrapper는 admin executor만, generic은 provider executor만 — PUBLIC은 둘 다 불가(§8.1).

    ADR-100 이전에는 이 분리를 두 LOGIN으로 쟀다. LOGIN이 하나가 되면서 그 축이
    사라졌고, 통합 LOGIN은 두 executor 모두의 member라 login으로는 갈리지 않는다.
    executor 층은 ADR-100이 건드리지 않았고 executor role끼리는 membership이 없으므로
    이 술어가 그 분리를 그대로 이어받는다.
    """

    checks: list[Check] = []
    for routine, admin_execute, provider_execute, owner in (
        (WRAPPER_ROUTINE, "true", "false", MANUAL_PROCEDURE_OWNER),
        (GENERIC_ROUTINE, "false", "true", None),
    ):
        rows = (
            await connection.execute(
                text(
                    "SELECT p.oid::regprocedure::text AS signature, "
                    f"has_function_privilege('{ADMIN_EXECUTOR}', p.oid, 'EXECUTE')::text "
                    "AS admin_side, "
                    f"has_function_privilege('{PROVIDER_EXECUTOR}', p.oid, 'EXECUTE')::text "
                    "AS provider_side, "
                    "has_function_privilege('public', p.oid, 'EXECUTE')::text AS anyone, "
                    "p.proowner::regrole::text AS owner "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    f"WHERE n.nspname = 'feature' AND p.proname = '{routine}'"
                )
            )
        ).mappings().all()
        checks.append(Check(f"routine.{routine}.is_unique", str(len(rows)), "1"))
        if len(rows) != 1:
            continue
        row = rows[0]
        checks.append(
            Check(f"routine.{routine}.admin_executor_execute", str(row["admin_side"]), admin_execute)
        )
        checks.append(
            Check(
                f"routine.{routine}.provider_executor_execute",
                str(row["provider_side"]),
                provider_execute,
            )
        )
        checks.append(Check(f"routine.{routine}.public_execute", str(row["anyone"]), "false"))
        if owner is not None:
            checks.append(Check(f"routine.{routine}.owner", str(row["owner"]), owner))
    return checks


async def run() -> list[Check]:
    settings = KorTravelMapSettings()
    pg_dsn = settings.pg_dsn
    if pg_dsn is None:
        raise RuntimeError("DSN이 없습니다: KOR_TRAVEL_MAP_PG_DSN")
    engine = make_async_engine(pg_dsn)
    try:
        async with engine.connect() as connection:
            return [
                *await _role_checks(connection),
                *await _relation_checks(connection),
                *await _routine_checks(connection),
            ]
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="기계가 읽는 결과")
    arguments = parser.parse_args()

    checks = asyncio.run(run())
    failed = [check for check in checks if not check.ok]
    if arguments.json:
        json.dump(
            {
                "checks": [
                    {
                        "name": check.name,
                        "observed": check.observed,
                        "expected": check.expected,
                        "ok": check.ok,
                    }
                    for check in checks
                ],
                "counts": {"total": len(checks), "failed": len(failed)},
                "result": "passed" if not failed else "failed",
                "version": 1,
            },
            sys.stdout,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        for check in checks:
            mark = "OK " if check.ok else "!! "
            print(f"{mark}{check.name}: observed={check.observed} expected={check.expected}")
        print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
