"""실제 codec/DB decoder와 실패 주입. PostgreSQL 실행이나 collector 활성화 증거는 아니다."""

import copy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from asyncpg.pgproto.pgproto import UUID as PgUUID

from kortravelmap.infra.provider_snapshot_result import decode_snapshot_apply_result
from kortravelmap.infra.rest_area_snapshot_artifact import encode_rest_area_snapshot_artifact
from kortravelmap.infra.transport_rest_evidence_reader import decode_transport_rest_evidence
from kortravelmap.providers import kor_travel_rest_apply as target
from kortravelmap.providers.kor_travel_rest_evidence import RestReobservationPreparation
from tests.unit.test_transport_rest_preparation import _PINS, _fixture


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
    wire, bundle, geo = await _fixture()
    evidence = decode_transport_rest_evidence(15, wire)
    preparation = RestReobservationPreparation(True, "unchanged_reobservation", evidence)
    payload = encode_rest_area_snapshot_artifact((bundle,), geo, pins=_PINS)
    fid = UUID(wire["items"][0]["feature"]["feature_id"])
    saved, calls = [], []
    counter = 0

    async def execute(sql, args=None):
        nonlocal counter
        name = str(sql)
        calls.append(name)
        if name.startswith("SELECT name,setting FROM pg_settings"):
            return _Result(
                [("statement_timeout", "30000"), ("lock_timeout", "1000"), ("jit", "on")]
            )
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
        if "capture_provider_snapshot_apply_input_set" in name:
            return _Result([dict(input_member_count=1, source_input_set_hash="c" * 64)])
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
    result = await target.apply_stored_rest_area_reobservation(
        session, payload, preparation, **args
    )
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
        await target.apply_stored_rest_area_reobservation(session, payload, preparation, **args)
    apply.assert_not_awaited()
    finish.assert_not_awaited()
    assert saved == []


async def test_missing_actual_source_after_apply_cannot_be_saved_as_success(monkeypatch):
    session, payload, preparation, args, saved, _, apply, finish = await _case(
        monkeypatch, after_exists=False
    )
    with pytest.raises(ValueError, match="lacks original source"):
        await target.apply_stored_rest_area_reobservation(session, payload, preparation, **args)
    apply.assert_awaited_once()
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
        ValueError,
        match="invalid rest-area snapshot artifact|complete unchanged|explicit caller",
    ):
        await target.apply_stored_rest_area_reobservation(session, payload, preparation, **args)
    assert not calls
    assert not saved
    apply.assert_not_awaited()
    finish.assert_not_awaited()


async def test_airport_pins_cannot_select_rest_apply(monkeypatch):
    from tests.unit.test_provider_snapshot_artifact import _PINS as airport_pins

    session, payload, prep, args, saved, calls, apply, finish = await _case(monkeypatch)
    args["pins"] = airport_pins
    with pytest.raises(ValueError, match="invalid rest-area snapshot artifact"):
        await target.apply_stored_rest_area_reobservation(session, payload, prep, **args)
    assert calls == saved == []
    apply.assert_not_awaited()
    finish.assert_not_awaited()


async def test_forged_eligible_preparation_does_not_authorize_changed_canonical_value(monkeypatch):
    session, _, prep, args, saved, _, apply, finish = await _case(monkeypatch)
    _, bundle, geo = await _fixture()
    forged = bundle.model_copy(deep=True)
    forged.feature.name = "FORGED NAME"
    payload = encode_rest_area_snapshot_artifact((forged,), geo, pins=_PINS)
    with pytest.raises(ValueError, match="requires EX: current_bundle_not_canonical"):
        await target.apply_stored_rest_area_reobservation(session, payload, prep, **args)
    assert saved == []
    apply.assert_not_awaited()
    finish.assert_not_awaited()


