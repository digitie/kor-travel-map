#!/usr/bin/env python3
"""Export OpenAPI spec for the kor-travel-map-api FastAPI app (ADR-031).

ADR-031 — Export/Drift gate 정책:
    - 본 패키지의 첫 FastAPI 라우터 등장 PR부터 즉시 활성화.
    - `openapi.json`을 저장소에 커밋 + DTO/라우터 변경 PR마다 갱신 강제.
    - CI: `--check` 옵션으로 git working tree와 비교 → drift 시 fail.
    - 사양은 docs/architecture/debug-ui-package.md §8 + docs/adr/README.md ADR-031.

본 skeleton은 코드 작성 단계 진입 전 placeholder. 실제 `app` import는
kortravelmap.api.app 모듈이 생성된 시점부터 동작한다 (Sprint 1).

Usage:
    # 1. full/admin spec 생성 + 저장
    python packages/kor-travel-map-api/scripts/export_openapi.py \\
        --output packages/kor-travel-map-api/openapi.json

    # 2. user spec 생성 + 저장
    python packages/kor-travel-map-api/scripts/export_openapi.py \\
        --profile user \\
        --output packages/kor-travel-map-api/openapi.user.json

    # 3. CI drift 검증 (변경 있으면 exit 1)
    python packages/kor-travel-map-api/scripts/export_openapi.py \\
        --profile all --check
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI

from kortravelmap.api.route_policy import RoutePolicy, build_route_policy_matrix

OpenApiProfile = Literal["admin", "user"]

API_OPENAPI_PATH = Path("packages/kor-travel-map-api/openapi.json")
USER_OPENAPI_PATH = Path("packages/kor-travel-map-api/openapi.user.json")
# T-VN-H07C(#812): per-surface digest manifest. 배포 compatible-pair(ADR-076 v5)는 이 파일
# **하나의** sha256만 핀하고, 이 파일이 각 표면 spec의 sha256을 담아 전체를 transitively pin한다.
OPENAPI_DIGEST_PATH = Path("packages/kor-travel-map-api/openapi-sha256.json")

# ADR-048/T-216g: 현재 pre-1.0 단계의 기계 정본은 ``/v1`` 경로를 in-place로
# 갱신하는 admin/user spec 2종이다. v1.0.0 GA 이후 breaking change는 ``/v2``와
# major별 별도 export 파일을 추가하고, N-1 지원 정책은 문서/CI에서 함께 고정한다.
HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
USER_ROUTE_POLICIES: frozenset[RoutePolicy] = frozenset(
    {
        RoutePolicy.PUBLIC_UNAUTHENTICATED,
        RoutePolicy.PUBLIC_KEYED,
        RoutePolicy.SERVICE,
    }
)
USER_RESPONSE_FORBIDDEN_PROPERTIES: frozenset[str] = frozenset(
    {
        "source_record_key",
        "raw_data",
        "raw_payload_hash",
        "payload",
        "fetched_at",
        "imported_at",
        "last_seen_at",
    }
)
CURATION_RESPONSE_FORBIDDEN_PROPERTIES: frozenset[str] = frozenset({"metadata"})


def _load_app() -> FastAPI:
    """Import kortravelmap.api.app:app lazily.

    코드 작성 단계 진입 전에는 모듈이 존재하지 않으므로 명시적 안내 메시지로
    실패한다. Sprint 1의 첫 라우터 PR에서 실제 import가 동작하기 시작한다.
    """
    try:
        from kortravelmap.api.app import app
    except ModuleNotFoundError as e:
        raise SystemExit(
            "kortravelmap.api 모듈이 아직 없습니다 (코드 작성 단계 진입 전).\n"
            "Sprint 1의 첫 FastAPI 라우터 PR에서 활성화됩니다.\n"
            f"원인: {e}"
        ) from e
    return app


def _collect_schema_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            refs.add(ref.rsplit("/", 1)[-1])
        for child in value.values():
            refs.update(_collect_schema_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_collect_schema_refs(child))
    return refs


def _prune_schemas(spec: dict[str, Any]) -> dict[str, Any]:
    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return spec

    required = _collect_schema_refs(spec.get("paths", {}))
    seen: set[str] = set()
    pending = set(required)
    while pending:
        name = pending.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        pending.update(_collect_schema_refs(schemas[name]) - seen)

    spec.setdefault("components", {})["schemas"] = {
        name: schemas[name] for name in sorted(seen) if name in schemas
    }
    return spec


def _prune_security_schemes(spec: dict[str, Any]) -> dict[str, Any]:
    """선택된 operation에서 실제 참조하는 security scheme만 남긴다."""

    referenced: set[str] = set()
    security_values: list[Any] = [spec.get("security", [])]
    paths = spec.get("paths", {})
    if isinstance(paths, dict):
        for path_item in paths.values():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                security_values.append(operation.get("security", []))

    for security in security_values:
        if not isinstance(security, list):
            continue
        for requirement in security:
            if isinstance(requirement, dict):
                referenced.update(str(name) for name in requirement)

    components = spec.get("components")
    if not isinstance(components, dict):
        return spec
    schemes = components.get("securitySchemes")
    if not isinstance(schemes, dict):
        return spec
    components["securitySchemes"] = {
        name: value for name, value in schemes.items() if name in referenced
    }
    return spec


def _openapi_operations(spec: dict[str, Any]) -> set[tuple[str, str]]:
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI spec paths must be an object.")

    return {
        (path, method)
        for path, path_item in paths.items()
        if isinstance(path, str) and isinstance(path_item, dict)
        for method in path_item
        if method in HTTP_METHODS
    }


def _user_operations(
    app: FastAPI,
    spec: dict[str, Any],
) -> dict[str, frozenset[str]]:
    """조립 route metadata와 full spec에서 user operation을 자동 파생한다."""

    route_policies: dict[str, RoutePolicy] = {}
    mounted_operations: set[tuple[str, str]] = set()
    for row in build_route_policy_matrix(app):
        if row.is_websocket or not row.include_in_schema:
            continue
        route_policies[row.schema_path] = row.policy
        mounted_operations.update(
            (row.schema_path, method.lower())
            for method in row.methods
            if method.lower() in HTTP_METHODS
        )

    full_operations = _openapi_operations(spec)
    if mounted_operations != full_operations:
        missing = sorted(mounted_operations - full_operations)
        extra = sorted(full_operations - mounted_operations)
        raise ValueError(
            "route/OpenAPI operation drift: "
            f"missing={missing!r}; extra={extra!r}"
        )

    selected: dict[str, set[str]] = {}
    for path, method in full_operations:
        policy = route_policies[path]
        if policy in USER_ROUTE_POLICIES:
            selected.setdefault(path, set()).add(method)
    return {
        path: frozenset(methods)
        for path, methods in sorted(selected.items())
    }


def _response_schema_roots(operation: dict[str, Any]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return roots
    for response in responses.values():
        if not isinstance(response, dict):
            continue
        content = response.get("content")
        if not isinstance(content, dict):
            continue
        for media in content.values():
            if not isinstance(media, dict):
                continue
            schema = media.get("schema")
            if isinstance(schema, dict):
                roots.append(schema)
    return roots


def _find_forbidden_schema_properties(
    schema: dict[str, Any],
    *,
    schemas: dict[str, Any],
    forbidden: frozenset[str],
    location: str,
    seen_refs: set[str],
) -> list[str]:
    violations: list[str] = []
    ref = schema.get("$ref")
    prefix = "#/components/schemas/"
    if isinstance(ref, str) and ref.startswith(prefix):
        name = ref.removeprefix(prefix)
        if name in seen_refs:
            return violations
        seen_refs.add(name)
        target = schemas.get(name)
        if isinstance(target, dict):
            violations.extend(
                _find_forbidden_schema_properties(
                    target,
                    schemas=schemas,
                    forbidden=forbidden,
                    location=f"{location} -> {name}",
                    seen_refs=seen_refs,
                )
            )

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for field in sorted(forbidden.intersection(properties)):
            violations.append(f"{location}.{field}")
        for field, child in properties.items():
            if isinstance(child, dict):
                violations.extend(
                    _find_forbidden_schema_properties(
                        child,
                        schemas=schemas,
                        forbidden=forbidden,
                        location=f"{location}.{field}",
                        seen_refs=seen_refs,
                    )
                )

    items = schema.get("items")
    if isinstance(items, dict):
        violations.extend(
            _find_forbidden_schema_properties(
                items,
                schemas=schemas,
                forbidden=forbidden,
                location=f"{location}[]",
                seen_refs=seen_refs,
            )
        )
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        violations.extend(
            _find_forbidden_schema_properties(
                additional,
                schemas=schemas,
                forbidden=forbidden,
                location=f"{location}{{}}",
                seen_refs=seen_refs,
            )
        )
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(keyword)
        if not isinstance(branches, list):
            continue
        for index, branch in enumerate(branches):
            if isinstance(branch, dict):
                violations.extend(
                    _find_forbidden_schema_properties(
                        branch,
                        schemas=schemas,
                        forbidden=forbidden,
                        location=f"{location}.{keyword}[{index}]",
                        seen_refs=seen_refs,
                    )
                )
    return violations


def _validate_user_response_schemas(spec: dict[str, Any]) -> None:
    """공개 response root에서 reachable raw lineage field를 fail-closed한다."""
    components = spec.get("components")
    paths = spec.get("paths", {})
    if not isinstance(components, dict) or not isinstance(paths, dict):
        raise ValueError("OpenAPI user spec paths/schemas must be objects.")
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        raise ValueError("OpenAPI user spec paths/schemas must be objects.")

    violations: list[str] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        forbidden = USER_RESPONSE_FORBIDDEN_PROPERTIES
        if path.startswith("/v1/curations"):
            forbidden |= CURATION_RESPONSE_FORBIDDEN_PROPERTIES
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            for index, root in enumerate(_response_schema_roots(operation)):
                violations.extend(
                    _find_forbidden_schema_properties(
                        root,
                        schemas=schemas,
                        forbidden=forbidden,
                        location=f"{method.upper()} {path} response[{index}]",
                        seen_refs=set(),
                    )
                )
    if violations:
        details = "; ".join(sorted(set(violations)))
        raise ValueError(f"user response raw lineage schema reachable: {details}")


def user_openapi_spec(spec: dict[str, Any], *, app: FastAPI) -> dict[str, Any]:
    """조립된 route policy에서 user-facing subset spec을 파생한다."""

    user_operations = _user_operations(app, spec)
    out = copy.deepcopy(spec)
    out["info"] = {
        **out.get("info", {}),
        "title": "kor-travel-map-user",
        "description": (
            "User-facing subset of kor-travel-map OpenAPI. "
            "Internal admin/debug/ops routes are intentionally excluded."
        ),
    }
    filtered_paths: dict[str, Any] = {}
    for path, allowed_methods in user_operations.items():
        path_item = spec.get("paths", {}).get(path)
        if not isinstance(path_item, dict):
            continue
        filtered_item: dict[str, Any] = {}
        for key, value in path_item.items():
            if key in HTTP_METHODS and key not in allowed_methods:
                continue
            filtered_item[key] = value
        if any(method in filtered_item for method in allowed_methods):
            filtered_paths[path] = filtered_item
    out["paths"] = filtered_paths
    out = _prune_security_schemes(_prune_schemas(out))
    _validate_user_response_schemas(out)
    return out


def _profile_spec(
    app: FastAPI,
    spec: dict[str, Any],
    profile: OpenApiProfile,
) -> dict[str, Any]:
    if profile == "admin":
        return spec
    return user_openapi_spec(spec, app=app)


def export(output: Path, *, profile: OpenApiProfile = "admin") -> dict[str, Any]:
    """Generate the selected OpenAPI spec and write it to `output`."""
    app = _load_app()
    spec = _profile_spec(app, app.openapi(), profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return spec


def check(output: Path, *, profile: OpenApiProfile = "admin") -> int:
    """Compare selected OpenAPI spec against `output`. Exit 1 if drift."""
    if not output.exists():
        print(f"missing: {output}", file=sys.stderr)
        print("hint: run without --check to generate first.", file=sys.stderr)
        return 1
    app = _load_app()
    current = json.dumps(
        _profile_spec(app, app.openapi(), profile),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    saved = output.read_text(encoding="utf-8")
    if current.strip() == saved.strip():
        return 0
    print(
        f"OpenAPI drift detected in {output}.\n"
        "  - Run scripts/export_openapi.py to regenerate, then commit.",
        file=sys.stderr,
    )
    return 1


def _digest_manifest(surfaces: dict[str, Path]) -> str:
    """표면별 spec 파일의 sha256을 담은 결정적 manifest JSON.

    key는 파일 basename(`openapi.json`/`openapi.user.json`)이라 경로 인자를 바꿔도 manifest
    내용은 안정적이다. 값은 **저장된 파일 바이트**의 sha256이므로, `--check`가 spec↔app 일치를
    먼저 확인한 뒤 이 manifest를 검증하면 manifest가 살아 있는 계약을 transitively pin한다.
    """
    digests = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in sorted(surfaces.items())
    }
    return json.dumps(digests, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def export_digest_manifest(manifest_path: Path, surfaces: dict[str, Path]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_digest_manifest(surfaces), encoding="utf-8")


def check_digest_manifest(manifest_path: Path, surfaces: dict[str, Path]) -> int:
    """저장된 digest manifest가 현재 spec 파일들과 일치하는지 확인한다."""
    if not manifest_path.exists():
        print(f"missing: {manifest_path}", file=sys.stderr)
        print("hint: run without --check to generate first.", file=sys.stderr)
        return 1
    expected = _digest_manifest(surfaces)
    saved = manifest_path.read_text(encoding="utf-8")
    if saved.strip() == expected.strip():
        return 0
    print(
        f"OpenAPI digest manifest drift detected in {manifest_path}.\n"
        "  - Run scripts/export_openapi.py --profile all to regenerate, then commit.",
        file=sys.stderr,
    )
    return 1


def _surfaces(args: argparse.Namespace) -> dict[str, Path]:
    """digest manifest 대상 — 두 표면 모두. profile과 무관하게 같은 집합을 덮는다."""
    return {
        cast(Path, args.output).name: cast(Path, args.output),
        cast(Path, args.user_output).name: cast(Path, args.user_output),
    }


def _output_for_profile(args: argparse.Namespace, profile: OpenApiProfile) -> Path:
    if profile == "admin":
        return cast(Path, args.output)
    return cast(Path, args.user_output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--profile",
        choices=("admin", "user", "all"),
        default="admin",
        help="export 대상 spec profile. all은 admin/user를 모두 처리.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=API_OPENAPI_PATH,
        help="admin OpenAPI 저장/비교 대상 경로.",
    )
    parser.add_argument(
        "--user-output",
        type=Path,
        default=USER_OPENAPI_PATH,
        help="user OpenAPI 저장/비교 대상 경로.",
    )
    parser.add_argument(
        "--digest-output",
        type=Path,
        default=OPENAPI_DIGEST_PATH,
        help="per-surface OpenAPI digest manifest 경로 (--profile all에서만 처리).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI 모드 — drift 발견 시 exit 1 (저장하지 않음)",
    )
    args = parser.parse_args(argv)

    profiles: tuple[OpenApiProfile, ...] = (
        ("admin", "user")
        if args.profile == "all"
        else (cast(OpenApiProfile, args.profile),)
    )
    # digest manifest는 두 표면을 함께 덮으므로 `--profile all`에서만 다룬다. CI(openapi.yml)가
    # `--profile all --check`로 돌기 때문에 별도 CI 단계 없이 같은 명령이 자동으로 게이트한다.
    manifest_scope = args.profile == "all"

    if args.check:
        failed = False
        for profile in profiles:
            failed = (
                bool(check(_output_for_profile(args, profile), profile=profile))
                or failed
            )
        if manifest_scope and not failed:
            # spec↔app 일치를 확인한 뒤에만 manifest를 검사한다 — spec이 이미 drift면
            # manifest 불일치는 파생 증상이라 원인 메시지를 가리지 않게 한다.
            failed = bool(check_digest_manifest(args.digest_output, _surfaces(args))) or failed
        return int(failed)
    for profile in profiles:
        output = _output_for_profile(args, profile)
        export(output, profile=profile)
        print(f"wrote {output}")
    if manifest_scope:
        export_digest_manifest(args.digest_output, _surfaces(args))
        print(f"wrote {args.digest_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
