"""430 A/B의 원문 보존·선취득 순서만 검사한다. 실제 paired PG를 대체하지 않는다."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "alembic" / "versions"


def _definition(sql: str, name: str) -> str:
    match = re.search(
        r"CREATE(?: OR REPLACE)? (?:FUNCTION|PROCEDURE) " + re.escape(name) + r"\(", sql
    )
    assert match is not None
    start = match.start()
    delimiter = re.search(r"\bAS (\$[A-Za-z0-9_]*\$)", sql[start:])
    assert delimiter is not None
    tag = delimiter.group(1)
    body_start = start + delimiter.end()
    return sql[start : sql.index(tag + ";", body_start) + len(tag) + 1]


def test_activation_preserves_old_body_except_strict_installer() -> None:
    old = _definition(
        (ROOT / "tests/unit/fixtures/provider_field_activation_429.sql").read_text(),
        "feature.activate_provider_field_policy",
    )
    new = _definition(
        (VERSIONS / "_430_activate_strict_guards.sql").read_text(),
        "feature.activate_provider_field_policy",
    )
    addition = (
        "\n    -- 실제 activation과 같은 TX에서 strict 정의 전체를 설치·검증한다.\n"
        "    PERFORM feature._install_strict_sh_data_guards();"
    )
    assert new.count(addition) == 1
    assert (
        new.replace(addition, "").replace("CREATE OR REPLACE PROCEDURE", "CREATE PROCEDURE", 1)
        == old
    )
    assert (
        new.index("ops.lock_scoped_feature_write_protocol(true)")
        < new.index("feature._install_strict_sh_data_guards()")
        < new.index("feature-curation-write")
    )


def test_common_scope_locks_actual_parent_before_scope_write() -> None:
    new = _definition(
        (VERSIONS / "_430_parent_scope_order.sql").read_text(),
        "ops._lock_scoped_feature_write_scope",
    )
    assert (
        new.index("ops.lock_scoped_feature_write_protocol(p_exclusive)")
        < new.index("FROM provider_sync.provider_datasets")
        < new.index("INSERT INTO ops.feature_write_dataset_scopes")
    )
    parent = new.split("FROM provider_sync.provider_datasets", 1)[1].split("IF NOT FOUND", 1)[0]
    assert "FOR SHARE" in parent
    assert "FOR UPDATE" not in parent
    assert "jsonb_array_length(p_regions)=0" in new
    assert (
        "FROM ops.feature_write_dataset_scopes WHERE provider_dataset_id=p_dataset FOR UPDATE"
        in new
    )


def test_begin_rereads_plan_after_protocol_before_sorted_parents() -> None:
    new = _definition(
        (VERSIONS / "_430_parent_scope_order.sql").read_text(), "ops.begin_scoped_feature_write"
    )
    protocol = new.index("ops.lock_scoped_feature_write_protocol(v_exclusive)")
    fresh_plan = new.index("SELECT * INTO v_plan", protocol)
    participants = new.index("SELECT array_agg(dataset ORDER BY dataset)")
    parent = new.index("FROM provider_sync.provider_datasets")
    scope = new.index("INSERT INTO ops.feature_write_dataset_scopes")
    assert protocol < fresh_plan < participants < parent < scope
    assert "v_plan.exclusive_protocol IS DISTINCT FROM v_exclusive" in new
    assert "cardinality(v_participants)>32" in new
    assert new.count("FOREACH v_dataset IN ARRAY v_participants LOOP") == 2


def test_begin_existing_manifest_apply_and_lease_validation_is_unchanged() -> None:
    old = (VERSIONS / "_411_begin_attempt.sql").read_text()
    new = _definition(
        (VERSIONS / "_430_parent_scope_order.sql").read_text(), "ops.begin_scoped_feature_write"
    )
    anchor = "    v_attempt:=ops._locked_scoped_feature_write_attempt(p_attempt,p_owner);"
    assert new[new.index(anchor) :] == old[old.index(anchor) :].rstrip()
    assert "ops._locked_scoped_feature_write_attempt" in new


def test_sidecars_do_not_change_isolation_or_install_outside_activation() -> None:
    parent = (VERSIONS / "_430_parent_scope_order.sql").read_text()
    activation = (VERSIONS / "_430_activate_strict_guards.sql").read_text()
    assert "SET TRANSACTION" not in parent + activation
    assert parent.count("CREATE OR REPLACE FUNCTION") == 2
    assert activation.count("CREATE OR REPLACE PROCEDURE") == 1
    assert "CREATE TRIGGER" not in parent + activation
