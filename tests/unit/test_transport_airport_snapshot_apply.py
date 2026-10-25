"""실제 codec/DB decoder와 실패 주입. PostgreSQL 실행이나 collector 활성화 증거는 아니다."""

import copy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from asyncpg.pgproto.pgproto import UUID as PgUUID

from kortravelmap.infra.provider_snapshot_artifact import encode_provider_snapshot_artifact
from kortravelmap.infra.provider_snapshot_result import decode_snapshot_apply_result
from kortravelmap.infra.transport_airport_evidence_reader import decode_transport_airport_evidence
from kortravelmap.providers import kor_travel_transport_apply as target
from kortravelmap.providers.kor_travel_transport_evidence import AirportReobservationPreparation
from tests.unit.test_provider_snapshot_artifact import _PINS
from tests.unit.test_transport_airport_preparation import _fixture


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def one(self):
        (row,) = self.rows
        return row


async def _case(monkeypatch, *, before_exists=False, after_exists=True, changed=False):
    wire, bundle = await _fixture()
    evidence = decode_transport_airport_evidence(15, wire)
    preparation = AirportReobservationPreparation(True, "unchanged_reobservation", evidence)
    payload = encode_provider_snapshot_artifact((bundle,), None, pins=_PINS)
    fid = UUID(wire["items"][0]["feature"]["feature_id"])
    saved, calls = [], []
    counter = 0

    async def execute(sql, args=None):
        nonlocal counter
        name = str(sql)
        calls.append(name)
        if "scalar_counter_state" in name:
            counter += 1
            return _Result(
                [
                    dict(
                        feature_id=PgUUID(str(fid)),
                        row_revision=1 if counter == 1 else 2,
                        record_exists=before_exists if counter == 1 else after_exists,
                    )
                ]
            )
        if "_bounded_provider_curation_input_set" in name:
            return _Result(
                [dict(capture_complete=True, input_member_count=1, source_input_set_hash="c" * 64)]
            )
        if "finish_provider_snapshot_apply" in name:
            saved.append(args["result"])
        return _Result([])

    fresh = copy.deepcopy(wire)
    if changed:
        fresh["items"][0]["feature"]["row_revision"] += 1

    async def scalar(sql, args=None):
        if "begin_provider_snapshot_apply" in str(sql):
            return {"snapshot_observation_generation": "original-root::retry:1"}
        return fresh

    session = SimpleNamespace(
        in_transaction=lambda: True,
        execute=AsyncMock(side_effect=execute),
        scalar=AsyncMock(side_effect=scalar),
    )
    begin = AsyncMock(return_value={"status": "applying"})
    validate, apply, finish = AsyncMock(), AsyncMock(return_value=[]), AsyncMock()
    monkeypatch.setattr(target, "lock_scoped_feature_write_protocol", AsyncMock())
    monkeypatch.setattr(target, "lock_provider_field_policy_epoch", AsyncMock())
    monkeypatch.setattr(target, "ensure_integrity_observation_run", AsyncMock())
    for name, stub in (
        ("_begin_batch", begin),
        ("_validate_batch_manifest", validate),
        ("_apply_batch_items", apply),
        ("_finish_batch", finish),
    ):
        monkeypatch.setattr(target.batch, name, stub)
    args = dict(
        pins=_PINS,
        snapshot_id=uuid4(),
        generation=1,
        fence=uuid4(),
        attempt_id=uuid4(),
        owner=uuid4(),
        manifest_digest="d" * 64,
    )
    return session, payload, preparation, args, saved, calls, apply, finish


