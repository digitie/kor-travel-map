"""PR #978 squash 뒤 active/legacy Alembic 경계를 고정한다."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_ACTIVE = _ROOT / "alembic" / "versions"
_LEGACY = _ROOT / "alembic" / "legacy_versions"
_ENV = _ROOT / "alembic" / "env.py"
_BASELINE = _ACTIVE / "0200_schema_baseline.py"
_RECEIPTS = _ACTIVE / "0201_tvn40_curation_receipts.py"
_ROLE_BOOTSTRAP = _ROOT / "docker" / "postgres-role-bootstrap.sh"
_GRAPH = _ROOT / "src" / "kortravelmap" / "_application_migration_graph.json"
_EXPECTED_REVISIONS = (
    "0200_schema_baseline",
    "0201_tvn40_curation_receipts",
    "0202_tvn40_candidate_commands",
    "0203_tvn40_candidate_promotion",
    "0204_tvn40_rule_generation",
    "0205_tvn40_rule_catalog_commands",
    "0206_tvn40_theme_catalog",
    "0207_tvn40_source_catalog",
    "0208_tvn40_provider_seal",
    "0209_tvn40_concierge_catalog",
    "0210_tvn40_provider_ops_cmds",
    "0211_tvn40_cancel_cmds",
    "0212_tvn40_collection_cmds",
    "0213_tvn40_item_cmds",
    "0214_tvn40_import_quarantine",
    "0215_tvn40_import_plans",
    "0216_tvn40_import_item_cmd",
    "0217_tvn40_metadata_check",
    "0218_tvn40_routine_acl",
)
_LEGACY_ARCHIVE_SHA256 = (
    "ae65901c78ea1d38ef6f5b7a7e8532744656e73c79392251452680d35f461e42"
)


def _literal(path: Path, name: str) -> str | tuple[str, ...] | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if isinstance(target, ast.Name) and target.id == name:
            value = ast.literal_eval(node.value)
            assert value is None or isinstance(value, (str, tuple))
            return value
    raise AssertionError(f"{path}: {name} literal이 없다")


def test_active_graph_is_only_0200_to_0218() -> None:
    paths = sorted(_ACTIVE.glob("[0-9]*.py"))
    revisions = tuple(str(_literal(path, "revision")) for path in paths)
    parents = tuple(_literal(path, "down_revision") for path in paths)

    assert revisions == _EXPECTED_REVISIONS
    assert parents == (None, *_EXPECTED_REVISIONS[:-1])
    assert json.loads(_GRAPH.read_text(encoding="utf-8"))["revisions"] == [
        {
            "revision": revision,
            "down_revision": [] if parent is None else [parent],
        }
        for revision, parent in zip(revisions, parents, strict=True)
    ]


def test_active_forward_only_boundary_and_diagnostics_use_squash_revisions() -> None:
    assert _literal(_ENV, "_FORWARD_ONLY_BOUNDARY") == "0200_schema_baseline"
    for path in sorted(_ACTIVE.glob("02*.py")):
        revision = str(_literal(path, "revision"))
        source = path.read_text(encoding="utf-8")
        assert f'"{revision} is forward-only' in source, (
            f"{path.name}: forward-only 진단이 자기 revision을 가리켜야 한다"
        )


def test_active_migrations_share_bootstrap_exact_role_contract() -> None:
    baseline_contract = _literal(_BASELINE, "_APPLICATION_ROLE_ASSERTIONS_SQL")
    receipts_contract = _literal(_RECEIPTS, "_APPLICATION_ROLE_ASSERTIONS_SQL")
    assert isinstance(baseline_contract, str)
    assert baseline_contract == receipts_contract

    bootstrap = _ROLE_BOOTSTRAP.read_text(encoding="utf-8")
    for token in (
        "rolcanlogin OR rolinherit OR rolsuper OR rolcreatedb",
        "OR rolcreaterole OR rolbypassrls OR rolreplication",
        "membership.admin_option",
        "membership.inherit_option",
        "membership.set_option",
        "SELECT * FROM expected EXCEPT SELECT * FROM actual",
        "SELECT * FROM actual EXCEPT SELECT * FROM expected",
    ):
        assert token in baseline_contract
        assert token in bootstrap


def test_legacy_archive_has_exact_109_file_digest() -> None:
    paths = sorted(_LEGACY.glob("[0-9]*.py"))
    payload = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
        f"alembic/legacy_versions/{path.name}\n"
        for path in paths
    ).encode()

    assert len(paths) == 109
    assert hashlib.sha256(payload).hexdigest() == _LEGACY_ARCHIVE_SHA256


def test_active_integration_suite_never_targets_legacy_revision() -> None:
    target_pattern = re.compile(
        r"command\.(?:upgrade|downgrade|stamp)\([^\n]*"
        r"['\"](?:000[1-9]|00[1-9][0-9]|010[0-4])_[a-z0-9_]+['\"]"
    )
    violations = []
    for path in sorted((_ROOT / "tests" / "integration").glob("*.py")):
        if target_pattern.search(path.read_text(encoding="utf-8")):
            violations.append(path.relative_to(_ROOT).as_posix())

    assert violations == [], (
        "0200 이전 revision은 읽기 전용 archive다. active integration에서 실행하지 마라: "
        + ", ".join(violations)
    )
