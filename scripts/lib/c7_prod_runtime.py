#!/usr/bin/env python3
"""C7·D2 production live runner의 runtime preflight.

ADR-102 결정 6 이전에는 이 자리에 `c7_prod_attestation.py`가 있었다. 그 모듈은 root
소유 스냅샷, `/etc/kor-travel-map`의 host attestation, Manager 내부 파일(v6 pinned
runtime manifest·v8 rebuild journal)을 다시 파싱해 "지금 떠 있는 것이 핀된 세대다"를
**두 번째로** 증명했다. Manager가 이미 모든 컨테이너 image를 핀된 세대와 대조하므로
그 증명은 걷어냈다(root 대 root, 위협 모델 밖).

남은 것은 **Manager 파일을 한 줄도 읽지 않고** caller env와 `docker inspect`만으로 잴 수
있는 기능 전제다.

- 공개 origin 세 개(UI·API websocket·Dagster GraphQL)가 caller가 선언한 sha256과 같고,
  셋 다 loopback·link-local이 아닌 HTTPS다.
- compose service 일곱이 각각 정확히 한 컨테이너로 running(healthcheck가 있으면 healthy)
  이고, 서로 다른 컨테이너이며, 한 compose project 안에 있다.
- T-VN-15 cursor secret은 Map API에만 있고 모양·전용성이 맞다.
- Map UI 런타임에 admin password hash가 있다.
- Map 네 runtime image의 OCI revision label이 `E2E_C7_EXPECTED_GIT_COMMIT`이다. PinVi
  runtime의 source revision은 Map env가 알 수 없으므로 Manager의 몫이다.
- Playwright executor image가 그 commit과 고정 base로 빌드됐다.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import Final
from urllib.parse import urlsplit, urlunsplit

SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
IMAGE_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_CONTAINER_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")

#: runtime role과 그 compose service 이름을 싣는 caller env. 일곱 전부를 실측한다.
ROLE_SERVICE_ENVS: Final[tuple[tuple[str, str], ...]] = (
    ("map_api", "E2E_C7_MAP_API_SERVICE"),
    ("map_ui", "E2E_C7_UI_SERVICE"),
    ("map_dagster_web", "E2E_C7_DAGSTER_WEB_SERVICE"),
    ("map_dagster_daemon", "E2E_C7_DAGSTER_DAEMON_SERVICE"),
    ("pinvi_api", "E2E_C7_PINVI_API_SERVICE"),
    ("pinvi_web", "E2E_C7_PINVI_WEB_SERVICE"),
    ("pinvi_dagster", "E2E_C7_PINVI_DAGSTER_SERVICE"),
)
PINVI_ROLES: Final = frozenset({"pinvi_api", "pinvi_web", "pinvi_dagster"})

_CURSOR_SECRET_ENV: Final = "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"
_CURSOR_PROTECTED_ENVS: Final = frozenset(
    {
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        "KOR_TRAVEL_MAP_API_VWORLD_API_KEY",
    }
)
_UI_PASSWORD_HASH_PREFIX: Final = "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH="

CommandRunner = Callable[[list[str], str], str]


class RuntimePreflightError(RuntimeError):
    """runtime 전제 위반을 값 노출 없이 나타낸다."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _runtime_environment(items: list[str]) -> dict[str, str]:
    """Docker Env 배열을 중복 없는 exact name/value mapping으로 만든다."""

    values: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise RuntimePreflightError("runtime environment shape")
        name, value = item.split("=", 1)
        if not name or name in values:
            raise RuntimePreflightError("runtime environment shape")
        values[name] = value
    return values


def _validate_cursor_secret_runtime(role: str, environment: Mapping[str, str]) -> None:
    """T-VN-15 cursor secret의 API-only shape·전용성을 값 노출 없이 검증한다."""

    if role != "map_api":
        if _CURSOR_SECRET_ENV in environment:
            raise RuntimePreflightError("cursor secret escaped API runtime")
        return
    cursor = environment.get(_CURSOR_SECRET_ENV)
    if (
        environment.get("KOR_TRAVEL_MAP_API_PROFILE") != "production"
        or environment.get("KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED") != "true"
        or cursor is None
        or len(cursor) < 32
        or any(character.isspace() for character in cursor)
    ):
        raise RuntimePreflightError("cursor secret runtime shape")
    protected = {
        environment[name]
        for name in _CURSOR_PROTECTED_ENVS
        if name in environment and environment[name]
    }
    if cursor in protected:
        raise RuntimePreflightError("cursor secret runtime reuse")


