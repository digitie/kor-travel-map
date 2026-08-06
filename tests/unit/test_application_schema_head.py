"""후보 API image의 정적 application schema head contract 회귀."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
_COMMAND_PATH = ROOT / "docker" / "application-schema-head.py"
_GENERATOR_PATH = ROOT / "scripts" / "generate_application_migration_graph.py"
_GRAPH_PATH = ROOT / "src" / "kortravelmap" / "_application_migration_graph.json"


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _command_module() -> ModuleType:
    return _module("test_application_schema_head_command", _COMMAND_PATH)


def _generator_module() -> ModuleType:
    return _module("test_application_migration_graph_generator", _GENERATOR_PATH)


def _package_root(tmp_path: Path, payload: Mapping[str, object]) -> Path:
    site_packages = tmp_path / "site-packages"
    package_root = site_packages / "kortravelmap"
    package_root.mkdir(parents=True)
    (package_root / "_application_migration_graph.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return site_packages


@pytest.mark.unit
def test_application_head_reads_only_installed_package_graph(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cwd의 decoy graph가 아닌 candidate Python prefix의 artifact만 읽는다."""
    command = _command_module()
    candidate_payload = {
        "schema": "kor-travel-map.application-migration-graph.v1",
        "revisions": [
            {"revision": "candidate_root", "down_revision": []},
            {"revision": "candidate_head", "down_revision": ["candidate_root"]},
        ],
    }
    site_packages = _package_root(tmp_path, candidate_payload)
    decoy_root = tmp_path / "decoy" / "kortravelmap"
    decoy_root.mkdir(parents=True)
    (decoy_root / "_application_migration_graph.json").write_text(
        json.dumps(
            {
                "schema": "kor-travel-map.application-migration-graph.v1",
                "revisions": [{"revision": "decoy", "down_revision": []}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(decoy_root.parent)
    monkeypatch.setattr(
        command.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_packages), "platlib": str(site_packages)},
    )

    assert command.main(["head"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "schema": "kor-travel-map.application-head.v1",
        "head": "candidate_head",
    }


@pytest.mark.unit
def test_application_head_never_executes_migration_module_top_level(
    tmp_path: Path,
) -> None:
    """graph 생성은 dangerous module import가 아니라 AST literal parse여야 한다."""
    generator = _generator_module()
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_side_effect.py").write_text(
        "revision = 'root'\n"
        "down_revision = None\n"
        "raise RuntimeError('migration module was executed')\n",
        encoding="utf-8",
    )
    (versions / "0002_dynamic.py").write_text(
        "revision: str = 'head'\n"
        "down_revision: str = 'root'\n"
        "raise RuntimeError('migration module was executed')\n",
        encoding="utf-8",
    )

    assert generator.build_application_migration_graph(versions) == {
        "schema": "kor-travel-map.application-migration-graph.v1",
        "revisions": [
            {"revision": "root", "down_revision": []},
            {"revision": "head", "down_revision": ["root"]},
        ],
    }


@pytest.mark.unit
def test_application_graph_artifact_matches_literal_source_graph() -> None:
    """새 migration은 immutable installed artifact를 함께 갱신해야 한다."""
    generator = _generator_module()

    assert json.loads(_GRAPH_PATH.read_text(encoding="utf-8")) == (
        generator.build_application_migration_graph(ROOT / "alembic" / "versions")
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("revisions", "error_code"),
    [
        ([], "application_graph_invalid"),
        (
            [
                {"revision": "root", "down_revision": []},
                {"revision": "left", "down_revision": ["root"]},
                {"revision": "right", "down_revision": ["root"]},
            ],
            "application_head_ambiguous",
        ),
        (
            [{"revision": "head", "down_revision": ["unknown"]}],
            "application_graph_invalid",
        ),
        (
            [
                {"revision": "root", "down_revision": []},
                {"revision": "head", "down_revision": ["root"]},
                {"revision": "cycle_a", "down_revision": ["cycle_b"]},
                {"revision": "cycle_b", "down_revision": ["cycle_a"]},
            ],
            "application_graph_invalid",
        ),
    ],
)
def test_application_head_fails_closed_for_invalid_or_ambiguous_graph(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    revisions: list[dict[str, object]],
    error_code: str,
) -> None:
    command = _command_module()
    site_packages = _package_root(
        tmp_path,
        {
            "schema": "kor-travel-map.application-migration-graph.v1",
            "revisions": revisions,
        },
    )
    monkeypatch.setattr(
        command.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_packages)},
    )

    assert command.main(["head"]) == 1

    assert json.loads(capsys.readouterr().err) == {
        "schema": "kor-travel-map.application-head-error.v1",
        "code": error_code,
    }


@pytest.mark.unit
def test_application_head_rejects_arguments_without_reading_the_graph(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _command_module()

    assert command.main(["migrate"]) == 1

    assert json.loads(capsys.readouterr().err) == {
        "schema": "kor-travel-map.application-head-error.v1",
        "code": "invalid_arguments",
    }
