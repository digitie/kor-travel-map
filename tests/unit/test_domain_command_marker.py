"""외부 command durable marker와 restore swap output 보안 경계 테스트."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest

from kortravelmap.infra import domain_command_marker as marker_mod

pytestmark = pytest.mark.unit


def _artifact(root: Path, backup_id: str = "backup-1") -> None:
    artifact = root / backup_id
    for directory in ("meta", "postgres", "rustfs"):
        (artifact / directory).mkdir(parents=True, exist_ok=True)
    files = {
        "postgres/app.dump": b"app",
        "postgres/dagster.dump": b"dagster",
        "rustfs/data.tar.gz": b"rustfs",
    }
    for relative_path, body in files.items():
        (artifact / relative_path).write_bytes(body)
    (artifact / "meta" / "manifest.json").write_text(
        json.dumps({"backup_id": backup_id}),
        encoding="utf-8",
    )
    (artifact / "meta" / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(body).hexdigest()}  {relative_path}\n"
            for relative_path, body in files.items()
        ),
        encoding="utf-8",
    )


def _marker_kwargs(root: Path) -> dict[str, Any]:
    return {
        "command_id": 11,
        "operation": "admin.backup.create",
        "marker_key": "command-11",
        "effect_kind": "create",
        "effect_state": "created",
        "backup_id": "backup-1",
        "input_digest": "a" * 64,
        "output_proof": marker_mod.backup_artifact_output_proof(
            root, "backup-1"
        ),
    }


def _load_swap_writer() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "write-restore-swap-env.py"
    spec = importlib.util.spec_from_file_location("write_restore_swap_env", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_marker_is_create_once_and_reuses_first_completion(tmp_path: Path) -> None:
    _artifact(tmp_path)
    kwargs = _marker_kwargs(tmp_path)

    first = marker_mod.write_domain_command_marker(tmp_path, **kwargs)
    marker_path = tmp_path / ".domain-command-markers" / "command-11.json"
    first_body = marker_path.read_bytes()
    second = marker_mod.write_domain_command_marker(tmp_path, **kwargs)

    assert second == first
    assert marker_path.read_bytes() == first_body
    assert marker_path.stat().st_nlink == 1


def test_marker_rejects_foreign_existing_identity(tmp_path: Path) -> None:
    _artifact(tmp_path)
    kwargs = _marker_kwargs(tmp_path)
    marker_mod.write_domain_command_marker(tmp_path, **kwargs)
    marker_path = tmp_path / ".domain-command-markers" / "command-11.json"
    original = marker_path.read_bytes()

    with pytest.raises(ValueError, match="mismatch"):
        marker_mod.write_domain_command_marker(
            tmp_path,
            **{**kwargs, "input_digest": "b" * 64},
        )

    assert marker_path.read_bytes() == original


def test_marker_rename_completion_survives_post_rename_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifact(tmp_path)
    kwargs = _marker_kwargs(tmp_path)
    original_rename = marker_mod._rename_noreplace

    def _crash_after_rename(directory_fd: int, source: str, destination: str) -> None:
        original_rename(directory_fd, source, destination)
        raise KeyboardInterrupt

    monkeypatch.setattr(marker_mod, "_rename_noreplace", _crash_after_rename)
    with pytest.raises(KeyboardInterrupt):
        marker_mod.write_domain_command_marker(tmp_path, **kwargs)
    monkeypatch.setattr(marker_mod, "_rename_noreplace", original_rename)

    digest = marker_mod.write_domain_command_marker(tmp_path, **kwargs)
    marker_path = tmp_path / ".domain-command-markers" / "command-11.json"
    assert digest == hashlib.sha256(marker_path.read_bytes()).hexdigest()
    assert marker_path.stat().st_nlink == 1


def test_backup_proof_rejects_symlink_and_hardlink_inputs(tmp_path: Path) -> None:
    _artifact(tmp_path)
    manifest = tmp_path / "backup-1" / "meta" / "manifest.json"
    original = manifest.read_bytes()
    manifest.unlink()
    external = tmp_path / "external-manifest"
    external.write_bytes(original)
    manifest.symlink_to(external)

    with pytest.raises(OSError, match="Too many levels"):
        marker_mod.backup_artifact_output_proof(tmp_path, "backup-1")

    manifest.unlink()
    os.link(external, manifest)
    with pytest.raises(PermissionError, match="regular file"):
        marker_mod.backup_artifact_output_proof(tmp_path, "backup-1")


def test_marker_rejects_symlink_destination(tmp_path: Path) -> None:
    _artifact(tmp_path)
    marker_directory = tmp_path / ".domain-command-markers"
    marker_directory.mkdir(mode=0o700)
    target = tmp_path / "foreign"
    target.write_text("foreign", encoding="utf-8")
    (marker_directory / "command-11.json").symlink_to(target)

    with pytest.raises(OSError, match="Too many levels"):
        marker_mod.write_domain_command_marker(
            tmp_path,
            **_marker_kwargs(tmp_path),
        )
    assert target.read_text(encoding="utf-8") == "foreign"


def test_backup_destination_reservation_is_command_owned_and_create_once(
    tmp_path: Path,
) -> None:
    first = marker_mod.reserve_backup_destination(
        tmp_path,
        command_id=41,
        backup_id="reserved-backup",
        input_digest="a" * 64,
    )
    second = marker_mod.reserve_backup_destination(
        tmp_path,
        command_id=41,
        backup_id="reserved-backup",
        input_digest="a" * 64,
    )
    reservation = (
        tmp_path
        / "reserved-backup"
        / ".domain-command-reservation.json"
    )

    assert first == second == hashlib.sha256(reservation.read_bytes()).hexdigest()
    assert reservation.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "reserved-backup").stat().st_mode & 0o777 == 0o700
    assert not list(tmp_path.glob(".reserve-*"))


def test_backup_destination_reservation_rejects_existing_artifact(
    tmp_path: Path,
) -> None:
    _artifact(tmp_path, "custom")

    with pytest.raises(
        (FileExistsError, FileNotFoundError, PermissionError),
    ):
        marker_mod.reserve_backup_destination(
            tmp_path,
            command_id=42,
            backup_id="custom",
            input_digest="b" * 64,
        )

    assert (tmp_path / "custom" / "meta" / "manifest.json").is_file()


def test_backup_destination_reservation_survives_post_rename_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_rename = marker_mod._rename_noreplace

    def _crash_after_rename(directory_fd: int, source: str, destination: str) -> None:
        original_rename(directory_fd, source, destination)
        raise KeyboardInterrupt

    monkeypatch.setattr(marker_mod, "_rename_noreplace", _crash_after_rename)
    with pytest.raises(KeyboardInterrupt):
        marker_mod.reserve_backup_destination(
            tmp_path,
            command_id=43,
            backup_id="reserved-backup",
            input_digest="c" * 64,
        )
    monkeypatch.setattr(marker_mod, "_rename_noreplace", original_rename)

    marker_mod.reserve_backup_destination(
        tmp_path,
        command_id=43,
        backup_id="reserved-backup",
        input_digest="c" * 64,
    )
    assert (
        tmp_path
        / "reserved-backup"
        / ".domain-command-reservation.json"
    ).is_file()


def test_restore_swap_env_is_fixed_secure_and_uri_encoded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _load_swap_writer()
    values = {
        "KOR_TRAVEL_MAP_POSTGRES_USER": "user:name",
        "KOR_TRAVEL_MAP_POSTGRES_PASSWORD": "p@ss/%#word",
        "KOR_TRAVEL_MAP_RESTORE_APP_DB": "app/db",
        "KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB": "dagster/db",
        "KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME": "restore-volume",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    path = writer.write_restore_swap_env(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    app_url = urlsplit(lines[2].split("=", 1)[1])
    dagster_url = urlsplit(lines[3].split("=", 1)[1])

    assert path == tmp_path / ".env.restore-swap"
    assert path.stat().st_mode & 0o777 == 0o600
    assert unquote(app_url.username or "") == values["KOR_TRAVEL_MAP_POSTGRES_USER"]
    assert unquote(app_url.password or "") == values["KOR_TRAVEL_MAP_POSTGRES_PASSWORD"]
    assert unquote(app_url.path.removeprefix("/")) == values[
        "KOR_TRAVEL_MAP_RESTORE_APP_DB"
    ]
    assert unquote(dagster_url.path.removeprefix("/")) == values[
        "KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB"
    ]


def test_restore_swap_env_rejects_symlink_and_untrusted_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _load_swap_writer()
    for name, value in {
        "KOR_TRAVEL_MAP_POSTGRES_USER": "user",
        "KOR_TRAVEL_MAP_POSTGRES_PASSWORD": "password",
        "KOR_TRAVEL_MAP_RESTORE_APP_DB": "app",
        "KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB": "dagster",
        "KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME": "volume",
    }.items():
        monkeypatch.setenv(name, value)
    foreign = tmp_path / "foreign"
    foreign.write_text("foreign", encoding="utf-8")
    (tmp_path / ".env.restore-swap").symlink_to(foreign)

    with pytest.raises(PermissionError, match="not trusted"):
        writer.write_restore_swap_env(tmp_path)
    assert foreign.read_text(encoding="utf-8") == "foreign"

    (tmp_path / ".env.restore-swap").unlink()
    tmp_path.chmod(0o777)
    with pytest.raises(PermissionError, match="root"):
        writer.write_restore_swap_env(tmp_path)
