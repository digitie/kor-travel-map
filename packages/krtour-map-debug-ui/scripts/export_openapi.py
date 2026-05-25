#!/usr/bin/env python3
"""Export OpenAPI spec for the krtour-map-debug-ui FastAPI app (ADR-031).

ADR-031 — Export/Drift gate 정책:
    - 본 패키지의 첫 FastAPI 라우터 등장 PR부터 즉시 활성화.
    - `openapi.json`을 저장소에 커밋 + DTO/라우터 변경 PR마다 갱신 강제.
    - CI: `--check` 옵션으로 git working tree와 비교 → drift 시 fail.
    - 사양은 docs/debug-ui-package.md §8 + docs/decisions.md ADR-031.

본 skeleton은 코드 작성 단계 진입 전 placeholder. 실제 `app` import는
krtour.map_debug_ui.app 모듈이 생성된 시점부터 동작한다 (Sprint 1).

Usage:
    # 1. spec 생성 + 저장
    python packages/krtour-map-debug-ui/scripts/export_openapi.py \\
        --output packages/krtour-map-debug-ui/openapi.json

    # 2. CI drift 검증 (변경 있으면 exit 1)
    python packages/krtour-map-debug-ui/scripts/export_openapi.py \\
        --check --output packages/krtour-map-debug-ui/openapi.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_app():
    """Import krtour.map_debug_ui.app:app lazily.

    코드 작성 단계 진입 전에는 모듈이 존재하지 않으므로 명시적 안내 메시지로
    실패한다. Sprint 1의 첫 라우터 PR에서 실제 import가 동작하기 시작한다.
    """
    try:
        from krtour.map_debug_ui.app import app  # type: ignore[import-not-found]
    except ModuleNotFoundError as e:
        raise SystemExit(
            "krtour.map_debug_ui 모듈이 아직 없습니다 (코드 작성 단계 진입 전).\n"
            "Sprint 1의 첫 FastAPI 라우터 PR에서 활성화됩니다.\n"
            f"원인: {e}"
        ) from e
    return app


def export(output: Path) -> dict:
    """Generate the FastAPI OpenAPI spec and write to `output`."""
    app = _load_app()
    spec = app.openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return spec


def check(output: Path) -> int:
    """Compare current FastAPI spec against `output`. Exit 1 if drift."""
    if not output.exists():
        print(f"missing: {output}", file=sys.stderr)
        print("hint: run without --check to generate first.", file=sys.stderr)
        return 1
    app = _load_app()
    current = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False)
    saved = output.read_text(encoding="utf-8")
    if current.strip() == saved.strip():
        return 0
    print(
        f"OpenAPI drift detected in {output}.\n"
        "  - Run scripts/export_openapi.py to regenerate, then commit.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("packages/krtour-map-debug-ui/openapi.json"),
        help="OpenAPI 저장/비교 대상 경로 (default: packages/krtour-map-debug-ui/openapi.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI 모드 — drift 발견 시 exit 1 (저장하지 않음)",
    )
    args = parser.parse_args(argv)

    if args.check:
        return check(args.output)
    export(args.output)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
