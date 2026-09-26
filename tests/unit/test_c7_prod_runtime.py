"""C7·D2 runtime preflight(`scripts/lib/c7_prod_runtime.py`)의 실행형 음수 테스트.

ADR-102 결정 6이 root 스냅샷·host attestation·Manager manifest/journal 재파싱을
걷어냈다. 이 파일은 그 뒤에 **남은** 기능 전제 — origin, compose runtime, cursor secret
위생, Map image revision, executor image — 가 여전히 하나씩 fail-close하는지 본다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "lib" / "c7_prod_runtime.py"
PROJECT = "/srv/kor-travel-map"
PLAYWRIGHT_BASE = "playwright@example"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("c7_prod_runtime", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = _load_module()

_SERVICE_ENVS = {
    "map_api": "E2E_C7_MAP_API_SERVICE",
    "map_dagster_daemon": "E2E_C7_DAGSTER_DAEMON_SERVICE",
    "map_dagster_web": "E2E_C7_DAGSTER_WEB_SERVICE",
    "map_ui": "E2E_C7_UI_SERVICE",
    "pinvi_api": "E2E_C7_PINVI_API_SERVICE",
    "pinvi_dagster": "E2E_C7_PINVI_DAGSTER_SERVICE",
    "pinvi_web": "E2E_C7_PINVI_WEB_SERVICE",
}
_MAP_ROLES = ("map_api", "map_ui", "map_dagster_web", "map_dagster_daemon")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class _Docker:
    """`docker compose ps`/`inspect`/`image inspect`를 흉내내는 결정론적 대역."""

    def __init__(self) -> None:
        self.map_commit = "a" * 40
        self.pinvi_commit = "b" * 40
        self.executor_image = "sha256:" + "3" * 64
        self.role_images = {
            "map_api": "sha256:" + "1" * 64,
            "map_ui": "sha256:" + "4" * 64,
            "map_dagster_web": "sha256:" + "5" * 64,
            "map_dagster_daemon": "sha256:" + "6" * 64,
            "pinvi_api": "sha256:" + "2" * 64,
            "pinvi_web": "sha256:" + "7" * 64,
            "pinvi_dagster": "sha256:" + "8" * 64,
        }
        self.services = {
            "map_api": "map-api",
            "map_dagster_daemon": "map-daemon",
            "map_dagster_web": "map-web",
            "map_ui": "map-ui",
            "pinvi_api": "pinvi-api",
            "pinvi_dagster": "pinvi-dagster",
            "pinvi_web": "pinvi-web",
        }
        environments: dict[str, list[str]] = {role: ["A=1"] for role in self.services}
        environments["map_api"] = [
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=admin-proxy-0000000000000000000000000000",
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=cursor-secret-000000000000000000000000000",
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true",
            "KOR_TRAVEL_MAP_API_METRICS_TOKEN=metrics-token-000000000000000000000000000",
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=ops-cancel-000000000000000000000000000",
            "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN=ops-fixture-0000000000000000000000000",
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=ops-read-00000000000000000000000000000",
            "KOR_TRAVEL_MAP_API_PROFILE=production",
            "KOR_TRAVEL_MAP_API_SERVICE_TOKEN=service-token-000000000000000000000000000",
            "KOR_TRAVEL_MAP_API_VWORLD_API_KEY=vworld-key-00000000000000000000000000000",
        ]
        environments["map_ui"] = ["KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH=hash"]
        self.records: dict[str, dict[str, object]] = {}
        self.service_ids: dict[str, str] = {}
        for index, (role, service) in enumerate(self.services.items(), start=1):
            container_id = f"{index:x}" * 64
            self.service_ids[service] = container_id
            self.records[container_id] = {
                "Config": {
                    "Env": environments[role],
                    "Labels": {
                        "com.docker.compose.project": "kor-travel-map-prod",
                        "com.docker.compose.service": service,
                    },
                },
                "Id": container_id,
                "Image": self.role_images[role],
                "State": {"Paused": False, "Restarting": False, "Running": True},
            }
        self.image_records: dict[str, dict[str, object]] = {
            image_id: {
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.revision": (
                            self.pinvi_commit if role in RUNTIME.PINVI_ROLES else self.map_commit
                        )
                    }
                }
            }
            for role, image_id in self.role_images.items()
        }
        self.image_records[self.executor_image] = {
            "Config": {
                "Labels": {
                    "io.kortravelmap.c7.playwright-base": PLAYWRIGHT_BASE,
                    "io.kortravelmap.c7.repository-commit": self.map_commit,
                }
            },
            "Id": self.executor_image,
        }
        self.commands: list[list[str]] = []

    def record(self, role: str) -> dict[str, object]:
        return self.records[self.service_ids[self.services[role]]]

    def environ(self) -> dict[str, str]:
        environ = {
            "E2E_BASE_URL": "https://map.example.test",
            "E2E_C7_EXPECTED_GIT_COMMIT": self.map_commit,
            "E2E_C7_PLAYWRIGHT_IMAGE": self.executor_image,
            "E2E_DAGSTER_URL": "https://dagster.example.test/graphql",
            "NEXT_PUBLIC_KOR_TRAVEL_MAP_API": "https://api.example.test",
            "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256": _sha256(b"wss://api.example.test"),
            "E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256": _sha256(
                b"https://dagster.example.test/graphql"
            ),
            "E2E_C7_EXPECTED_UI_ORIGIN_SHA256": _sha256(b"https://map.example.test"),
        }
        environ.update(
            {env_name: self.services[role] for role, env_name in _SERVICE_ENVS.items()}
        )
        return environ

    def __call__(self, command: list[str], project_directory: str) -> str:
        assert project_directory == PROJECT
        self.commands.append(command)
        if command[:2] == ["docker", "compose"]:
            container_id = self.service_ids.get(command[-1])
            return f"{container_id}\n" if container_id else ""
        if command[:3] == ["docker", "inspect", "--"]:
            return json.dumps([self.records[command[3]]])
        if command[:4] == ["docker", "image", "inspect", "--"]:
            return json.dumps([self.image_records[command[4]]])
        raise AssertionError(f"unexpected command: {command}")


def _verify(docker: _Docker, environ: dict[str, str] | None = None) -> None:
    RUNTIME.verify_runtime(
        PROJECT,
        PLAYWRIGHT_BASE,
        environ=docker.environ() if environ is None else environ,
        run_json=docker,
    )


def test_exact_runtime_passes_and_inspects_all_seven_services() -> None:
    """양성 경로가 없으면 아래 음성 테스트는 '항상 raise'와 구별되지 않는다."""

    docker = _Docker()
    _verify(docker)

    inspected = {
        command[-1] for command in docker.commands if command[:2] == ["docker", "compose"]
    }
    assert inspected == set(docker.services.values())
    assert [role for role, _ in RUNTIME.ROLE_SERVICE_ENVS] == [
        "map_api",
        "map_ui",
        "map_dagster_web",
        "map_dagster_daemon",
        "pinvi_api",
        "pinvi_web",
        "pinvi_dagster",
    ]


def test_module_reads_no_manager_or_attestation_file() -> None:
    """ADR-102 결정 6: preflight는 Manager 내부 파일과 host attestation을 모른다."""

    source = MODULE_PATH.read_text(encoding="utf-8")
    code = source[source.index("from __future__") :]
    for forbidden in (
        "pinned_runtime",
        "rebuild_journal",
        "journal_generation",
        "active_generation",
        "/etc/kor-travel-map",
        "/usr/local/lib/kor-travel-map",
        "/var/lib/kor-travel-docker-manager",
        "open(",
        "read_bytes",
        "read_text",
    ):
        assert forbidden not in code, forbidden


def test_public_origin_brackets_ipv6_and_rejects_scope() -> None:
    """#805: IPv6 origin은 netloc에서 bracket + canonical로 재구성하고 zone-id는 거부한다."""

    origin = RUNTIME._public_origin  # noqa: SLF001
    err = RUNTIME.RuntimePreflightError

    assert origin("https://[2001:db8::1]:8443/") == "https://[2001:db8::1]:8443"
    assert origin("https://[2001:db8::1]/") == "https://[2001:db8::1]"
    assert (
        origin("https://[2001:0db8:0000:0000:0000:0000:0000:0001]:443/")
        == "https://[2001:db8::1]:443"
    )
    assert origin("https://[2001:db8::1]:9443/", websocket=True) == "wss://[2001:db8::1]:9443"
    # "%" guard가 ip_address() 파싱보다 먼저 실행돼야 한다(guard 순서가 load-bearing).
    with pytest.raises(err, match="scoped address"):
        origin("https://[2001:db8::1%25eth0]/")
    with pytest.raises(err, match="unsafe address"):
        origin("https://[::1]/")
    with pytest.raises(err, match="unsafe address"):
        origin("https://[fe80::1]/")
    with pytest.raises(err, match="unsafe address"):
        origin("https://[::]/")
    assert origin("https://map.example.org:443/") == "https://map.example.org:443"
    assert origin("https://192.0.2.10:8443/") == "https://192.0.2.10:8443"


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("E2E_C7_EXPECTED_UI_ORIGIN_SHA256", "0" * 64),
        ("E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256", "0" * 64),
        ("E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256", "0" * 64),
    ],
)
def test_rejects_each_caller_origin_mismatch(env_name: str, value: str) -> None:
    docker = _Docker()
    environ = docker.environ()
    environ[env_name] = value

    with pytest.raises(RUNTIME.RuntimePreflightError, match="caller origin mismatch"):
        _verify(docker, environ)


