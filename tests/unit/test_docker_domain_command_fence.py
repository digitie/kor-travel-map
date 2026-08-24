"""Durable Docker domain-command fence의 identity/shape fail-close 테스트."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "docker-domain-command-fence.py"
IMAGE_ID = "sha256:" + "a" * 64


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "docker_domain_command_fence",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _identity(module: ModuleType, *, token: str = "1" * 64) -> Any:
    return module.EffectIdentity(
        effect_token=token,
        command_id=17,
        operation="admin.backup.create",
        effect_kind="create",
        input_digest="2" * 64,
        marker_key="command-17",
        backup_id="backup-17",
    )


def _resource(
    module: ModuleType,
    identity: Any,
    *,
    status: str = "running",
    read_only: bool = True,
) -> dict[str, Any]:
    labels = {
        f"{module._LABEL_PREFIX}.{key}": value
        for key, value in identity.labels(image_id=IMAGE_ID).items()
    }
    return {
        "Image": IMAGE_ID,
        "Config": {
            "Labels": labels,
            "User": "65534:65534",
            "Entrypoint": ["/bin/sh"],
            "Cmd": ["-c", module.FENCE_COMMAND],
        },
        "State": {"Status": status},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": read_only,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "PidsLimit": 32,
        },
    }


@pytest.mark.unit
def test_foreign_fence_is_reported_without_canonical_service_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    expected = _identity(module)
    foreign = _identity(module, token="3" * 64)
    monkeypatch.setattr(
        module,
        "_inspect",
        lambda _name: _resource(module, foreign),
    )
    lookup = pytest.fail
    monkeypatch.setattr(module, "_resolve_canonical_image_id", lookup)

    result = module.acquire(
        expected,
        fence_name="test-fence",
        canonical_container=None,
        adopt_existing_exact=True,
    )

    assert result == module.RECONCILIATION_REQUIRED_EXIT


@pytest.mark.unit
def test_prepared_retry_adopts_only_exact_running_hardened_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    identity = _identity(module)
    monkeypatch.setattr(
        module,
        "_inspect",
        lambda _name: _resource(module, identity),
    )
    monkeypatch.setattr(
        module,
        "_resolve_canonical_image_id",
        pytest.fail,
    )

    result = module.acquire(
        identity,
        fence_name="test-fence",
        canonical_container=None,
        adopt_existing_exact=True,
    )

    assert result == 0


@pytest.mark.unit
def test_shape_mismatch_is_never_adopted_or_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    identity = _identity(module)
    resource = _resource(module, identity, read_only=False)
    monkeypatch.setattr(module, "_inspect", lambda _name: resource)
    docker = pytest.fail
    monkeypatch.setattr(module, "_docker", docker)

    assert (
        module.acquire(
            identity,
            fence_name="test-fence",
            canonical_container=None,
            adopt_existing_exact=True,
        )
        == module.RECONCILIATION_REQUIRED_EXIT
    )
    assert (
        module.release(identity, fence_name="test-fence")
        == module.RECONCILIATION_REQUIRED_EXIT
    )


@pytest.mark.unit
def test_fresh_fence_uses_local_image_id_and_locked_down_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    identity = _identity(module)
    resource: dict[str, Any] | None = None
    calls: list[tuple[str, ...]] = []

    def _inspect(_name: str) -> dict[str, Any] | None:
        return resource

    def _docker(
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal resource
        del check
        calls.append(args)
        if args[0] == "create":
            resource = _resource(module, identity, status="created")
        elif args[0] == "start":
            assert resource is not None
            resource["State"]["Status"] = "running"
        return subprocess.CompletedProcess(["docker", *args], 0, "", "")

    monkeypatch.setattr(module, "_inspect", _inspect)
    monkeypatch.setattr(
        module,
        "_resolve_canonical_image_id",
        lambda _container: IMAGE_ID,
    )
    monkeypatch.setattr(module, "_docker", _docker)

    assert (
        module.acquire(
            identity,
            fence_name="test-fence",
            canonical_container="canonical",
            adopt_existing_exact=False,
        )
        == 0
    )
    create = calls[0]
    for expected in (
        "--pull=never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--pids-limit",
        "32",
    ):
        assert expected in create
    assert IMAGE_ID in create
