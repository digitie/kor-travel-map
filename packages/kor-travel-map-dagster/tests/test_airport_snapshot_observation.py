"""원 관측의 재현만 확인한다. Geo HTTP/DB/postprocess 실행은 없다."""

import json
from collections import Counter
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import (
    SnapshotArtifactPins,
    encode_provider_snapshot_artifact,
)
from kortravelmap.providers.kor_travel_transport import TransportAirport, TransportCoordinate
from kortravelmap.providers.kor_travel_transport_native import (
    AIRPORT_NAME_NORMALIZER_REVISION,
    TransportGeoEvidence,
    transport_item_to_native_bundle,
)

from kortravelmap.dagster import airport_snapshot_observation as observation
from kortravelmap.dagster.validation import (
    FeatureAddressIssue,
    FeatureAddressValidationSummary,
    validate_feature_bundles_address,
)

_PINS = SnapshotArtifactPins(
    "a" * 40,
    "b" * 64,
    "kor-travel-transport",
    "transport_airports",
    "airport",
    AIRPORT_NAME_NORMALIZER_REVISION,
    "transport-airport-geo-v1",
    "aware-clock-preserved-v1",
)
_AT = datetime(2026, 10, 25, 3, 2, 1, 123456, tzinfo=UTC)
_VERSION, _DATA = "dv1-" + "1" * 32, "dd1-" + "2" * 32


async def _artifact(count=1, *, geo=True, warning=False, mixed_clock=False, error=False):
    bundles = []
    for n in range(count):
        municipality = None if error else "서울특별시 종로구" if warning else "서울"
        item = TransportAirport(
            f"P{n:02}",
            "공항",
            "Airport",
            "ZZZZ",
            municipality,
            TransportCoordinate(lat=37.5, lon=127.0) if geo else None,
            {},
        )
        evidence = (
            TransportGeoEvidence(
                "resolved",
                _VERSION,
                _DATA,
                Address(bjd_code="1156011000", sigungu_name="기장군"),
                "0" * 64,
            )
            if geo
            else TransportGeoEvidence("not_requested")
        )
        bundles.append(await transport_item_to_native_bundle(item, fetched_at=_AT, geo=evidence))
    if mixed_clock:
        bundles[-1].source_record.fetched_at = _AT + timedelta(seconds=1)
    context = (
        GeoLoadContext(
            GeoApplied(reverse=True, geocode=False),
            DatasetRef(version_token=_VERSION, data_token=_DATA),
            {_DATA},
        )
        if geo
        else None
    )
    raw = encode_provider_snapshot_artifact(tuple(bundles), context, pins=_PINS)
    stats = (
        GeoCallStats(
            calls=Counter({"reverse": 1, "dataset_version": 0}),
            failures=Counter({"reverse": 0}),
            empty=Counter({"reverse_result": 0}),
            reuse=Counter({"skipped": count, "geocoded": 0}),
            observed_data_tokens={_DATA},
        )
        if geo
        else None
    )
    return raw, stats, tuple(bundles)


def _encode(artifact, stats, *, generation="root::retry:2", root="root", eof=True):
    return observation.encode_airport_observation_context(
        artifact,
        pins=_PINS,
        root_run_id=root,
        observation_generation=generation,
        upstream_eof=eof,
        geo_stats=stats,
    )


def _decode(raw, artifact, *, root="root", pins=_PINS):
    return observation.decode_airport_observation_context(
        raw,
        artifact,
        expected_pins=pins,
        expected_root_run_id=root,
    )


@pytest.mark.parametrize("warning", [False, True])
async def test_actual_fifteen_artifact_original_full_validation_and_stats_roundtrip(warning):
    artifact, stats, bundles = await _artifact(15, warning=warning)
    expected = validate_feature_bundles_address(bundles)
    assert expected.error_count == 0
    if warning:
        assert expected.warning_count == 15
        assert len(expected.issues) == 15
    raw = _encode(artifact, stats)
    result = _decode(raw, artifact)
    assert result.validation == expected
    assert result.fetched_at is result.artifact.bundles[0].source_record.fetched_at
    assert result.fetched_at == _AT
    assert result.observation_generation == "root::retry:2"
    assert result.root_run_id == "root"
    assert result.source_observations == 15
    assert result.dropped == 0
    assert result.upstream_eof is True
    assert result.validation_mode == "strict"
    assert len(raw) <= 8192
    assert result.geo_stats is not stats
    assert result.geo_stats.as_metadata() == stats.as_metadata()
    assert result.geo_stats.summary() == stats.summary()
    assert result.geo_stats.calls is not stats.calls
    assert dict(result.geo_stats.calls) == dict(stats.calls)  # explicit zero도 보존.
    assert dict(result.geo_stats.failures) == dict(stats.failures)
    assert dict(result.geo_stats.empty) == dict(stats.empty)
    assert dict(result.geo_stats.reuse) == dict(stats.reuse)
    assert result.geo_stats.observed_data_tokens is not stats.observed_data_tokens
    assert _encode(artifact, result.geo_stats) == raw
    stats.calls["reverse"] += 10
    stats.observed_data_tokens.clear()
    assert result.geo_stats.calls["reverse"] == 1
    assert result.geo_stats.observed_data_tokens == {_DATA}


