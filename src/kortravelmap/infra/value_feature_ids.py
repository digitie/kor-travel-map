"""값 적재(weather·price)가 받은 feature 참조를 **정본 키**로 고정한다.

## 왜 이 모듈이 있는가

`WeatherValue.feature_id`·`PriceValue.feature_id`는 provider 변환기가 채운다. 그
변환기는 `make_feature_id(...)`가 유도한 legacy `f_*`밖에 알지 못한다 — ADR-098
뒤 정본 키는 **서버가 적재 시점에 발급**하고, 변환은 적재보다 먼저 일어나기
때문이다.

그런데 T-VN-39가 `feature.feature_weather_values.feature_id`와
`feature.feature_price_values.feature_id`를 uuid로 옮겼다. 그래서 재키 뒤
운영 경로(dagster asset · kma_weather · API etl fixture · `load_air_quality`)가
값을 적재하면 전부 22P02다. SQL의 **모양은 옳으므로** head Parse 오라클
(`tests/integration/test_product_sql_parses_against_head.py`)이 볼 수 없는
부류다 — 틀린 것은 문장이 아니라 값이다.

## 왜 producer가 아니라 여기서 고치나

세 가지 이유다.

1. **producer는 정본 키를 알 수 없다.** `load_air_quality`는 측정소 bundle 적재와
   값 적재를 한 transaction에 묶는 것이 존재 이유이고, 값이 참조할 정본 키는 그
   transaction 안의 `load_bundles`가 발급한다. 호출자가 미리 알 방법이 없다.
2. **값 키를 흔들지 않는다.** `make_weather_value_key`/`make_price_value_key`는
   `feature_id`를 해시 입력에 넣는다. producer가 넘기는 값을 canonical로 바꾸면
   기존 행 전체의 키가 달라져 다음 적재가 통째로 중복이 된다. 여기서 바꾸는 것은
   **컬럼에 들어가는 값**뿐이고 키는 producer가 만든 그대로다.
3. **한 자리에서 모든 producer를 덮는다.** 네 경로가 같은 결함을 갖고 있었다.

## 무엇을 받아들이나

legacy `f_*`와 canonical uuid를 **둘 다** 받는다 — 해석 우선순위는
:func:`kortravelmap.infra.feature_identity.resolve_feature_identities_bulk`가
정한다(uuid 정본 조회 → alias fallback). 테스트는 이미 canonical을 넘기고 운영은
legacy를 넘기므로 둘 다 받는 것이 사실에 맞다.

해석되지 않는 참조는 **조용히 넘기지 않는다.** 그대로 두면 FK 위반으로 죽는데,
그 오류는 "어느 참조가 문제인지" 말하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["UnresolvedValueFeatureRefError", "resolve_value_feature_ids"]


class UnresolvedValueFeatureRefError(ValueError):
    """값이 가리키는 Feature 참조를 정본 키로 풀지 못했다."""


async def resolve_value_feature_ids(
    session: AsyncSession, refs: Iterable[str]
) -> Mapping[str, str]:
    """``ref → canonical uuid`` 표. 왕복은 참조 개수와 무관하게 2회다."""
    from kortravelmap.infra.feature_identity import resolve_feature_identities_bulk

    unique = sorted({ref for ref in refs})
    if not unique:
        return {}
    identities = await resolve_feature_identities_bulk(session, unique)
    missing = [ref for ref in unique if ref not in identities]
    if missing:
        raise UnresolvedValueFeatureRefError(
            "값이 가리키는 Feature를 정본 키로 풀지 못했습니다: "
            + ", ".join(missing[:5])
            + (f" 외 {len(missing) - 5}건" if len(missing) > 5 else "")
        )
    return {ref: identities[ref].feature_id for ref in unique}
