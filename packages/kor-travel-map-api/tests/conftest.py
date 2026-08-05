"""kor-travel-map-api 단위 테스트 공용 fixture.

T-VN-32B 경계 alias 해석(`kortravelmap.api.feature_ref` →
`kortravelmap.infra.feature_identity.resolve_feature_identity`)은 모든
``/{feature_id}`` 경로 handler의 첫 줄에서 실행된다. 본 패키지 테스트는 DB가
없으므로(autouse) 해석을 **echo-resolve**로 대체한다 — 참조 문자열을 그대로
legacy 정본 키로 보고 짝이 되는 uuid를 돌려주되, 형식 계약
(``validate_feature_ref`` — 빈 문자열/공백 패딩/길이 초과 422)은 실제 검증을
태운다. UUID 참조 해석·미해석 404 같은 특수 시나리오는 각 테스트가 이 patch를
자기 resolver로 덮어쓴다(테스트 내 ``monkeypatch.setattr``이 우선).

``feature_uuid_from_legacy``를 쓰는 이유는 **파생이 계약이라서가 아니라
결정적 mock이 필요해서**다 — 참조 문자열 하나로 테스트가 기대 uuid를 다시
계산할 수 있어 fixture 배선이 없어도 된다. 실제 저장 계약은 0083(T-VN-32C)
이후 **비파생 UUIDv7**이고(``core.ids.make_feature_uuid``), 파생 등식은 더
이상 어느 계층에서도 강제되지 않는다. 이 patch가 만드는 값을 "정본 규칙"으로
읽으면 안 된다.

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
        # 결정적 mock 값 — 저장 계약(0083 비파생 v7)이 아니라 테스트 편의 규약.
        return feature_identity.FeatureIdentity(
            feature_id=ref,
            feature_uuid=str(feature_uuid_from_legacy(ref)),
        )

    async def _resolve_bulk(
        _session: Any, refs: Any
    ) -> dict[str, feature_identity.FeatureIdentity]:
        # T-VN-32C PR-2 — write/scope·batch 경계의 일괄 해석도 echo-resolve.
        # 모든 참조가 해석되는 세계이므로 "미해석 422/missing" 시나리오는 각
        # 테스트가 자기 resolver로 덮어쓴다 (단건 patch와 같은 규약).
        resolved: dict[str, feature_identity.FeatureIdentity] = {}
        for ref in refs:
            feature_identity.validate_feature_ref(ref)
            resolved[ref] = feature_identity.FeatureIdentity(
                feature_id=ref,
                feature_uuid=str(feature_uuid_from_legacy(ref)),
            )
        return resolved

    async def _uuid_map(_session: Any, feature_ids: Any) -> dict[str, str]:
        # additive 병행 노출(weather batch 등)용 legacy id → uuid map echo.
        return {
            feature_id: str(feature_uuid_from_legacy(feature_id))
            for feature_id in feature_ids
            if feature_id
        }

    monkeypatch.setattr(feature_identity, "resolve_feature_identity", _resolve)
    monkeypatch.setattr(
        feature_identity, "resolve_feature_identities_bulk", _resolve_bulk
    )
    monkeypatch.setattr(feature_identity, "get_feature_uuid_map", _uuid_map)
