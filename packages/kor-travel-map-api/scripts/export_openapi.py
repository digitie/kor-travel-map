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

    # 2. user/PinVi spec 생성 + 저장
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
import json
import sys
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI

OpenApiProfile = Literal["admin", "user"]

API_OPENAPI_PATH = Path("packages/kor-travel-map-api/openapi.json")
USER_OPENAPI_PATH = Path("packages/kor-travel-map-api/openapi.user.json")

# ADR-048/T-216g: 현재 pre-1.0 단계의 기계 정본은 ``/v1`` 경로를 in-place로
# 갱신하는 admin/user spec 2종이다. v1.0.0 GA 이후 breaking change는 ``/v2``와
# major별 별도 export 파일을 추가하고, N-1 지원 정책은 문서/CI에서 함께 고정한다.
USER_OPERATIONS: dict[str, frozenset[str]] = {
    # 사용자/서비스 표면은 ``/v1`` prefix. liveness ``/health``·``/version``은
    # 비버저닝 유지(ADR-048).
    "/v1/features/in-bounds": frozenset({"get"}),
    "/v1/features/{feature_id}": frozenset({"get"}),
    "/v1/features/{feature_id}/weather": frozenset({"get"}),
    "/v1/features/search": frozenset({"get"}),
    "/v1/features/nearby": frozenset({"get"}),
    "/v1/features/nearby/by-target": frozenset({"get"}),
    "/v1/public/beaches": frozenset({"get"}),
    "/v1/public/beaches/map-markers": frozenset({"get"}),
    "/v1/public/beaches/{feature_id}": frozenset({"get"}),
    "/v1/public/festivals/monthly": frozenset({"get"}),
    "/v1/public/festivals/map-markers": frozenset({"get"}),
    "/v1/public/festivals/{feature_id}": frozenset({"get"}),
    "/v1/curated-themes": frozenset({"get"}),
    "/v1/curated-sources": frozenset({"get"}),
    "/v1/curated-features": frozenset({"get"}),
    "/v1/curated-features/{curated_feature_id}": frozenset({"get"}),
    "/v1/curated-features/{curated_feature_id}/pinvi-copy": frozenset({"get"}),
    "/v1/categories": frozenset({"get"}),
    "/v1/providers": frozenset({"get"}),
    "/v1/providers/{provider}/last-sync": frozenset({"get"}),
    "/health": frozenset({"get"}),
    "/version": frozenset({"get"}),
    "/v1/features/batch": frozenset({"post"}),
}

HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


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


def _validate_user_operations(spec: dict[str, Any]) -> None:
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI spec paths must be an object.")

    missing: list[str] = []
    for path, allowed_methods in USER_OPERATIONS.items():
        path_item = paths.get(path)
        if not isinstance(path_item, dict):
            missing.append(path)
            continue
        available_methods = {
            method for method in path_item if method in HTTP_METHODS
        }
        missing_methods = sorted(allowed_methods - available_methods)
        if missing_methods:
            missing.append(f"{path} [{', '.join(missing_methods)}]")
    if missing:
        details = "; ".join(sorted(missing))
        raise ValueError(f"USER_OPERATIONS drift: missing {details}")


def user_openapi_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return PinVi/user-facing subset spec from the full admin spec."""
    _validate_user_operations(spec)
    out = copy.deepcopy(spec)
    out["info"] = {
        **out.get("info", {}),
        "title": "kor-travel-map-user",
        "description": (
            "PinVi/user-facing subset of kor-travel-map OpenAPI. "
            "Internal admin/debug/ops routes are intentionally excluded."
        ),
    }
    filtered_paths: dict[str, Any] = {}
    for path, allowed_methods in USER_OPERATIONS.items():
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
    return _prune_schemas(out)


def _profile_spec(spec: dict[str, Any], profile: OpenApiProfile) -> dict[str, Any]:
    if profile == "admin":
        return spec
    return user_openapi_spec(spec)


def export(output: Path, *, profile: OpenApiProfile = "admin") -> dict[str, Any]:
    """Generate the selected OpenAPI spec and write it to `output`."""
    app = _load_app()
    spec = _profile_spec(app.openapi(), profile)
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
        _profile_spec(app.openapi(), profile),
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
        help="user/PinVi OpenAPI 저장/비교 대상 경로.",
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
    if args.check:
        failed = False
        for profile in profiles:
            failed = (
                bool(check(_output_for_profile(args, profile), profile=profile))
                or failed
            )
        return int(failed)
    for profile in profiles:
        output = _output_for_profile(args, profile)
        export(output, profile=profile)
        print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
