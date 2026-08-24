"""`300` root와 retired Alembic cohort의 실행 경계를 고정한다."""

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
_RETIRED = _ROOT / "alembic" / "retired_versions" / "0200-0236"
_ENV = _ROOT / "alembic" / "env.py"
_BASELINE = _ACTIVE / "300_schema_baseline.py"
_ROLE_BOOTSTRAP = _ROOT / "docker" / "postgres-role-bootstrap.sh"
_PRE_SQUASH_REVISIONS = _ROOT / "docker" / "pre-squash-revisions.txt"
_GRAPH = _ROOT / "src" / "kortravelmap" / "_application_migration_graph.json"
_EXPECTED_REVISIONS = ("300",)
#: `alembic_version.version_num`의 컬럼 폭(alembic 기본값).
_ALEMBIC_VERSION_NUM_LENGTH = 32
_LEGACY_ARCHIVE_SHA256 = (
    "ae65901c78ea1d38ef6f5b7a7e8532744656e73c79392251452680d35f461e42"
)


def _string_constants(tree: ast.Module) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    invalid: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            invalid.add(node.arg)
            continue
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            candidates.setdefault(target.id, set()).add(node.value.value)
        else:
            invalid.add(target.id)
    return {
        name: next(iter(values))
        for name, values in candidates.items()
        if len(values) == 1 and name not in invalid
    }


