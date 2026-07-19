#!/usr/bin/env python3
"""Targeted live helper/executor의 SIGKILL-safe Docker lifecycle supervisor."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PROBE_MESSAGE = (
    "production profile is fail-closed (ADR-066): "
    "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET must be configured while "
    "the public features surface is enabled"
)


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )


def _state(args: argparse.Namespace, action: str, values: list[str]) -> None:
    completed = _run([sys.executable, str(args.state_helper), action, *values])
    if completed.returncode != 0:
        raise RuntimeError("state helper rejected supervisor journal")


def _start_ticks() -> int:
    fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
    if len(fields) < 22:
        raise RuntimeError("process stat shape mismatch")
    return int(fields[21])


def _write_all(descriptor: int, body: bytes) -> None:
    offset = 0
    while offset < len(body):
        offset += os.write(descriptor, body[offset:])


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Supervisor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.pid = os.getpid()
        self.pgid = os.getpgrp()
        self.sid = os.getsid(0)
        self.start_ticks = _start_ticks()
        self.container_id = ""
        self.container_exit: int | None = None
        self.sequence = 0

    def _identity_args(self) -> list[str]:
        return [
            "--pid",
            str(self.pid),
            "--pgid",
            str(self.pgid),
            "--sid",
            str(self.sid),
            "--start-ticks",
            str(self.start_ticks),
        ]

    def active(self, phase: str, status: str) -> None:
        values = [
            "--path",
            str(self.args.active_file),
            "--run-key",
            self.args.run_key,
            "--actor",
            self.args.actor,
            "--attempt",
            str(self.args.attempt),
            "--operation",
            self.args.operation,
            "--phase",
            phase,
            "--status",
            status,
            "--container-name",
            self.args.container_name,
            "--container-id",
            self.container_id,
            *self._identity_args(),
        ]
        if self.container_exit is not None:
            values.extend(("--exit-code", str(self.container_exit)))
        _state(self.args, "write-active", values)

    def lifecycle(self, phase: str, kind: str) -> None:
        self.sequence += 1
        path = self.args.lifecycle_dir / (
            f"{self.args.actor}-{self.args.attempt}-{self.args.operation}-"
            f"{self.sequence:02d}-{phase}.json"
        )
        values = [
            "--path",
            str(path),
            "--actor",
            self.args.actor,
            "--attempt",
            str(self.args.attempt),
            "--kind",
            kind,
            "--operation",
            self.args.operation,
            "--phase",
            phase,
            "--container-name",
            self.args.container_name,
            "--container-id",
            self.container_id,
        ]
        if self.container_exit is not None:
            values.extend(("--exit-code", str(self.container_exit)))
        _state(self.args, "write-lifecycle", values)

    def verify_barrier(self) -> None:
        observed = os.fstat(self.args.barrier_fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != 0
            or observed.st_gid != 0
            or stat.S_IMODE(observed.st_mode) != 0o600
        ):
            raise RuntimeError("unsafe inherited barrier")
        fcntl.flock(self.args.barrier_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def ensure_name_absent(self) -> None:
        observed = _run(
            ["docker", "container", "inspect", "--", self.args.container_name]
        )
        if observed.returncode == 0:
            raise RuntimeError("deterministic container name is occupied")

    def create(self, command: list[str], kind: str) -> None:
        self.lifecycle("claim-pending", kind)
        self.active("create-pending", "active")
        self.ensure_name_absent()
        completed = _run(command, capture=True)
        if completed.returncode != 0:
            raise RuntimeError("docker create failed")
        container_id = completed.stdout.decode("ascii", errors="strict").strip()
        if _CONTAINER_ID_RE.fullmatch(container_id) is None:
            raise RuntimeError("docker create returned invalid CID")
        self.container_id = container_id
        self.lifecycle("created", kind)
        self.active("created", "active")

    def start_wait(self, kind: str) -> int:
        self.lifecycle("start-pending", kind)
        self.active("start-pending", "active")
        if _run(["docker", "start", "--", self.container_id]).returncode != 0:
            raise RuntimeError("docker start failed")
        self.lifecycle("started", kind)
        self.active("started", "active")
        completed = _run(["docker", "wait", "--", self.container_id], capture=True)
        if completed.returncode != 0:
            raise RuntimeError("docker wait failed")
        raw = completed.stdout.decode("ascii", errors="strict").strip()
        if not raw.isdigit() or not 0 <= int(raw) <= 255:
            raise RuntimeError("docker wait returned invalid status")
        self.container_exit = int(raw)
        self.lifecycle("exited", kind)
        self.active("exited", "active")
        return self.container_exit

    def remove(self, kind: str) -> None:
        if self.container_id:
            if (
                _run(
                    ["docker", "container", "rm", "--force", "--", self.container_id]
                ).returncode
                != 0
            ):
                raise RuntimeError("docker container removal failed")
            if (
                _run(["docker", "container", "inspect", "--", self.container_id]).returncode
                == 0
            ):
                raise RuntimeError("container remained after removal")
        self.lifecycle("removed", kind)
        self.active("removed", "active")

    def terminal(self, kind: str, succeeded: bool) -> None:
        self.lifecycle("terminal", kind)
        self.active("terminal", "succeeded" if succeeded else "failed")

    def labels(self) -> list[str]:
        return [
            "--label",
            f"io.kortravelmap.admin-feature-acceptance.run-key={self.args.run_key}",
            "--label",
            f"io.kortravelmap.admin-feature-acceptance.actor={self.args.actor}",
            "--label",
            f"io.kortravelmap.admin-feature-acceptance.attempt={self.args.attempt}",
            "--label",
            f"io.kortravelmap.admin-feature-acceptance.operation={self.args.operation}",
        ]

    def helper(self) -> int:
        inspected = _run(
            ["docker", "inspect", "--", self.args.api_container], capture=True
        )
        if inspected.returncode != 0:
            raise RuntimeError("API runtime inspection failed")
        records = json.loads(inspected.stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise RuntimeError("API runtime inspection shape")
        record = records[0]
        config = record.get("Config")
        networks = record.get("NetworkSettings", {}).get("Networks")
        environment = config.get("Env") if isinstance(config, dict) else None
        if (
            not isinstance(environment, list)
            or not all(
                isinstance(value, str) and "\n" not in value and "\r" not in value
                for value in environment
            )
            or not isinstance(networks, dict)
            or not networks
            or not all(_NETWORK_RE.fullmatch(value) for value in networks)
        ):
            raise RuntimeError("API runtime clone inputs are unsafe")
        env_file = self.args.runtime_dir / f".{self.args.operation}.env"
        descriptor = os.open(
            env_file,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.fchown(descriptor, 0, 0)
            body = ("\n".join(environment) + "\n").encode()
            _write_all(descriptor, body)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            command = [
                "docker",
                "create",
                "--pull=never",
                "--name",
                self.args.container_name,
                *self.labels(),
                "--network",
                "none",
                "--read-only",
                "--security-opt",
                "no-new-privileges",
                "--cap-drop",
                "ALL",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,mode=1777",
                "--env-file",
                str(env_file),
                "--volumes-from",
                f"{self.args.api_container}:ro",
                "--mount",
                f"type=bind,src={self.args.fixture},dst=/opt/admin-feature-live-fixture.py,readonly",
                "--entrypoint",
                "python",
                self.args.image,
                "/opt/admin-feature-live-fixture.py",
                self.args.helper_action,
                "--run-id",
                self.args.run_id,
            ]
            self.create(command, "helper")
        finally:
            try:
                os.unlink(env_file)
                _fsync_directory(env_file.parent)
            except FileNotFoundError:
                pass
        for network in sorted(networks):
            if (
                _run(["docker", "network", "connect", "--", network, self.container_id]).returncode
                != 0
            ):
                raise RuntimeError("helper network attachment failed")
        self.lifecycle("prepared", "helper")
        self.active("prepared", "active")
        status = self.start_wait("helper")
        log = _run(["docker", "logs", "--", self.container_id], capture=True)
        if log.returncode != 0:
            raise RuntimeError("helper output capture failed")
        descriptor = os.open(
            self.args.output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.fchown(descriptor, 0, 0)
            _write_all(descriptor, log.stdout)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.remove("helper")
        return status

    def executor(self) -> int:
        command = [
            "docker",
            "create",
            "--pull=never",
            "--name",
            self.args.container_name,
            *self.labels(),
            "--network",
            "bridge",
            "--ipc",
            "private",
            "--read-only",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,mode=1777",
            "--tmpfs",
            "/root/.cache:rw,nosuid,nodev,noexec,mode=700",
            "--tmpfs",
            "/root/.config:rw,nosuid,nodev,noexec,mode=700",
            "--tmpfs",
            "/root/.npm:rw,nosuid,nodev,noexec,mode=700",
            "--mount",
            f"type=bind,src={self.args.artifact_dir},dst=/evidence",
            "--env",
            "E2E_BASE_URL",
            "--env",
            "E2E_ADMIN_PASSWORD",
            "--env",
            "E2E_LIVE_ALLOW_PROD=1",
            "--env",
            "E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1",
            "--env",
            f"E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID={self.args.run_id}",
            "--env",
            "E2E_C7_EXPECTED_UI_ORIGIN_SHA256",
            "--env",
            "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256",
            "--env",
            "E2E_LIVE_WORKERS=1",
            "--env",
            "PLAYWRIGHT_ARTIFACT_ROOT=/evidence",
            "--env",
            "E2E_STORAGE_STATE=/tmp/admin-feature-acceptance-state.json",
        ]
        if os.environ.get("E2E_ADMIN_USERNAME"):
            command.extend(("--env", "E2E_ADMIN_USERNAME"))
        if self.args.recovery_only:
            command.extend(("--env", "E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY=1"))
        command.extend(
            (
                self.args.image,
                "npm",
                "run",
                "e2e:live",
                "--",
                "e2e/live/admin-feature-acceptance-write.live.spec.ts",
                "--workers=1",
                "--retries=0",
            )
        )
        self.create(command, "executor")
        self.lifecycle("prepared", "executor")
        self.active("prepared", "active")
        status = self.start_wait("executor")
        self.remove("executor")
        return status

    def probe(self) -> int:
        command = [
            "docker",
            "create",
            "--pull=never",
            "--name",
            self.args.container_name,
            *self.labels(),
            "--network",
            "none",
            "--read-only",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--env",
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=probe-admin-0000000000000000000000000000",
            "--env",
            "KOR_TRAVEL_MAP_API_SERVICE_TOKEN=probe-service-00000000000000000000000000",
            "--env",
            "KOR_TRAVEL_MAP_API_PROFILE=production",
            "--env",
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true",
            "--env",
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false",
            "--env",
            "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED=true",
            "--env",
            "KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED=false",
            self.args.image,
        ]
        self.create(command, "probe")
        self.lifecycle("prepared", "probe")
        self.active("prepared", "active")
        status = self.start_wait("probe")
        log = _run(["docker", "logs", "--", self.container_id], capture=True)
        body = (log.stdout + log.stderr).decode("utf-8", errors="strict").strip()
        if log.returncode != 0 or status != 1 or body != _PROBE_MESSAGE:
            raise RuntimeError("API cursor fail-closed probe mismatch")
        _state(
            self.args,
            "write-probe",
            [
                "--path",
                str(self.args.output),
                "--result",
                "cursor-secret-missing",
                "--exit-code",
                "1",
            ],
        )
        self.remove("probe")
        return 0

    def execute(self) -> int:
        self.verify_barrier()
        self.active("intent", "active")
        if self.args.mode == "helper":
            return self.helper()
        if self.args.mode == "executor":
            return self.executor()
        return self.probe()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("helper", "executor", "probe"), required=True)
    parser.add_argument("--actor", choices=("main", "recovery"), required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--barrier-fd", type=int, required=True)
    parser.add_argument("--state-helper", type=Path, required=True)
    parser.add_argument("--active-file", type=Path, required=True)
    parser.add_argument("--lifecycle-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--api-container", default="")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--helper-action", choices=("seed", "cleanup", "audit"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--recovery-only", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    supervisor = Supervisor(args)
    status = 1
    kind = args.mode
    try:
        status = supervisor.execute()
        succeeded = status == 0
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        succeeded = False
        status = 1
        if supervisor.container_id:
            removed = _run(
                ["docker", "container", "rm", "--force", "--", supervisor.container_id]
            )
            if removed.returncode == 0:
                try:
                    supervisor.lifecycle("removed", kind)
                    supervisor.active("removed", "active")
                except (OSError, RuntimeError):
                    pass
    try:
        supervisor.terminal(kind, succeeded)
    except (OSError, RuntimeError):
        return 1
    return status if args.mode != "probe" else (0 if succeeded else 1)


if __name__ == "__main__":
    raise SystemExit(main())
