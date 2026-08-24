"""`300` application catalog contract의 빠른 구조 회귀 방지 검사."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_catalog_contract_tracks_relation_access_method_and_named_tablespace() -> None:
    """table AM/tablespace semantic drift가 relation receipt에서 빠지면 안 된다.

    PostgreSQL 기본 설치에는 대개 ``heap`` 하나만 있어 ``ALTER TABLE .. SET ACCESS
    METHOD``의 서로 다른 실제값을 portable integration fixture로 만들 수 없다. 대신
    contract SQL의 canonical fields/join을 직접 고정해 그 축이 다시 빠지는 회귀를 막는다.
    """

    contract = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )
    relation_branch = contract.split("    SELECT\n        'relation',", maxsplit=1)[1].split(
        "    UNION ALL\n    SELECT\n        'composite_relation',", maxsplit=1
    )[0]

    assert "LEFT JOIN pg_catalog.pg_am AS access_method" in relation_branch
    assert "CASE WHEN relation.relam = 0 THEN '<none>'" in relation_branch
    assert "ELSE COALESCE(access_method.amname, '<missing>') END" in relation_branch
    assert "LEFT JOIN pg_catalog.pg_tablespace AS tablespace" in relation_branch
    assert "WHEN relation.reltablespace = 0 THEN '<database-default>'" in relation_branch
    assert "ELSE COALESCE(tablespace.spcname, '<missing>')" in relation_branch
    assert "relation.reltablespace::regclass" not in relation_branch


def test_catalog_contract_tracks_application_and_composite_physical_attribute_slots() -> None:
    """logical column numbering이 숨긴 dropped slot도 receipt에 남긴다."""

    contract = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )
    relation_branch = contract.split("    SELECT\n        'relation',", maxsplit=1)[1].split(
        "    UNION ALL\n    SELECT\n        'composite_relation',", maxsplit=1
    )[0]
    composite_branch = contract.split(
        "    SELECT\n        'composite_relation',", maxsplit=1
    )[1].split("    UNION ALL\n    SELECT\n        'constraint',", maxsplit=1)[0]

    assert "'relation_attribute_slot'" in contract
    assert "'composite_attribute_slot'" in contract
    assert contract.count("attribute.attisdropped::text") >= 2
    assert "relation.relnatts" in relation_branch
    assert "relation.relnatts" in composite_branch


def test_catalog_contract_tracks_row_type_acl_and_composite_layout() -> None:
    """관계 ACL과 별개인 row type 권한·composite attribute를 hash한다."""

    contract = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )

    assert "'row_type'" in contract
    assert "type_row.typrelid <> 0" in contract
    assert "COALESCE(type_row.typacl::text, '')" in contract
    assert "'composite_relation'" in contract
    assert "'composite_attribute'" in contract
    assert "attribute.attnum::text || ':' || attribute.attname" in contract
    assert "AND relation.relkind = 'c'" in contract


def test_catalog_contract_tracks_custom_range_semantics() -> None:
    """range subtype/opclass/canonical/subdiff/multirange link가 receipt에서 빠지지 않는다."""

    contract = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )

    assert "'range_type'" in contract
    assert "range_row.rngsubtype::regtype::text" in contract
    assert "range_opclass_namespace.nspname || '.' || range_opclass.opcname" in contract
    assert "range_row.rngcanonical::regprocedure::text" in contract
    assert "range_row.rngsubdiff::regprocedure::text" in contract
    assert "range_row.rngmultitypid::regtype::text" in contract


def test_catalog_contract_rejects_all_public_semantic_residue_axes() -> None:
    """public text-search/operator semantic object가 handoff receipt에서 빠지지 않는다."""

    contract = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )

    for kind in (
        "public_residue_conversion",
        "public_residue_opfamily",
        "public_residue_opclass",
        "public_residue_amop",
        "public_residue_amproc",
        "public_residue_ts_config",
        "public_residue_ts_config_map",
        "public_residue_ts_dictionary",
        "public_residue_ts_parser",
        "public_residue_ts_template",
        "public_residue_transform",
    ):
        assert f"'{kind}'" in contract

    for catalog in (
        "pg_catalog.pg_conversion",
        "pg_catalog.pg_opfamily",
        "pg_catalog.pg_opclass",
        "pg_catalog.pg_amop",
        "pg_catalog.pg_amproc",
        "pg_catalog.pg_ts_config",
        "pg_catalog.pg_ts_config_map",
        "pg_catalog.pg_ts_dict",
        "pg_catalog.pg_ts_parser",
        "pg_catalog.pg_ts_template",
        "pg_catalog.pg_transform",
    ):
        assert catalog in contract


def test_catalog_contract_binds_public_alembic_exception_shape() -> None:
    """stamp 대상인 public Alembic table은 이름 예외가 아닌 full receipt여야 한다."""

    contract = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )
    migration = (_ROOT / "alembic/versions/300_schema_baseline.py").read_text(
        encoding="utf-8"
    )
    handoff = (
        _ROOT / "docker/transition-application-schema-0236-to-300.py"
    ).read_text(encoding="utf-8")

    assert "'public_alembic_version_contract'" in contract
    public_alembic_contract = contract.split(
        "'public_alembic_version_contract'", maxsplit=1
    )[1].split("'public_residue_routine'", maxsplit=1)[0]
    for field in (
        "'attribute_slots'",
        "'columns'",
        "'constraints'",
        "'indexes'",
        "'policies'",
        "'rules'",
        "'triggers'",
        "'row_type'",
    ):
        assert field in contract
    for field in ("'grantable'", "'grantee'", "'grantor'", "'privilege'"):
        assert field in public_alembic_contract
    assert "FROM aclexplode(type_row.typacl)" in public_alembic_contract
    assert "'array_type'" in public_alembic_contract
    assert "FROM aclexplode(type_array.typacl)" in public_alembic_contract
    assert "type_array.typelem::regtype::text" in public_alembic_contract
    assert "type_row.typrelid = relation.oid" in public_alembic_contract
    assert "'attribute_slot_count', relation.relnatts" in contract
    assert "WHEN relation.reltablespace = 0 THEN '<database-default>'" in contract
    assert "table_access_method.amname" in contract
    assert "index_access_method.amname" in contract
    assert "pg_catalog.pg_index" in contract
    assert "pg_catalog.pg_trigger" in contract
    assert "pg_catalog.pg_rewrite" in contract
    assert "pg_catalog.pg_policy" in contract

    assert "public.alembic_version contract is not exact" in migration
    assert "index_relation.relname = 'alembic_version_pkc'" in migration
    assert "attribute.attname <> 'version_num'" in migration
    assert "object.relnatts = 1" in migration
    assert "row_type.typrelid = object.oid" in migration
    assert "row_type.typacl IS NULL" in migration
    assert "array_type.typacl IS NULL" in migration
    assert "array_type.typelem = row_type.oid" in migration
    assert "privilege.grantor = object.relowner" in migration
    assert "attribute.attisdropped" in migration
    assert "table_access_method.amname = 'heap'" in migration
    assert "index_access_method.amname = 'btree'" in migration
    assert "index_relation.reltablespace = 0" in migration
    assert "NOT trigger.tgisinternal" in migration
    assert "rule.rulename <> '_RETURN'" in migration
    assert "object.relacl IS NOT NULL" in migration
    assert "GRANT SELECT ON TABLE public.alembic_version TO ktm_feature_runtime" in migration
    assert "final public Alembic runtime-read ACL is not exact" in handoff


def test_direct_extension_amop_and_amproc_members_fail_closed() -> None:
    """family member child projection만 지원하고 direct child member는 허용하지 않는다."""

    migration = (_ROOT / "alembic/versions/300_schema_baseline.py").read_text(
        encoding="utf-8"
    )
    handoff = (
        _ROOT / "docker/transition-application-schema-0236-to-300.py"
    ).read_text(encoding="utf-8")
    catalog = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )

    for source in (migration, handoff):
        allowlist = source.split("dependency.classid <> ALL (ARRAY[", maxsplit=1)[1].split(
            "])", maxsplit=1
        )[0]
        assert "pg_catalog.pg_amop" not in allowlist
        assert "pg_catalog.pg_amproc" not in allowlist

    assert "'extension_member_amop'" in catalog
    assert "'extension_member_amproc'" in catalog
    assert catalog.count("member.classid = 'pg_catalog.pg_opfamily'::regclass") >= 3


def test_catalog_contract_and_final_guards_bind_all_procedural_languages() -> None:
    """routine이 없어도 custom procedural language를 receipt/guard가 막는다."""

    migration = (_ROOT / "alembic/versions/300_schema_baseline.py").read_text(
        encoding="utf-8"
    )
    handoff = (
        _ROOT / "docker/transition-application-schema-0236-to-300.py"
    ).read_text(encoding="utf-8")
    catalog = (_ROOT / "alembic/baseline/application-catalog.sql").read_text(
        encoding="utf-8"
    )

    assert "'language'" in catalog
    assert "FROM pg_catalog.pg_language AS language" in catalog
    assert "procedural language inventory must be exact" in migration
    assert "final procedural language inventory is not exact" in handoff
