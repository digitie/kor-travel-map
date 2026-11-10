"""``ktmctl mcst-theme-plan`` — 기존 MCST Feature 전환 dry-run 계획(ADR-121 §8.1, 읽기 전용).

운영 MCST active Feature 전부를 붙임 규칙 ``theme-attach-v1``로 판정해
``retire``/``attach``/``collapse``/``keep``/``ambiguous`` 개수를 dataset별로 낸다. DB에는 아무것도
쓰지 않는다 — ``SET TRANSACTION READ ONLY`` 안에서 읽고 끝난다.

PinVi 참조 수는 다른 DB라 여기서 세지 않는다. ``--ids-out``이 퇴역 예정 Feature
(``retire``·``attach``·``collapse``)를 ``feature_id<TAB>action<TAB>target`` 한 줄씩
쓰고, 운영자가 그 목록으로 PinVi DB를 읽기 전용으로 센다.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.theme_attach import (
    THEME_ATTACH_RULE_VERSION,
    PlanEntry,
    PlanFeature,
    plan_existing_features,
)
from kortravelmap.infra.theme_attach_repo import PlanDatasetConfig, fetch_mcst_plan_features
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PET_BUSINESS_CATEGORIES

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = ["mcst_plan_dataset_configs", "plan_report", "run_mcst_theme_plan"]

_RETIRING_ACTIONS = frozenset({"retire", "attach", "collapse"})


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


def plan_report(
    features: list[PlanFeature], entries: list[PlanEntry], *, samples: int, seed: int = 1121
) -> dict[str, Any]:
    """계획 결과를 보고서(JSON 직렬화 가능)로 만든다."""

    by_id = {feature.feature_id: feature for feature in features}
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
        "retiring_feature_count": sum(
            1 for entry in entries if entry.action in _RETIRING_ACTIONS
        ),
    }


async def run_mcst_theme_plan(
    engine: AsyncEngine, *, samples: int
) -> tuple[dict[str, Any], list[PlanEntry]]:
    """읽기 전용 transaction에서 계획을 만든다. ``(보고서, 퇴역 예정 계획 행)``."""

    async with AsyncSession(engine) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        features = await fetch_mcst_plan_features(
            session, datasets=mcst_plan_dataset_configs()
        )
    entries = plan_existing_features(features)
    retiring = sorted(
        (entry for entry in entries if entry.action in _RETIRING_ACTIONS),
        key=lambda entry: entry.feature_id,
    )
    return plan_report(features, entries, samples=samples), retiring
