"""``krtour.map.client`` — ``AsyncKrtourMapClient`` (라이브러리 진입점).

TripMate가 `pip install` 후 import하는 단일 진입점. SQLAlchemy 2 async
engine + provider client 인스턴스를 주입받아 메서드 호출로 사용.

**Sprint 2 PR에서 실제 코드 작성 예정** — 본 PR#17은 placeholder.

ADR 참조
--------
- ADR-002 — async-only (sync 인터페이스 추가 금지)
- ADR-003 — TripMate 연계는 함수 직접 호출 (REST 없음)
- ADR-020 — 본 모듈에 FastAPI/Uvicorn import 금지 (디버그 REST는 별도 패키지)

호출자 (TripMate) 측 사용 예시:
    from krtour.map.client import AsyncKrtourMapClient

    async with AsyncKrtourMapClient(
        engine=tripmate_engine,
        providers=provider_clients,
        file_store=file_store,
        settings=KrtourMapSettings(),
    ) as client:
        features = await client.features_in_bounds(bbox, kinds=["place"])
        weather = await client.build_weather_card(feature_id, asof=kst_now())
"""

from __future__ import annotations

__all__: list[str] = []
# Sprint 2에서 채워질 예정:
#   AsyncKrtourMapClient — features_in_bounds, features_nearby, get_feature,
#     load_feature_bundles, upload_feature_files, upsert_sync_state,
#     build_weather_card, ...
