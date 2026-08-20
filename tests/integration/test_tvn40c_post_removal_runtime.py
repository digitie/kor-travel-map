"""T-VN-40C 물리 제거 뒤 runtime이 실제로 성립하는지 — DB catalog + API 표면.

`contracts/vnext/t-vn-40c-removal-manifest-v1.json`의 `verification` 항목 중 실행 가능한
넷을 저장소 안에 고정한다.

* migrated-head DB catalog zero — 표/트리거/제약/인덱스 **이름**뿐 아니라
  `pg_proc.prosrc` 본문에도 legacy 식별자가 없어야 한다. 이름만 보면 procedure 안에
  남은 `curated_features` 참조를 놓친다.
* `reconcile_runtime_privileges`가 실제 DB와 맞는지 — ACL 표에 없는 relation에 runtime
  권한이 남아 있지 않은지.
* API smoke — 제거된 라우트가 앱에 아예 없고, 잔존 catalog·공개 curation 라우트는 산다.
* curation typed command가 SECURITY DEFINER·command owner·dagster EXECUTE 금지를
  유지하는지 — D4가 procedure를 재작성했으므로 경계가 흘렀는지 본다.

`migrated_session` fixture가 fresh DB를 `head`(= `0225`)까지 올리고
`reconcile_runtime_privileges()`를 실행한 뒤를 본다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

# manifest `static_zero_gate.identifiers` 중 DB catalog에 나타날 수 있는 것들.
_LEGACY_DB_IDENTIFIERS: tuple[str, ...] = (
    "curated_features",
    "curated_feature_detail_snapshots",
    "curated_pinvi_copy_snapshots",
    "legacy_projection_id",
    "sync_curated_feature_collection",
    "set_curation_item_legacy_component_identity",
    "issue_curation_source_rule_decision",
)

# 40C가 지운 라우트 template. 앱에 존재하면 안 된다.
_REMOVED_ROUTE_TEMPLATES: tuple[str, ...] = (
    "/v1/curated-features",
    "/v1/curated-features/{curated_feature_id}",
    "/v1/curated-features/{curated_feature_id}/pinvi-copy",
    "/v1/curated-sources",
    "/v1/curated-themes",
    "/v1/admin/features/curated",
    "/v1/admin/features/curated/{curated_feature_id}",
    "/v1/admin/features/curated/{curated_feature_id}/detail-snapshot",
    "/v1/admin/features/curated/{curated_feature_id}/place-search",
    "/v1/admin/features/curated/{curated_feature_id}/select",
    "/v1/admin/features/curated/{curated_feature_id}/unselect",
)

# 40C 뒤에도 남아야 하는 라우트 template.
_RETAINED_ROUTE_TEMPLATES: tuple[str, ...] = (
    "/v1/curations",
    "/v1/curations/collections",
    "/v1/curations/collections/{collection_id}",
    "/v1/curations/features/{feature_id}",
    "/v1/admin/curated-themes",
    "/v1/admin/curated-themes/{theme_id}",
    "/v1/admin/curated-sources",
    "/v1/admin/curated-sources/{source_id}",
    "/v1/admin/curated-source-rules",
    "/v1/admin/curated-source-rules/{rule_id}",
    "/v1/admin/curations",
    "/v1/admin/curations/{collection_id}",
    "/v1/service/curation-cutover/identity-mappings",
)


def _app_openapi_paths() -> set[str]:
    """`export_openapi.py`와 같은 app의 **OpenAPI 표면**을 본다.

    `app.routes`를 직접 세면 안 된다 — 이 앱은 라우터를 `_IncludedRouter` 37개로
    감싸 두어 top-level route 객체에는 `path`가 없다. 그래서 처음 이 검사를 썼을 때
    잔존 표면 13개가 전부 "사라진" 것으로 보였고, 제거 표면 검사 쪽은 **아무 것도
    안 보면서 초록**이었다. 계약 표면은 생성된 spec이 정본이다.
    """
    from kortravelmap.api.app import app

    return set(app.openapi()["paths"])


def test_route_sets_and_the_app_surface_are_not_empty() -> None:
    """목록이 비거나 표면을 못 읽으면 아래 검사가 자명하게 통과한다."""
    assert len(_REMOVED_ROUTE_TEMPLATES) == 11
    assert len(_RETAINED_ROUTE_TEMPLATES) == 13
    assert not set(_REMOVED_ROUTE_TEMPLATES) & set(_RETAINED_ROUTE_TEMPLATES)
    paths = _app_openapi_paths()
    assert len(paths) > 100, f"OpenAPI 표면이 너무 작다: {len(paths)}"
    assert "/v1/features" in paths


def test_removed_routes_are_absent_from_the_app() -> None:
    """제거된 라우트는 410/404가 아니라 **애초에 없다**."""
    paths = _app_openapi_paths()
    still_mounted = sorted(p for p in _REMOVED_ROUTE_TEMPLATES if p in paths)
    assert not still_mounted, f"40C가 지운 라우트가 아직 mount돼 있다: {still_mounted}"


def test_retained_routes_survive_the_removal() -> None:
    """제거가 잔존 표면까지 같이 걷어내지 않았는지 — 과잉 삭제 검출."""
    paths = _app_openapi_paths()
    missing = sorted(p for p in _RETAINED_ROUTE_TEMPLATES if p not in paths)
    assert not missing, f"남아야 할 라우트가 사라졌다: {missing}"


async def test_db_catalog_has_no_legacy_object_names(
    migrated_session: AsyncSession,
) -> None:
    """표·뷰·트리거·제약·인덱스 이름에 legacy 식별자가 없다."""
    found: list[str] = []
    for identifier in _LEGACY_DB_IDENTIFIERS:
        rows = await migrated_session.execute(
            text(
                """
                SELECT 'relation' AS kind, n.nspname || '.' || c.relname AS name
                FROM pg_catalog.pg_class AS c
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND c.relname LIKE '%' || :ident || '%'
                UNION ALL
                SELECT 'trigger', t.tgname
                FROM pg_catalog.pg_trigger AS t
                WHERE NOT t.tgisinternal AND t.tgname LIKE '%' || :ident || '%'
                UNION ALL
                SELECT 'constraint', con.conname
                FROM pg_catalog.pg_constraint AS con
                WHERE con.conname LIKE '%' || :ident || '%'
                UNION ALL
                SELECT 'column', a.attrelid::regclass::text || '.' || a.attname
                FROM pg_catalog.pg_attribute AS a
                JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                WHERE a.attnum > 0 AND NOT a.attisdropped
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND a.attname LIKE '%' || :ident || '%'
                """
            ),
            {"ident": identifier},
        )
        found.extend(f"{kind}:{name} [{identifier}]" for kind, name in rows)
    assert not found, "migrated head DB에 legacy catalog object가 남았다:\n" + "\n".join(found)


async def test_db_routine_bodies_have_no_legacy_identifier(
    migrated_session: AsyncSession,
) -> None:
    """`pg_proc.prosrc` 본문까지 본다 — 이름만 보면 procedure 안의 참조를 놓친다."""
    found: list[str] = []
    for identifier in _LEGACY_DB_IDENTIFIERS:
        rows = await migrated_session.execute(
            text(
                """
                SELECT n.nspname || '.' || p.proname
                FROM pg_catalog.pg_proc AS p
                JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND p.prosrc LIKE '%' || :ident || '%'
                """
            ),
            {"ident": identifier},
        )
        found.extend(f"{row[0]} [{identifier}]" for row in rows)
    assert not found, "procedure 본문에 legacy 식별자가 남았다:\n" + "\n".join(found)


async def test_runtime_privileges_table_matches_the_database(
    migrated_session: AsyncSession,
) -> None:
    """ACL 표 밖의 feature relation에 runtime 권한이 남지 않았다.

    `reconcile_runtime_privileges`는 fixture가 이미 실행했다. 여기서는 그 결과를 DB에
    되물어, 표에서 지운 relation의 GRANT가 실제로 사라졌는지 확인한다 — 표만 고치고
    DB에 GRANT가 남으면 lint는 초록인데 경계는 열려 있다.
    """
    from kortravelmap.infra import runtime_privileges

    # `_runtime_relation_grants`가 권한을 주는 경로는 넷이다. 표 두 개만 세면
    # column-level `_CORE_FEATURE_GRANTS`로 권한을 받는 protected 표가 전부
    # "미선언"으로 잡혀 검사가 늘 red다.
    declared = (
        set(runtime_privileges._FEATURE_TABLE_PRIVILEGES)  # noqa: SLF001
        | set(runtime_privileges._FEATURE_VIEW_PRIVILEGES)  # noqa: SLF001
        | set(runtime_privileges._PROTECTED_FEATURE_TABLES)  # noqa: SLF001
        | set(runtime_privileges._ROUTE_AREA_RUNTIME_INSERT_COLUMNS)  # noqa: SLF001
    )
    rows = await migrated_session.execute(
        text(
            """
            SELECT DISTINCT c.relname
            FROM pg_catalog.pg_class AS c
            JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'feature'
              AND c.relkind IN ('r', 'p', 'v')
              AND (
                has_table_privilege('ktm_feature_runtime', c.oid, 'SELECT')
                OR has_table_privilege('ktm_feature_runtime', c.oid, 'INSERT')
                OR has_table_privilege('ktm_feature_runtime', c.oid, 'UPDATE')
                OR has_table_privilege('ktm_feature_runtime', c.oid, 'DELETE')
              )
            """
        )
    )
    granted = {row[0] for row in rows}
    undeclared = sorted(granted - declared)
    assert not undeclared, (
        "ACL 표에 없는데 runtime 권한이 남은 feature relation: " f"{undeclared}"
    )


async def test_curation_command_procedures_keep_their_owner_and_fence(
    migrated_session: AsyncSession,
) -> None:
    """curation typed command가 40C 뒤에도 SECURITY DEFINER + dagster EXECUTE 금지인지.

    40C는 legacy procedure를 지우면서 canonical command 정의도 재작성했다(D4).
    재작성이 `SECURITY DEFINER`나 소유자를 흘리면 권한 경계가 조용히 열린다 —
    `reconcile_runtime_privileges`는 표 권한만 보므로 여기서 잡는다.
    """
    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT p.proname,
                       pg_get_userbyid(p.proowner) AS owner,
                       p.prosecdef AS security_definer,
                       has_function_privilege(
                         'ktm_feature_dagster_runtime', p.oid, 'EXECUTE'
                       ) AS dagster_execute
                FROM pg_catalog.pg_proc AS p
                JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
                WHERE n.nspname = 'feature'
                  AND p.proname LIKE '%curation%command%'
                ORDER BY p.proname
                """
            )
        )
    ).mappings().all()

    assert len(rows) >= 10, f"curation command procedure가 너무 적다: {len(rows)}"

    bad_owner = [r["proname"] for r in rows if r["owner"] != "ktm_curation_command_owner"]
    assert not bad_owner, f"소유자가 command owner가 아닌 procedure: {bad_owner}"

    reachable = [r["proname"] for r in rows if r["dagster_execute"]]
    assert not reachable, f"dagster runtime이 EXECUTE 가능한 command: {reachable}"

    # `claim_*_effect`는 command 본문이 부르는 내부 helper라 SECDEF가 아니다.
    not_definer = sorted(
        r["proname"]
        for r in rows
        if not r["security_definer"] and not r["proname"].startswith("claim_")
    )
    assert not not_definer, f"SECURITY DEFINER가 아닌 command: {not_definer}"
