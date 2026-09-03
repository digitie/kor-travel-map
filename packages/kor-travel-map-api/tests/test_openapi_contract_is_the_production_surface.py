"""커밋된 OpenAPI 계약이 **운영이 실제로 제공하는 표면**인지 본다.

`/v1/debug/mois-license/{license_id}`는 `debug_routes_enabled` 뒤에 있었다. 그
flag의 코드 기본값은 `True`(local-dev)이고 Docker image 기본 profile은
`production`이며, production은 그 flag를 반드시 `False`로 둔다 — 인증이 없기
때문이다. 그래서 `export_openapi.py`가 기본 설정으로 만든 계약은 **운영이 절대
제공하지 않는 라우트**를 기술했다.

실행 중 표면과 계약을 바이트 비교하는 M05 live attestation은 그 때문에 운영
구성에서 통과할 수 없었다. 2026-09-03 격리 e2e가
`live Map admin OpenAPI does not match the pinned source artifact`로 막혔고,
실측하니 핀된 이미지는 161 path, 계약은 162 path였다 — 그 하나만 차이였고
스키마는 내내 정상이었다.

라우트는 삭제했다. 도입(SPRINT-4 Step D) 이후 admin frontend에 호출부가 한 번도
생기지 않았고(생성 타입만 있었다), 운영에서는 도달할 수 없는 표면이었다.

이 게이트는 **환경에 따라 있었다 없었다 하는 표면이 계약에 다시 들어오는 것**을
막는다. 그런 표면은 attestation을 구조적으로 통과 불가능하게 만든다.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT = _PACKAGE_ROOT / "openapi.json"
_SOURCE_ROOT = _PACKAGE_ROOT / "src" / "kortravelmap" / "api"

# `test_route_policy.py`와 같은 dummy secret 규약. production 자세를 세우려면
# fail-closed 검증을 모두 만족시켜야 한다.
_HERMETIC_ENV_PREFIX = "KOR_TRAVEL_MAP_"


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 환경의 `KOR_TRAVEL_MAP_*`가 결과를 바꾸지 못하게 한다.

    형제 테스트들과 같은 규약이다 — 통과 여부가 기계가 아니라 환경에 달리면
    게이트가 아니다(적대 리뷰 지적).
    """
    for name in list(os.environ):
        if name.startswith(_HERMETIC_ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)


def _production_settings() -> Any:
    from kortravelmap.api.settings import ApiSettings

    return ApiSettings(
        _env_file=None,
        profile="production",
        debug_routes_enabled=False,
        features_routes_enabled=True,
        admin_routes_enabled=True,
        ops_routes_enabled=True,
        prometheus_metrics_enabled=True,
        public_api_key_required=True,
        admin_proxy_secret="admin-proxy-secret-000000000000000000000000",
        admin_feature_create_token_sha256="0" * 64,
        ops_read_token="read-token-00000000000000000000000000000000",
        ops_cancel_token="cancel-token-000000000000000000000000000000",
        ops_fixture_token="fixture-token-00000000000000000000000000000",
        service_token="service-token-0000000000000000000000000000",
        cursor_signing_secret="cursor-signing-secret-000000000000000000000000",
        metrics_token="metrics-token-0000000000000000000000000000",
        vworld_api_key=None,
    )


def _contract() -> dict[str, Any]:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def test_the_committed_contract_documents_no_debug_route() -> None:
    """운영이 내리는 라우트가 계약에 남으면 attestation이 영원히 실패한다."""
    offenders = sorted(
        path
        for path in _contract()["paths"]
        if path == "/v1/debug" or "/debug/" in path
    )
    assert offenders == [], offenders


_ROUTE_DECORATORS = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "trace",
        "api_route",
        "add_api_route",
        "websocket",
    }
)


def _declared_debug_paths(module: ast.Module) -> list[str]:
    """`APIRouter(prefix=...)`와 route 데코레이터의 **경로 리터럴만** 본다."""

    found: list[str] = []

    def _flag(value: object, line: int) -> None:
        if not isinstance(value, str):
            return
        normalized = value.removeprefix("/v1")
        if normalized == "/debug" or normalized.startswith("/debug/"):
            found.append(f"{line}: {value}")

    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "APIRouter":
            for keyword in node.keywords:
                if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                    _flag(keyword.value.value, node.lineno)
        elif isinstance(func, ast.Attribute) and func.attr in _ROUTE_DECORATORS:
            for argument in node.args:
                if isinstance(argument, ast.Constant):
                    _flag(argument.value, node.lineno)
    return found


