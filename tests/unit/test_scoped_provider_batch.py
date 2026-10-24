"""batch 총예산/정렬·중복 계약은 DB와 각 item hash 전에 거부한다."""

from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.dto import Feature, FeatureBundle, PlaceDetail, SourceLink, SourceRecord
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra import scoped_provider_refresh as native

_AT = datetime(2026, 10, 24, 12, tzinfo=ZoneInfo("Asia/Seoul"))


def _item(index=1, *, raw_extra=None, dataset="batch-unit"):
    provider = "batch-unit-provider"
    raw = {"name": f"item-{index}", "phones": []}
    if raw_extra is not None:
        raw["extra"] = raw_extra
    payload_hash = make_payload_hash(raw)
    record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset,
        source_entity_type="place",
        source_entity_id=str(index),
        raw_payload_hash=payload_hash,
    )
    alias = make_feature_id(
        bjd_code=None,
        kind="place",
        category="01010100",
        source_type=provider,
        source_natural_key=str(index),
    )
    return batch.ProviderScalarRefreshItem(
        UUID(int=index),
        FeatureBundle(
            feature=Feature(
                feature_id=alias,
                provider_natural_key=str(index),
                kind="place",
                name=f"item-{index}",
                category="01010100",
                marker_icon="marker",
                marker_color="P-01",
                detail=PlaceDetail(feature_id=alias),
            ),
            source_record=SourceRecord(
                provider=provider,
                dataset_key=dataset,
                source_entity_type="place",
                source_entity_id=str(index),
                raw_data=raw,
                raw_payload_hash=payload_hash,
                source_record_key=record_key,
                fetched_at=_AT,
                imported_at=_AT,
            ),
            source_link=SourceLink(
                feature_id=alias,
                source_record_key=record_key,
                source_role="primary",
                match_method="fixture",
                confidence=100,
            ),
            provider_field_presence=ProviderFieldPresence(
                normalizer_revision="batch-unit-v1",
                supplied_fields={"core.name"},
            ),
        ),
    )


def _digest(items):
    return batch.scoped_provider_refresh_batch_input_digest(items, dataset_id=1, policy_revision=1)


def test_batch_digest_is_order_independent_and_canonical_uuid_bound():
    first, second = _item(1), _item(2)
    assert _digest([first, second]) == _digest([second, first])
    assert _digest([first, second]) != _digest(
        [first, batch.ProviderScalarRefreshItem(uuid4(), second.bundle)]
    )
    assert _digest([first]) != native.scoped_provider_refresh_input_digest(
        first.bundle, feature_id=first.feature_id, dataset_id=1, policy_revision=1
    )


@pytest.mark.parametrize("kind", ["empty", "uuid", "entity", "dataset"])
def test_empty_and_duplicate_identity_or_dataset_is_rejected(kind):
    first, second = _item(1), _item(2)
    items = {
        "empty": [],
        "uuid": [first, batch.ProviderScalarRefreshItem(first.feature_id, second.bundle)],
        "entity": [first, batch.ProviderScalarRefreshItem(second.feature_id, first.bundle)],
        "dataset": [first, _item(2, dataset="different")],
    }[kind]
    with pytest.raises(ValueError, match="empty|duplicate|one provider dataset"):
        _digest(items)


def test_infinite_iterable_stops_at_limit_plus_one_before_serialization(monkeypatch):
    reads = 0
    bundle = _item().bundle

    def items():
        nonlocal reads
        while True:
            reads += 1
            yield batch.ProviderScalarRefreshItem(UUID(int=reads), bundle)

    def forbidden(*args, **kwargs):
        pytest.fail("over-count iterable reached artifact encoding")

    monkeypatch.setattr(native, "_artifact_digest", forbidden)
    with pytest.raises(ValueError, match="bounded"):
        _digest(items())
    assert reads == batch._MAX_BATCH_ITEMS + 1


@pytest.mark.parametrize("kind", ["aggregate-bytes", "depth"])
def test_whole_budget_is_checked_before_any_individual_bundle_hash(monkeypatch, kind):
    extra = "x" * 600_000
    if kind == "depth":
        extra = {}
        for _ in range(70):
            extra = {"child": extra}
    items = [_item(1, raw_extra=extra), _item(2, raw_extra=extra)]

    def forbidden(*args, **kwargs):
        pytest.fail("whole-batch over-budget reached per-item raw/hash validation")

    monkeypatch.setattr(native, "scoped_provider_refresh_input_digest", forbidden)
    with pytest.raises(ValueError, match="budget|1 MiB"):
        _digest(items)


@pytest.mark.parametrize("field", ["dataset_id", "policy_revision"])
def test_batch_dataset_and_revision_require_positive_integer(field):
    for value in (0, -1, True, "1"):
        params = {"dataset_id": 1, "policy_revision": 1, field: value}
        with pytest.raises(ValueError, match="positive"):
            batch.scoped_provider_refresh_batch_input_digest([_item()], **params)
