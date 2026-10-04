"""D2 api-audit의 **실패 경로**(restored) 계약 — 2026-10-04 prod 실측 행으로 결박한다.

2026-10-04 D2(run ``live-20261004102457-782ce6e6b79b``, Map a68c2b7d)는 main spec이
create 응답을 받지 못해 실패했다. spec의 ``finally``가 Feature를 ``{REASON}:cleanup``으로
retire했고, 그 retire가 ``lifecycle_state`` override를 ``reason=…:cleanup``으로 남겼다.
helper의 api-audit은 그 override에 ``…:retire``만 허용하고 완주 사슬
``initial → :suppress → :retire``만 받아서, **spec 실패 뒤에는 구조적으로 통과할 수
없었다.** 러너는 그것을 ``cleanup-failed``로 기록했고(원래는 ``test-failed-restored``),
``recover``도 같은 감사를 부르므로 BLOCKED가 영구화됐다.

아래 행은 그 run이 prod DB에 남긴 것을 그대로 옮겼다(비밀 없음 — id·이름·reason만).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "scripts" / "admin_feature_live_fixture.py"
_STATE = _ROOT / "scripts" / "admin_feature_live_state.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = _load("admin_feature_live_fixture_restored", _FIXTURE)
state = _load("admin_feature_live_state_restored", _STATE)

RUN_ID = "live-20261004102457-782ce6e6b79b"
FEATURE_ID = "01a1067c-a1c0-7e60-8687-88af9a2da41e"
REASON = f"tvn36-live-{RUN_ID}"
CREATE_COMMAND_ID = 100

_CREATE_PATHS = (
    "core.category",
    "core.coord",
    "core.coord_precision_digits",
    "core.marker_color",
    "core.marker_icon",
    "core.name",
)


def _feature_row() -> dict[str, Any]:
    return {
        "feature_id": FEATURE_ID,
        "feature_uuid": FEATURE_ID,
        "kind": "place",
        "name": f"E2E TVN36 state fixture {RUN_ID}",
        "category": "01070300",
        "lifecycle_state": "retired",
        "publication_state": "suppressed",
        "quality_state": "valid",
        "marker_icon": "marker",
        "marker_color": "P-02",
        "coord_precision_digits": 6,
        "lon": 127.5,
        "lat": 36.5,
    }


def _transition(
    kind: str,
    reason: str,
    before: tuple[str | None, str | None, str | None],
    after: tuple[str, str, str],
    causation: str | None,
) -> dict[str, Any]:
    return {
        "feature_id": FEATURE_ID,
        "feature_uuid": FEATURE_ID,
        "from_lifecycle_state": before[0],
        "from_publication_state": before[1],
        "from_quality_state": before[2],
        "to_lifecycle_state": after[0],
        "to_publication_state": after[1],
        "to_quality_state": after[2],
        "transition_kind": kind,
        "reason_code": reason,
        "principal": "admin",
        "causation_ref": causation,
        "provider_dataset_id": None,
        "source_entity_key": None,
        "source_record_key": None,
        "provider_evidence": None,
    }


_INITIAL = _transition(
    "initial",
    "admin_feature_create",
    (None, None, None),
    ("active", "published", "valid"),
    f"domain-command:{CREATE_COMMAND_ID}",
)
_SUPPRESS = _transition(
    "admin",
    f"{REASON}:suppress",
    ("active", "published", "valid"),
    ("active", "suppressed", "valid"),
    None,
)


def _retire(suffix: str, *, after_suppress: bool) -> dict[str, Any]:
    before = ("active", "suppressed" if after_suppress else "published", "valid")
    return _transition(
        "admin", f"{REASON}:{suffix}", before, ("retired", "suppressed", "valid"), None
    )


def _override(field_path: str, reason: str, *, lifecycle: bool = False) -> dict[str, Any]:
    return {
        "feature_id": FEATURE_ID,
        "field_path": field_path,
        "status": "active",
        "reason": reason,
        "created_by": "admin",
        "command_id": None if lifecycle else CREATE_COMMAND_ID,
        "base_revision": None,
        "prevent_provider_reactivation": lifecycle,
        "revoked_at": None,
        "revoked_by": None,
        "revoked_reason": None,
        "source_record_key": None,
        "source_provider_dataset_id": None,
        "source_entity_key": None,
        "source_raw_payload_hash": None,
    }


def _overrides(lifecycle_reason: str) -> list[dict[str, Any]]:
    rows = [_override(path, f"{REASON}:create") for path in _CREATE_PATHS]
    rows.append(_override("lifecycle_state", lifecycle_reason, lifecycle=True))
    return rows


def _commands(state_commands: int) -> list[dict[str, Any]]:
    rows = [
        {
            "command_id": CREATE_COMMAND_ID,
            "actor": "admin",
            "operation": fixture._ADMIN_CREATE_OPERATION,
            "response_status": 201,
            "subject_feature_uuid": FEATURE_ID,
        }
    ]
    for offset in range(state_commands):
        rows.append(
            {
                "command_id": CREATE_COMMAND_ID + 1 + offset,
                "actor": "admin",
                "operation": fixture._ADMIN_STATE_OPERATION,
                "response_status": 200,
                "subject_feature_uuid": FEATURE_ID,
            }
        )
    return rows


class _Result:
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self._rows = list(rows)

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[Mapping[str, Any]]:
        return list(self._rows)


class _Session:
    """api-audit이 읽는 네 SQL만 아는 가짜 세션. 모르는 SQL은 실패시킨다."""

    def __init__(
        self,
        *,
        features: list[dict[str, Any]],
        transitions: list[dict[str, Any]],
        overrides: list[dict[str, Any]],
        commands: list[dict[str, Any]],
    ) -> None:
        self._by_sql = {
            fixture._API_OWNED_FEATURE_SQL: features,
            fixture._API_OWNED_TRANSITION_SQL: transitions,
            fixture._API_OWNED_OVERRIDE_SQL: overrides,
            fixture._API_OWNED_COMMAND_SQL: commands,
        }

    async def execute(self, clause: Any, params: Any = None) -> _Result:
        return _Result(self._by_sql[clause.text])


@pytest.fixture(autouse=True)
def _fk_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """단일 열 FK 감사는 override 행 수만큼만 본다(이 lane은 alias를 만들지 않는다)."""

    async def fake(session: _Session, feature_ids: tuple[str, ...]) -> dict[str, int]:
        overrides = session._by_sql[fixture._API_OWNED_OVERRIDE_SQL]
        return {"ops.feature_overrides.feature_id": len(overrides) if feature_ids else 0}

    monkeypatch.setattr(fixture, "_foreign_key_reference_counts", fake)


def _observed_2026_10_04() -> _Session:
    """prod에 남은 그대로: create → spec ``finally``의 cleanup retire."""

    return _Session(
        features=[_feature_row()],
        transitions=[_INITIAL, _retire("cleanup", after_suppress=False)],
        overrides=_overrides(f"{REASON}:cleanup"),
        commands=_commands(1),
    )


def _audit(session: _Session, expect: str) -> Any:
    return asyncio.run(fixture._audit_api_owned(session, RUN_ID, expect=expect))


def test_the_observed_failed_run_passes_the_restored_audit() -> None:
    counts, foreign_keys, uuids, ids = _audit(_observed_2026_10_04(), "restored")
    assert counts == {
        "domain_commands": 2,
        "features": 1,
        "field_overrides": 7,
        "state_transitions": 2,
    }
    assert foreign_keys == {"ops.feature_overrides.feature_id": 7}
    assert uuids == (FEATURE_ID,)
    assert ids == (FEATURE_ID,)


def test_the_observed_failed_run_still_fails_the_complete_audit() -> None:
    """green 경로의 엄격함은 그대로다 — 실패한 run은 완료 감사를 통과하지 못한다."""

    with pytest.raises(RuntimeError, match="완료 API-owned 행 집합이 예상과 다릅니다"):
        _audit(_observed_2026_10_04(), "complete")


def test_the_lifecycle_override_reason_is_bound_to_the_retiring_transition() -> None:
    """``:cleanup``으로 은퇴했는데 override가 ``:retire``라고 말하면 거짓 증거다."""

    session = _Session(
        features=[_feature_row()],
        transitions=[_INITIAL, _retire("cleanup", after_suppress=False)],
        overrides=_overrides(f"{REASON}:retire"),
        commands=_commands(1),
    )
    with pytest.raises(RuntimeError, match="API-owned field override 소유권이 다릅니다"):
        _audit(session, "restored")


def test_a_lifecycle_override_without_a_retiring_transition_is_rejected() -> None:
    session = _Session(
        features=[_feature_row()],
        transitions=[_INITIAL, _SUPPRESS],
        overrides=_overrides(f"{REASON}:retire"),
        commands=_commands(1),
    )
    with pytest.raises(RuntimeError):
        _audit(session, "restored")


def test_suppress_then_cleanup_is_a_restored_shape() -> None:
    session = _Session(
        features=[_feature_row()],
        transitions=[_INITIAL, _SUPPRESS, _retire("cleanup", after_suppress=True)],
        overrides=_overrides(f"{REASON}:cleanup"),
        commands=_commands(2),
    )
    counts, *_ = _audit(session, "restored")
    assert counts["state_transitions"] == 3
    with pytest.raises(RuntimeError, match="완료 API-owned 행 집합이 예상과 다릅니다"):
        _audit(session, "complete")


def test_the_green_run_shape_passes_both_audits() -> None:
    def session() -> _Session:
        return _Session(
            features=[_feature_row()],
            transitions=[_INITIAL, _SUPPRESS, _retire("retire", after_suppress=True)],
            overrides=_overrides(f"{REASON}:retire"),
            commands=_commands(2),
        )

    expected = {
        "domain_commands": 3,
        "features": 1,
        "field_overrides": 7,
        "state_transitions": 3,
    }
    assert _audit(session(), "complete")[0] == expected
    assert _audit(session(), "restored")[0] == expected


def test_a_run_that_never_created_its_feature_is_restored_empty() -> None:
    session = _Session(features=[], transitions=[], overrides=[], commands=[])
    counts, foreign_keys, uuids, ids = _audit(session, "restored")
    assert counts == {
        "domain_commands": 0,
        "features": 0,
        "field_overrides": 0,
        "state_transitions": 0,
    }
    assert uuids == ()
    assert ids == ()
    assert not any(foreign_keys.values())
    with pytest.raises(RuntimeError, match="완료 API-owned 행 집합이 예상과 다릅니다"):
        _audit(session, "complete")


def test_a_cleanup_chain_with_a_missing_state_command_is_rejected() -> None:
    session = _Session(
        features=[_feature_row()],
        transitions=[_INITIAL, _retire("cleanup", after_suppress=False)],
        overrides=_overrides(f"{REASON}:cleanup"),
        commands=_commands(0),
    )
    with pytest.raises(RuntimeError):
        _audit(session, "restored")


def test_an_unknown_expectation_is_rejected() -> None:
    with pytest.raises(ValueError, match="api-audit expectation must be one of"):
        _audit(_observed_2026_10_04(), "lenient")


# ── 검증기 쪽 ────────────────────────────────────────────────────────────────


def _write_api_audit(tmp_path: Path, counts: dict[str, int], references: int) -> Path:
    path = tmp_path / "direct-api-audit.json"
    uuids = [FEATURE_ID] if counts["features"] else []
    path.write_text(
        json.dumps(
            {
                "action": "api-audit",
                "counts": counts,
                "feature_ids": uuids,
                "feature_uuids": uuids,
                "foreign_key_constraints_checked": 21,
                "foreign_key_references": references,
                "version": 1,
            }
        )
    )
    os.chmod(path, 0o600)
    return path


@pytest.fixture
def _root_owned_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """검증기의 root:root 0600 소유 검사는 이 테스트의 대상이 아니다."""

    monkeypatch.setattr(state, "_read_root_json", lambda path: json.loads(Path(path).read_text()))


_OBSERVED_COUNTS = {
    "domain_commands": 2,
    "features": 1,
    "field_overrides": 7,
    "state_transitions": 2,
}
_COMPLETE_COUNTS = {
    "domain_commands": 3,
    "features": 1,
    "field_overrides": 7,
    "state_transitions": 3,
}


@pytest.mark.usefixtures("_root_owned_reads")
def test_the_recovery_validator_accepts_the_observed_restored_evidence(
    tmp_path: Path,
) -> None:
    path = _write_api_audit(tmp_path, _OBSERVED_COUNTS, 7)
    assert state._validate_api_audit(path, allow_restored=True) == _OBSERVED_COUNTS


@pytest.mark.usefixtures("_root_owned_reads")
def test_the_normal_validator_still_requires_the_complete_evidence(
    tmp_path: Path,
) -> None:
    path = _write_api_audit(tmp_path, _OBSERVED_COUNTS, 7)
    with pytest.raises(ValueError, match="direct evidence mismatch"):
        state._validate_api_audit(path, allow_restored=False)
    complete = _write_api_audit(tmp_path, _COMPLETE_COUNTS, 7)
    assert state._validate_api_audit(complete, allow_restored=False) == _COMPLETE_COUNTS


@pytest.mark.usefixtures("_root_owned_reads")
def test_the_recovery_validator_rejects_counts_no_restored_chain_can_produce(
    tmp_path: Path,
) -> None:
    impossible = {
        "domain_commands": 3,
        "features": 1,
        "field_overrides": 7,
        "state_transitions": 2,
    }
    path = _write_api_audit(tmp_path, impossible, 7)
    with pytest.raises(ValueError, match="direct evidence mismatch"):
        state._validate_api_audit(path, allow_restored=True)


# ── 배선 ─────────────────────────────────────────────────────────────────────

_RUNNER = _ROOT / "scripts" / "run-admin-feature-live-acceptance.sh"
_SUPERVISOR = _ROOT / "scripts" / "admin_feature_live_supervisor.py"


def _shell_function(name: str) -> str:
    source = _RUNNER.read_text(encoding="utf-8")
    start = source.index(f"\n{name}() {{\n")
    return source[start : source.index("\n}\n", start)]


def test_the_normal_lane_audits_restored_only_when_the_spec_failed() -> None:
    body = _shell_function("run_new")
    executor = body.index("run_executor executor-main")
    choice = body.index("(( test_status == 0 )) || api_audit_expect=restored")
    audit = body.index(
        'run_helper api-audit "$RUNTIME_DIR/direct-api-audit.json" "$api_audit_expect"'
    )
    assert executor < choice < audit
    assert "local api_audit_expect=complete" in body


def test_the_recovery_lane_always_audits_restored() -> None:
    body = _shell_function("recover_run")
    assert 'run_helper api-audit "$RUNTIME_DIR/direct-api-audit.json" restored' in body
    assert "api_audit_expect" not in body


def test_the_supervisor_forwards_the_expectation_to_the_helper() -> None:
    source = _SUPERVISOR.read_text(encoding="utf-8")
    assert '"--helper-audit-expect", choices=("complete", "restored")' in source
    assert 'helper_extra = [] if expect is None else ["--expect", expect]' in source
    assert "*helper_extra," in source
    assert '("complete", "restored")' in _FIXTURE.read_text(encoding="utf-8")