@pytest.mark.parametrize(
    ("env_name", "value", "expected"),
    [
        ("E2E_BASE_URL", "http://map.example.test", "unsafe origin"),
        ("E2E_BASE_URL", "https://localhost", "local origin"),
        ("NEXT_PUBLIC_KOR_TRAVEL_MAP_API", "https://127.0.0.1", "unsafe address"),
        ("E2E_DAGSTER_URL", "https://dagster.example.test/graphql?x=1", "unsafe origin"),
    ],
)
def test_rejects_non_public_https_origins(env_name: str, value: str, expected: str) -> None:
    docker = _Docker()
    environ = docker.environ()
    environ[env_name] = value

    with pytest.raises(RUNTIME.RuntimePreflightError, match=expected):
        _verify(docker, environ)


@pytest.mark.parametrize("role", _MAP_ROLES)
def test_rejects_each_map_runtime_image_from_another_revision(role: str) -> None:
    docker = _Docker()
    image = docker.role_images[role]
    labels = docker.image_records[image]["Config"]
    assert isinstance(labels, dict)
    labels["Labels"] = {"org.opencontainers.image.revision": "c" * 40}

    with pytest.raises(RUNTIME.RuntimePreflightError, match="source provenance"):
        _verify(docker)


def test_pinvi_runtime_revision_is_left_to_the_manager() -> None:
    """PinVi의 기대 revision은 Map env에 없다 — ADR-102 이후 그것은 Manager의 몫이다.

    그래서 PinVi image는 revision label을 보지 않는다(보지 않는다는 사실을 고정한다).
    running·compose project·cursor secret 부재는 그대로 본다.
    """

    docker = _Docker()
    for role in RUNTIME.PINVI_ROLES:
        docker.image_records[docker.role_images[role]] = {"Config": {"Labels": {}}}

    _verify(docker)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.update({"Id": "sha256:" + "f" * 64}), "executor identity"),
        (
            lambda value: value["Config"]["Labels"].update(
                {"io.kortravelmap.c7.repository-commit": "c" * 40}
            ),
            "executor identity",
        ),
        (
            lambda value: value["Config"]["Labels"].update(
                {"io.kortravelmap.c7.playwright-base": "other@base"}
            ),
            "executor identity",
        ),
    ],
)
def test_rejects_executor_image_that_is_not_this_commit(
    mutation: Callable[[dict[str, object]], None], expected: str
) -> None:
    docker = _Docker()
    mutation(docker.image_records[docker.executor_image])

    with pytest.raises(RUNTIME.RuntimePreflightError, match=expected):
        _verify(docker)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"Running": False}, "runtime is not healthy"),
        ({"Running": True, "Paused": True}, "runtime is not healthy"),
        ({"Running": True, "Restarting": True}, "runtime is not healthy"),
        ({"Running": True, "Health": {"Status": "unhealthy"}}, "runtime is not healthy"),
    ],
)
@pytest.mark.parametrize("role", sorted(_SERVICE_ENVS))
def test_rejects_any_runtime_that_is_not_running_and_healthy(
    role: str, state: dict[str, object], expected: str
) -> None:
    docker = _Docker()
    docker.record(role)["State"] = state

    with pytest.raises(RUNTIME.RuntimePreflightError, match=expected):
        _verify(docker)


