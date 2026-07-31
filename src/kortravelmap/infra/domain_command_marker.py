"""외부 효과 domain command의 durable completion marker.

marker는 백업 root 아래 전용 ``0700`` 디렉터리에만 저장한다. 파일은 같은
디렉터리에서 ``O_NOFOLLOW | O_EXCL``로 생성하고 file/dir ``fsync`` 뒤 원자적으로
교체한다. 따라서 API process와 host script가 같은 완료 증거 계약을 공유한다.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
)

__all__ = [
    "backup_artifact_output_proof",
    "delete_output_proof",
    "read_domain_command_marker",
    "reserve_backup_destination",
    "restore_output_proof",
    "swap_output_proof",
    "verify_domain_command_marker",
    "write_domain_command_marker",
]

_MARKER_DIRECTORY = ".domain-command-markers"
_RESERVATION_FILE = ".domain-command-reservation.json"
_SAFE_COMPONENT = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
_RENAME_NOREPLACE = 1


def _rename_noreplace(
    directory_fd: int,
    source: str,
    destination: str,
) -> None:
    """Linux ``renameat2(RENAME_NOREPLACE)``로 create-once rename을 수행한다."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = libc.renameat2
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd,
        os.fsencode(source),
        directory_fd,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def _validate_component(value: str, *, label: str) -> None:
    if not value or any(character not in _SAFE_COMPONENT for character in value):
        raise ValueError(f"invalid {label}: {value!r}")


def _read_regular_file_at(directory_fd: int, name: str) -> bytes:
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise PermissionError(f"backup proof input is not a regular file: {name}")
        chunks: list[bytes] = []
        while chunk := os.read(file_fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(file_fd)


def _open_directory_at(directory_fd: int, name: str) -> int:
    opened = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=directory_fd,
    )
    if not stat.S_ISDIR(os.fstat(opened).st_mode):
        os.close(opened)
        raise PermissionError(f"backup proof input is not a directory: {name}")
    return opened


def _read_artifact_relative_file(artifact_fd: int, relative_path: str) -> bytes:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe backup checksum path: {relative_path!r}")
    current_fd = os.dup(artifact_fd)
    try:
        for component in path.parts[:-1]:
            next_fd = _open_directory_at(current_fd, component)
            os.close(current_fd)
            current_fd = next_fd
        return _read_regular_file_at(current_fd, path.parts[-1])
    finally:
        os.close(current_fd)