def _public_origin(raw: str, *, websocket: bool = False, require_root_path: bool = True) -> str:
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or (require_root_path and parsed.path not in {"", "/"})
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimePreflightError("unsafe origin")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise RuntimePreflightError("local origin")
    if "%" in host:
        # IPv6 zone-id(scope)는 로컬 인터페이스 스코프라 public origin에 유효하지 않다.
        raise RuntimePreflightError("scoped address")
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_loopback or address.is_link_local or address.is_unspecified
    ):
        raise RuntimePreflightError("unsafe address")
    port = f":{parsed.port}" if parsed.port is not None else ""
    # IPv6 리터럴 host는 netloc 재구성 시 bracket으로 감싸야 `:port`와 모호하지 않다
    # (예: `2001:db8::1` + `:443` → `[2001:db8::1]:443`). 압축 canonical 형으로 정규화해
    # 동등한 IPv6 표기가 같은 origin으로 해시되게 한다. domain/IPv4는 무변경.
    netloc_host = f"[{address.compressed}]" if isinstance(address, ipaddress.IPv6Address) else host
    return urlunsplit(("wss" if websocket else "https", f"{netloc_host}{port}", "", "", ""))


def _canonical_graphql(raw: str) -> str:
    parsed = urlsplit(raw)
    origin = _public_origin(raw, require_root_path=False)
    pathname = parsed.path.rstrip("/")
    pathname = pathname if pathname.endswith("/graphql") else f"{pathname}/graphql"
    return f"{origin}{pathname}"


def verify_caller_origins(environ: Mapping[str, str]) -> None:
    """caller가 선언한 origin sha256 세 개가 실제 URL env의 canonical 형과 같은지 본다."""

    observed = {
        "E2E_C7_EXPECTED_UI_ORIGIN_SHA256": _sha256_text(
            _public_origin(environ["E2E_BASE_URL"])
        ),
        "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256": _sha256_text(
            _public_origin(environ["NEXT_PUBLIC_KOR_TRAVEL_MAP_API"], websocket=True)
        ),
        "E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256": _sha256_text(
            _canonical_graphql(environ["E2E_DAGSTER_URL"])
        ),
    }
    for env_name, value in observed.items():
        if environ[env_name] != value:
            raise RuntimePreflightError("caller origin mismatch")


