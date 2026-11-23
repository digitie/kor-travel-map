"""``ktmctl mcst-theme-plan`` — 기존 MCST Feature 전환 dry-run 계획(ADR-121 §8.1, 읽기 전용).

운영 MCST active Feature 전부를 붙임 규칙 ``theme-attach-v1``로 판정해
``retire``/``attach``/``collapse``/``keep``/``ambiguous`` 개수를 dataset별로 낸다. DB에는 아무것도
쓰지 않는다 — ``SET TRANSACTION READ ONLY`` 안에서 읽고 끝난다.

PinVi 참조 수는 다른 DB라 여기서 세지 않는다. ``--ids-out``이 퇴역 예정 Feature
(``retire``·``attach``·``collapse``)를 ``feature_id<TAB>action<TAB>target`` 한 줄씩
쓰고, 운영자가 그 목록으로 PinVi DB를 읽기 전용으로 센다.

``--exclude <dataset>:<action>``(반복)은 그 쌍을 전환하지 않는다 — 정밀도 게이트(§5.4)를 못 넘은
목록·action을 계획에서 빼는 정식 경로다(계획 파일을 손으로 고치지 않는다). 제외된 행은 실행
계획의 ``excluded_items``에 원래 action 그대로 기록되고(``plan_sha256``에 포함), ``--ids-out``·
``retiring_feature_count``에서 빠진다. 실행기는 같은 ``--exclude``를 다시 받아 대조한다.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.theme_attach import (
    THEME_ATTACH_RULE_VERSION,
    PlanEntry,
    PlanFeature,
    plan_existing_features,
)
from kortravelmap.infra.mcst_theme_transition_repo import (
    TransitionExclusion,
    TransitionPlan,
    TransitionPlanItem,
    build_transition_plan,
    check_plan_exclusions,
    execute_transition_batch,
)
from kortravelmap.infra.theme_attach_repo import PlanDatasetConfig, fetch_mcst_plan_features
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PET_BUSINESS_CATEGORIES

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = [
    "mcst_plan_dataset_configs",
    "parse_exclusions",
    "plan_report",
    "run_mcst_theme_plan",
    "run_mcst_theme_transition",
]

_RETIRING_ACTIONS = frozenset({"retire", "attach", "collapse"})
TRANSITION_LOGIN = "ktm_feature_service"
"""전환 실행 DSN의 로그인 — 사건 writer(448)가 이 session_user만 받는다."""


def mcst_plan_dataset_configs() -> dict[str, PlanDatasetConfig]:
    """provider 메타표 → 계획기 설정."""

    return {
        spec.dataset_key: PlanDatasetConfig(
            master_category_prefixes=spec.master_category_prefixes,
            attribute_list=spec.attribute_list,
            pet_business=(
                MCST_PET_BUSINESS_CATEGORIES
                if spec.slug == "pet_friendly_culture_facilities_csv"
                else frozenset()
            ),
        )
        for spec in MCST_FILE_DATASETS.values()
    }


def _dataset_aliases() -> dict[str, str]:
    """``mcst_barrier_free_places_csv``·``barrier_free_places_csv``·``barrier_free_places`` →
    dataset_key. 계획에는 언제나 dataset_key가 기록된다."""

    aliases: dict[str, str] = {}
    for spec in MCST_FILE_DATASETS.values():
        for alias in (spec.dataset_key, spec.slug, spec.slug.removesuffix("_csv")):
            aliases[alias] = spec.dataset_key
    return aliases


def parse_exclusions(values: list[str] | None) -> tuple[TransitionExclusion, ...]:
    """``--exclude <dataset>:<action>`` 값들 → 정렬된 ``(dataset_key, action)``.

    dataset은 dataset_key 또는 slug(``_csv`` 생략 가능), action은 ``attach``·``collapse``·
    ``retire``다. 모르는 dataset·action, 같은 쌍의 반복은 ``ValueError``.
    """

    aliases = _dataset_aliases()
    seen: list[TransitionExclusion] = []
    for raw in values or ():
        dataset, sep, action = raw.strip().rpartition(":")
        if not sep or not dataset or not action:
            raise ValueError(f"--exclude는 <dataset>:<action> 모양이어야 한다: {raw!r}")
        if action not in _RETIRING_ACTIONS:
            raise ValueError(
                f"--exclude action은 {sorted(_RETIRING_ACTIONS)} 중 하나다: {raw!r}"
            )
        dataset_key = aliases.get(dataset)
        if dataset_key is None:
            raise ValueError(f"--exclude의 dataset을 모른다: {dataset!r}")
        pair = (dataset_key, action)
        if pair in seen:
            raise ValueError(f"--exclude가 같은 쌍을 두 번 말한다: {dataset_key}:{action}")
        seen.append(pair)
    return tuple(sorted(seen))


def _target_view(by_id: dict[str, PlanFeature], entry: PlanEntry) -> dict[str, Any]:
    """표본 행에 **실제 대상**의 이름·거리를 싣는다 — 물려받은 attach·collapse 생존자는
    근거(evidence)의 후보와 다를 수 있어, 대상 id로 후보를 다시 찾는다."""

    target = entry.target_feature_id
    if target is None:
        return {"target_name": None, "target_distance_m": None}
    for candidate in by_id[entry.feature_id].candidates:
        if candidate.feature_id == target:
            return {
                "target_name": candidate.name,
                "target_distance_m": round(candidate.distance_m, 1),
            }
    survivor = by_id.get(target)
    return {"target_name": survivor.name if survivor else None, "target_distance_m": None}


def plan_report(
    features: list[PlanFeature],
    entries: list[PlanEntry],
    *,
    samples: int,
    seed: int = 1121,
    exclusions: tuple[TransitionExclusion, ...] = (),
) -> dict[str, Any]:
    """계획 결과를 보고서(JSON 직렬화 가능)로 만든다.

    ``by_dataset``·``totals``·``samples``는 **판정** 그대로다(제외와 무관 — 표본 감사가 제외 전후로
    같은 숫자를 본다). 제외는 ``exclusions``(쌍마다 행 수)로 따로 싣고,
    ``retiring_feature_count``는 제외를 뺀 **실제 퇴역 예정** 수다.
    """

    by_id = {feature.feature_id: feature for feature in features}
    excluded = frozenset(exclusions)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    grouped: dict[tuple[str, str], list[PlanEntry]] = defaultdict(list)
    for entry in entries:
        counts[entry.dataset_key][entry.action] += 1
        totals[entry.action] += 1
        grouped[(entry.dataset_key, entry.action)].append(entry)
    rng = random.Random(seed)  # noqa: S311  # 표본 추출 — 보안 용도 아님
    sample_rows: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for (dataset_key, action), items in sorted(grouped.items()):
        if action not in ("attach", "collapse", "ambiguous"):
            continue
        picked = rng.sample(items, min(samples, len(items)))
        sample_rows[dataset_key][action] = [
            {
                "feature_id": entry.feature_id,
                "name": by_id[entry.feature_id].name,
                "target_feature_id": entry.target_feature_id,
                **_target_view(by_id, entry),
                "evidence": dict(entry.evidence),
            }
            for entry in picked
        ]
    return {
        "rule_version": THEME_ATTACH_RULE_VERSION,
        "features_total": len(entries),
        "totals": dict(sorted(totals.items())),
        "by_dataset": {key: dict(sorted(value.items())) for key, value in sorted(counts.items())},
        "samples": dict(sample_rows),
        "exclusions": [
            {
                "dataset_key": dataset_key,
                "action": action,
                "feature_count": counts.get(dataset_key, Counter())[action],
            }
            for dataset_key, action in exclusions
        ],
        "retiring_feature_count": sum(
            1
            for entry in entries
            if entry.action in _RETIRING_ACTIONS
            and (entry.dataset_key, entry.action) not in excluded
        ),
    }


async def run_mcst_theme_plan(
    engine: AsyncEngine, *, samples: int, exclusions: tuple[TransitionExclusion, ...] = ()
) -> tuple[dict[str, Any], list[PlanEntry], TransitionPlan]:
    """읽기 전용 transaction에서 계획을 만든다. ``(보고서, 퇴역 예정 계획 행, 실행 계획)``.

    ``exclusions``(:func:`parse_exclusions`)는 DB를 읽은 뒤 메모리에서만 적용한다 — 읽기 전용
    transaction은 그대로다. 퇴역 예정 계획 행(``--ids-out``)에서도 빠진다.
    """

    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        features = await fetch_mcst_plan_features(
            session, datasets=mcst_plan_dataset_configs()
        )
    entries = plan_existing_features(features)
    excluded = frozenset(exclusions)
    retiring = sorted(
        (
            entry
            for entry in entries
            if entry.action in _RETIRING_ACTIONS
            and (entry.dataset_key, entry.action) not in excluded
        ),
        key=lambda entry: entry.feature_id,
    )
    transition = build_transition_plan(
        entries,
        revisions={feature.feature_id: feature.row_revision for feature in features},
        rule_version=THEME_ATTACH_RULE_VERSION,
        exclusions=exclusions,
    )
    report = plan_report(features, entries, samples=samples, exclusions=transition.exclusions)
    report["plan_sha256"] = transition.plan_sha256
    return report, retiring, transition


async def run_mcst_theme_transition(
    engine: AsyncEngine,
    *,
    plan: TransitionPlan,
    batch_size: int,
    execute: bool,
    max_batches: int | None = None,
    sample_per_action: int | None = None,
    exclusions: tuple[TransitionExclusion, ...] = (),
) -> dict[str, Any]:
    """계획을 batch로 실행한다. ``execute``가 아니면 batch마다 되감는 **리허설**이다.

    batch 하나가 transaction 하나다. 실행 중 Feature 하나라도 ``error``면 그 batch를 통째로
    되감고 멈춘다 — 앞 batch는 남고, 다시 돌리면 이미 commit된 batch는 건너뛴다
    (``(plan_sha256, batch_size, batch_index)``). DSN 로그인은 ``ktm_feature_service``여야 한다.

    ``exclusions``(실행자가 다시 말한 ``--exclude``)는 계획에 기록된 제외와 정확히 같아야 한다 —
    다르면 DB에 닿기 전에 ``ValueError``. 제외된 행(``plan.excluded_items``)은 돌리지 않는다.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    check_plan_exclusions(plan, exclusions)
    async with AsyncSession(engine) as probe:
        login = await probe.scalar(text("SELECT session_user::text"))
    if login != TRANSITION_LOGIN:
        # 사건 writer가 이 로그인만 받는다 — 다른 로그인이면 모든 Feature가 실패한다.
        raise ValueError(f"DSN 로그인이 {TRANSITION_LOGIN}가 아니다: {login!r}")
    totals: Counter[str] = Counter()
    batches_done = 0
    batches_skipped = 0
    errors: list[dict[str, Any]] = []
    items = plan.items
    if sample_per_action is not None:
        if execute:
            raise ValueError("표본 리허설은 실행(--execute)과 함께 쓸 수 없다")
        # 리허설 전용: action마다 앞 N개만. 되감으므로 batch 번호가 실행과 달라도 남는 것이 없다.
        seen: Counter[str] = Counter()
        picked: list[TransitionPlanItem] = []
        for item in items:
            if seen[item.action] < sample_per_action:
                seen[item.action] += 1
                picked.append(item)
        items = tuple(picked)
    for batch_index, start in enumerate(range(0, len(items), batch_size)):
        if max_batches is not None and batch_index >= max_batches:
            break
        chunk = items[start : start + batch_size]
        async with AsyncSession(engine) as session:
            transaction = await session.begin()
            try:
                result = await execute_transition_batch(
                    session,
                    plan=plan,
                    batch_size=batch_size,
                    batch_index=batch_index,
                    items=chunk,
                )
            except BaseException:
                await transaction.rollback()
                raise
            failed = [outcome for outcome in result.outcomes if outcome.status == "error"]
            if execute and not failed:
                await transaction.commit()
            else:
                # 실행 중 실패가 하나라도 있으면 그 batch를 통째로 되감고 멈춘다 — 전부 실패한
                # batch가 commit돼 재실행을 막는 일을 없앤다(R4 적대 리뷰).
                await transaction.rollback()
        if result.skipped_batch:
            batches_skipped += 1
            continue
        if execute and failed:
            errors.extend(asdict(outcome) for outcome in failed)
            return {
                "mode": "execute",
                "aborted_at_batch": batch_index,
                "plan_sha256": plan.plan_sha256,
                "exclusions": [":".join(pair) for pair in plan.exclusions],
                "excluded_items": len(plan.excluded_items),
                "items": len(items),
                "batch_size": batch_size,
                "batches_run": batches_done,
                "batches_already_committed": batches_skipped,
                "counts": dict(sorted(totals.items())),
                "errors": errors[:200],
            }
        batches_done += 1
        totals.update(result.counts())
        errors.extend(
            asdict(outcome) for outcome in result.outcomes if outcome.status == "error"
        )
    skipped_items = sum(
        count
        for key, count in totals.items()
        if key.rsplit(":", 1)[1].startswith("stale_") or key.endswith(":conflict")
    )
    return {
        "mode": "execute" if execute else "rehearsal",
        # 건너뛴 Feature는 같은 (sha, 크기)로는 다시 시도되지 않는다 — 새 계획을 뽑아야 한다.
        "skipped_items": skipped_items,
        "plan_sha256": plan.plan_sha256,
        "exclusions": [":".join(pair) for pair in plan.exclusions],
        "excluded_items": len(plan.excluded_items),
        "items": len(items),
        "batch_size": batch_size,
        "batches_run": batches_done,
        "batches_already_committed": batches_skipped,
        "counts": dict(sorted(totals.items())),
        "errors": errors[:200],
    }
