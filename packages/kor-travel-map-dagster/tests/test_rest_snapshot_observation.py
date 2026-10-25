"""단일 window/원 관측은 보존하고 위조·시각/EOF 손실은 거부한다. HTTP/PG0."""

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.rest_area_snapshot_artifact import encode_rest_area_snapshot_artifact
from kortravelmap.providers.kor_travel_transport import TransportCollection, TransportRestArea
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)
from kortravelmap.providers.krex import rest_area_natural_key

from kortravelmap.dagster import rest_snapshot_observation as target

_AT = datetime(2026, 10, 25, 5, 0, 1, 123456, tzinfo=UTC)
_PINS = SnapshotArtifactPins(
    "a" * 40,
    "b" * 64,
    "kor-travel-transport",
    "transport_rest_areas",
    "rest_area",
    "transport-rest-area-name-phones-v1",
    "transport-rest-area-geo-v1",
    "aware-clock-preserved-v1",
)


async def _artifact(count=1, *, resolved=False):
    bundles = []
    for i in range(count):
        item = TransportRestArea(
            "pending",
            f"휴게소{i}",
            "경부선",
            "상행",
            127.0 if resolved else None,
            37.5 if resolved else None,
            "031-123-4567",
            None,
            None,
            None,
            {},
        )
        item = replace(item, natural_key=rest_area_natural_key(item))
        bundles.append(
            await transport_item_to_native_bundle(
                item,
                fetched_at=_AT,
                geo=(
                    TransportGeoEvidence(
                        "resolved",
                        "dv1-" + "1" * 32,
                        "dd1-" + "2" * 32,
                        Address(bjd_code="1156011000"),
                        "0" * 64,
                    )
                    if resolved
                    else TransportGeoEvidence("not_requested")
                ),
            )
        )
    geo = (
        GeoLoadContext(
            GeoApplied(reverse=True, geocode=False),
            DatasetRef(version_token="dv1-" + "1" * 32, data_token="dd1-" + "2" * 32),
            {"dd1-" + "2" * 32},
        )
        if resolved
        else None
    )
    artifact = encode_rest_area_snapshot_artifact(tuple(bundles), geo, pins=_PINS)
    window = target.RestExportWindow(
        count,
        1024,
        "c" * 64,
        _AT,
        TransportCollection("krex_rest_area", _AT - timedelta(seconds=1), False, False),
    )
    return artifact, window, tuple(bundles)


def _encode(artifact, window):
    return target.encode_rest_observation_context(
        artifact,
        pins=_PINS,
        root_run_id="root",
        observation_generation="root::retry:2",
        upstream_eof=True,
        geo_stats=None,
        export_window=window,
    )


async def test_original_clock_window_and_lossless_canonical_recovery():
    artifact, window, bundles = await _artifact(2)
    raw = _encode(artifact, window)
    restored = target.decode_rest_observation_context(
        raw,
        artifact,
        expected_pins=_PINS,
        expected_root_run_id="root",
    )
    assert restored.export_window == window
    assert restored.fetched_at == _AT
    assert restored.observation_generation == "root::retry:2"
    assert restored.source_observations == 2
    assert restored.dropped == 0
    assert restored.artifact.bundles == bundles
    assert restored.artifact.bundles[0] is not bundles[0]
    assert len(raw) <= 8192
    assert _encode(artifact, window) == raw


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("export_window", "has_more"), True),
        (("export_window", "next_cursor"), "next"),
        (("export_window", "item_count"), 2),
        (("export_window", "limit"), 1000),
        (("export_window", "path"), "/other"),
        (("export_window", "body_bytes"), 2097153),
        (("export_window", "body_sha256"), "invalid"),
        (("export_window", "captured_at"), "2026-10-25T05:00:02+00:00"),
        (("export_window", "collection", "source"), "other"),
        (("export_window", "collection", "failed"), True),
        (("export_window", "collection", "stale"), True),
        (("export_window", "collection", "last_success_at"), "2026-10-25T05:00:00"),
        (("export_window", "collection", "last_success_at"), "2026-10-25T06:00:00+00:00"),
        (("upstream_eof",), False),
        (("source_observations",), 2),
        (("observation_generation",), "other-root"),
        (("validation", "full_summary_sha256"), "0" * 64),
    ],
)
async def test_forged_window_clock_count_generation_and_validation_fail_closed(path, value):
    artifact, window, _ = await _artifact()
    data = json.loads(_encode(artifact, window))
    location = data
    for key in path[:-1]:
        location = location[key]
    location[path[-1]] = value
    forged = target._bytes(data)
    with pytest.raises(target.UnsupportedRestObservation):
        target.decode_rest_observation_context(
            forged,
            artifact,
            expected_pins=_PINS,
            expected_root_run_id="root",
        )


async def test_missing_export_object_or_duplicate_key_is_not_eof_proof():
    artifact, window, _ = await _artifact()
    data = json.loads(_encode(artifact, window))
    del data["export_window"]
    for raw in [target._bytes(data), b'{"version":1,' + _encode(artifact, window)[1:]]:
        with pytest.raises(target.UnsupportedRestObservation):
            target.decode_rest_observation_context(
                raw, artifact, expected_pins=_PINS, expected_root_run_id="root"
            )


async def test_original_geo_stats_and_tokens_restore_without_mutable_alias():
    artifact, window, _ = await _artifact(resolved=True)
    stats = GeoCallStats(
        calls=Counter({"reverse": 1}),
        failures=Counter({"reverse": 0}),
        empty=Counter({"reverse_result": 0}),
        reuse=Counter({"geocoded": 1}),
        observed_data_tokens={"dd1-" + "2" * 32},
    )
    raw = target.encode_rest_observation_context(
        artifact,
        pins=_PINS,
        root_run_id="root",
        observation_generation="root",
        upstream_eof=True,
        geo_stats=stats,
        export_window=window,
    )
    stats.calls["reverse"] = 99
    stats.observed_data_tokens.clear()
    restored = target.decode_rest_observation_context(
        raw, artifact, expected_pins=_PINS, expected_root_run_id="root"
    )
    assert restored.geo_stats.calls["reverse"] == 1
    assert restored.geo_stats.observed_data_tokens == {"dd1-" + "2" * 32}
    assert restored.artifact.geo.observed_data_tokens == {"dd1-" + "2" * 32}
