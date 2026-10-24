"""DB/container 없이 측정 엔진의 고정 identity·counter·artifact 계약을 검증한다."""

from __future__ import annotations

import json

import pytest

from scripts._scoped_write_baseline_pg import (
    _container_sample,
    cpu_delta,
    feature_id,
    record,
    write_report,
)
from scripts.scoped_write_baseline import load_fixture


def test_shared_claims_are_n_to_one_but_independent_claims_are_not() -> None:
    point = load_fixture().points[0]
    assert feature_id("shared", "left", point) == feature_id("shared", "right", point)
    assert feature_id("independent", "left", point) != feature_id("independent", "right", point)


def test_replay_keeps_source_identity_payload_and_clock() -> None:
    fixture = load_fixture()
    point = fixture.points[0]
    seed = record("shared", "left", point, fixture, measured=False)
    first = record("shared", "left", point, fixture, measured=True)
    replay = record("shared", "left", point, fixture, measured=True)
    other = record("shared", "right", point, fixture, measured=True)
    assert first.model_dump() == replay.model_dump()
    assert seed.source_record_key != first.source_record_key
    assert first.source_entity_id == seed.source_entity_id
    assert first.raw_payload_hash == other.raw_payload_hash
    assert first.source_record_key != other.source_record_key
    assert first.fetched_at > seed.fetched_at


def test_cpu_counter_reset_is_failure_not_a_negative_saving() -> None:
    assert cpu_delta({"cpu_ns": 10}, {"cpu_ns": 20}) == 10 / 1_000_000_000
    with pytest.raises(RuntimeError, match="역행"):
        cpu_delta({"cpu_ns": 20}, {"cpu_ns": 10})


def test_completed_artifact_never_overwrites_an_existing_measurement(tmp_path) -> None:
    path = tmp_path / "report.json"
    write_report(path, {"passed": True})
    assert json.loads(path.read_text()) == {"passed": True}
    with pytest.raises(FileExistsError):
        write_report(path, {"passed": False})
    assert json.loads(path.read_text()) == {"passed": True}
    assert list(tmp_path.iterdir()) == [path]


async def test_external_docker_host_is_rejected_before_creating_resources(monkeypatch) -> None:
    from scripts._scoped_write_baseline_pg import run_baseline

    monkeypatch.setenv("DOCKER_HOST", "tcp://example.invalid:2375")
    with pytest.raises(RuntimeError, match="로컬 Unix"):
        await run_baseline(load_fixture())


def test_container_sample_is_one_shot_and_does_not_invent_lifetime_peak() -> None:
    class Fake:
        def stats(self, **kwargs):
            assert kwargs == {"stream": False, "one_shot": True}
            return {
                "cpu_stats": {"cpu_usage": {"total_usage": 10}},
                "memory_stats": {"usage": 20, "max_usage": 0},
            }

    assert _container_sample(Fake()) == {
        "cpu_ns": 10,
        "memory_bytes": 20,
        "lifetime_peak_bytes": None,
    }
