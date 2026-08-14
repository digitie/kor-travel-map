"""PR #978 squash 뒤 active/legacy Alembic 경계를 고정한다."""

from __future__ import annotations

import ast
import hashlib
import json
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


def _string_constants(tree: ast.Module) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            candidates.setdefault(target.id, set()).add(node.value.value)
    return {name: next(iter(values)) for name, values in candidates.items() if len(values) == 1}


def _resolved_string(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _alembic_command_target_violations(source: str, *, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    constants = _string_constants(tree)
    command_aliases = {"command"}
    direct_command_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "alembic":
            command_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "command"
            )
        elif isinstance(node, ast.Import):
            command_aliases.update(
                alias.asname or alias.name.rsplit(".", 1)[-1]
                for alias in node.names
                if alias.name == "alembic.command"
            )

        elif isinstance(node, ast.ImportFrom) and node.module == "alembic.command":
            direct_command_aliases.update(
                {
                    alias.asname or alias.name: alias.name
                    for alias in node.names
                    if alias.name in {"upgrade", "downgrade", "stamp"}
                }
            )

    def operation_for_callable(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return direct_command_aliases.get(node.id)
        if not isinstance(node, ast.Attribute):
            return None
        if node.attr not in {"upgrade", "downgrade", "stamp"}:
            return None
        owner = node.value
        if isinstance(owner, ast.Name) and owner.id in command_aliases:
            return node.attr
        if (
            isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "alembic"
            and owner.attr == "command"
        ):
            return node.attr
        return None

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        operation = operation_for_callable(node.func)
        command_args = node.args
        if operation is None and node.args:
            is_to_thread = (
                isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread"
            ) or (isinstance(node.func, ast.Name) and node.func.id == "to_thread")
            if is_to_thread:
                operation = operation_for_callable(node.args[0])
                command_args = node.args[1:]
        if operation is None:
            continue
        revision_node = next(
            (
                keyword.value
                for keyword in node.keywords
                if keyword.arg in {"revision", "revisions"}
            ),
            command_args[1] if len(command_args) > 1 else None,
        )
        if revision_node is None:
            violations.append(f"{filename}:{node.lineno}: revision 인자 없음")
            continue
        revision = _resolved_string(revision_node, constants)
        if revision == "head" or revision in _EXPECTED_REVISIONS:
            continue
        call_source = "\n".join(
            source.splitlines()[node.lineno - 1 : node.end_lineno]
        )
        if (
            operation == "stamp"
            and revision == "base"
            and "intentional-squash-boundary-rejection" in call_source
        ):
            continue
        detail = revision if revision is not None else "dynamic/unresolved"
        violations.append(f"{filename}:{node.lineno}: {detail}")
    return violations


def _legacy_module_execution_violations(source: str, *, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    references_legacy = any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "legacy_versions" in node.value
        for node in ast.walk(tree)
    )
    if not references_legacy:
        return []
    return [
        f"{filename}:{node.lineno}: legacy module execution"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"exec_module", "load_module"}
    ]


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
    violations: list[str] = []
    for path in sorted((_ROOT / "tests" / "integration").glob("*.py")):
        relative = path.relative_to(_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        violations.extend(
            _alembic_command_target_violations(source, filename=relative)
        )
        violations.extend(_legacy_module_execution_violations(source, filename=relative))

    assert violations == [], (
        "0200 이전 revision은 읽기 전용 archive다. active integration에서 실행하지 마라: "
        + ", ".join(violations)
    )


def test_legacy_execution_scanner_rejects_multiline_constant_and_wrapper() -> None:
    direct = '''
from alembic import command
LEGACY = "0079_cache_target_writer_drain"
command.upgrade(
    config,
    LEGACY,
)
'''
    wrapper = '''
from alembic import command
def migrate(target: str) -> None:
    command.upgrade(config, target)
migrate("head")
'''
    archive_exec = '''
from pathlib import Path
path = Path("alembic") / "legacy_versions" / "0079.py"
spec.loader.exec_module(module)
'''

    direct_violations = _alembic_command_target_violations(
        direct,
        filename="direct.py",
    )
    wrapper_violations = _alembic_command_target_violations(
        wrapper,
        filename="wrapper.py",
    )
    archive_violations = _legacy_module_execution_violations(
        archive_exec,
        filename="archive.py",
    )
    assert any("0079_cache_target_writer_drain" in row for row in direct_violations)
    assert any("dynamic/unresolved" in row for row in wrapper_violations)
    assert archive_violations == ["archive.py:4: legacy module execution"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            '''
import asyncio
from alembic import command
asyncio.to_thread(command.upgrade, config, "0079_cache_target_writer_drain")
''',
            "0079_cache_target_writer_drain",
        ),
        (
            '''
def migrate() -> None:
    from alembic import command
    command.upgrade(config, "0079_cache_target_writer_drain")
''',
            "0079_cache_target_writer_drain",
        ),
        (
            '''
from alembic.command import upgrade
upgrade(config, "0079_cache_target_writer_drain")
''',
            "0079_cache_target_writer_drain",
        ),
        (
            '''
from alembic import command
command.upgrade(config, "02_not_an_active_revision")
''',
            "02_not_an_active_revision",
        ),
        (
            '''
from alembic import command
command.stamp(config, "base")
''',
            "base",
        ),
    ],
)
def test_legacy_execution_scanner_rejects_indirect_and_unknown_targets(
    source: str, expected: str
) -> None:
    violations = _alembic_command_target_violations(source, filename="bypass.py")
    assert any(expected in row for row in violations)


def test_production_docker_build_context_never_copies_legacy_migrations() -> None:
    for path in sorted((_ROOT / "docker").glob("*.Dockerfile")):
        source = path.read_text(encoding="utf-8")
        assert "COPY alembic ./alembic" not in source
        assert "COPY alembic/legacy_versions" not in source