@pytest.mark.parametrize("already_exists", [False, True])
async def test_original_counters_and_full_capture_are_saved_once(monkeypatch, already_exists):
    session, payload, preparation, args, saved, calls, apply, finish = await _case(
        monkeypatch, before_exists=already_exists
    )
    result = await target.apply_stored_airport_reobservation(session, payload, preparation, **args)
    assert result.load.features_updated == 1
    assert result.load.source_records_inserted == (0 if already_exists else 1)
    assert result.load.bundles_total == result.load.curation_input_member_count == 1
    assert (
        result.retired == result.load.source_links_inserted == result.load.geo_stamps_written == 0
    )
    assert len(saved) == 1
    assert decode_snapshot_apply_result(saved[0]) == result
    apply.assert_awaited_once()
    finish.assert_awaited_once()
    begin_call = next(
        c for c in session.scalar.await_args_list if "begin_provider" in str(c.args[0])
    )
    import hashlib

    assert begin_call.args[1]["artifact_sha"] == hashlib.sha256(payload).hexdigest()
    assert not hasattr(session, "commit")


async def test_fresh_evidence_changed_after_locks_does_not_apply_or_complete(monkeypatch):
    session, payload, preparation, args, saved, _, apply, finish = await _case(
        monkeypatch, changed=True
    )
    with pytest.raises(ValueError, match="changed after locking"):
        await target.apply_stored_airport_reobservation(session, payload, preparation, **args)
    apply.assert_not_awaited()
    finish.assert_not_awaited()
    assert saved == []


async def test_missing_actual_source_after_apply_cannot_be_saved_as_success(monkeypatch):
    session, payload, preparation, args, saved, _, apply, finish = await _case(
        monkeypatch, after_exists=False
    )
    with pytest.raises(ValueError, match="lacks original source"):
        await target.apply_stored_airport_reobservation(session, payload, preparation, **args)
    apply.assert_awaited_once()
    finish.assert_not_awaited()
    assert saved == []


async def test_apply_exception_propagates_without_kernel_or_receipt_completion(monkeypatch):
    session, payload, preparation, args, saved, _, apply, finish = await _case(monkeypatch)
    apply.side_effect = RuntimeError("injected source write failure")
    with pytest.raises(RuntimeError, match="injected"):
        await target.apply_stored_airport_reobservation(session, payload, preparation, **args)
    finish.assert_not_awaited()
    assert saved == []


@pytest.mark.parametrize("broken", ["payload", "pins", "preparation", "transaction"])
async def test_invalid_input_stops_before_lock_or_dml(monkeypatch, broken):
    session, payload, preparation, args, saved, calls, apply, finish = await _case(monkeypatch)
    if broken == "payload":
        payload += b" "
    elif broken == "pins":
        args["pins"] = replace(_PINS, code_revision="f" * 40)
    elif broken == "preparation":
        preparation = replace(preparation, eligible=False)
    else:
        session.in_transaction = lambda: False
    with pytest.raises(
        ValueError, match="invalid airport snapshot|complete unchanged|explicit caller"
    ):
        await target.apply_stored_airport_reobservation(session, payload, preparation, **args)
    assert not calls
    assert not saved
    apply.assert_not_awaited()
    finish.assert_not_awaited()


async def test_other_canonical_payload_cannot_reuse_eligible_preparation(monkeypatch):
    from kortravelmap.providers.kor_travel_transport import TransportAirport
    from kortravelmap.providers.kor_travel_transport_native import (
        TransportGeoEvidence,
        transport_item_to_native_bundle,
    )

    session, _, preparation, args, saved, _, apply, finish = await _case(monkeypatch)
    wire, original = await _fixture()
    genuine = await target.assess_transport_airport_reobservation_evidence(
        (original,), decode_transport_airport_evidence(15, wire)
    )
    assert genuine.eligible is True
    other = await transport_item_to_native_bundle(
        TransportAirport("P01", "변경", "TEST", None, None, None, {}),
        fetched_at=original.source_record.fetched_at,
        geo=TransportGeoEvidence("not_requested"),
    )
    payload = encode_provider_snapshot_artifact((other,), None, pins=_PINS)
    with pytest.raises(ValueError, match="requires EX: changed_raw_requires_ex"):
        await target.apply_stored_airport_reobservation(session, payload, genuine, **args)
    apply.assert_not_awaited()
    finish.assert_not_awaited()
    assert not saved
