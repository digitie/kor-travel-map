from __future__ import annotations

from krtour_map.models import Feature, FeatureSummary


def summarize_feature(feature: Feature) -> FeatureSummary:
    providers = {ref.provider for ref in feature.raw_refs}
    return FeatureSummary(
        feature_id=feature.feature_id,
        kind=str(feature.kind),
        name=feature.name,
        category=feature.category,
        provider_count=len(providers),
        status=str(feature.status),
    )


def process_feature_response(feature: Feature) -> FeatureSummary:
    return summarize_feature(feature)
