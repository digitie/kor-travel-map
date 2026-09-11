"""kor-travel-map-api 단위 테스트 공용 fixture.

T-VN-32B 경계 alias 해석(`kortravelmap.api.feature_ref` →
`kortravelmap.infra.feature_identity.resolve_feature_identity`)은 모든
``/{feature_id}`` 경로 handler의 첫 줄에서 실행된다. 본 패키지 테스트는 DB가
없으므로(autouse) 해석을 **echo-resolve**로 대체한다 — 참조를 :func:`canonical_ref`가
정하는 정본 키(uuid)로 풀되, 형식 계약
(``validate_feature_ref`` — 빈 문자열/공백 패딩/길이 초과 422)은 실제 검증을
태운다. 미해석 404/422 같은 특수 시나리오는 각 테스트가 이 patch를
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

**T-VN-39-ECHO 뒤 이 echo는 재키 뒤 세계를 모사한다.** 종전에는 ``feature_id=ref``,
즉 참조 문자열이 곧 정본 키이던 시절의 등식이었고 그래서 "legacy 주소가 정본 uuid로
바뀌어 repo로 내려가는가"를 **관측할 수 없었다**. 지금은 :func:`canonical_ref`가 그
사상을 세운다 — legacy 주소는 결정적 파생 uuid로, 이미 uuid인 참조는 그대로.

남은 한계 하나는 그대로다: echo는 **모든** 참조를 "해석 성공"으로 만들기 때문에
"어떤 Feature도 가리키지 않는 참조가 422가 되는가"
(:func:`~kortravelmap.infra.feature_identity.canonical_feature_id_for_filter`)는
여기서 관측되지 않는다. 그 축을 재는 테스트는 **자기 resolver를 설치해야 한다** —
위 규약대로 테스트 안 ``monkeypatch.setattr``이 이 patch를 덮는다.
"""

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


from typing import Any

import pytest


def canonical_ref(ref: str) -> str:
    """이 패키지의 테스트가 쓰는 **재키 뒤** 참조 → 정본 uuid 규약.

    309 뒤 ``features.feature_id``는 uuid다. 그래서 legacy ``f_*`` 주소를 경계에
    넣으면 돌아오는 정본 키는 그 문자열이 **아니라** uuid이고, 이미 uuid인 참조는
    그대로 정본 키다. DB 없는 이 패키지에서 그 사상을 결정적으로 세우는 것이
    :func:`feature_uuid_from_legacy`다 — 저장 계약(0083 비파생 v7)이 아니라
    테스트 편의 규약이며, 실효 검증은 통합이 소유한다
    (``tests/integration/test_feature_identity_boundary.py``).

    테스트가 응답의 feature 키를 단언할 때 원문 참조 대신 이 함수를 쓴다.
    """
    from kortravelmap.core.ids import feature_uuid_from_legacy
    from kortravelmap.infra import feature_identity

    if feature_identity.is_canonical_uuid_ref(ref):
        return ref
    return str(feature_uuid_from_legacy(ref))


@pytest.fixture(autouse=True)
def _echo_feature_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.infra import feature_identity

    def _identity_of(ref: str) -> feature_identity.FeatureIdentity:
        # 309 뒤 두 슬롯은 같은 ``features.feature_id``에서 나온다 — 같은 값이다.
        canonical = canonical_ref(ref)
        return feature_identity.FeatureIdentity(
            feature_id=canonical,
            feature_uuid=canonical,
        )

    async def _resolve(_session: Any, ref: str) -> feature_identity.FeatureIdentity:
        feature_identity.validate_feature_ref(ref)
        return _identity_of(ref)

    async def _resolve_bulk(
        _session: Any, refs: Any
    ) -> dict[str, feature_identity.FeatureIdentity]:
        # T-VN-32C PR-2 — write/scope·batch 경계의 일괄 해석도 echo-resolve.
        # 모든 참조가 해석되는 세계이므로 "미해석 422/missing" 시나리오는 각
        # 테스트가 자기 resolver로 덮어쓴다 (단건 patch와 같은 규약).
        resolved: dict[str, feature_identity.FeatureIdentity] = {}
        for ref in refs:
            feature_identity.validate_feature_ref(ref)
            resolved[ref] = _identity_of(ref)
        return resolved

    async def _uuid_map(_session: Any, feature_ids: Any) -> dict[str, str]:
        # 309 뒤 이 사상은 존재하는 정본 키에 대한 **항등**이다(정규화가 실질).
        return {
            feature_id: canonical_ref(feature_id)
            for feature_id in feature_ids
            if feature_id
        }

    monkeypatch.setattr(feature_identity, "resolve_feature_identity", _resolve)
    monkeypatch.setattr(
        feature_identity, "resolve_feature_identities_bulk", _resolve_bulk
    )
    monkeypatch.setattr(feature_identity, "get_feature_uuid_map", _uuid_map)