def test_rejects_missing_or_duplicated_compose_container() -> None:
    missing = _Docker()
    missing.service_ids.pop(missing.services["pinvi_web"])
    with pytest.raises(RUNTIME.RuntimePreflightError, match="compose service cardinality"):
        _verify(missing)

    duplicated = _Docker()
    original = duplicated.__call__

    def run_json(command: list[str], project_directory: str) -> str:
        output = original(command, project_directory)
        if command[:2] == ["docker", "compose"] and command[-1] == duplicated.services["map_ui"]:
            return output + "f" * 64 + "\n"
        return output

    with pytest.raises(RUNTIME.RuntimePreflightError, match="compose service cardinality"):
        RUNTIME.verify_runtime(
            PROJECT, PLAYWRIGHT_BASE, environ=duplicated.environ(), run_json=run_json
        )


def test_rejects_services_that_are_not_distinct() -> None:
    docker = _Docker()
    environ = docker.environ()
    environ["E2E_C7_PINVI_WEB_SERVICE"] = environ["E2E_C7_PINVI_API_SERVICE"]

    with pytest.raises(RUNTIME.RuntimePreflightError, match="compose services are not distinct"):
        _verify(docker, environ)


def test_rejects_runtime_from_another_compose_project() -> None:
    docker = _Docker()
    config = docker.record("pinvi_dagster")["Config"]
    assert isinstance(config, dict)
    config["Labels"]["com.docker.compose.project"] = "someone-else"

    with pytest.raises(RUNTIME.RuntimePreflightError, match="wrong compose project"):
        _verify(docker)


