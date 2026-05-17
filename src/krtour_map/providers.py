from __future__ import annotations

CANONICAL_PROVIDER_NAMES: frozenset[str] = frozenset(
    {
        "python-kraddr-base",
        "python-kraddr-geo",
        "python-vworld-api",
        "python-visitkorea-api",
        "python-krmois-api",
        "python-opinet-api",
        "python-krex-api",
        "python-kma-api",
        "python-krairport-api",
        "python-khoa-api",
        "python-airkorea-api",
        "python-mcst-api",
        "python-krforest-api",
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
    "krex": "python-krex-api",
    "krforest": "python-krforest-api",
    "krmois": "python-krmois-api",
    "mcst": "python-mcst-api",
    "mois": "python-krmois-api",
    "opinet": "python-opinet-api",
    "pyairkorea": "python-airkorea-api",
    "pykma": "python-kma-api",
    "pykhoa": "python-khoa-api",
    "pykrairport": "python-krairport-api",
    "pykrex": "python-krex-api",
    "pykrforest": "python-krforest-api",
    "pykrmois": "python-krmois-api",
    "pyopinet": "python-opinet-api",
    "pyvworld": "python-vworld-api",
    "visitkorea": "python-visitkorea-api",
    "vworld": "python-vworld-api",
}


def normalize_provider_name(provider: str) -> str:
    normalized = provider.strip().lower().replace("_", "-")
    normalized = LEGACY_PROVIDER_ALIASES.get(normalized, normalized)
    if normalized not in CANONICAL_PROVIDER_NAMES:
        raise ValueError(f"Unsupported provider: {provider}")
    return normalized