def _read_secure_regular_path(path: Path) -> bytes:
    directory_fd = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            metadata = os.fstat(file_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise PermissionError("secure output proof file is not trusted")
            chunks: list[bytes] = []
            while chunk := os.read(file_fd, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)


def backup_artifact_output_proof(
    backup_root: Path,
    backup_id: str,
) -> dict[str, object]:
    """검증 완료된 backup artifact의 논리 출력을 고정한다."""

    _validate_component(backup_id, label="backup_id")
    root_fd = os.open(
        backup_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        artifact_fd = _open_directory_at(root_fd, backup_id)
    finally:
        os.close(root_fd)
    try:
        meta_fd = _open_directory_at(artifact_fd, "meta")
        try:
            manifest = _read_regular_file_at(meta_fd, "manifest.json")
            checksums = _read_regular_file_at(meta_fd, "SHA256SUMS")
        finally:
            os.close(meta_fd)
        decoded_manifest = json.loads(manifest)
        if (
            not isinstance(decoded_manifest, dict)
            or decoded_manifest.get("backup_id") != backup_id
        ):
            raise ValueError("backup manifest identity mismatch")
        checksum_count = 0
        for raw_line in checksums.decode("utf-8").splitlines():
            if not raw_line:
                continue
            try:
                expected, relative_path = raw_line.split(maxsplit=1)
            except ValueError as exc:
                raise ValueError("invalid SHA256SUMS entry") from exc
            relative_path = relative_path.removeprefix("*")
            if len(expected) != 64 or any(
                character not in "0123456789abcdef" for character in expected
            ):
                raise ValueError("invalid SHA256SUMS digest")
            actual = hashlib.sha256(
                _read_artifact_relative_file(artifact_fd, relative_path)
            ).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"backup artifact checksum mismatch: {relative_path}"
                )
            checksum_count += 1
        if checksum_count == 0:
            raise ValueError("backup artifact has no checksums")
        return {
            "backup_id": backup_id,
            "checksum_count": checksum_count,
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "sha256sums_sha256": hashlib.sha256(checksums).hexdigest(),
        }
    finally:
        os.close(artifact_fd)


def delete_output_proof(
    *,
    backup_id: str,
    prepared_result: dict[str, Any],
) -> dict[str, object]:
    """삭제 전 동결 snapshot과 삭제 후 부재를 결합한 증거."""

    return {
        "artifact_absent": True,
        "backup_id": backup_id,
        "prepared_result_digest": canonical_domain_command_fingerprint(
            prepared_result
        ),
    }


def restore_output_proof(
    backup_root: Path,
    backup_id: str,
    *,
    app_db: str,
    dagster_db: str,
    rustfs_volume: str,
    verification: str,
) -> dict[str, object]:
    """restore script가 검증한 source와 target identity를 고정한다."""

    if verification not in {"performed", "recovery_performed", "skipped"}:
        raise ValueError(f"invalid restore verification: {verification!r}")
    return {
        "source": backup_artifact_output_proof(backup_root, backup_id),
        "targets": {
            "app_db": app_db,
            "dagster_db": dagster_db,
            "rustfs_volume": rustfs_volume,
        },
        "verification": verification,
    }


def swap_output_proof(
    backup_root: Path,
    backup_id: str,
    *,
    app_db: str,
    dagster_db: str,
    rustfs_volume: str,
    env_file: Path,
    effect_state: str,
    verification: str,
) -> dict[str, object]:
    """swap의 planned/applied 상태와 exact env output을 고정한다."""

    if effect_state not in {"swap_planned", "swap_applied"}:
        raise ValueError(f"invalid swap effect state: {effect_state!r}")
    if verification not in {"performed", "recovery_performed", "skipped"}:
        raise ValueError(f"invalid swap verification: {verification!r}")
    env_body = _read_secure_regular_path(env_file)
    return {
        "effect_state": effect_state,
        "env_file_sha256": hashlib.sha256(env_body).hexdigest(),
        "source": backup_artifact_output_proof(backup_root, backup_id),
        "targets": {
            "app_db": app_db,
            "dagster_db": dagster_db,
            "rustfs_volume": rustfs_volume,
        },
        "verification": verification,
    }


def _marker_body(
    *,
    command_id: int,
    operation: str,
    marker_key: str,
    effect_kind: str,
    effect_state: str,
    backup_id: str,
    input_digest: str,
    output_proof: dict[str, object],
) -> bytes:
    _validate_component(marker_key, label="marker_key")
    _validate_component(backup_id, label="backup_id")
    if command_id <= 0:
        raise ValueError("command_id must be positive")
    if len(input_digest) != 64 or any(
        character not in "0123456789abcdef" for character in input_digest
    ):
        raise ValueError("input_digest must be lowercase SHA-256")
    body = {
        "backup_id": backup_id,
        "command_id": command_id,
        "completed_at": datetime.now(UTC).isoformat(),
        "effect_kind": effect_kind,
        "effect_state": effect_state,
        "input_digest": input_digest,
        "marker_key": marker_key,
        "operation": operation,
        "output_digest": canonical_domain_command_fingerprint(output_proof),
        "output_proof": output_proof,
        "schema_version": 1,
    }
    return (
        json.dumps(
            body,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _open_marker_directory(backup_root: Path) -> int:
    root_fd = os.open(
        backup_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        with suppress(FileExistsError):
            os.mkdir(_MARKER_DIRECTORY, mode=0o700, dir_fd=root_fd)
        directory_fd = os.open(
            _MARKER_DIRECTORY,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=root_fd,
        )
    finally:
        os.close(root_fd)
    metadata = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        os.close(directory_fd)
        raise PermissionError("domain command marker directory is not trusted")
    return directory_fd


def _validate_regular_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise PermissionError("domain command marker file is not trusted")


def _write_all(file_fd: int, body: bytes) -> None:
    remaining = memoryview(body)
    while remaining:
        written = os.write(file_fd, remaining)
        if written <= 0:
            raise OSError("durable command proof write made no progress")
        remaining = remaining[written:]


def _reservation_body(
    *,
    command_id: int,
    backup_id: str,
    input_digest: str,
) -> bytes:
    _validate_component(backup_id, label="backup_id")
    if command_id <= 0:
        raise ValueError("command_id must be positive")
    if len(input_digest) != 64 or any(
        character not in "0123456789abcdef" for character in input_digest
    ):
        raise ValueError("input_digest must be lowercase SHA-256")
    return (
        json.dumps(
            {
                "backup_id": backup_id,
                "command_id": command_id,
                "input_digest": input_digest,
                "schema_version": 1,
            },
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _validate_reserved_destination(
    root_fd: int,
    *,
    backup_id: str,
    expected_body: bytes,
) -> None:
    artifact_fd = _open_directory_at(root_fd, backup_id)
    try:
        metadata = os.fstat(artifact_fd)
        if (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise PermissionError("backup destination reservation is not trusted")
        actual_body = _read_regular_file_at(artifact_fd, _RESERVATION_FILE)
        reservation_metadata = os.stat(
            _RESERVATION_FILE,
            dir_fd=artifact_fd,
            follow_symlinks=False,
        )
        _validate_regular_file(reservation_metadata)
        if actual_body != expected_body:
            raise FileExistsError(
                errno.EEXIST,
                "backup destination is owned by another command",
                backup_id,
            )
    finally:
        os.close(artifact_fd)


def reserve_backup_destination(
    backup_root: Path,
    *,
    command_id: int,
    backup_id: str,
    input_digest: str,
) -> str:
    """backup destination을 command identity에 원자적으로 예약한다.

    빈 임시 디렉터리에 fsync된 reservation을 먼저 쓴 뒤
    ``renameat2(RENAME_NOREPLACE)``로 destination을 공개한다. 따라서 기존
    artifact나 다른 command의 partial output은 새 command가 채택할 수 없다.
    """

    expected_body = _reservation_body(
        command_id=command_id,
        backup_id=backup_id,
        input_digest=input_digest,
    )
    root_fd = os.open(
        backup_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    temporary = f".reserve-{command_id}-{secrets.token_hex(16)}"
    temporary_fd: int | None = None
    reservation_fd: int | None = None
    try:
        os.mkdir(temporary, mode=0o700, dir_fd=root_fd)
        temporary_fd = _open_directory_at(root_fd, temporary)
        reservation_fd = os.open(
            _RESERVATION_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=temporary_fd,
        )
        _validate_regular_file(os.fstat(reservation_fd))
        _write_all(reservation_fd, expected_body)
        os.fsync(reservation_fd)
        os.close(reservation_fd)
        reservation_fd = None
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        try:
            _rename_noreplace(root_fd, temporary, backup_id)
        except FileExistsError:
            cleanup_fd = _open_directory_at(root_fd, temporary)
            try:
                os.unlink(_RESERVATION_FILE, dir_fd=cleanup_fd)
            finally:
                os.close(cleanup_fd)
            os.rmdir(temporary, dir_fd=root_fd)
            _validate_reserved_destination(
                root_fd,
                backup_id=backup_id,
                expected_body=expected_body,
            )
        else:
            _validate_reserved_destination(
                root_fd,
                backup_id=backup_id,
                expected_body=expected_body,
            )
        os.fsync(root_fd)
    except BaseException:
        if reservation_fd is not None:
            os.close(reservation_fd)
        if temporary_fd is not None:
            with suppress(FileNotFoundError):
                os.unlink(_RESERVATION_FILE, dir_fd=temporary_fd)
            os.close(temporary_fd)
        with suppress(FileNotFoundError):
            os.rmdir(temporary, dir_fd=root_fd)
        raise
    finally:
        os.close(root_fd)
    return hashlib.sha256(expected_body).hexdigest()


def write_domain_command_marker(
    backup_root: Path,
    *,
    command_id: int,
    operation: str,
    marker_key: str,
    effect_kind: str,
    effect_state: str,
    backup_id: str,
    input_digest: str,
    output_proof: dict[str, object],
) -> str:
    """marker를 안전하고 durable하게 한 번만 만들고 raw SHA-256을 반환한다."""

    existing_digest = verify_domain_command_marker(
        backup_root,
        command_id=command_id,
        operation=operation,
        marker_key=marker_key,
        effect_kind=effect_kind,
        effect_state=effect_state,
        backup_id=backup_id,
        input_digest=input_digest,
        output_proof=output_proof,
    )
    if existing_digest is not None:
        return existing_digest
    directory_fd = _open_marker_directory(backup_root)
    filename = f"{marker_key}.json"
    temporary = f".{marker_key}.{secrets.token_hex(16)}.tmp"
    file_fd: int | None = None
    try:
        body = _marker_body(
            command_id=command_id,
            operation=operation,
            marker_key=marker_key,
            effect_kind=effect_kind,
            effect_state=effect_state,
            backup_id=backup_id,
            input_digest=input_digest,
            output_proof=output_proof,
        )
        file_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        _validate_regular_file(os.fstat(file_fd))
        remaining = memoryview(body)
        while remaining:
            written = os.write(file_fd, remaining)
            if written <= 0:
                raise OSError("domain command marker write made no progress")
            remaining = remaining[written:]
        os.fsync(file_fd)
        os.close(file_fd)
        file_fd = None
        try:
            _rename_noreplace(directory_fd, temporary, filename)
        except FileExistsError:
            os.unlink(temporary, dir_fd=directory_fd)
            os.fsync(directory_fd)
            existing_digest = verify_domain_command_marker(
                backup_root,
                command_id=command_id,
                operation=operation,
                marker_key=marker_key,
                effect_kind=effect_kind,
                effect_state=effect_state,
                backup_id=backup_id,
                input_digest=input_digest,
                output_proof=output_proof,
            )
            if existing_digest is None:
                raise RuntimeError(
                    "domain command marker creation raced"
                ) from None
            return existing_digest
        _validate_regular_file(
            os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        )
        os.fsync(directory_fd)
    except BaseException:
        if file_fd is not None:
            os.close(file_fd)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory_fd)
        raise
    finally:
        os.close(directory_fd)
    return hashlib.sha256(body).hexdigest()


def read_domain_command_marker(
    backup_root: Path,
    marker_key: str,
) -> tuple[dict[str, Any], str] | None:
    """신뢰 가능한 marker만 읽는다."""

    _validate_component(marker_key, label="marker_key")
    directory = backup_root / _MARKER_DIRECTORY
    try:
        directory_fd = os.open(
            directory,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except FileNotFoundError:
        return None
    try:
        directory_metadata = os.fstat(directory_fd)
        if (
            directory_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            raise PermissionError("domain command marker directory is not trusted")
        try:
            file_fd = os.open(
                f"{marker_key}.json",
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            return None
        try:
            _validate_regular_file(os.fstat(file_fd))
            chunks: list[bytes] = []
            while chunk := os.read(file_fd, 64 * 1024):
                chunks.append(chunk)
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)
    raw = b"".join(chunks)
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("domain command marker must be a JSON object")
    return decoded, hashlib.sha256(raw).hexdigest()


def verify_domain_command_marker(
    backup_root: Path,
    *,
    command_id: int,
    operation: str,
    marker_key: str,
    effect_kind: str,
    effect_state: str,
    backup_id: str,
    input_digest: str,
    output_proof: dict[str, object],
) -> str | None:
    """marker identity와 effect-specific output proof를 검증한다."""

    read = read_domain_command_marker(backup_root, marker_key)
    if read is None:
        return None
    marker, raw_digest = read
    expected = {
        "backup_id": backup_id,
        "command_id": command_id,
        "effect_kind": effect_kind,
        "effect_state": effect_state,
        "input_digest": input_digest,
        "marker_key": marker_key,
        "operation": operation,
        "output_digest": canonical_domain_command_fingerprint(output_proof),
        "output_proof": output_proof,
        "schema_version": 1,
    }
    comparable = {key: marker.get(key) for key in expected}
    if comparable != expected:
        raise ValueError("domain command marker identity or output proof mismatch")
    completed_at = marker.get("completed_at")
    if not isinstance(completed_at, str):
        raise ValueError("domain command marker completion time is missing")
    datetime.fromisoformat(completed_at)
    return raw_digest