@pytest.mark.parametrize(
    ("prior_statement", "prior_lock", "expected_statement", "expected_lock"),
    [(30000, 1000, 3000, 1000), (750, 250, 750, 250), (0, 0, 3000, 1000)],
)
@pytest.mark.parametrize("prior_jit", ["on", "off"])
async def test_locked_reader_has_its_own_server_cap_then_restores_caller_before_apply(
    monkeypatch, prior_statement, prior_lock, expected_statement, expected_lock, prior_jit
):
    session, payload, preparation, args, _, _, apply, _ = await _case(monkeypatch)
    settings = {
        "statement_timeout": str(prior_statement), "lock_timeout": str(prior_lock), "jit": prior_jit
    }
    original = dict(settings)
    execute, scalar = session.execute.side_effect, session.scalar.side_effect
    events = []

    async def bounded_execute(sql, params=None):
        statement = str(sql)
        if statement.startswith("SELECT name,setting FROM pg_settings"):
            events.append("save")
            return _Result(list(settings.items()))
        if "FROM pg_settings JOIN" in statement:
            events.append("lower")
            for name, cap in (
                ("statement_timeout", params["statement"]),
                ("lock_timeout", params["lock"]),
            ):
                settings[name] = str(min(int(settings[name]) or cap, cap))
            return _Result([])
        if statement == "SELECT set_config(:name,:value,true)":
            events.append(
                "jit-off"
                if params == {"name": "jit", "value": "off"} and "reader" not in events
                else "restore:" + params["name"]
            )
            settings[params["name"]] = params["value"]
            return _Result([])
        return await execute(sql, params)

    async def bounded_scalar(sql, params=None):
        if "read_transport_rest_snapshot_evidence" in str(sql):
            events.append("reader")
            assert settings == {
                "statement_timeout": str(expected_statement),
                "lock_timeout": str(expected_lock),
                "jit": "off",
            }
        return await scalar(sql, params)

    async def apply_after_restore(*args, **kwargs):
        assert settings == original
        events.append("apply")
        return []

    session.execute.side_effect = bounded_execute
    session.scalar.side_effect = bounded_scalar
    apply.side_effect = apply_after_restore
    await target.apply_stored_rest_area_reobservation(session, payload, preparation, **args)
    assert events == [
        "save",
        "lower",
        "jit-off",
        "reader",
        "restore:statement_timeout",
        "restore:lock_timeout",
        "restore:jit",
        "apply",
    ]
    assert settings == original


@pytest.mark.parametrize("cancel", [False, True])
async def test_locked_reader_failure_keeps_original_error_and_requires_outer_rollback(
    monkeypatch, cancel
):
    import asyncio

    session, payload, preparation, args, saved, _, apply, finish = await _case(monkeypatch)
    execute, scalar = session.execute.side_effect, session.scalar.side_effect
    events = []
    error = asyncio.CancelledError() if cancel else RuntimeError("owned reader SQL failure")

    async def execute_before_failure(sql, params=None):
        statement = str(sql)
        if statement.startswith("SELECT name,setting FROM pg_settings"):
            events.append("save")
            return _Result(
                [("statement_timeout", "30000"), ("lock_timeout", "1000"), ("jit", "on")]
            )
        if "FROM pg_settings JOIN" in statement:
            events.append("lower")
            return _Result([])
        if statement == "SELECT set_config(:name,:value,true)":
            if params == {"name": "jit", "value": "off"}:
                events.append("jit-off")
                return _Result([])
            pytest.fail("aborted/cancelled SQL must not be followed by restoration SQL")
        return await execute(sql, params)

    async def failing_reader(sql, params=None):
        if "read_transport_rest_snapshot_evidence" in str(sql):
            events.append("reader")
            raise error
        return await scalar(sql, params)

    session.execute.side_effect = execute_before_failure
    session.scalar.side_effect = failing_reader
    with pytest.raises(type(error)) as raised:
        await target.apply_stored_rest_area_reobservation(session, payload, preparation, **args)
    assert raised.value is error
    assert events == ["save", "lower", "jit-off", "reader"]
    apply.assert_not_awaited()
    finish.assert_not_awaited()
    assert saved == []


async def test_decoded_artifact_still_requires_bounded_geo_context(monkeypatch):
    session, _, prep, args, saved, _, apply, finish = await _case(monkeypatch)
    from kortravelmap.dto.geo_dataset import GeoApplied, GeoLoadContext

    _, bundle, _ = await _fixture()
    geo = GeoLoadContext(GeoApplied(reverse=False, geocode=False), None,
                         {f"{n:064x}" for n in range(33)})
    payload = encode_rest_area_snapshot_artifact((bundle,), geo, pins=_PINS)
    with pytest.raises(ValueError, match="invalid canonical rest Geo context"):
        await target.apply_stored_rest_area_reobservation(session, payload, prep, **args)
    assert saved == []
    apply.assert_not_awaited()
    finish.assert_not_awaited()
