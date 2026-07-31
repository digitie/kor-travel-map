#!/usr/bin/env python3
"""Docker daemon에 backup/restore domain command의 durable global fence를 둔다."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

FENCE_NAME: Final = "kor-travel-map-maintenance-effect-fence-v1"
SOURCE_REVISION: Final = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
RECONCILIATION_REQUIRED_EXIT: Final = 4
FENCE_COMMAND: Final = (
    "trap '' TERM INT; while :; do sleep 3600; done"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPERATION = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_EFFECT_KIND = re.compile(r"^(create|restore|swap)$")
_MARKER_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_BACKUP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FENCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

_LABEL_PREFIX: Final = "io.kortravelmap.domain-command-fence"
_LABEL_KEYS: Final = (
    "version",
    "source-revision",
    "fence-image-id",
    "effect-token",
    "command-id",
    "operation",
    "effect-kind",
    "input-digest",
    "marker-key",
    "backup-id",
)


@dataclass(frozen=True, slots=True)
class EffectIdentity:
    effect_token: str
    command_id: int
    operation: str
    effect_kind: str
    input_digest: str
    marker_key: str
    backup_id: str

    def labels(self, *, image_id: str) -> dict[str, str]:
        return {
            "version": "1",
            "source-revision": SOURCE_REVISION,
            "fence-image-id": image_id,
            "effect-token": self.effect_token,
            "command-id": str(self.command_id),
            "operation": self.operation,
            "effect-kind": self.effect_kind,
            "input-digest": self.input_digest,
            "marker-key": self.marker_key,
            "backup-id": self.backup_id,
        }


class DockerCommandError(RuntimeError):
    """Docker CLI 자체가 실행되지 않았거나 예상하지 못한 결과를 반환했다."""


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["docker", *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise DockerCommandError(f"docker CLI 실행 실패: {exc}") from exc
    if check and result.returncode != 0:
        raise DockerCommandError(
            f"docker {' '.join(args[:2])} 실패: {result.stderr.strip()}"
        )
    return result


def _inspect(fence_name: str) -> dict[str, Any] | None:
    result = _docker("inspect", fence_name, check=False)
    if result.returncode != 0:
        stderr = result.stderr.lower()
        if "no such" in stderr or "not found" in stderr:
            return None
        raise DockerCommandError(
            f"docker inspect 실패: {result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DockerCommandError("docker inspect JSON 해석 실패") from exc
    if not isinstance(payload, list) or len(payload) != 1:
        raise DockerCommandError("docker inspect가 정확히 한 resource를 반환하지 않음")
    item = payload[0]
    if not isinstance(item, dict):
        raise DockerCommandError("docker inspect resource 형식 오류")
    return item


def _resolve_canonical_image_id(canonical_container: str | None) -> str:
    container = canonical_container
    if container is None:
        result = _docker(
            "compose",
            "--env-file",
            "/dev/null",
            "ps",
            "-q",
            "postgres",
        )
        container = result.stdout.strip()
        if not container or "\n" in container:
            raise DockerCommandError(
                "canonical compose postgres container를 정확히 하나 찾지 못함"
            )
    resource = _inspect(container)
    if resource is None:
        raise DockerCommandError("canonical local container inspect evidence가 없음")
    image_id = str(resource.get("Image", ""))
    if not _IMAGE_ID.fullmatch(image_id):
        raise DockerCommandError("canonical local container의 immutable Image ID가 없음")
    return image_id


def _actual_identity(
    resource: dict[str, Any],
) -> tuple[dict[str, str], str, tuple[str, ...]]:
    config = resource.get("Config")
    state = resource.get("State")
    host_config = resource.get("HostConfig")
    if (
        not isinstance(config, dict)
        or not isinstance(state, dict)
        or not isinstance(host_config, dict)
    ):
        raise DockerCommandError("Docker fence resource의 Config/State/HostConfig가 없음")
    raw_labels = config.get("Labels")
    if not isinstance(raw_labels, dict):
        raw_labels = {}
    labels = {
        key: str(raw_labels.get(f"{_LABEL_PREFIX}.{key}", ""))
        for key in _LABEL_KEYS
    }
    shape_errors: list[str] = []
    image_id = str(resource.get("Image", ""))
    if image_id != labels["fence-image-id"] or not _IMAGE_ID.fullmatch(image_id):
        shape_errors.append("image_id")
    if config.get("User") != "65534:65534":
        shape_errors.append("user")
    if config.get("Entrypoint") != ["/bin/sh"]:
        shape_errors.append("entrypoint")
    if config.get("Cmd") != ["-c", FENCE_COMMAND]:
        shape_errors.append("command")
    if host_config.get("NetworkMode") != "none":
        shape_errors.append("network")
    if host_config.get("ReadonlyRootfs") is not True:
        shape_errors.append("read_only")
    cap_drop = host_config.get("CapDrop")
    if not isinstance(cap_drop, list) or "ALL" not in cap_drop:
        shape_errors.append("cap_drop")
    security_opt = host_config.get("SecurityOpt")
    if (
        not isinstance(security_opt, list)
        or "no-new-privileges" not in security_opt
    ):
        shape_errors.append("no_new_privileges")
    if host_config.get("PidsLimit") != 32:
        shape_errors.append("pids_limit")
    return labels, str(state.get("Status", "unknown")), tuple(shape_errors)


def _reconciliation_required(
    *,
    reason: str,
    fence_name: str,
    expected: EffectIdentity,
    resource: dict[str, Any] | None,
) -> int:
    actual: dict[str, str] | None = None
    resource_status = "missing"
    if resource is not None:
        actual, resource_status, shape_errors = _actual_identity(resource)
        if shape_errors:
            actual = {**actual, "shape-errors": ",".join(shape_errors)}
    diagnostic = {
        "code": "BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED",
        "reason": reason,
        "fence_name": fence_name,
        "resource_status": resource_status,
        "expected": {
            "effect_token": expected.effect_token,
            "command_id": expected.command_id,
            "operation": expected.operation,
            "effect_kind": expected.effect_kind,
            "input_digest": expected.input_digest,
            "source_revision": SOURCE_REVISION,
        },
        "actual": actual,
    }
    print(
        "KTM_EFFECT_RECONCILIATION_REQUIRED "
        + json.dumps(diagnostic, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
    )
    return RECONCILIATION_REQUIRED_EXIT


def acquire(
    identity: EffectIdentity,
    *,
    fence_name: str,
    canonical_container: str | None,
    adopt_existing_exact: bool,
) -> int:
    resource = _inspect(fence_name)
    if resource is not None:
        actual, status, shape_errors = _actual_identity(resource)
        expected_existing = identity.labels(
            image_id=actual["fence-image-id"]
        )
        if (
            adopt_existing_exact
            and actual == expected_existing
            and status == "running"
            and not shape_errors
        ):
            return 0
        return _reconciliation_required(
            reason="다른 실행 또는 이전 crash의 global Docker fence가 이미 존재함",
            fence_name=fence_name,
            expected=identity,
            resource=resource,
        )

    image_id = _resolve_canonical_image_id(canonical_container)
    expected_labels = identity.labels(image_id=image_id)
    labels = expected_labels
    create_args = [
        "create",
        "--pull=never",
        "--name",
        fence_name,
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
        "--entrypoint",
        "/bin/sh",
    ]
    for key in _LABEL_KEYS:
        create_args.extend(
            ["--label", f"{_LABEL_PREFIX}.{key}={labels[key]}"]
        )
    create_args.extend(
        [
            image_id,
            "-c",
            FENCE_COMMAND,
        ]
    )
    created = _docker(*create_args, check=False)
    if created.returncode != 0:
        # create 경합 또는 create 응답 유실은 inspect evidence로만 판단한다.
        raced = _inspect(fence_name)
        if raced is not None:
            return _reconciliation_required(
                reason="Docker fence create 결과가 경합 또는 응답 유실로 모호함",
                fence_name=fence_name,
                expected=identity,
                resource=raced,
            )
        raise DockerCommandError(
            f"docker create 실패: {created.stderr.strip()}"
        )
    resource = _inspect(fence_name)
    if resource is None:
        raise DockerCommandError("docker create 성공 뒤 fence inspect evidence가 없음")
    actual, _, shape_errors = _actual_identity(resource)
    if actual != labels or shape_errors:
        return _reconciliation_required(
            reason="새 Docker fence label이 요청 identity와 다름",
            fence_name=fence_name,
            expected=identity,
            resource=resource,
        )
    started = _docker("start", fence_name, check=False)
    if started.returncode != 0:
        return _reconciliation_required(
            reason="Docker fence는 생성됐지만 start 결과가 모호함",
            fence_name=fence_name,
            expected=identity,
            resource=_inspect(fence_name),
        )
    running = _inspect(fence_name)
    if running is None:
        raise DockerCommandError("docker start 성공 뒤 fence inspect evidence가 없음")
    running_labels, status, running_shape_errors = _actual_identity(running)
    if (
        running_labels != labels
        or status != "running"
        or running_shape_errors
    ):
        return _reconciliation_required(
            reason="Docker fence running evidence가 exact identity와 일치하지 않음",
            fence_name=fence_name,
            expected=identity,
            resource=running,
        )
    return 0


def verify(identity: EffectIdentity, *, fence_name: str) -> int:
    resource = _inspect(fence_name)
    if resource is None:
        return _reconciliation_required(
            reason="pre-acquired Docker fence가 없음",
            fence_name=fence_name,
            expected=identity,
            resource=None,
        )
    actual, status, shape_errors = _actual_identity(resource)
    expected = identity.labels(image_id=actual["fence-image-id"])
    if actual != expected or status != "running" or shape_errors:
        return _reconciliation_required(
            reason="pre-acquired Docker fence identity/shape/running evidence 불일치",
            fence_name=fence_name,
            expected=identity,
            resource=resource,
        )
    return 0


def release(identity: EffectIdentity, *, fence_name: str) -> int:
    resource = _inspect(fence_name)
    if resource is None:
        # marker writer 성공 뒤 release 재시도는 idempotent하다.
        return 0
    actual, _, shape_errors = _actual_identity(resource)
    expected = identity.labels(image_id=actual["fence-image-id"])
    if actual != expected or shape_errors:
        return _reconciliation_required(
            reason="foreign/mismatched Docker fence는 해제할 수 없음",
            fence_name=fence_name,
            expected=identity,
            resource=resource,
        )
    removed = _docker("rm", "--force", fence_name, check=False)
    if removed.returncode != 0:
        return _reconciliation_required(
            reason="exact Docker fence 해제 결과가 모호함",
            fence_name=fence_name,
            expected=identity,
            resource=_inspect(fence_name),
        )
    return 0


def _identity(args: argparse.Namespace) -> EffectIdentity:
    if not _HEX64.fullmatch(args.effect_token):
        raise ValueError("effect-token은 64자리 lowercase hex여야 함")
    if args.command_id <= 0:
        raise ValueError("command-id는 양수여야 함")
    if not _OPERATION.fullmatch(args.operation):
        raise ValueError("operation 형식 오류")
    if not _EFFECT_KIND.fullmatch(args.effect_kind):
        raise ValueError("effect-kind 형식 오류")
    if not _HEX64.fullmatch(args.input_digest):
        raise ValueError("input-digest는 64자리 lowercase hex여야 함")
    if not _MARKER_KEY.fullmatch(args.marker_key):
        raise ValueError("marker-key 형식 오류")
    if not _BACKUP_ID.fullmatch(args.backup_id):
        raise ValueError("backup-id 형식 오류")
    if not _FENCE_NAME.fullmatch(args.fence_name):
        raise ValueError("fence-name 형식 오류")
    return EffectIdentity(
        effect_token=args.effect_token,
        command_id=args.command_id,
        operation=args.operation,
        effect_kind=args.effect_kind,
        input_digest=args.input_digest,
        marker_key=args.marker_key,
        backup_id=args.backup_id,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("acquire", "verify", "release"))
    parser.add_argument("--effect-token", required=True)
    parser.add_argument("--command-id", required=True, type=int)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--effect-kind", required=True)
    parser.add_argument("--input-digest", required=True)
    parser.add_argument("--marker-key", required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--fence-name", default=FENCE_NAME)
    parser.add_argument("--canonical-container")
    parser.add_argument("--adopt-existing-exact", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        identity = _identity(args)
        if args.action == "acquire":
            return acquire(
                identity,
                fence_name=args.fence_name,
                canonical_container=args.canonical_container,
                adopt_existing_exact=args.adopt_existing_exact,
            )
        if args.action == "verify":
            return verify(identity, fence_name=args.fence_name)
        return release(identity, fence_name=args.fence_name)
    except (DockerCommandError, ValueError) as exc:
        print(f"docker effect fence error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
