"""``kortravelmap.core.providers`` — provider 이름 정규화 + canonical 카탈로그.

``CANONICAL_PROVIDER_NAMES``는 본 라이브러리가 알고 있는 모든 provider의
공식 명칭 (`python-*-api` 또는 `data.go.kr-standard` 등). provider raw에서
받는 이름을 본 카탈로그의 canonical name으로 정규화한다 (alias 매핑).

``docs/architecture/provider-contract.md §2`` + ADR-024 (canonical name) + ADR-028 (knps).

ADR 참조
--------
- ADR-024 — provider canonical name (`python-mois-api` 등 ``python-*-api``)
- ADR-028 — `python-knps-api` 등록
- ADR-029 — `@kor-travel-map/map-marker-react` npm 패키지 (Python측 카탈로그는 본 모듈)
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "CANONICAL_PROVIDER_NAMES",
    "PROVIDER_ALIASES",
    "normalize_provider_name",
    "is_known_provider",
]


CANONICAL_PROVIDER_NAMES: Final[tuple[str, ...]] = (
    # data.go.kr 표준데이터 — 본 라이브러리 내부 client
    "data.go.kr-standard",
    # python-*-api provider 라이브러리들 (ADR-024 canonical name)
    "python-visitkorea-api",
    "python-kma-api",
    "python-krheritage-api",
    "python-krforest-api",
    "python-knps-api",
    "python-krex-api",
    "python-khoa-api",
    "python-airkorea-api",
    "python-opinet-api",
    "python-mcst-api",
    "python-mois-api",  # ADR-024 — krmois → mois 정정
    "python-krairport-api",
    "python-kasi-api",
    "python-datagokr-api",
    # 외부 보강 (place phone enrichment 등)
    "kakao-local-api",
    "naver-search-api",
    "google-places-api-new",
    # 외부 app provider (kor-travel-concierge YouTube 장소 후보)
    "kor-travel-concierge-youtube",
)
"""본 라이브러리가 알고 있는 provider canonical name.

신규 provider 추가 시 본 tuple에 추가 + `PROVIDER_ALIASES`에 alias 매핑 +
ADR 작성 (`docs/adr/README.md`).
"""


PROVIDER_ALIASES: Final[dict[str, str]] = {
    # 과거 명칭 / 변형 → canonical 매핑.
    # ADR-024: krmois → python-mois-api
    "krmois": "python-mois-api",
    "pykrmois": "python-mois-api",
    "python-krmois-api": "python-mois-api",
    "mois": "python-mois-api",
    # 짧은 식별자.
    "visitkorea": "python-visitkorea-api",
    "tour_api": "python-visitkorea-api",
    "kma": "python-kma-api",
    "krheritage": "python-krheritage-api",
    "krforest": "python-krforest-api",
    "knps": "python-knps-api",
    "krex": "python-krex-api",
    "khoa": "python-khoa-api",
    "airkorea": "python-airkorea-api",
    "opinet": "python-opinet-api",
    "mcst": "python-mcst-api",
    "krairport": "python-krairport-api",
    "kasi": "python-kasi-api",
    "datagokr": "python-datagokr-api",
    "standard": "data.go.kr-standard",
    "data.go.kr": "data.go.kr-standard",
    # 외부 보강.
    "kakao": "kakao-local-api",
    "kakao_local": "kakao-local-api",
    "naver": "naver-search-api",
    "naver_search": "naver-search-api",
    "google": "google-places-api-new",
    "google_places": "google-places-api-new",
    # 외부 app provider.
    "kor-travel-concierge": "kor-travel-concierge-youtube",
    "kor_travel_concierge": "kor-travel-concierge-youtube",
    "kor_travel_concierge_youtube": "kor-travel-concierge-youtube",
    "youtube_place_candidates": "kor-travel-concierge-youtube",
}
"""provider name alias → canonical 매핑. provider raw에서 들어오는 다양한
표기를 단일 canonical로 정규화."""


def normalize_provider_name(value: str) -> str:
    """provider 이름을 canonical name으로 정규화.

    Parameters
    ----------
    value
        provider raw name (canonical / alias / 약식 모두 허용).

    Returns
    -------
    str
        canonical name (`CANONICAL_PROVIDER_NAMES`의 한 값).

    Raises
    ------
    ValueError
        ``value``가 빈 문자열이거나 canonical/alias 어느 것에도 매칭되지 않음.

    Examples
    --------
    >>> normalize_provider_name("python-knps-api")
    'python-knps-api'
    >>> normalize_provider_name("knps")
    'python-knps-api'
    >>> normalize_provider_name("krmois")  # ADR-024
    'python-mois-api'
    """
    if not value:
        raise ValueError("provider name은 비어 있을 수 없음.")
    # 1) 정확 canonical 매칭.
    if value in CANONICAL_PROVIDER_NAMES:
        return value
    # 2) alias 매칭.
    if value in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[value]
    # 3) 미지원 — 명시적 에러 (silent fallback 금지, ADR-006 정신).
    raise ValueError(
        f"알 수 없는 provider name: {value!r}. "
        "`CANONICAL_PROVIDER_NAMES` 또는 `PROVIDER_ALIASES`에 추가 필요. "
        "신규 provider는 ADR 작성 + 본 모듈 + `docs/architecture/provider-contract.md` 동기."
    )


def is_known_provider(value: str) -> bool:
    """provider name이 canonical 또는 alias로 알려진지 확인 (raise 없이)."""
    return value in CANONICAL_PROVIDER_NAMES or value in PROVIDER_ALIASES
