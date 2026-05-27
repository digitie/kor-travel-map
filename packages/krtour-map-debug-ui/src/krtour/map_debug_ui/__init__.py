"""``krtour.map_debug_ui`` — TripMate `python-krtour-map` 디버그/관리 UI 백엔드.

본 패키지는 `python-krtour-map` 메인 라이브러리와 **별도 distribution**이지만
같은 ``krtour`` PEP 420 implicit namespace를 공유한다 (ADR-022). 메인 패키지에
FastAPI/Uvicorn 의존을 강제하지 않기 위해 분리 (ADR-020).

운영 범위 (ADR-035, 2026-05-27 — ADR-005/020 amendment):
- ``/debug/...`` — 개발자용 (fixture replay, EXPLAIN 등)
- ``/admin/...`` — 운영자용 (jobs / dedup-review / backup, ADR-040)
- ``/ops/...`` — 옵저버빌리티 (consistency / metrics)
- ``/features/...`` — feature 조회 (디버그/공통)

인증/접근 제어는 네트워크 계층(Cloudflare Tunnel / SSO / IP allowlist)에 둔다.
패키지 자체에 인증 로직 침투 금지 (ADR-005 + ADR-035).

자세한 사양은 ``docs/debug-ui-package.md``.
"""

from __future__ import annotations

__version__: str = "0.2.0-dev"
"""distribution version. ``pyproject.toml`` `version`과 동기 유지."""

__all__ = ["__version__"]
