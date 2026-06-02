"""Dagster asset에서 재사용하는 FeatureBundle 검증 + DB 적재 helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dagster import Failure

from krtour.map_dagster.validation import (
    FeatureAddressValidationSummary,
    validate_feature_bundles_address,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from dagster import AssetExecutionContext
    from krtour.map.client import AsyncKrtourMapClient
    from krtour.map.dto import FeatureBundle
    from krtour.map.infra.feature_repo import FeatureLoadResult


@dataclass(frozen=True)
class DagsterFeatureLoadResult:
    """Dagster provider load asset 결과."""

    provider: str
    dataset_key: str
    feature_ids: tuple[str, ...]
    load: FeatureLoadResult
    address_validation: FeatureAddressValidationSummary

    def as_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "feature_ids": list(self.feature_ids),
            "bundles_total": self.load.bundles_total,
            "features_inserted": self.load.features_inserted,
            "features_updated": self.load.features_updated,
            "source_records_inserted": self.load.source_records_inserted,
            "source_links_inserted": self.load.source_links_inserted,
            "source_links_updated": self.load.source_links_updated,
        }
        metadata.update(self.address_validation.as_metadata())
        return metadata


async def load_feature_bundles_for_dagster(
    *,
    context: AssetExecutionContext,
    client: AsyncKrtourMapClient,
    bundles: Sequence[FeatureBundle],
    provider: str,
    dataset_key: str,
    strict_address: bool = True,
) -> DagsterFeatureLoadResult:
    """주소/좌표 검증 후 ``AsyncKrtourMapClient``로 PostGIS에 적재한다."""
    validation = validate_feature_bundles_address(bundles)
    if strict_address and validation.has_errors:
        _add_output_metadata(context, validation.as_metadata())
        codes = ", ".join(
            issue.code for issue in validation.issues if issue.severity == "error"
        )
        raise Failure(
            description=f"Feature 주소/좌표 검증 실패: {codes}",
            metadata=validation.as_metadata(),
        )

    load = await client.load_feature_bundles(bundles)
    result = DagsterFeatureLoadResult(
        provider=provider,
        dataset_key=dataset_key,
        feature_ids=tuple(bundle.feature.feature_id for bundle in bundles),
        load=load,
        address_validation=validation,
    )
    _add_output_metadata(context, result.as_metadata())
    return result


def _add_output_metadata(
    context: AssetExecutionContext, metadata: Mapping[str, object]
) -> None:
    try:
        context.add_output_metadata(metadata)
    except Exception as exc:
        if exc.__class__.__name__ != "DagsterInvalidPropertyError":
            raise
