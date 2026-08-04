"""kor-travel-map-api 단위 테스트 공용 fixture.

T-VN-32B 경계 alias 해석(`kortravelmap.api.feature_ref` →
`kortravelmap.infra.feature_identity.resolve_feature_identity`)은 모든
``/{feature_id}`` 경로 handler의 첫 줄에서 실행된다. 본 패키지 테스트는 DB가
없으므로(autouse) 해석을 **echo-resolve**로 대체한다 — 참조 문자열을 그대로
legacy 정본 키로 보고 uuid5 파생 쌍을 돌려주되, 형식 계약
(``validate_feature_ref`` — 빈 문자열/공백 패딩/길이 초과 422)은 실제 검증을
태운다. UUID 참조 해석·미해석 404 같은 특수 시나리오는 각 테스트가 이 patch를
자기 resolver로 덮어쓴다(테스트 내 ``monkeypatch.setattr``이 우선).

한계(적대 리뷰 F4-④): 이 autouse patch 때문에 **실 DB 기반 UUID 해석·404
회귀는 본 패키지 unit에서 잡히지 않는다** — 그 축의 실효 검증은
``tests/integration/test_feature_identity_boundary.py``(실 PostGIS)가 소유한다.
경로에 해석을 새로 붙일 때는 반드시 통합 쪽에도 회귀를 더해라.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _echo_feature_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.core.ids import feature_uuid_from_legacy
    from kortravelmap.infra import feature_identity

    async def _resolve(_session: Any, ref: str) -> feature_identity.FeatureIdentity:
        feature_identity.validate_feature_ref(ref)
        return feature_identity.FeatureIdentity(
            feature_id=ref,
            feature_uuid=str(feature_uuid_from_legacy(ref)),
        )

    monkeypatch.setattr(feature_identity, "resolve_feature_identity", _resolve)
