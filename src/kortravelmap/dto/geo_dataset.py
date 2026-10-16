"""geo 데이터셋 식별과 run의 geo 사용 신호 — 지오코딩 스탬프의 입력 DTO (ADR-109 결정 1~3).

``DatasetRef``는 kor-travel-geo가 답을 계산한 **로컬 데이터셋**의 식별이다(geo ADR-069 D7).
``data_token``(``dd1-`` + 32 hex)이 변화 신호다 — **동등성으로만** 비교한다. ``version_token``
(``dv1-``)은 릴리스 행의 식별이라 같은 데이터의 재빌드에도 바뀐다. 관측용이다.

``GeoApplied``는 호출자가 "이 run이 ``reverse_geocoder=``/``address_resolver=``를 실제로 넘겼는가"를
알리는 run 신호다 — outcome 판정의 첫 입력이다(``docs/etl/address-geocoding.md`` §2).

``GeoAttemptEvidence``는 MOIS처럼 행마다 "reverse를 시도했는가·geocode를 시도해 코드를 받았는가"를
변환 단계에서 아는 provider가 넘기는 행 증거다(판정 표 ②).

이 셋을 ``geocoding`` 층이 아니라 ``dto``에 두는 이유: ``infra``(스탬프 repo)가 import한다 —
``geocoding``에 두면 ``infra → geocoding`` 역행이다(ADR-109 결정 2, ``lint-imports``).
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DATA_TOKEN_PATTERN",
    "VERSION_TOKEN_PATTERN",
    "DatasetRef",
    "GeoApplied",
    "GeoAttemptEvidence",
    "GeoLoadContext",
    "ReverseOutcome",
]

#: geo 계약의 토큰 형식(geo ``dto/v2.py`` ``_VERSION_TOKEN_PATTERN``·``_DATA_TOKEN_PATTERN``).
#: migration 407의 CHECK와 같은 식이다 — 형식이 틀린 값이 비교 키가 되면 모든 행이 영구 stale이다.
VERSION_TOKEN_PATTERN: Final[str] = r"^dv1-[0-9a-f]{32}$"
DATA_TOKEN_PATTERN: Final[str] = r"^dd1-[0-9a-f]{32}$"

ReverseOutcome = Literal["called", "geocoded", "not_called"]
"""스탬프의 ``reverse_outcome``. ``not_called``만 토큰 비교 대상이 아니다(ADR-109 결정 1)."""


class DatasetRef(BaseModel):
    """geo 답의 근거 데이터셋.

    ``data_token``이 None이면 "변화를 판정할 수 없다"이지 "바뀌었다"가 아니다.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    version_token: str = Field(pattern=VERSION_TOKEN_PATTERN)
    data_token: str | None = Field(default=None, pattern=DATA_TOKEN_PATTERN)


class GeoApplied(BaseModel):
    """run 신호 — 이 run이 geo 콜러블을 실제로 넘겼는가."""

    model_config = ConfigDict(frozen=True)

    reverse: bool
    geocode: bool


class GeoAttemptEvidence(BaseModel):
    """행 단위 geo 시도 증거(MOIS 판정 표 ②).

    ``geocode_obtained_code``는 geocode를 시도해 법정동코드를 **받았는가**다 — 시도만 하고 못 받은
    행은 geo 유도 값이 0개라 ``not_called``다(판정 표 ④와 같은 결과 기준). "받았다"가 "시도했다"를
    함의하므로 시도 여부는 따로 두지 않는다 — 판정에 쓰이지 않는 필드는 틀려도 아무것도
    빨개지지 않는다.
    """

    model_config = ConfigDict(frozen=True)

    reverse_attempted: bool
    geocode_obtained_code: bool = False


@dataclass(frozen=True)
class GeoLoadContext:
    """적재 경로가 받는 run의 geo 입력 — 사용 신호·run-scoped 현재 토큰·관측 토큰(ADR-109).

    ``observed_data_tokens``는 run의 ``GeoCallStats.observed_data_tokens``를 **그대로
    가리키는**(복사가 아닌) 집합이다 — 적재 시점까지 응답에서 본 토큰이 다 들어 있다. 그 안에 현재
    토큰과 다른 값이 하나라도 있으면 이 run은 데이터셋 전환을 가로질렀다는 뜻이고, 그때
    :meth:`effective_token`은 None이다 — stale 분기·스탬프 쓰기를 하지 않는다(옛 데이터로 해석한
    행이 새 토큰으로 봉인되는 것을 막는 안전 방향; 다음 계획이 다시 고른다).

    geo를 쓰는 run(``geo_applied``의 어느 쪽이든 참)이 관측 집합을 넘기지 않으면(None) 전환을
    볼 수 없으므로 :meth:`effective_token`은 None이다(fail closed). geo를 전혀 쓰지 않는 run은
    관측할 것이 없으니 None이 빈 집합과 같다.
    """

    geo_applied: GeoApplied
    current_dataset: DatasetRef | None = None
    observed_data_tokens: AbstractSet[str] | None = None

    def effective_token(self) -> str | None:
        """이 적재에서 비교·스탬프에 쓸 토큰. 없거나, 전환을 가로질렀거나, 볼 수 없으면 None."""
        if self.current_dataset is None or self.current_dataset.data_token is None:
            return None
        token = self.current_dataset.data_token
        observed = self.observed_data_tokens
        if observed is None:
            uses_geo = self.geo_applied.reverse or self.geo_applied.geocode
            return None if uses_geo else token
        if any(seen != token for seen in observed):
            return None
        return token
