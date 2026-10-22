"""``kortravelmap.infra.retention_repo`` — latest-only dataset 정리 (ADR-114).

정책(어느 dataset이 이력을 두지 않는가, 종료 notice를 언제 지우는가)은 :mod:`kortravelmap.core.retention`
에 있다. 이 모듈은 그 정책을 migration 410의 SECURITY DEFINER 함수 셋으로 집행한다.

- :func:`apply_latest_only_retention` — **적재 transaction 안, curation seal을 잡기 전에** 부른다. 같은
  transaction이라 seal(``current_provider_curation_input_set``)이 정리 뒤의 상태를 본다 — 별도
  transaction에서 지우면 적재가 잡은 seal과 child 완료 시점의 입력이 달라져 run이 실패한다
  (``ck_tvn40_provider_snapshot_load_input``). 정책 밖 dataset이면 아무것도 하지 않는다.
- :func:`apply_latest_only_retention_maintenance` — maintenance op용. 같은 정리에 price fact prune까지
  하고, 진행 중인 provider 적재가 있는 dataset은 건너뛴다(그 적재의 seal을 깨지 않게).

commit은 호출자 책임이다. 모든 단계가 집합 술어라 몇 번 돌아도 결과가 같다(멱등) — 기존 백로그는 첫
실행이 지운다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from kortravelmap.core.retention import (
    LATEST_ONLY_DATASETS,
    ended_notice_delete_after,
    is_latest_only,
)
from kortravelmap.infra.feature_repo import FeatureLoadResult, lock_feature_curation_write
from kortravelmap.infra.price_repo import (
    materialize_current_price_summary,
    prune_superseded_price_facts,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "LatestOnlyRetentionResult",
    "apply_latest_only_retention",
    "apply_latest_only_retention_by_id",
    "apply_latest_only_retention_maintenance",
]


@dataclass(frozen=True)
class LatestOnlyRetentionResult:
    """한 dataset에 대한 latest-only 정리 결과.

    ``*_held``는 증거가 붙들어 남긴 수다(지우지 않은 것). ``skipped``가 있으면 아무것도 하지 않은 이유다.
    """

    provider: str
    dataset_key: str
    price_facts_pruned: int = 0
    records_pruned: int = 0
    entities_pruned: int = 0
    lineage_states_pruned: int = 0
    records_held: int = 0
    entities_held: int = 0
    notices_purged: int = 0
    notices_held: int = 0
    empty_snapshot_guarded: bool = False
    skipped: str | None = None

    def as_load_result(self) -> FeatureLoadResult:
        """적재 결과에 합칠 계수(``FeatureLoadResult.merge``)."""
        return FeatureLoadResult(
            retention_records_pruned=self.records_pruned,
            retention_entities_pruned=self.entities_pruned,
            retention_notices_purged=self.notices_purged,
            retention_held=self.records_held + self.entities_held + self.notices_held,
        )

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 낼 값. 0이 아닌 계수와 건너뛴 이유만 싣는다."""
        values: dict[str, object] = {
            "retention_price_facts_pruned": self.price_facts_pruned,
            "retention_records_pruned": self.records_pruned,
            "retention_entities_pruned": self.entities_pruned,
            "retention_lineage_states_pruned": self.lineage_states_pruned,
            "retention_records_held": self.records_held,
            "retention_entities_held": self.entities_held,
            "retention_notices_purged": self.notices_purged,
            "retention_notices_held": self.notices_held,
        }
        metadata: dict[str, object] = {key: value for key, value in values.items() if value}
        if self.empty_snapshot_guarded:
            metadata["retention_empty_snapshot_guarded"] = True
        if self.skipped is not None:
            metadata["retention_skipped"] = self.skipped
        return metadata


_DATASET_BY_ID_SQL: Final[str] = """
SELECT provider, dataset_key
FROM provider_sync.provider_datasets
WHERE provider_dataset_id = :provider_dataset_id
"""

_DATASET_SQL: Final[str] = """
SELECT provider_dataset_id, is_active
FROM provider_sync.provider_datasets
WHERE provider = :provider
  AND dataset_key = :dataset_key
"""

_PURGE_ENDED_NOTICES_SQL: Final[str] = """
SELECT purged_count, held_count, empty_snapshot_guarded
FROM feature.purge_ended_provider_notices(
    CAST(:provider_dataset_id AS bigint),
    CAST(:grace AS interval)
)
"""

_PRUNE_LINEAGE_SQL: Final[str] = """
SELECT records_pruned, entities_pruned, lineage_states_pruned, records_held, entities_held
FROM provider_sync.prune_latest_only_lineage(CAST(:provider_dataset_id AS bigint))
"""

#: 이 dataset을 member로 둔 provider 적재가 아직 끝나지 않았는가(child 또는 그 root). 끝나지 않은 적재는
#: 자기 seal(적재 transaction 안에서 잡은 입력 hash)을 child 완료·root 완결 때 다시 대조한다 — 그 사이에
#: maintenance가 entity·Feature를 지우면 그 run이 실패한다.
_IN_FLIGHT_LOAD_SQL: Final[str] = """
SELECT EXISTS (
    SELECT 1
    FROM ops.import_job_datasets AS member
    JOIN ops.import_jobs AS job
      ON job.job_id = member.job_id
    LEFT JOIN ops.import_jobs AS root
      ON root.job_id = job.parent_job_id
    WHERE member.provider_dataset_id = :provider_dataset_id
      AND (job.status IN ('queued', 'running') OR root.status IN ('queued', 'running'))
)
"""


def _grace_literal(grace: timedelta) -> str:
    return f"{int(grace.total_seconds())} seconds"