def _resolved_string(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolved_string(node.left, constants)
        right = _resolved_string(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _alembic_command_target_violations(source: str, *, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    constants = _string_constants(tree)
    command_aliases = {"command"}
    alembic_aliases = {"alembic"}
    direct_command_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "alembic":
            command_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "command"
            )
        elif isinstance(node, ast.Import):
            alembic_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "alembic"
            )
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
            and owner.value.id in alembic_aliases
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
        if operation is None:
            escaped = [
                (index, candidate)
                for index, candidate in enumerate(node.args)
                if operation_for_callable(candidate) is not None
            ]
            if len(escaped) == 1:
                index, candidate = escaped[0]
                operation = operation_for_callable(candidate)
                command_args = node.args[index + 1 :]
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
        if "intentional-squash-boundary-rejection" in call_source:
            continue
        detail = revision if revision is not None else "dynamic/unresolved"
        violations.append(f"{filename}:{node.lineno}: {detail}")
    return violations


def _legacy_module_execution_violations(source: str, *, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    constants = _string_constants(tree)
    references_retired = any(
        (value := _resolved_string(node, constants)) is not None
        and ("legacy_versions" in value or "retired_versions" in value)
        for node in ast.walk(tree)
    )
    if not references_retired:
        return []
    return [
        f"{filename}:{node.lineno}: legacy module execution"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_module_execution_call(node)
    ]


def _is_module_execution_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id in {"exec_module", "load_module"}
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in {"exec_module", "load_module"}
    if not (
        isinstance(node.func, ast.Call)
        and isinstance(node.func.func, ast.Name)
        and node.func.func.id == "getattr"
        and len(node.func.args) >= 2
    ):
        return False
    method = node.func.args[1]
    return isinstance(method, ast.Constant) and method.value in {"exec_module", "load_module"}


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


def test_revision_identifiers_fit_alembic_version_column() -> None:
    """revision id는 `alembic_version.version_num varchar(32)`에 들어가야 한다.

    길면 migration이 **DB에 닿아서야** `StringDataRightTruncationError`로 죽는다 —
    unit/ruff/mypy는 전부 green이고 integration(PostGIS 컨테이너)에서만 드러나므로
    피드백이 가장 늦은 축이다. 실제로 `0224`가 40자로 들어왔다가 여기서 걸렸다.
    """
    too_long = {
        revision: len(revision)
        for revision in (
            str(_literal(path, "revision")) for path in sorted(_ACTIVE.glob("[0-9]*.py"))
        )
        if len(revision) > _ALEMBIC_VERSION_NUM_LENGTH
    }
    assert not too_long, (
        f"revision id가 varchar({_ALEMBIC_VERSION_NUM_LENGTH})를 넘는다: {too_long}"
    )


def test_active_graph_has_only_the_300_root() -> None:
    paths = sorted(_ACTIVE.glob("[0-9]*.py"))
    revisions = tuple(str(_literal(path, "revision")) for path in paths)
    parents_by_revision = {
        str(_literal(path, "revision")): _literal(path, "down_revision") for path in paths
    }

    assert revisions == _EXPECTED_REVISIONS
    assert parents_by_revision == {"300": None}
    assert json.loads(_GRAPH.read_text(encoding="utf-8"))["revisions"] == [
        {"revision": "300", "down_revision": []}
    ]


def test_active_forward_only_boundary_allows_only_exact_handoff() -> None:
    assert _literal(_ENV, "_BASELINE_300_REVISION") == "300"
    assert (
        _literal(_ENV, "_BASELINE_300_HANDOFF_SOURCE")
        == "0236_tvn41s_compaction_drained"
    )
    source = _ENV.read_text(encoding="utf-8")
    assert "generic Alembic stamp is unsupported" in source
    assert "300_schema_baseline is forward-only" in source
    assert "stamp_baseline_300_after_purge" in source
    assert "script._stamp_revs" not in source

    baseline_source = _BASELINE.read_text(encoding="utf-8")
    assert "300_schema_baseline is forward-only" in baseline_source


def test_active_migrations_share_bootstrap_exact_role_contract() -> None:
    baseline_contract = _literal(_BASELINE, "_FINAL_APPLICATION_ROLE_ASSERTIONS_SQL")
    assert isinstance(baseline_contract, str)

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

    final_phase_roles = (
        "ktm_manual_feature_procedure_owner",
        "ktm_manual_feature_admin_executor",
        "ktm_feature_create_provider_executor",
        "ktm_feature_request_procedure_owner",
        "ktm_feature_request_service_executor",
        "ktm_feature_request_admin_executor",
        "ktm_manual_provider_dedup_procedure_owner",
        "ktm_manual_provider_dedup_detector_executor",
        "ktm_manual_provider_dedup_admin_executor",
        "ktm_feature_reference_reconciliation_service_executor",
    )
    for role in final_phase_roles:
        assert f"'{role}'" in baseline_contract
        assert f"'{role}'" in bootstrap
    assert (
        "baseline-300 bootstrap found an unexpected application role membership edge"
        in bootstrap
    )
    assert "baseline-300 bootstrap requires a fresh DB" in bootstrap


def test_legacy_archive_has_exact_109_file_digest() -> None:
    paths = sorted(_LEGACY.glob("[0-9]*.py"))
    payload = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
        f"alembic/legacy_versions/{path.name}\n"
        for path in paths
    ).encode()

    assert len(paths) == 109
    assert hashlib.sha256(payload).hexdigest() == _LEGACY_ARCHIVE_SHA256


def test_pre_squash_revision_manifest_matches_archive_exactly() -> None:
    archived_revisions = sorted(
        str(_literal(path, "revision")) for path in _LEGACY.glob("[0-9]*.py")
    )
    manifest_revisions = _PRE_SQUASH_REVISIONS.read_text(encoding="utf-8").splitlines()

    assert manifest_revisions == archived_revisions
    assert len(manifest_revisions) == len(set(manifest_revisions)) == 109


def test_retired_0200_to_0236_manifest_matches_archive_exactly() -> None:
    manifest = (_RETIRED / "manifest.sha256").read_text(encoding="utf-8").splitlines()
    paths = sorted(_RETIRED.glob("[0-9]*.py"))
    expected = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in paths
    ]
    revisions = tuple(str(_literal(path, "revision")) for path in paths)

    assert manifest == expected
    assert len(revisions) == len(set(revisions)) == 37
    assert revisions[0] == "0200_schema_baseline"
    assert revisions[-1] == "0236_tvn41s_compaction_drained"


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
        "retired Alembic revision은 읽기 전용 archive다. active integration에서 실행하지 마라: "
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
        (
            '''
from asyncio import to_thread as run_in_thread
from alembic import command
run_in_thread(command.upgrade, config, "0079_cache_target_writer_drain")
''',
            "0079_cache_target_writer_drain",
        ),
        (
            '''
import alembic as a
a.command.upgrade(config, "0079_cache_target_writer_drain")
''',
            "0079_cache_target_writer_drain",
        ),
        (
            '''
from alembic import command
TARGET = "head"
def migrate(TARGET: str) -> None:
    command.upgrade(config, TARGET)
migrate("0079_cache_target_writer_drain")
''',
            "dynamic/unresolved",
        ),
        (
            '''
from alembic import command
loop.run_in_executor(None, command.upgrade, config, "0079_cache_target_writer_drain")
''',
            "0079_cache_target_writer_drain",
        ),
        (
            '''
import functools
from alembic import command
functools.partial(command.upgrade, config, "0079_cache_target_writer_drain")()
''',
            "0079_cache_target_writer_drain",
        ),
        (
            '''
import anyio
from alembic import command
anyio.to_thread.run_sync(command.upgrade, config, "0079_cache_target_writer_drain")
''',
            "0079_cache_target_writer_drain",
        ),
    ],
)
def test_legacy_execution_scanner_rejects_indirect_and_unknown_targets(
    source: str, expected: str
) -> None:
    violations = _alembic_command_target_violations(source, filename="bypass.py")
    assert any(expected in row for row in violations)


@pytest.mark.parametrize(
    "source",
    [
        '''
path = "alembic/" + "legacy_" + "versions/0079.py"
spec.loader.exec_module(module)
''',
        '''
path = "alembic/" + "legacy_" + "versions/0079.py"
getattr(spec.loader, "exec_module")(module)
''',
    ],
)
def test_legacy_execution_scanner_rejects_computed_path_and_getattr(source: str) -> None:
    assert _legacy_module_execution_violations(source, filename="archive.py") == [
        "archive.py:3: legacy module execution"
    ]


def test_production_docker_build_context_never_copies_legacy_migrations() -> None:
    for path in sorted((_ROOT / "docker").glob("*.Dockerfile")):
        source = path.read_text(encoding="utf-8")
        assert "COPY alembic ./alembic" not in source
        assert "COPY alembic/legacy_versions" not in source
        assert "COPY alembic/retired_versions" not in source
    api = (_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")
    assert "COPY alembic/versions ./alembic/versions" in api