async def test_full_validation_projection_covers_every_current_summary_and_issue_field():
    artifact, stats, _ = await _artifact(warning=True)
    value = json.loads(_encode(artifact, stats))
    assert set(value["validation"]) == {
        "total",
        "issue_count",
        "error_count",
        "warning_count",
        "full_summary_sha256",
    }
    assert {f.name for f in fields(FeatureAddressValidationSummary)} == {
        "total",
        "issue_count",
        "error_count",
        "warning_count",
        "issues",
        "evidence_grade_counts",
        "name_state_counts",
    }
    assert {f.name for f in fields(FeatureAddressIssue)} == {
        "feature_id",
        "source_record_key",
        "code",
        "severity",
        "message",
        "provider_address",
        "bjd_code",
        "sigungu_code",
    }


@pytest.mark.parametrize("generation", ["root", "root::retry:1", "root::retry:9223372036854775807"])
async def test_original_generation_is_separate_from_logical_root(generation):
    artifact, stats, _ = await _artifact()
    result = _decode(_encode(artifact, stats, generation=generation), artifact)
    assert result.root_run_id == "root"
    assert result.observation_generation == generation


@pytest.mark.parametrize(
    "bad",
    [
        "other",
        "other::retry:1",
        "root::retry:0",
        "root::retry:01",
        "root::retry:-1",
        "root::retry:9223372036854775808",
        "root ",
        "root::retry:1::retry:2",
        "x" * 161,
        True,
    ],
)
async def test_invalid_generation_or_root_is_not_normalized(bad):
    artifact, stats, _ = await _artifact()
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats, generation=bad)


@pytest.mark.parametrize("bad", [False, 1, None])
async def test_upstream_eof_is_only_explicit_true(bad):
    artifact, stats, _ = await _artifact()
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats, eof=bad)


async def test_original_fetched_at_must_be_exact_for_the_whole_artifact():
    artifact, stats, _ = await _artifact(2, mixed_clock=True)
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats)
    artifact, stats, bundles = await _artifact(2)
    bundles[-1].source_record.fetched_at = _AT.astimezone(timezone(timedelta(0), "GMT"))
    same_instant = encode_provider_snapshot_artifact(
        bundles, _decode(_encode(artifact, stats), artifact).artifact.geo, pins=_PINS
    )
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(same_instant, stats)


async def test_real_validation_errors_prevent_a_strict_drop_zero_context():
    artifact, stats, bundles = await _artifact(geo=False, error=True)
    assert validate_feature_bundles_address(bundles).error_count == 1
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats)


async def test_none_stats_and_empty_stats_and_geo_absence_are_distinct():
    artifact, _, _ = await _artifact(geo=False)
    absent = _encode(artifact, None)
    empty = _encode(artifact, GeoCallStats())
    assert absent != empty
    assert _decode(absent, artifact).geo_stats is None
    assert _decode(empty, artifact).geo_stats is not None
    assert _decode(empty, artifact).geo_stats.observed_data_tokens == set()


@pytest.mark.parametrize("bad", [None, frozenset({_DATA}), {"dd1-" + "3" * 32}])
async def test_stats_tokens_must_match_the_original_artifact_exactly(bad):
    artifact, stats, _ = await _artifact()
    stats.observed_data_tokens = bad
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats)


@pytest.mark.parametrize("field", ["calls", "failures", "empty", "reuse"])
@pytest.mark.parametrize("bad", [-1, True, 1.0, 2**63, "1"])
async def test_every_counter_rejects_noncanonical_values(field, bad):
    artifact, stats, _ = await _artifact()
    getattr(stats, field)["skipped" if field == "reuse" else "reverse"] = bad
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats)