async def _resolve_dataset(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> tuple[int, bool] | None:
    row = (
        await session.execute(
            text(_DATASET_SQL), {"provider": provider, "dataset_key": dataset_key}
        )
    ).mappings().one_or_none()
    if row is None:
        return None
    return int(row["provider_dataset_id"]), bool(row["is_active"])


async def _prune_lineage_and_notices(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    provider_dataset_id: int,
    price_facts_pruned: int = 0,
) -> LatestOnlyRetentionResult:
    notices_purged = 0
    notices_held = 0
    guarded = False
    grace = ended_notice_delete_after(provider, dataset_key)
    if grace is not None:
        notice_row = (
            await session.execute(
                text(_PURGE_ENDED_NOTICES_SQL),
                {"provider_dataset_id": provider_dataset_id, "grace": _grace_literal(grace)},
            )
        ).mappings().one()
        notices_purged = int(notice_row["purged_count"])
        notices_held = int(notice_row["held_count"])
        guarded = bool(notice_row["empty_snapshot_guarded"])
    lineage_row = (
        await session.execute(
            text(_PRUNE_LINEAGE_SQL), {"provider_dataset_id": provider_dataset_id}
        )
    ).mappings().one()
    return LatestOnlyRetentionResult(
        provider=provider,
        dataset_key=dataset_key,
        price_facts_pruned=price_facts_pruned,
        records_pruned=int(lineage_row["records_pruned"]),
        entities_pruned=int(lineage_row["entities_pruned"]),
        lineage_states_pruned=int(lineage_row["lineage_states_pruned"]),
        records_held=int(lineage_row["records_held"]),
        entities_held=int(lineage_row["entities_held"]),
        notices_purged=notices_purged,
        notices_held=notices_held,
        empty_snapshot_guarded=guarded,
    )


async def apply_latest_only_retention(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
) -> LatestOnlyRetentionResult:
    """적재 transaction 안에서 latest-only dataset의 이력을 정리한다(ADR-114 결정 3·4·5).

    순서: (돌발이면) 종료 notice purge → 비-head record·orphan entity·닫힌 계보 상태 prune. price fact는
    여기서 지우지 않는다 — 가격 적재가 summary 물화 직후 같은 transaction에서 지운다
    (``price_repo.load_price_values``).

    ``feature-curation-write`` gate를 잡는다(적재 경로에서는 이미 쥐고 있어 즉시 돌아온다). 정책 밖이거나
    비활성 dataset이면 아무것도 하지 않는다.
    """
    if not is_latest_only(provider, dataset_key):
        return LatestOnlyRetentionResult(
            provider=provider, dataset_key=dataset_key, skipped="not_latest_only"
        )
    resolved = await _resolve_dataset(session, provider=provider, dataset_key=dataset_key)
    if resolved is None or not resolved[1]:
        return LatestOnlyRetentionResult(
            provider=provider, dataset_key=dataset_key, skipped="dataset_inactive"
        )
    await lock_feature_curation_write(session)
    return await _prune_lineage_and_notices(
        session,
        provider=provider,
        dataset_key=dataset_key,
        provider_dataset_id=resolved[0],
    )


async def apply_latest_only_retention_by_id(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
) -> LatestOnlyRetentionResult:
    """``provider_dataset_id``로 고른 :func:`apply_latest_only_retention`(가격 적재 경로용)."""
    row = (
        await session.execute(
            text(_DATASET_BY_ID_SQL), {"provider_dataset_id": provider_dataset_id}
        )
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"provider dataset {provider_dataset_id} does not exist")
    return await apply_latest_only_retention(
        session, provider=str(row["provider"]), dataset_key=str(row["dataset_key"])
    )


async def apply_latest_only_retention_maintenance(
    session: AsyncSession,
) -> list[LatestOnlyRetentionResult]:
    """maintenance op — 정책의 모든 dataset을 정리한다(백로그·1일 경과 돌발·오래 멈춘 적재).

    한 transaction. 잠금 순서는 적재와 같다(``feature-curation-write`` → price summary lock). gate를 쥔
    뒤 진행 중인 provider 적재가 있는 dataset은 건너뛴다 — gate를 쥔 동안 새 적재는 쓰기를 시작하지
    못하므로, 이 판정과 정리 사이에 새 seal이 끼지 않는다. price dataset은 summary를 먼저 물화한
    뒤(같은 transaction) superseded fact를 지운다.
    """
    await lock_feature_curation_write(session)
    results: list[LatestOnlyRetentionResult] = []
    summary_fresh = False
    for provider, dataset_key in sorted(LATEST_ONLY_DATASETS):
        resolved = await _resolve_dataset(session, provider=provider, dataset_key=dataset_key)
        if resolved is None or not resolved[1]:
            results.append(
                LatestOnlyRetentionResult(
                    provider=provider, dataset_key=dataset_key, skipped="dataset_inactive"
                )
            )
            continue
        provider_dataset_id = resolved[0]
        in_flight = bool(
            await session.scalar(
                text(_IN_FLIGHT_LOAD_SQL), {"provider_dataset_id": provider_dataset_id}
            )
        )
        if in_flight:
            results.append(
                LatestOnlyRetentionResult(
                    provider=provider, dataset_key=dataset_key, skipped="load_in_flight"
                )
            )
            continue
        if not summary_fresh:
            await materialize_current_price_summary(session, run_kind="reconcile")
            summary_fresh = True
        price_facts_pruned = await prune_superseded_price_facts(
            session, provider_dataset_ids=[provider_dataset_id]
        )
        results.append(
            await _prune_lineage_and_notices(
                session,
                provider=provider,
                dataset_key=dataset_key,
                provider_dataset_id=provider_dataset_id,
                price_facts_pruned=price_facts_pruned,
            )
        )
    return results
