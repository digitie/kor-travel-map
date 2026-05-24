from __future__ import annotations

CANONICAL_PROVIDER_NAMES: frozenset[str] = frozenset(
    {
        "python-kraddr-base",
        "python-kraddr-geo",
        "python-visitkorea-api",
        "python-krmois-api",
        "python-opinet-api",
        "python-krex-api",
        "python-kma-api",
        "python-krairport-api",
        "python-khoa-api",
        "python-datagokr-api",
        "python-airkorea-api",
        "python-mcst-api",
        "python-krforest-api",
        "python-krheritage-api",
        "data.go.kr-standard",
        "google-places-api-new",
        "kakao-local-api",
        "naver-search-api",
        "manual",
        "system",
    }
)

LEGACY_PROVIDER_ALIASES: dict[str, str] = {
    "airkorea": "python-airkorea-api",
    "kex": "python-krex-api",
    "kma": "python-kma-api",
    "khoa": "python-khoa-api",
    "krairport": "python-krairport-api",
    "datagokr": "python-datagokr-api",
    "krex": "python-krex-api",
    "krforest": "python-krforest-api",
    "kheritage": "python-krheritage-api",
    "krheritage": "python-krheritage-api",
    "krmois": "python-krmois-api",
    "mcst": "python-mcst-api",
    "mois": "python-krmois-api",
    "opinet": "python-opinet-api",
    "pyairkorea": "python-airkorea-api",
    "pykma": "python-kma-api",
    "pykhoa": "python-khoa-api",
    "pykrairport": "python-krairport-api",
    "pydatagokr": "python-datagokr-api",
    "pykrex": "python-krex-api",
    "pykrforest": "python-krforest-api",
    "pykheritage": "python-krheritage-api",
    "pykrheritage": "python-krheritage-api",
    "pykrmois": "python-krmois-api",
    "pyopinet": "python-opinet-api",
    "datagokr-standard": "data.go.kr-standard",
    "data-go-kr-standard": "data.go.kr-standard",
    "data.go.kr.standard": "data.go.kr-standard",
    "standard-data": "data.go.kr-standard",
    "google-places": "google-places-api-new",
    "google-places-new": "google-places-api-new",
    "kakao": "kakao-local-api",
    "kakao-local": "kakao-local-api",
    "naver": "naver-search-api",
    "naver-local": "naver-search-api",
    "naver-search": "naver-search-api",
    "visitkorea": "python-visitkorea-api",
    "python-kheritage-api": "python-krheritage-api",
}


def normalize_provider_name(provider: str) -> str:
    normalized = provider.strip().lower().replace("_", "-")
    normalized = LEGACY_PROVIDER_ALIASES.get(normalized, normalized)
    if normalized not in CANONICAL_PROVIDER_NAMES:
        raise ValueError(f"Unsupported provider: {provider}")
    return normalized
