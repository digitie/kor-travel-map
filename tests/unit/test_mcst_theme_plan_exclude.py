"""ADR-121 R4 계획 제외(``--exclude <dataset>:<action>``) — 파싱·계획 내용·sha·실행기 준수.

R4 표본 판정(2026-11-23)에서 barrier_free·world_restaurants의 ``collapse``가 정밀도 게이트 0.97을
못 넘었다. 제외는 계획을 손으로 고치지 않고 그 쌍을 전환에서 빼는 정식 경로다.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, cast

import pytest

from kortravelmap.cli import mcst_theme_plan as plan_module
from kortravelmap.cli.main import build_parser
from kortravelmap.cli.mcst_theme_plan import (
    parse_exclusions,
    plan_report,
    run_mcst_theme_transition,
)
from kortravelmap.core.theme_attach import PlanEntry, PlanFeature
from kortravelmap.infra.mcst_theme_transition_repo import (
    TransitionBatchResult,
    TransitionItemOutcome,
    TransitionPlan,
    build_transition_plan,
    check_plan_exclusions,
    execute_transition_batch,
    load_transition_plan,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

_BF = "mcst_barrier_free_places_csv"
_WR = "mcst_world_restaurants_csv"
_FI = "mcst_family_infant_culture_facilities_csv"
_PET = "mcst_pet_friendly_culture_facilities_csv"


def _entries() -> list[PlanEntry]:
    return [
        PlanEntry("f-bf-attach", _BF, "attach", "m-1", {}),
        PlanEntry("f-bf-collapse", _BF, "collapse", "s-1", {}),
        PlanEntry("s-1", _FI, "keep", None, {}),
        PlanEntry("f-wr-collapse", _WR, "collapse", "s-2", {}),
        PlanEntry("s-2", _WR, "keep", None, {}),
        PlanEntry("f-fi-collapse", _FI, "collapse", "s-1", {}),
        PlanEntry("f-pet", _PET, "retire", None, {}),
        PlanEntry("f-amb", _FI, "ambiguous", None, {}),
    ]


def _build(exclusions: tuple[tuple[str, str], ...] = ()) -> TransitionPlan:
    return build_transition_plan(
        _entries(),
        revisions={entry.feature_id: 3 for entry in _entries()},
        rule_version="theme-attach-v1",
        exclusions=exclusions,
    )


_R4 = ((_BF, "collapse"), (_WR, "collapse"))


# --- 파싱 -----------------------------------------------------------------------------------


def test_parse_accepts_key_slug_and_short_slug() -> None:
    assert parse_exclusions(
        ["barrier_free_places:collapse", "world_restaurants_csv:collapse", f"{_PET}:retire"]
    ) == ((_BF, "collapse"), (_PET, "retire"), (_WR, "collapse"))
    assert parse_exclusions(None) == ()
    assert parse_exclusions([]) == ()


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("barrier_free_places", "<dataset>:<action>"),
        (":collapse", "<dataset>:<action>"),
        ("barrier_free_places:", "<dataset>:<action>"),
        ("barrier_free_places:keep", "action"),
        ("barrier_free_places:ambiguous", "action"),
        ("nope_list:collapse", "dataset"),
    ],
)
def test_parse_rejects_malformed(value: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_exclusions([value])


def test_parse_rejects_same_pair_in_any_spelling() -> None:
    with pytest.raises(ValueError, match="두 번"):
        parse_exclusions(["barrier_free_places:collapse", f"{_BF}:collapse"])


def test_cli_registers_repeatable_exclude_on_both_commands() -> None:
    parser = build_parser()
    plan_args = parser.parse_args(
        [
            "mcst-theme-plan",
            "--exclude",
            "barrier_free_places:collapse",
            "--exclude",
            "world_restaurants:collapse",
        ]
    )
    assert plan_args.exclude == ["barrier_free_places:collapse", "world_restaurants:collapse"]
    assert parser.parse_args(["mcst-theme-plan"]).exclude == []
    run_args = parser.parse_args(
        ["mcst-theme-transition", "plan.json", "--exclude", "barrier_free_places:collapse"]
    )
    assert run_args.exclude == ["barrier_free_places:collapse"]
    assert parser.parse_args(["mcst-theme-transition", "plan.json"]).exclude == []


# --- 계획 내용·sha ---------------------------------------------------------------------------


def test_excluded_pairs_are_recorded_with_original_action() -> None:
    plan = _build(_R4)
    assert plan.exclusions == _R4
    assert [(i.feature_id, i.action) for i in plan.items] == [
        ("f-bf-attach", "attach"),
        ("f-fi-collapse", "collapse"),
        ("f-pet", "retire"),
    ]
    assert [(i.feature_id, i.action, i.target_feature_id) for i in plan.excluded_items] == [
        ("f-bf-collapse", "collapse", "s-1"),
        ("f-wr-collapse", "collapse", "s-2"),
    ]
    payload = plan.as_json()
    assert payload["exclusions"] == [
        {"dataset_key": _BF, "action": "collapse"},
        {"dataset_key": _WR, "action": "collapse"},
    ]
    assert [raw["feature_id"] for raw in payload["excluded_items"]] == [
        "f-bf-collapse",
        "f-wr-collapse",
    ]
    assert load_transition_plan(payload) == plan


def test_plan_without_exclusions_round_trips_with_empty_records() -> None:
    plan = _build()
    assert plan.exclusions == ()
    assert plan.excluded_items == ()
    assert len(plan.items) == 5
    payload = plan.as_json()
    assert payload["exclusions"] == []
    assert payload["excluded_items"] == []
    assert load_transition_plan(payload) == plan


def test_sha_covers_exclusions() -> None:
    plain = _build()
    one = _build(((_BF, "collapse"),))
    two = _build(_R4)
    assert len({plain.plan_sha256, one.plan_sha256, two.plan_sha256}) == 3
    # 같은 제외는 순서·반복과 무관하게 같은 계획·sha.
    assert _build(((_WR, "collapse"), (_BF, "collapse"), (_BF, "collapse"))) == two
    # 아무 행도 빼지 않는 제외도 sha를 바꾼다(승인한 sha가 제외 범위까지 고정한다).
    empty_pair = _build(((_WR, "attach"),))
    assert empty_pair.items == plain.items
    assert empty_pair.excluded_items == ()
    assert empty_pair.plan_sha256 != plain.plan_sha256


def _with(payload: dict[str, Any], **changes: Any) -> dict[str, Any]:
    edited = copy.deepcopy(payload)
    edited.update(changes)
    return edited


def test_load_rejects_edited_exclusions() -> None:
    payload = _build(((_BF, "collapse"),)).as_json()
    # 제외를 지우고 행을 실행 목록으로 되돌린 계획은 모양은 맞아도 sha가 다르다.
    with pytest.raises(ValueError, match="plan_sha256"):
        load_transition_plan(
            _with(
                payload,
                exclusions=[],
                items=[*payload["items"], *payload["excluded_items"]],
                excluded_items=[],
            )
        )
    with pytest.raises(ValueError, match="제외 목록에 없는"):
        load_transition_plan(_with(payload, exclusions=[]))
    with pytest.raises(ValueError, match="실행 목록에 있다"):
        load_transition_plan(
            _with(payload, items=[*payload["items"], *payload["excluded_items"]])
        )
    with pytest.raises(ValueError, match="두 번"):
        load_transition_plan(
            _with(payload, excluded_items=payload["excluded_items"] * 2)
        )
    with pytest.raises(ValueError, match="정렬"):
        load_transition_plan(_with(payload, exclusions=payload["exclusions"] * 2))
    with pytest.raises(ValueError, match="제외할 수 없는"):
        load_transition_plan(
            _with(payload, exclusions=[{"dataset_key": _BF, "action": "keep"}])
        )
    # 같은 쌍의 행을 제외에서 몰래 빼 버린 계획도 sha가 다르다.
    with pytest.raises(ValueError, match="plan_sha256"):
        load_transition_plan(_with(payload, excluded_items=[]))


def test_load_rejects_old_format_without_exclusion_records() -> None:
    payload = _build().as_json()
    old = {k: v for k, v in payload.items() if k not in ("exclusions", "excluded_items")}
    with pytest.raises(ValueError, match="옛 형식"):
        load_transition_plan(old)


def test_build_refuses_remaining_item_targeting_excluded_feature() -> None:
    entries = [
        PlanEntry("x", _BF, "collapse", "s", {}),
        PlanEntry("y", _FI, "collapse", "x", {}),  # 계획기는 만들지 않는 모양(대상이 패자)
    ]
    with pytest.raises(ValueError, match="제외된 Feature를 대상"):
        build_transition_plan(
            entries,
            revisions={"x": 1, "y": 1},
            rule_version="theme-attach-v1",
            exclusions=((_BF, "collapse"),),
        )


def test_build_refuses_non_transition_action() -> None:
    with pytest.raises(ValueError, match="제외할 수 없는"):
        _build(((_BF, "keep"),))


def test_plan_report_records_exclusions_and_actual_retiring_count() -> None:
    features = [
        PlanFeature(
            feature_id=entry.feature_id,
            dataset_key=entry.dataset_key,
            name=entry.feature_id,
            created_at="1",
            place_list=False,
            pet_business=False,
            master_category_prefixes=None,
            candidates=(),
        )
        for entry in _entries()
    ]
    report = plan_report(features, _entries(), samples=0, exclusions=_R4)
    # 판정 숫자는 제외와 무관하다(표본 감사가 같은 숫자를 본다).
    assert report["by_dataset"][_BF] == {"attach": 1, "collapse": 1}
    assert report["exclusions"] == [
        {"dataset_key": _BF, "action": "collapse", "feature_count": 1},
        {"dataset_key": _WR, "action": "collapse", "feature_count": 1},
    ]
    assert report["retiring_feature_count"] == 3
    baseline = plan_report(features, _entries(), samples=0)
    assert baseline["retiring_feature_count"] == 5
    assert baseline["exclusions"] == []


# --- 실행기 ----------------------------------------------------------------------------------


def test_check_requires_exact_restatement() -> None:
    plan = _build(_R4)
    check_plan_exclusions(plan, ((_WR, "collapse"), (_BF, "collapse")))
    for stated in ((), ((_BF, "collapse"),), (*_R4, (_PET, "retire"))):
        with pytest.raises(ValueError, match="--exclude"):
            check_plan_exclusions(plan, stated)
    check_plan_exclusions(_build(), ())
    with pytest.raises(ValueError, match="--exclude"):
        check_plan_exclusions(_build(), ((_BF, "collapse"),))


class _Untouchable:
    """닿으면 실패한다 — 제외 불일치·제외 행은 DB에 닿기 전에 거부돼야 한다."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"touched: {name}")


