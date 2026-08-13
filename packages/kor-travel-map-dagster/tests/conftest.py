"""dagster 패키지 테스트 공통 설정."""

from __future__ import annotations

import os

# ADR-090 이후 ``KorTravelMapSettings.pg_dsn``에는 기본값이 없다 — 운영 process는
# 전용 runtime login DSN을 주입받아야 하고, 없으면 fail-closed다. 그 규칙은 옳지만
# 이 패키지의 테스트는 **DB에 붙지 않으면서** engine/DSN 경로를 지나므로 placeholder가
# 필요하다. 없으면 dependency 해석 단계에서 RuntimeError가 나 401/404 같은 단언이
# 500으로 바뀐다(실측: 이 주입 없이 api 41건·dagster 6건 실패).
#
# 도달 불가 주소를 쓴다 — 실수로라도 실 DB에 붙지 않는다. ``setdefault``라 명시적으로
# DSN을 준 실행(통합 테스트 등)은 그대로 우선한다. DSN **부재** 자체를 검증하는
# 테스트는 루트 ``tests/``에 있어 이 conftest의 영향을 받지 않는다.
os.environ.setdefault(
    "KOR_TRAVEL_MAP_PG_DSN",
    "postgresql+asyncpg://placeholder:placeholder@127.0.0.1:1/placeholder",
)