def test_no_router_declares_a_debug_path() -> None:
    """계약이 아니라 **소스**에서 본다 — 라우터가 없으면 계약에도 못 들어온다.

    `prefix="/debug` 리터럴 하나만 grep하면 `prefix='/v1/debug/...'`이나
    데코레이터의 `@router.get("/debug/...")`를 놓친다(적대 리뷰 지적). 그렇다고
    문자열을 넓게 grep하면 운영 거부 코드 자신이 걸린다 — 그쪽은 경로를 이름
    대야 하기 때문이다. 그래서 텍스트가 아니라 **AST의 route 선언**만 본다.
    """
    offenders = [
        f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{entry}"
        for path in sorted(_SOURCE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for entry in _declared_debug_paths(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
    ]
    assert offenders == [], offenders


def test_production_refuses_to_serve_a_debug_surface() -> None:
    """불변식을 flag가 아니라 **표면 위**에서 강제한다.

    `debug_routes_enabled`는 flag를 거부할 뿐 표면을 거부하지 않는다. 라우트를
    지운 뒤 그 flag를 보는 코드가 하나도 남지 않아, 무조건 마운트된 `/v1/debug`
    라우터는 production에서도 그냥 제공됐을 것이다 — 문서만 막는다고 말하는
    상태였다(적대 리뷰 지적).

    정책표에 `/debug` 항목이 있는지로 막지 않는다. 그러면 라우트가 정당하게
    돌아올 때 교착이 되고(`build_route_policy_matrix`는 마운트된 모든 route에
    정책을 **요구**한다) 탈출구가 "게이트를 지운다"가 된다. 대신 production
    기동을 거부한다 — 되돌릴 수 있는 결정 지점이지 금지가 아니다.
    """
    from kortravelmap.api.app import _assert_no_production_debug_surface
    from kortravelmap.api.route_policy import RoutePolicyError
    from kortravelmap.api.settings import ApiSettings

    class _Route:
        def __init__(self, path: str) -> None:
            self.path = path

    class _App:
        def __init__(self, *paths: str) -> None:
            self.routes = [_Route(path) for path in paths]

    local_dev = ApiSettings(_env_file=None)
    assert not local_dev.is_production
    # local-dev는 통과한다 — 금지가 아니라 운영 경계다.
    _assert_no_production_debug_surface(_App("/v1/debug/anything"), local_dev)

    production = _production_settings()
    assert production.is_production
    _assert_no_production_debug_surface(_App("/v1/features"), production)
    for path in ("/v1/debug", "/v1/debug/mois-license/{license_id}"):
        with pytest.raises(RoutePolicyError, match="/v1/debug"):
            _assert_no_production_debug_surface(_App(path), production)


def test_production_still_forbids_enabling_debug_routes() -> None:
    """flag 자체는 남겨 둔다 — 미래에 `/debug` 표면이 생기면 운영이 거부해야 한다.

    운영이 debug를 허용하도록 규칙이 바뀌면 여기서 깨진다. 그때는 계약을 어느
    표면으로 둘지 사람이 다시 정해야 하고, 조용히 갈라지면 안 된다.
    """
    from kortravelmap.api.settings import ApiSettings

    with pytest.raises(Exception) as raised:  # noqa: PT011 - 저장소 예외형에 묶지 않는다
        ApiSettings(_env_file=None, profile="production", debug_routes_enabled=True)
    assert "DEBUG_ROUTES_ENABLED" in str(raised.value)


def test_the_contract_matches_the_surface_the_exporter_produces() -> None:
    """계약이 생성기 산출물과 같은지 본다 — drift 게이트와 같은 비교다.

    `_env_file=None`을 명시한다. 그러지 않으면 개발자 환경의 `.env`나
    `KOR_TRAVEL_MAP_API_*`가 결과를 바꿔, 통과 여부가 기계가 아니라 환경에
    달리게 된다(형제 `test_route_policy.py`의 같은 규약).
    """
    from kortravelmap.api.app import create_app
    from kortravelmap.api.settings import ApiSettings

    application = create_app(ApiSettings(_env_file=None))
    assert set(application.openapi()["paths"]) == set(_contract()["paths"])


def test_no_mount_flag_can_add_a_path_the_contract_lacks() -> None:
    """**실제로 마운트를 가르는** flag를 흔들어도 계약 밖 경로가 생기지 않아야 한다.

    `debug_routes_enabled`만 흔드는 것은 이제 공허하다 — 그 flag를 보는 코드가
    없기 때문이다(적대 리뷰 지적). 표면을 실제로 가르는 것은
    `features_routes_enabled`와 그것을 따르는 `admin`/`ops` flag이므로 그 조합을
    본다. 계약보다 **넓은** 표면을 내는 조합이 있으면, 그 자세로 배포된 이미지는
    계약과 바이트 비교에서 어긋난다 — 2026-09-03을 만든 결함과 같은 계열이다.
    """
    from itertools import product

    from kortravelmap.api.app import create_app
    from kortravelmap.api.settings import ApiSettings

    contract_paths = set(_contract()["paths"])
    offenders: list[str] = []
    for features, admin, ops in product((True, False), repeat=3):
        application = create_app(
            ApiSettings(
                _env_file=None,
                features_routes_enabled=features,
                admin_routes_enabled=admin,
                ops_routes_enabled=ops,
            )
        )
        extra = set(application.openapi()["paths"]) - contract_paths
        if extra:
            offenders.append(f"features={features} admin={admin} ops={ops}: {sorted(extra)}")
    assert offenders == [], offenders