def _subprocess_output(command: list[str], project_directory: str) -> str:
    completed = subprocess.run(
        command,
        cwd=project_directory,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _single_inspect_record(raw: str, label: str) -> dict[str, object]:
    records = json.loads(raw)
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise RuntimePreflightError(f"{label} inspect shape")
    record: dict[str, object] = records[0]
    return record


def _compose_container(
    service: str,
    project_directory: str,
    run_json: CommandRunner,
) -> dict[str, object]:
    ids_value = run_json(
        [
            "docker",
            "compose",
            "--project-directory",
            project_directory,
            "ps",
            "-q",
            service,
        ],
        project_directory,
    )
    ids = [line.strip() for line in ids_value.splitlines() if line.strip()]
    if len(ids) != 1:
        raise RuntimePreflightError("compose service cardinality")
    return _single_inspect_record(
        run_json(["docker", "inspect", "--", ids[0]], project_directory), "container"
    )


def _image_labels(image_id: str, project_directory: str, run_json: CommandRunner) -> object:
    record = _single_inspect_record(
        run_json(["docker", "image", "inspect", "--", image_id], project_directory), "image"
    )
    config = record.get("Config")
    return config.get("Labels") if isinstance(config, dict) else None


def verify_runtime(
    project_directory: str,
    playwright_base: str,
    *,
    environ: Mapping[str, str],
    run_json: CommandRunner = _subprocess_output,
) -> None:
    """caller env와 실제 Docker runtime을 대조한다. Manager 파일은 읽지 않는다."""

    commit = environ["E2E_C7_EXPECTED_GIT_COMMIT"]
    executor_image = environ["E2E_C7_PLAYWRIGHT_IMAGE"]
    if (
        COMMIT_PATTERN.fullmatch(commit) is None
        or IMAGE_PATTERN.fullmatch(executor_image) is None
    ):
        raise RuntimePreflightError("caller identity shape")
    verify_caller_origins(environ)

    role_services = {role: environ[env_name] for role, env_name in ROLE_SERVICE_ENVS}
    if len(set(role_services.values())) != len(role_services):
        raise RuntimePreflightError("compose services are not distinct")
    observed_containers: set[str] = set()
    compose_projects: set[str] = set()
    for role, service in role_services.items():
        record = _compose_container(service, project_directory, run_json)
        container_id = record.get("Id")
        if (
            not isinstance(container_id, str)
            or _CONTAINER_ID_PATTERN.fullmatch(container_id) is None
        ):
            raise RuntimePreflightError("runtime container identity")
        observed_containers.add(container_id)
        config = record.get("Config")
        state = record.get("State")
        if not isinstance(config, dict) or not isinstance(state, dict):
            raise RuntimePreflightError("runtime inspect")
        health = state.get("Health")
        if (
            state.get("Running") is not True
            or state.get("Paused") is True
            or state.get("Restarting") is True
            or (isinstance(health, dict) and health.get("Status") != "healthy")
        ):
            raise RuntimePreflightError("runtime is not healthy")
        labels = config.get("Labels")
        environment = config.get("Env")
        if (
            not isinstance(labels, dict)
            or labels.get("com.docker.compose.service") != service
            or not isinstance(environment, list)
            or not all(isinstance(item, str) for item in environment)
        ):
            raise RuntimePreflightError("compose/runtime identity")
        _validate_cursor_secret_runtime(role, _runtime_environment(environment))
        project_name = labels.get("com.docker.compose.project")
        if not isinstance(project_name, str) or not project_name:
            raise RuntimePreflightError("compose project identity")
        compose_projects.add(project_name)
        if role == "map_ui":
            password_hashes = [
                item.removeprefix(_UI_PASSWORD_HASH_PREFIX)
                for item in environment
                if item.startswith(_UI_PASSWORD_HASH_PREFIX)
            ]
            if len(password_hashes) != 1 or not password_hashes[0]:
                raise RuntimePreflightError("UI admin password hash")
        image_id = record.get("Image")
        if not isinstance(image_id, str) or IMAGE_PATTERN.fullmatch(image_id) is None:
            raise RuntimePreflightError("runtime image identity")
        if role not in PINVI_ROLES:
            image_labels = _image_labels(image_id, project_directory, run_json)
            if (
                not isinstance(image_labels, dict)
                or image_labels.get("org.opencontainers.image.revision") != commit
            ):
                raise RuntimePreflightError("runtime image source provenance")
    if len(observed_containers) != len(role_services):
        raise RuntimePreflightError("runtime containers are not distinct")
    if len(compose_projects) != 1:
        raise RuntimePreflightError("wrong compose project")

    executor = _single_inspect_record(
        run_json(["docker", "image", "inspect", "--", executor_image], project_directory),
        "executor",
    )
    executor_config = executor.get("Config")
    executor_labels = executor_config.get("Labels") if isinstance(executor_config, dict) else None
    if (
        executor.get("Id") != executor_image
        or not isinstance(executor_labels, dict)
        or executor_labels.get("io.kortravelmap.c7.repository-commit") != commit
        or executor_labels.get("io.kortravelmap.c7.playwright-base") != playwright_base
    ):
        raise RuntimePreflightError("executor identity")


def main(argv: list[str] | None = None) -> int:
    """runner 전용 CLI: ``runtime PROJECT_DIR PLAYWRIGHT_BASE``. 실패 세부값은 내지 않는다."""

    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 3 or arguments[0] != "runtime":
        return 2
    try:
        verify_runtime(arguments[1], arguments[2], environ=os.environ)
    except (
        RuntimePreflightError,
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