@pytest.mark.parametrize("kind", ["counter", "key", "number", "run"])
async def test_foreign_counter_string_and_integer_hooks_are_never_called(kind):
    calls = []

    class ForeignCounter(Counter):
        def items(self):
            calls.append("items")
            raise RuntimeError("must not call")

    class ForeignString(str):
        def encode(self, *args, **kwargs):
            calls.append("encode")
            raise RuntimeError("must not call")

    class ForeignInt(int):
        def __lt__(self, other):
            calls.append("compare")
            raise RuntimeError("must not call")

    artifact, stats, _ = await _artifact()
    root = "root"
    if kind == "counter":
        stats.calls = ForeignCounter()
    elif kind == "key":
        stats.calls = Counter({ForeignString("reverse"): 1})
    elif kind == "number":
        stats.calls["reverse"] = ForeignInt(1)
    else:
        root = ForeignString("root")
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats, root=root)
    assert calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "root",
        "pins",
        "validation",
        "drop",
        "count",
        "mode",
        "extra",
        "duplicate",
        "whitespace",
    ],
)
async def test_context_is_exactly_bound_to_artifact_root_pins_and_recomputed_validation(mutation):
    artifact, stats, _ = await _artifact()
    raw = _encode(artifact, stats)
    data = json.loads(raw)
    if mutation == "hash":
        data["artifact_sha256"] = "0" * 64
    elif mutation == "root":
        with pytest.raises(observation.UnsupportedAirportObservation):
            _decode(raw, artifact, root="different-root")
        return
    elif mutation == "pins":
        with pytest.raises(observation.UnsupportedAirportObservation):
            _decode(raw, artifact, pins=replace(_PINS, code_revision="c" * 40))
        return
    elif mutation == "validation":
        data["validation"]["full_summary_sha256"] = "0" * 64
    elif mutation == "drop":
        data["dropped"] = 1
    elif mutation == "count":
        data["source_observations"] = 0
    elif mutation == "mode":
        data["validation_mode"] = "off"
    elif mutation == "extra":
        data["extra"] = True
    if mutation == "duplicate":
        raw = b'{"version":1,' + raw[1:]
    elif mutation == "whitespace":
        raw = json.dumps(data).encode()
    else:
        raw = observation._bytes(data)
    with pytest.raises(observation.UnsupportedAirportObservation):
        _decode(raw, artifact)


@pytest.mark.parametrize("raw", [b"[" * 1000, b"{}", b"\xff", b"x" * 8193, b'{"x":NaN}'])
async def test_invalid_context_bytes_fail_before_unbounded_parsing(raw):
    artifact, _, _ = await _artifact()
    with pytest.raises(observation.UnsupportedAirportObservation):
        _decode(raw, artifact)


async def test_validation_hash_projection_contains_all_current_fields_without_metadata_truncation(
    monkeypatch,
):
    artifact, stats, _ = await _artifact(warning=True)
    captured = []
    original_digest = observation._artifact_digest

    def record_projection(value):
        captured.append(value[1])
        return original_digest(value)

    monkeypatch.setattr(observation, "_artifact_digest", record_projection)
    raw = _encode(artifact, stats)
    result = _decode(raw, artifact)
    projection = captured[0]
    summary_fields = {field.name for field in fields(FeatureAddressValidationSummary)}
    assert set(projection) == summary_fields
    for name in summary_fields - {"issues"}:
        assert projection[name] == getattr(result.validation, name)
    for saved, issue in zip(projection["issues"], result.validation.issues, strict=True):
        assert saved == {
            field.name: getattr(issue, field.name) for field in fields(FeatureAddressIssue)
        }


async def test_geo_none_and_observed_none_are_not_implicitly_empty_stats():
    _, _, bundles = await _artifact(geo=False)
    geo = GeoLoadContext(GeoApplied(reverse=False, geocode=False), None, None)
    artifact = encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    result = _decode(_encode(artifact, None), artifact)
    assert result.artifact.geo is not None
    assert result.artifact.geo.observed_data_tokens is None
    assert result.geo_stats is None
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, GeoCallStats())


async def test_stats_set_with_artifact_frozenset_is_explicitly_outside_initial_context_subset():
    _, _, bundles = await _artifact(geo=False)
    geo = GeoLoadContext(GeoApplied(reverse=False, geocode=False), None, frozenset())
    artifact = encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, GeoCallStats())


async def test_empty_and_explicit_zero_counters_are_distinct():
    artifact, _, _ = await _artifact(geo=False)
    missing = _encode(artifact, GeoCallStats())
    zero = _encode(artifact, GeoCallStats(calls=Counter({"reverse": 0})))
    assert missing != zero
    assert dict(_decode(zero, artifact).geo_stats.calls) == {"reverse": 0}
    assert dict(_decode(missing, artifact).geo_stats.calls) == {}


async def test_counter_total_also_fits_pg_bigint():
    artifact, stats, _ = await _artifact()
    stats.calls = Counter({"reverse": 2**63 - 1, "geocode": 1})
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(artifact, stats)


async def test_different_artifact_bytes_with_same_scope_cannot_reuse_context():
    artifact, stats, _ = await _artifact()
    raw = _encode(artifact, stats)
    different, _, _ = await _artifact(2)
    with pytest.raises(observation.UnsupportedAirportObservation):
        _decode(raw, different)


async def test_named_utc_and_utc_singleton_clocks_are_not_silently_combined():
    artifact, stats, bundles = await _artifact(2)
    bundles[-1].source_record.fetched_at = _AT.astimezone(timezone(timedelta(0), "UTC"))
    geo = _decode(_encode(artifact, stats), artifact).artifact.geo
    altered = encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    with pytest.raises(observation.UnsupportedAirportObservation):
        _encode(altered, stats)