def test_rejects_container_whose_service_label_differs() -> None:
    docker = _Docker()
    config = docker.record("map_ui")["Config"]
    assert isinstance(config, dict)
    config["Labels"]["com.docker.compose.service"] = "other"

    with pytest.raises(RUNTIME.RuntimePreflightError, match="compose/runtime identity"):
        _verify(docker)


def test_rejects_ui_without_admin_password_hash() -> None:
    docker = _Docker()
    config = docker.record("map_ui")["Config"]
    assert isinstance(config, dict)
    config["Env"] = ["A=1"]

    with pytest.raises(RUNTIME.RuntimePreflightError, match="UI admin password hash"):
        _verify(docker)


def _replace_env(values: list[str], prefix: str, replacement: str | None) -> None:
    index = next(i for i, item in enumerate(values) if item.startswith(prefix))
    if replacement is None:
        values.pop(index)
    else:
        values[index] = replacement


_CURSOR = "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET="


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: _replace_env(values, _CURSOR, None),
        lambda values: _replace_env(values, _CURSOR, f"{_CURSOR}short"),
        lambda values: _replace_env(
            values, _CURSOR, f"{_CURSOR}cursor secret with whitespace 000000000000"
        ),
        lambda values: _replace_env(
            values, "KOR_TRAVEL_MAP_API_PROFILE=", "KOR_TRAVEL_MAP_API_PROFILE=local-dev"
        ),
        lambda values: _replace_env(
            values,
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=",
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false",
        ),
    ],
)
def test_rejects_invalid_api_cursor_secret_shape(
    mutation: Callable[[list[str]], None],
) -> None:
    docker = _Docker()
    config = docker.record("map_api")["Config"]
    assert isinstance(config, dict)
    mutation(config["Env"])

    with pytest.raises(RUNTIME.RuntimePreflightError, match="cursor secret runtime shape"):
        _verify(docker)


@pytest.mark.parametrize(
    "protected_name",
    [
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        "KOR_TRAVEL_MAP_API_VWORLD_API_KEY",
    ],
)
def test_rejects_api_cursor_secret_reuse(protected_name: str) -> None:
    docker = _Docker()
    config = docker.record("map_api")["Config"]
    assert isinstance(config, dict)
    values: list[str] = config["Env"]
    cursor = next(item.split("=", 1)[1] for item in values if item.startswith(_CURSOR))
    _replace_env(values, f"{protected_name}=", f"{protected_name}={cursor}")

    with pytest.raises(RUNTIME.RuntimePreflightError, match="cursor secret runtime reuse"):
        _verify(docker)


def test_rejects_duplicate_cursor_secret_name() -> None:
    docker = _Docker()
    config = docker.record("map_api")["Config"]
    assert isinstance(config, dict)
    config["Env"].append(f"{_CURSOR}duplicate-0000000000000000000000000000")

    with pytest.raises(RUNTIME.RuntimePreflightError, match="runtime environment shape"):
        _verify(docker)


@pytest.mark.parametrize("role", sorted(set(_SERVICE_ENVS) - {"map_api"}))
def test_rejects_cursor_secret_outside_api(role: str) -> None:
    docker = _Docker()
    config = docker.record(role)["Config"]
    assert isinstance(config, dict)
    config["Env"].append(f"{_CURSOR}escaped-00000000000000000000000000000")

    with pytest.raises(RUNTIME.RuntimePreflightError, match="escaped API runtime"):
        _verify(docker)


def test_cli_takes_only_project_directory_and_playwright_base() -> None:
    """runner 호출 모양을 고정한다 — manifest/journal/attestation 인자는 받지 않는다."""

    assert RUNTIME.main(["runtime", "/tmp/a", "/tmp/b", "/tmp/c", PROJECT, PLAYWRIGHT_BASE]) == 2
    assert RUNTIME.main(["snapshot", PROJECT, PLAYWRIGHT_BASE]) == 2