@pytest.mark.parametrize("execute", [False, True])
async def test_transition_refuses_mismatched_exclusions_before_db(execute: bool) -> None:
    with pytest.raises(ValueError, match="--exclude"):
        await run_mcst_theme_transition(
            cast("AsyncEngine", _Untouchable()),
            plan=_build(((_BF, "collapse"),)),
            batch_size=10,
            execute=execute,
        )


async def test_execute_batch_refuses_excluded_item_before_any_write() -> None:
    plan = _build(((_BF, "collapse"),))
    [held] = plan.excluded_items
    with pytest.raises(ValueError, match="제외한 행"):
        await execute_transition_batch(
            cast("AsyncSession", _Untouchable()),
            plan=plan,
            batch_size=10,
            batch_index=0,
            items=(held,),
        )


class _Tx:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log.append("commit")

    async def rollback(self) -> None:
        self._log.append("rollback")


async def test_transition_runs_only_plan_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """리허설·실행·표본 리허설 모두 ``plan.items``만 batch로 넘기고 제외 행은 넘기지 않는다."""

    plan = _build(_R4)
    seen: list[str] = []
    tx_log: list[str] = []

    async def fake_batch(
        _session: Any,
        *,
        plan: TransitionPlan,
        batch_size: int,
        batch_index: int,
        items: Any,
    ) -> TransitionBatchResult:
        del plan, batch_size
        seen.extend(item.feature_id for item in items)
        return TransitionBatchResult(
            batch_index=batch_index,
            skipped_batch=False,
            outcomes=tuple(
                TransitionItemOutcome(item.feature_id, item.action, "done") for item in items
            ),
        )

    class _Session:
        def __init__(self, _engine: Any) -> None:
            pass

        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def scalar(self, _stmt: Any) -> str:
            return plan_module.TRANSITION_LOGIN

        async def begin(self) -> _Tx:
            return _Tx(tx_log)

    monkeypatch.setattr(plan_module, "execute_transition_batch", fake_batch)
    monkeypatch.setattr(plan_module, "AsyncSession", _Session)
    for execute in (False, True):
        seen.clear()
        tx_log.clear()
        summary = await run_mcst_theme_transition(
            cast("AsyncEngine", object()),
            plan=plan,
            batch_size=2,
            execute=execute,
            exclusions=((_WR, "collapse"), (_BF, "collapse")),
        )
        assert seen == ["f-bf-attach", "f-fi-collapse", "f-pet"]
        assert tx_log == (["commit"] * 2 if execute else ["rollback"] * 2)
        assert summary["mode"] == ("execute" if execute else "rehearsal")
        assert summary["items"] == 3
        assert summary["excluded_items"] == 2
        assert summary["exclusions"] == [f"{_BF}:collapse", f"{_WR}:collapse"]
    seen.clear()
    await run_mcst_theme_transition(
        cast("AsyncEngine", object()),
        plan=plan,
        batch_size=10,
        execute=False,
        sample_per_action=50,
        exclusions=plan.exclusions,
    )
    assert seen == ["f-bf-attach", "f-fi-collapse", "f-pet"]
