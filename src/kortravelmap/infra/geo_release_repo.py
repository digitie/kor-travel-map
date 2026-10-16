"""geo 릴리스 재지오코딩 계획 — 감지·계획·항목 전이·완료(ADR-109 결정 5, T-GR-04, migration 408).

kor-travel-geo가 새 데이터셋(새 ``data_token``)을 서빙하면 geo 유도 값을 가진 dataset을 다시 적재해
스탬프가 낡은 행을 고친다(재해석 자체는 적재 경로의 stale 분기 — ADR-109 결정 4). 이 모듈은 그
재적재의 **계획**을 DB에 둔다:

- :func:`plan_geo_release` — 감지한 현재 데이터셋으로 계획을 만들거나 기존 계획을 돌려준다. Dagster
  센서(T-GR-05)와 운영 API ``POST /v1/ops/geo-releases/detect``가 **이 함수 하나**를 부른다.
  처음 관측한 토큰은 계획 없이 기준선(``baseline`` 행)으로만 남긴다(소유자 결정 2026-10-15).
- :func:`build_release_items` — 항목 입력은 DB 정본(``provider_dataset_operations`` ⋈ 활성
  dataset)이고, job·geo 의존·자동 적재 꺼짐은 core 상수(``core/feature_operation.py``)로 판정한다.
  **항목 1행 = run 1개**다 — ``(operation_key, run_config)``가 같은 dataset은 한 항목에
  묶인다(MCST는 dataset 13개가 run 1개, KNPS는 dataset마다 run_config가 달라 항목 5개).
- :func:`run_config_for_dataset` — dataset을 고르는 run_config(KNPS·datagokr fileData)와 쿼터 민감
  dataset의 replay 지시.
- :func:`skip_item`·:func:`replan`·:func:`complete_plan` — 운영자 skip, 다시 계획, 완료 판정(잔여
  1회 sweep → 링크 재동기화 → ``done``).

raw SQL은 이 모듈의 상수다(ADR-004). commit은 호출자 책임이다.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import BigInteger

from kortravelmap.core.feature_operation import (
    DATASET_CONFIGURED_OPERATION_RESOURCES,
    FEATURE_LOAD_DISABLED_OPERATION_KEYS,
    FEATURE_LOAD_JOB_OPERATION_KEYS,
    GEO_DEPENDENT_OPERATION_KEYS,
    REPLAY_RECORDS_RESOURCES,
    SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS,
)
from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.infra.feature_geocode_stamp_repo import GeoCoverage, coverage
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTargetFeatureLinkCandidate,
    sync_poi_cache_target_feature_links,
)
from kortravelmap.infra.scope_repo import resolve_cache_target_keys

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.infra.scope_repo import SigunguByRadiusResolver

__all__ = [
    "GeoReleaseCompletion",
    "GeoReleaseConflict",
    "GeoReleaseDataset",
    "GeoReleaseItem",
    "GeoReleaseItemSpec",
    "GeoReleasePlan",
    "GeoReleasePlanOutcome",
    "GeoReleaseNotFound",
    "GeoReleaseResolverRequired",
    "build_release_items",
    "complete_plan",
    "get_geo_release_plan",
    "launch_blocked_reason",
    "mark_item_requested",
    "list_geo_release_plans",
    "plan_geo_release",
    "plan_coverage",
    "replan",
    "requeue_item",
    "run_config_for_dataset",
    "settle_item",
    "skip_item",
]

PlanState = Literal["baseline", "planned", "running", "done", "superseded"]
ItemState = Literal["pending", "requested", "done", "failed", "skipped"]
#: 항목 ``state_reason`` 어휘 — migration 408·409의 CHECK와 같다. ``run_not_launched``부터는
#: 센서(T-GR-05)가 쓴다.
ItemStateReason = Literal[
    "disabled",
    "no_geo_dependency",
    "queue_only",
    "operator",
    "sweep",
    "run_not_launched",
    "no_progress",
    "run_failed",
    "superseded",
    "canceled",
]
LaunchBlockedReason = Literal["replay_not_launchable_before_t_gr_08"]
PlanOutcomeKind = Literal[
    "no_token", "baseline_recorded", "baseline", "existing", "created", "already_complete"
]
CompletionKind = Literal["not_ready", "sweep", "done"]

#: 활성 계획 상태. 같은 토큰에 하나뿐이다(부분 UNIQUE), 그리고 :func:`plan_geo_release`가 새 계획을
#: 만들 때 다른 토큰의 활성 계획을 ``superseded``로 닫으므로 전체에서도 하나다.
_ACTIVE_STATES: Final[tuple[str, ...]] = ("planned", "running")
_TERMINAL_ITEM_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "skipped"})

_LOGGER = logging.getLogger(__name__)

#: 센서와 ``/detect``가 동시에 감지해도 계획이 둘 생기지 않게 하는 transaction 잠금.
_PLAN_LOCK_SQL: Final = text(
    "SELECT pg_advisory_xact_lock(hashtextextended('kortravelmap:geo_release_plan', 0))"
)


class GeoReleaseConflict(RuntimeError):
    """요청한 전이를 지금 상태에서 할 수 없다(끝난 계획·끝난 항목·최신이 아닌 토큰 등)."""


class GeoReleaseNotFound(GeoReleaseConflict):
    """계획이나 항목이 없다(API 404)."""


class GeoReleaseResolverRequired(RuntimeError):
    """``sigungu_by_radius`` cache target이 있는데 sigungu resolver 없이 완료하려 했다.

    링크 재동기화 도중 실패해 transaction 전체가 되돌아가는 대신, 쓰기 전에 거부한다.
    """


@dataclass(frozen=True)
class GeoReleaseDataset:
    """항목이 다시 적재하는 dataset 하나."""

    provider_dataset_id: int
    provider: str
    dataset_key: str


@dataclass(frozen=True)
class GeoReleaseItemSpec:
    """계획에 넣을 항목 후보(아직 DB에 없다) — run 1개."""

    operation_key: str
    datasets: tuple[GeoReleaseDataset, ...]
    feature_kind: str | None
    run_config: dict[str, Any] | None
    state: Literal["pending", "skipped"]
    state_reason: ItemStateReason | None
    stale_count: int = 0

    @property
    def provider_dataset_ids(self) -> tuple[int, ...]:
        return tuple(dataset.provider_dataset_id for dataset in self.datasets)


@dataclass(frozen=True)
class GeoReleaseItem:
    """계획 항목 1행 — run 1개(그 run이 다시 적재하는 dataset 목록을 담는다)."""

    plan_id: int
    position: int
    operation_key: str
    datasets: tuple[GeoReleaseDataset, ...]
    run_config: dict[str, Any] | None
    attempt_seq: int
    state: str
    state_reason: str | None
    run_key: str | None
    dagster_run_id: str | None
    requested_at: datetime | None

    @property
    def provider_dataset_ids(self) -> tuple[int, ...]:
        return tuple(dataset.provider_dataset_id for dataset in self.datasets)

    @property
    def launch_blocked_reason(self) -> LaunchBlockedReason | None:
        return launch_blocked_reason(self.operation_key, self.run_config)


@dataclass(frozen=True)
class GeoReleasePlan:
    """계획 1행(+ 항목)."""

    plan_id: int
    geo_data_token: str
    plan_seq: int
    geo_version_token: str
    activated_at: datetime | None
    reference_months: dict[str, Any] | None
    state: str
    residual_stale: int | None
    sweep_started_at: datetime | None
    observed_at: datetime
    completed_at: datetime | None
    items: tuple[GeoReleaseItem, ...] = ()


@dataclass(frozen=True)
class GeoReleasePlanOutcome:
    """:func:`plan_geo_release`의 결과.

    - ``no_token`` — geo가 ``data_token``을 주지 않았다(지문 backfill 전). 계획 없음.
    - ``baseline_recorded`` — 처음 관측한 토큰을 기준선으로 기록했다. 계획 없음.
    - ``baseline`` — 관측 토큰이 아직 기준선 그대로다. 계획 없음.
    - ``existing`` — 같은 토큰의 활성 계획이 이미 있다(멱등).
    - ``created`` — 새 계획을 만들었다(``superseded_plan_ids``는 그때 닫은 옛 활성 계획).
    - ``already_complete`` — 그 토큰의 최신 계획이 끝났고 잔여가 0이다. 계획 없음.
    """

    kind: PlanOutcomeKind
    plan: GeoReleasePlan | None = None
    superseded_plan_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class GeoReleaseCompletion:
    """:func:`complete_plan`의 결과."""

    kind: CompletionKind
    plan: GeoReleasePlan
    coverage: GeoCoverage | None = None
    sweep_positions: tuple[int, ...] = ()
    linked_target_count: int = 0
    link_count: int = 0


# -- run_config --------------------------------------------------------------------------------


def run_config_for_dataset(operation_key: str, dataset_key: str) -> dict[str, Any] | None:
    """그 dataset을 다시 적재하는 Dagster run_config. 필요 없으면 None(job 기본값).

    - dataset을 run_config로 고르는 operation(KNPS 2개·datagokr fileData)은 resource마다
      ``{"config": {"dataset_key": …}}`` — ``knps_schedule_binding``과 같은 꼴이다.
    - 쿼터 민감 operation은 records resource에 ``source_mode=replay``(ADR-109 결정 7). resource
      쪽 구현은 T-GR-08이다 — 그 전에는 이 run_config를 Dagster가 거부한다.
    """
    resources: dict[str, dict[str, dict[str, Any]]] = {}
    for resource in DATASET_CONFIGURED_OPERATION_RESOURCES.get(operation_key, ()):
        resources[resource] = {"config": {"dataset_key": dataset_key}}
    records = REPLAY_RECORDS_RESOURCES.get(operation_key)
    if records is not None:
        resources.setdefault(records, {"config": {}})["config"]["source_mode"] = "replay"
    return {"resources": resources} if resources else None


def launch_blocked_reason(
    operation_key: str, run_config: dict[str, Any] | None
) -> LaunchBlockedReason | None:
    """센서가 이 항목의 run을 낼 수 없는 이유(없으면 None) — replay 게이트.

    replay run_config(records resource의 ``source_mode=replay``)를 가진 항목은 그 operation이
    ``SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS``에 들 때만 낼 수 있다(T-GR-08이 resource를 구현하며
    채운다). 그 전에 내면 Dagster config 검증이 run을 거부한다.
    """
    resources = (run_config or {}).get("resources")
    if not isinstance(resources, dict):
        return None
    replay = any(
        isinstance(resource, dict)
        and isinstance(resource.get("config"), dict)
        and resource["config"].get("source_mode") == "replay"
        for resource in resources.values()
    )
    if replay and operation_key not in SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS:
        return "replay_not_launchable_before_t_gr_08"
    return None


# -- 항목 후보 ---------------------------------------------------------------------------------

#: 계획 입력 — 실행 가능한(``refresh``, enabled) operation ⋈ 활성 dataset. ``refresh``가 operation
#: key(= Dagster job 이름)를 dataset에 결박하는 kind다(``feature_load`` kind 행은 DB에 없다 —
#: ADR-109 결정 5.3의 표기와 다르다, acceptance §T-GR-04 구현 메모).
_CANDIDATE_OPERATIONS_SQL: Final = text(
    """
SELECT operation.operation_key, dataset.provider_dataset_id, dataset.provider, dataset.dataset_key
  FROM provider_sync.provider_dataset_operations AS operation
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = operation.provider_dataset_id
 WHERE operation.operation_kind = 'refresh'
   AND operation.is_enabled
   AND dataset.is_active
 ORDER BY operation.operation_key, dataset.dataset_key
"""
)

#: dataset별 stale 행 수(좌표 보유 활성 provider Feature) — 항목 순서용이다.
_STALE_BY_DATASET_SQL: Final = text(
    """
SELECT entity.provider_dataset_id, count(DISTINCT feature.feature_id) AS stale
  FROM feature.features AS feature
  JOIN provider_sync.source_links AS link
    ON link.feature_id = feature.feature_id AND link.source_role = 'primary'
  JOIN provider_sync.source_entities AS entity
    ON entity.source_entity_key = link.source_entity_key
  LEFT JOIN feature.feature_geocode_stamps AS stamp
    ON stamp.feature_id = feature.feature_id
 WHERE feature.lifecycle_state = 'active'
   AND feature.coord IS NOT NULL
   AND entity.provider_dataset_id = ANY(:provider_dataset_ids)
   AND (stamp.feature_id IS NULL
        OR (stamp.reverse_outcome <> 'not_called'
            AND stamp.geo_data_token IS DISTINCT FROM CAST(:current_data_token AS text)))
 GROUP BY entity.provider_dataset_id
"""
).bindparams(bindparam("provider_dataset_ids", type_=ARRAY(BigInteger)))


def _feature_kind(operation_key: str) -> str | None:
    """``feature_<kind>_…_job`` → kind. job이 아니면 None."""
    parts = operation_key.split("_")
    return parts[1] if len(parts) > 2 and parts[0] == "feature" else None


def _classify(
    operation_key: str,
) -> tuple[Literal["pending", "skipped"], ItemStateReason | None]:
    if operation_key not in FEATURE_LOAD_JOB_OPERATION_KEYS:
        return "skipped", "queue_only"
    if operation_key in FEATURE_LOAD_DISABLED_OPERATION_KEYS:
        return "skipped", "disabled"
    if operation_key not in GEO_DEPENDENT_OPERATION_KEYS:
        return "skipped", "no_geo_dependency"
    return "pending", None


def _order_key(spec: GeoReleaseItemSpec) -> tuple[int, int, str, str]:
    """ADR-109 결정 5.3 순서 — ① 공개 place ② event·route·geometry·geo price ③ concierge
    ④ replay(쿼터 민감, MOIS 맨 끝) ⑤ skip. 같은 묶음 안에서는 stale 수 내림차순."""
    if spec.state == "skipped":
        group = 6
    elif spec.operation_key == "feature_place_mois_licenses_job":
        group = 5
    elif spec.operation_key in REPLAY_RECORDS_RESOURCES:
        group = 4
    elif spec.operation_key == "feature_place_kor_travel_concierge_youtube_job":
        group = 3
    elif spec.feature_kind == "place":
        group = 1
    else:
        group = 2
    return group, -spec.stale_count, spec.operation_key, spec.datasets[0].dataset_key


async def build_release_items(
    session: AsyncSession, current_data_token: str | None
) -> list[GeoReleaseItemSpec]:
    """현재 DB의 실행 가능한 operation·dataset으로 항목 후보를 만든다 — 순서까지 정한 목록.

    ``(operation_key, run_config)``가 같은 dataset은 한 항목(run 1개)으로 묶는다.
    """
    rows = (await session.execute(_CANDIDATE_OPERATIONS_SQL)).mappings().all()
    pending_ids = [
        int(row["provider_dataset_id"])
        for row in rows
        if _classify(str(row["operation_key"]))[0] == "pending"
    ]
    stale: dict[int, int] = {}
    if pending_ids:
        stale_rows = (
            await session.execute(
                _STALE_BY_DATASET_SQL,
                {
                    "provider_dataset_ids": sorted(set(pending_ids)),
                    "current_data_token": current_data_token,
                },
            )
        ).mappings()
        stale = {int(row["provider_dataset_id"]): int(row["stale"]) for row in stale_rows}
    grouped: dict[tuple[str, str | None], list[tuple[GeoReleaseDataset, dict[str, Any] | None]]]
    grouped = defaultdict(list)
    for row in rows:
        operation_key = str(row["operation_key"])
        dataset = GeoReleaseDataset(
            provider_dataset_id=int(row["provider_dataset_id"]),
            provider=str(row["provider"]),
            dataset_key=str(row["dataset_key"]),
        )
        state, _ = _classify(operation_key)
        run_config = (
            run_config_for_dataset(operation_key, dataset.dataset_key)
            if state == "pending"
            else None
        )
        key = json.dumps(run_config, sort_keys=True) if run_config is not None else None
        grouped[(operation_key, key)].append((dataset, run_config))
    specs: list[GeoReleaseItemSpec] = []
    for (operation_key, _), members in grouped.items():
        state, reason = _classify(operation_key)
        datasets = tuple(sorted((m[0] for m in members), key=lambda d: d.provider_dataset_id))
        specs.append(
            GeoReleaseItemSpec(
                operation_key=operation_key,
                datasets=datasets,
                feature_kind=_feature_kind(operation_key),
                run_config=members[0][1],
                state=state,
                state_reason=reason,
                stale_count=sum(stale.get(d.provider_dataset_id, 0) for d in datasets),
            )
        )
    return sorted(specs, key=_order_key)


# -- 계획 읽기 ---------------------------------------------------------------------------------

_PLAN_COLUMNS: Final[str] = """
plan_id, geo_data_token, plan_seq, geo_version_token, activated_at, reference_months, state,
residual_stale, sweep_started_at, observed_at, completed_at
"""

_GET_PLAN_SQL: Final = text(
    f"SELECT {_PLAN_COLUMNS} FROM ops.kor_travel_geo_releases WHERE plan_id = :plan_id"
)
_LATEST_PLAN_SQL: Final = text(
    f"SELECT {_PLAN_COLUMNS} FROM ops.kor_travel_geo_releases ORDER BY plan_id DESC LIMIT 1"
)
_LATEST_NON_SUPERSEDED_SQL: Final = text(
    f"SELECT {_PLAN_COLUMNS} FROM ops.kor_travel_geo_releases "
    "WHERE state <> 'superseded' ORDER BY plan_id DESC LIMIT 1"
)
_LATEST_FOR_TOKEN_SQL: Final = text(
    f"SELECT {_PLAN_COLUMNS} FROM ops.kor_travel_geo_releases "
    "WHERE geo_data_token = :token ORDER BY plan_seq DESC LIMIT 1"
)
_ACTIVE_PLANS_SQL: Final = text(
    f"SELECT {_PLAN_COLUMNS} FROM ops.kor_travel_geo_releases "
    "WHERE state IN ('planned', 'running') ORDER BY plan_id"
)
_LIST_PLANS_SQL: Final = text(
    f"SELECT {_PLAN_COLUMNS} FROM ops.kor_travel_geo_releases ORDER BY plan_id DESC LIMIT :limit"
)
_ITEMS_SQL: Final = text(
    """
SELECT plan_id, "position", operation_key, provider_dataset_ids, run_config, attempt_seq, state,
       state_reason, run_key, dagster_run_id, requested_at
  FROM ops.kor_travel_geo_release_items
 WHERE plan_id = :plan_id
 ORDER BY "position"
"""
)
_DATASETS_SQL: Final = text(
    """
SELECT provider_dataset_id, provider, dataset_key
  FROM provider_sync.provider_datasets
 WHERE provider_dataset_id = ANY(:ids)
"""
).bindparams(bindparam("ids", type_=ARRAY(BigInteger)))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _plan(row: RowMapping, items: Sequence[GeoReleaseItem] = ()) -> GeoReleasePlan:
    return GeoReleasePlan(
        plan_id=int(row["plan_id"]),
        geo_data_token=str(row["geo_data_token"]),
        plan_seq=int(row["plan_seq"]),
        geo_version_token=str(row["geo_version_token"]),
        activated_at=row["activated_at"],
        reference_months=_json_value(row["reference_months"]),
        state=str(row["state"]),
        residual_stale=row["residual_stale"],
        sweep_started_at=row["sweep_started_at"],
        observed_at=row["observed_at"],
        completed_at=row["completed_at"],
        items=tuple(items),
    )


def _dataset_or_placeholder(
    provider_dataset_id: int, datasets: dict[int, GeoReleaseDataset]
) -> GeoReleaseDataset:
    """항목의 dataset id에 ``provider_datasets`` 행이 없으면 경고하고 빈 이름으로 채운다.

    dataset은 지우지 않고 비활성화만 하므로(408 docstring) 정상 경로에서는 일어나지 않는다 —
    일어나면 누가 행을 지웠다는 뜻이라 조용히 넘기지 않는다.
    """
    found = datasets.get(provider_dataset_id)
    if found is not None:
        return found
    _LOGGER.warning(
        "geo 릴리스 항목의 provider_dataset_id=%s에 provider_datasets 행이 없다 — 누가 지웠다",
        provider_dataset_id,
    )
    return GeoReleaseDataset(provider_dataset_id, "", "")


def _item(row: RowMapping, datasets: dict[int, GeoReleaseDataset]) -> GeoReleaseItem:
    return GeoReleaseItem(
        plan_id=int(row["plan_id"]),
        position=int(row["position"]),
        operation_key=str(row["operation_key"]),
        datasets=tuple(
            _dataset_or_placeholder(int(value), datasets)
            for value in row["provider_dataset_ids"]
        ),
        run_config=_json_value(row["run_config"]),
        attempt_seq=int(row["attempt_seq"]),
        state=str(row["state"]),
        state_reason=row["state_reason"],
        run_key=row["run_key"],
        dagster_run_id=row["dagster_run_id"],
        requested_at=row["requested_at"],
    )


async def _items(session: AsyncSession, plan_id: int) -> tuple[GeoReleaseItem, ...]:
    rows = (await session.execute(_ITEMS_SQL, {"plan_id": plan_id})).mappings().all()
    ids = sorted({int(value) for row in rows for value in row["provider_dataset_ids"]})
    datasets: dict[int, GeoReleaseDataset] = {}
    if ids:
        for meta in (await session.execute(_DATASETS_SQL, {"ids": ids})).mappings():
            dataset = GeoReleaseDataset(
                provider_dataset_id=int(meta["provider_dataset_id"]),
                provider=str(meta["provider"]),
                dataset_key=str(meta["dataset_key"]),
            )
            datasets[dataset.provider_dataset_id] = dataset
    return tuple(_item(row, datasets) for row in rows)


async def get_geo_release_plan(session: AsyncSession, plan_id: int) -> GeoReleasePlan | None:
    """계획 1건과 항목(없으면 None)."""
    row = (await session.execute(_GET_PLAN_SQL, {"plan_id": plan_id})).mappings().first()
    if row is None:
        return None
    return _plan(row, await _items(session, plan_id))


async def list_geo_release_plans(
    session: AsyncSession, *, limit: int = 20
) -> tuple[GeoReleasePlan, ...]:
    """최근 계획(항목 없이) — ``plan_id`` 내림차순."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    rows = (await session.execute(_LIST_PLANS_SQL, {"limit": limit})).mappings().all()
    return tuple(_plan(row) for row in rows)


# -- 계획 만들기 --------------------------------------------------------------------------------

_INSERT_PLAN_SQL: Final = text(
    f"""
INSERT INTO ops.kor_travel_geo_releases (
    geo_data_token, plan_seq, geo_version_token, activated_at, reference_months, state,
    completed_at
)
SELECT :token,
       COALESCE((SELECT max(plan_seq) FROM ops.kor_travel_geo_releases
                  WHERE geo_data_token = :token), 0) + 1,
       :version_token, :activated_at, CAST(:reference_months AS jsonb), :state,
       CASE WHEN :state = 'baseline' THEN now() END
RETURNING {_PLAN_COLUMNS}
"""
)
_SUPERSEDE_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_releases
   SET state = 'superseded', completed_at = now(), updated_at = now()
 WHERE plan_id = :plan_id AND state IN ('planned', 'running')
"""
)
#: 닫히는 계획의 진행 중 항목 — 진행 중으로 남은 고아가 없어야 "한 번에 run 1개" 상한이 성립한다.
_SUPERSEDE_REQUESTED_ITEMS_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_release_items
   SET state = 'failed', state_reason = 'superseded', updated_at = now()
 WHERE plan_id = :plan_id AND state = 'requested'
"""
)
_INSERT_ITEM_SQL: Final = text(
    """
INSERT INTO ops.kor_travel_geo_release_items (
    plan_id, "position", operation_key, provider_dataset_ids, run_config, state, state_reason
) VALUES (
    :plan_id, :position, :operation_key, :provider_dataset_ids, CAST(:run_config AS jsonb),
    :state, :state_reason
)
"""
).bindparams(bindparam("provider_dataset_ids", type_=ARRAY(BigInteger)))


async def _insert_plan(
    session: AsyncSession, current: DatasetRef, *, state: PlanState
) -> GeoReleasePlan:
    assert current.data_token is not None
    row = (
        (
            await session.execute(
                _INSERT_PLAN_SQL,
                {
                    "token": current.data_token,
                    "version_token": current.version_token,
                    "activated_at": current.activated_at,
                    "reference_months": (
                        json.dumps(current.reference_months, sort_keys=True)
                        if current.reference_months is not None
                        else None
                    ),
                    "state": state,
                },
            )
        )
        .mappings()
        .one()
    )
    return _plan(row)


async def _create_plan(
    session: AsyncSession, current: DatasetRef, specs: Sequence[GeoReleaseItemSpec]
) -> tuple[GeoReleasePlan, tuple[int, ...]]:
    superseded = await _supersede_active(session)
    plan = await _insert_plan(session, current, state="planned")
    for position, spec in enumerate(specs, start=1):
        await session.execute(
            _INSERT_ITEM_SQL,
            {
                "plan_id": plan.plan_id,
                "position": position,
                "operation_key": spec.operation_key,
                "provider_dataset_ids": list(spec.provider_dataset_ids),
                "run_config": (
                    json.dumps(spec.run_config, sort_keys=True)
                    if spec.run_config is not None
                    else None
                ),
                "state": spec.state,
                "state_reason": spec.state_reason,
            },
        )
    created = await get_geo_release_plan(session, plan.plan_id)
    assert created is not None
    return created, superseded


async def _supersede_active(session: AsyncSession) -> tuple[int, ...]:
    superseded: list[int] = []
    for active in (await session.execute(_ACTIVE_PLANS_SQL)).mappings().all():
        await session.execute(_SUPERSEDE_SQL, {"plan_id": int(active["plan_id"])})
        await session.execute(
            _SUPERSEDE_REQUESTED_ITEMS_SQL, {"plan_id": int(active["plan_id"])}
        )
        superseded.append(int(active["plan_id"]))
    return tuple(superseded)


async def plan_geo_release(session: AsyncSession, current: DatasetRef) -> GeoReleasePlanOutcome:
    """관측한 geo 현재 데이터셋으로 계획을 만들거나 기존 계획을 돌려준다(ADR-109 결정 5.1·5.2).

    센서와 ``POST /v1/ops/geo-releases/detect``의 **단일 정본**이다. 규칙(위에서 처음 맞는 것):

    1. ``data_token``이 None → ``no_token``(지문 backfill/복구 필요 — 계획 없음).
    2. 같은 토큰의 활성 계획 → ``existing``(멱등).
    3. 계획 행이 하나도 없다(처음 관측) → 기준선 행을 쓰고 ``baseline_recorded``(소유자 결정
       2026-10-15 — 첫 토큰은 재해석 없이 기준선). 스탬프 없는 행은 평소 적재가 채운다.
    4. **전체 최신 행**이 이 토큰의 행이다 — 기준선이면 ``baseline``, ``done``이면
       ``already_complete``(잔여가 남았어도 — 그 토큰은 이미 한 사이클을 돌았고 남은 것은
       ``residual_stale``로 기록됐다. 다시 돌리는 것은 운영자 ``replan``이다. 그렇지 않으면 감지가
       올 때마다 MOIS·replay 쿼터를 다시 쓴다).
    5. 이 토큰의 이전 행이 있고 비-skip dataset의 잔여(``stamped_other + unstamped``)가 0 →
       다른 토큰의 활성 계획을 ``superseded``로 닫고 ``already_complete``(롤백: B 계획이 돌기 전에
       geo가 A로 돌아왔다).
    6. 그 외 → 다른 토큰의 활성 계획을 ``superseded``로 닫고 ``plan_seq = max + 1`` 새 계획
       (``created``). A→B→A의 두 번째 A는 B가 더 새 행이므로 여기 온다.

    한 transaction 안에서 advisory 잠금으로 직렬화한다 — 동시 감지가 계획을 둘 만들지 않는다.
    """
    if current.data_token is None:
        return GeoReleasePlanOutcome(kind="no_token")
    token = current.data_token
    await session.execute(_PLAN_LOCK_SQL)
    for active in (await session.execute(_ACTIVE_PLANS_SQL)).mappings().all():
        if str(active["geo_data_token"]) == token:
            return GeoReleasePlanOutcome(
                kind="existing", plan=await get_geo_release_plan(session, int(active["plan_id"]))
            )
    latest = (await session.execute(_LATEST_PLAN_SQL)).mappings().first()
    if latest is None:
        return GeoReleasePlanOutcome(
            kind="baseline_recorded",
            plan=await _insert_plan(session, current, state="baseline"),
        )
    if str(latest["geo_data_token"]) == token:
        if latest["state"] == "baseline":
            return GeoReleasePlanOutcome(kind="baseline", plan=_plan(latest))
        if latest["state"] == "done":
            return GeoReleasePlanOutcome(kind="already_complete", plan=_plan(latest))
    latest_for_token = (
        (await session.execute(_LATEST_FOR_TOKEN_SQL, {"token": token})).mappings().first()
    )
    specs = await build_release_items(session, token)
    if (
        latest_for_token is not None
        and (await _coverage_for_specs(session, token, specs)).remaining == 0
    ):
        superseded = await _supersede_active(session)
        return GeoReleasePlanOutcome(
            kind="already_complete",
            plan=_plan(latest_for_token),
            superseded_plan_ids=superseded,
        )
    plan, superseded = await _create_plan(session, current, specs)
    return GeoReleasePlanOutcome(kind="created", plan=plan, superseded_plan_ids=superseded)


async def _coverage_for_specs(
    session: AsyncSession, token: str | None, items: Sequence[GeoReleaseItemSpec | GeoReleaseItem]
) -> GeoCoverage:
    included = {i for item in items if item.state != "skipped" for i in item.provider_dataset_ids}
    skipped = {i for item in items if item.state == "skipped" for i in item.provider_dataset_ids}
    return await coverage(
        session, token, provider_dataset_ids=included, skipped_provider_dataset_ids=skipped
    )


async def plan_coverage(session: AsyncSession, plan: GeoReleasePlan) -> GeoCoverage:
    """계획 토큰 기준 커버리지 — 분모는 그 계획의 비-skip 항목 dataset이다."""
    items = plan.items or await _items(session, plan.plan_id)
    return await _coverage_for_specs(session, plan.geo_data_token, items)


# -- 운영자 전이 --------------------------------------------------------------------------------

_SKIP_ITEM_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_release_items
   SET state = 'skipped', state_reason = :reason, updated_at = now()
 WHERE plan_id = :plan_id AND "position" = :position
   AND state IN ('pending', 'failed')
RETURNING plan_id
"""
)


async def _active_plan(session: AsyncSession, plan_id: int) -> GeoReleasePlan:
    plan = await get_geo_release_plan(session, plan_id)
    if plan is None:
        raise GeoReleaseNotFound(f"geo 릴리스 계획 {plan_id}이 없다")
    if plan.state not in _ACTIVE_STATES:
        raise GeoReleaseConflict(f"geo 릴리스 계획 {plan_id}은 {plan.state} 상태다 — 활성이 아니다")
    return plan


async def skip_item(
    session: AsyncSession, plan_id: int, position: int, *, reason: str = "operator"
) -> GeoReleasePlan:
    """활성 계획의 대기·실패 항목을 운영자가 건너뛴다(``skipped(operator)``)."""
    await session.execute(_PLAN_LOCK_SQL)
    plan = await _active_plan(session, plan_id)
    if not any(item.position == position for item in plan.items):
        raise GeoReleaseNotFound(f"계획 {plan_id}에 항목 {position}이 없다")
    updated = (
        await session.execute(
            _SKIP_ITEM_SQL, {"plan_id": plan_id, "position": position, "reason": reason}
        )
    ).first()
    if updated is None:
        raise GeoReleaseConflict(
            f"계획 {plan_id} 항목 {position}은 대기·실패 상태가 아니다 — 건너뛸 수 없다"
        )
    refreshed = await get_geo_release_plan(session, plan_id)
    assert refreshed is not None
    return refreshed


async def replan(session: AsyncSession, plan_id: int) -> GeoReleasePlan:
    """그 계획의 토큰으로 ``plan_seq + 1`` 새 계획을 만든다(운영자 "다시 계획").

    잔여 판정 없이 새로 만든다 — 완료 판정의 두 번째 sweep은 운영자 몫이다(ADR-109 결정 5.6).
    **허용 조건**: 계획 행 전체의 최신 행과 같은 토큰이고(그 토큰이 지금 기준이다 — 옛 토큰을 다시
    계획하면 새 토큰의 결과를 되돌린다), 기준선 행이 아니다(기준선은 계획하지 않는다는 소유자
    결정). 활성 계획은 ``superseded``로 닫는다. 항목은 지금 DB의 operation·dataset으로 다시 만든다.
    """
    await session.execute(_PLAN_LOCK_SQL)
    source = await get_geo_release_plan(session, plan_id)
    if source is None:
        raise GeoReleaseNotFound(f"geo 릴리스 계획 {plan_id}이 없다")
    if source.state == "baseline":
        raise GeoReleaseConflict(f"계획 {plan_id}은 기준선이다 — 기준선은 다시 계획하지 않는다")
    # 기준은 **최신 비-superseded 행**이다 — 롤백(규칙 5)은 B를 superseded로 닫고 A 행을 새로 쓰지
    # 않으므로, 최신 행 그대로 보면 geo가 서빙하는 A의 replan을 거부하고 B의 replan을 허용한다.
    latest = (await session.execute(_LATEST_NON_SUPERSEDED_SQL)).mappings().one()
    if str(latest["geo_data_token"]) != source.geo_data_token:
        raise GeoReleaseConflict(
            f"계획 {plan_id}의 토큰은 최신 관측 토큰이 아니다 — 옛 토큰은 다시 계획하지 않는다"
        )
    current = DatasetRef(
        version_token=source.geo_version_token,
        data_token=source.geo_data_token,
        activated_at=source.activated_at,
        reference_months=source.reference_months,
    )
    specs = await build_release_items(session, source.geo_data_token)
    plan, _ = await _create_plan(session, current, specs)
    return plan


# -- 센서 전이(T-GR-05) ---------------------------------------------------------------------------

_MARK_REQUESTED_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_release_items
   SET state = 'requested', state_reason = NULL, run_key = :run_key, dagster_run_id = NULL,
       requested_at = now(), updated_at = now()
 WHERE plan_id = :plan_id AND "position" = :position AND state = 'pending'
   AND attempt_seq = :attempt_seq
RETURNING plan_id
"""
)
_START_PLAN_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_releases
   SET state = 'running', updated_at = now()
 WHERE plan_id = :plan_id AND state = 'planned'
"""
)
_SETTLE_ITEM_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_release_items
   SET state = :state, state_reason = :reason,
       dagster_run_id = COALESCE(:dagster_run_id, dagster_run_id), updated_at = now()
 WHERE plan_id = :plan_id AND "position" = :position AND state = 'requested'
RETURNING plan_id
"""
)
_REQUEUE_ITEM_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_release_items
   SET state = 'pending', state_reason = NULL, attempt_seq = attempt_seq + 1, run_key = NULL,
       dagster_run_id = NULL, requested_at = NULL, updated_at = now()
 WHERE plan_id = :plan_id AND "position" = :position AND state = 'requested'
RETURNING attempt_seq
"""
)


async def mark_item_requested(
    session: AsyncSession, plan_id: int, position: int, *, attempt_seq: int, run_key: str
) -> bool:
    """대기 항목을 ``requested``로 — 센서가 RunRequest를 내기 직전. 계획은 ``running``이 된다.

    ``attempt_seq``가 다르거나 이미 대기가 아니면 False(다른 tick이 먼저 냈다 — 내지 않는다).
    """
    await session.execute(_PLAN_LOCK_SQL)
    marked = (
        await session.execute(
            _MARK_REQUESTED_SQL,
            {
                "plan_id": plan_id,
                "position": position,
                "attempt_seq": attempt_seq,
                "run_key": run_key,
            },
        )
    ).first()
    if marked is None:
        return False
    await session.execute(_START_PLAN_SQL, {"plan_id": plan_id})
    return True


async def settle_item(
    session: AsyncSession,
    plan_id: int,
    position: int,
    *,
    state: Literal["done", "failed"],
    reason: ItemStateReason | None = None,
    dagster_run_id: str | None = None,
) -> bool:
    """``requested`` 항목을 run 결과로 끝낸다(``done`` 또는 ``failed(reason)``)."""
    await session.execute(_PLAN_LOCK_SQL)
    settled = (
        await session.execute(
            _SETTLE_ITEM_SQL,
            {
                "plan_id": plan_id,
                "position": position,
                "state": state,
                "reason": reason,
                "dagster_run_id": dagster_run_id,
            },
        )
    ).first()
    return settled is not None


async def requeue_item(session: AsyncSession, plan_id: int, position: int) -> int | None:
    """``requested`` 항목을 다음 ``attempt_seq``의 대기로 되돌린다(자동 재요청·MOIS 이어 달리기).

    돌려주는 것은 새 ``attempt_seq``(이미 ``requested``가 아니면 None).
    """
    await session.execute(_PLAN_LOCK_SQL)
    row = (
        await session.execute(_REQUEUE_ITEM_SQL, {"plan_id": plan_id, "position": position})
    ).first()
    return None if row is None else int(row[0])


# -- 완료 -------------------------------------------------------------------------------------

_SWEEP_ITEMS_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_release_items
   SET state = 'pending', state_reason = 'sweep', attempt_seq = attempt_seq + 1,
       run_key = NULL, dagster_run_id = NULL, requested_at = NULL, updated_at = now()
 WHERE plan_id = :plan_id AND "position" = ANY(:positions)
"""
).bindparams(bindparam("positions", type_=ARRAY(BigInteger)))
_START_SWEEP_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_releases
   SET state = 'running', sweep_started_at = now(), updated_at = now()
 WHERE plan_id = :plan_id
"""
)
_FINISH_PLAN_SQL: Final = text(
    """
UPDATE ops.kor_travel_geo_releases
   SET state = 'done', residual_stale = :residual, completed_at = now(), updated_at = now()
 WHERE plan_id = :plan_id
"""
)
_SIGUNGU_TARGETS_SQL: Final = text(
    """
SELECT count(*)
  FROM ops.poi_cache_targets
 WHERE deleted_at IS NULL AND update_enabled AND refresh_policy <> 'disabled'
   AND scope_mode = 'sigungu_by_radius'
"""
)
_ACTIVE_CACHE_TARGETS_SQL: Final = text(
    """
SELECT external_system, target_key
  FROM ops.poi_cache_targets
 WHERE deleted_at IS NULL AND update_enabled AND refresh_policy <> 'disabled'
 ORDER BY external_system, target_key
"""
)


async def _resync_cache_target_links(
    session: AsyncSession, *, sigungu_resolver: SigunguByRadiusResolver | None
) -> tuple[int, int]:
    """활성 cache target 전부의 feature 링크를 다시 계산한다 — (target 수, 링크 수).

    ``sync_poi_cache_target_feature_links``의 다른 호출처는 큐 executor뿐이라 prod(schedule
    STOPPED)에서는 ``sigungu_code``가 바뀐 feature의 ``same_sigungu`` 링크가 저절로 따라오지 않는다
    (ADR-109 결정 5.6). 계획 완료가 그 재동기화를 한 번 한다.
    """
    by_system: dict[str, list[str]] = defaultdict(list)
    for row in (await session.execute(_ACTIVE_CACHE_TARGETS_SQL)).mappings():
        by_system[str(row["external_system"])].append(str(row["target_key"]))
    targets = 0
    links = 0
    for external_system, target_keys in by_system.items():
        resolution = await resolve_cache_target_keys(
            session,
            external_system=external_system,
            target_keys=target_keys,
            sigungu_resolver=sigungu_resolver,
        )
        target_ids = tuple(target.target_id for target in resolution.cache_targets)
        if not target_ids:
            continue
        synced = await sync_poi_cache_target_feature_links(
            session,
            target_ids=target_ids,
            candidates=tuple(
                PoiCacheTargetFeatureLinkCandidate(
                    target_id=match.target_id,
                    feature_id=match.feature_id,
                    provider_dataset_id=match.provider_dataset_id,
                    distance_m=match.distance_m,
                    relation=match.relation,
                )
                for match in resolution.cache_target_matches
            ),
        )
        targets += len(target_ids)
        links += len(synced)
    return targets, links


async def complete_plan(
    session: AsyncSession,
    plan_id: int,
    *,
    sigungu_resolver: SigunguByRadiusResolver | None,
) -> GeoReleaseCompletion:
    """모든 항목이 끝난 계획의 완료 판정(ADR-109 결정 5.6).

    - 끝나지 않은 항목이 있으면 ``not_ready``.
    - 비-skip dataset의 잔여가 있고 아직 sweep을 하지 않았으면 잔여가 있는 항목을 다음
      ``attempt_seq``의 ``pending(sweep)``으로 되돌리고 ``sweep``(센서가 다시 낸다).
    - 그 외(잔여 0, 또는 sweep 뒤에도 남음) → 잔여를 ``residual_stale``로 기록하고 활성 cache
      target 링크를 재동기화한 뒤 ``done``. 두 번째 sweep은 운영자 ``replan``이다.

    ``sigungu_resolver``는 필수 인자다(None도 명시). 완료 단계(링크 재동기화)에 이르렀는데 활성
    ``sigungu_by_radius`` target이 있고 None이면 쓰기 전에 :class:`GeoReleaseResolverRequired`다.
    """
    await session.execute(_PLAN_LOCK_SQL)
    plan = await _active_plan(session, plan_id)
    if any(item.state not in _TERMINAL_ITEM_STATES for item in plan.items):
        return GeoReleaseCompletion(kind="not_ready", plan=plan)
    cov = await _coverage_for_specs(session, plan.geo_data_token, plan.items)
    if cov.remaining > 0 and plan.sweep_started_at is None:
        included = [item for item in plan.items if item.state != "skipped"]
        remaining = (
            await session.execute(
                _STALE_BY_DATASET_SQL,
                {
                    "provider_dataset_ids": sorted(
                        {i for item in included for i in item.provider_dataset_ids}
                    ),
                    "current_data_token": plan.geo_data_token,
                },
            )
        ).mappings()
        stale_ids = {int(row["provider_dataset_id"]) for row in remaining if int(row["stale"])}
        positions = tuple(
            item.position for item in included if set(item.provider_dataset_ids) & stale_ids
        )
        if positions:
            await session.execute(
                _SWEEP_ITEMS_SQL, {"plan_id": plan_id, "positions": list(positions)}
            )
            await session.execute(_START_SWEEP_SQL, {"plan_id": plan_id})
            refreshed = await get_geo_release_plan(session, plan_id)
            assert refreshed is not None
            return GeoReleaseCompletion(
                kind="sweep", plan=refreshed, coverage=cov, sweep_positions=positions
            )
    # resolver는 링크 재동기화에만 필요하다 — not_ready·sweep에서는 묻지 않는다.
    if sigungu_resolver is None and int(
        (await session.execute(_SIGUNGU_TARGETS_SQL)).scalar_one()
    ):
        raise GeoReleaseResolverRequired(
            "sigungu_by_radius cache target이 있다 — 링크 재동기화에 sigungu resolver가 필요하다"
        )
    targets, links = await _resync_cache_target_links(session, sigungu_resolver=sigungu_resolver)
    await session.execute(_FINISH_PLAN_SQL, {"plan_id": plan_id, "residual": cov.remaining})
    finished = await get_geo_release_plan(session, plan_id)
    assert finished is not None
    return GeoReleaseCompletion(
        kind="done",
        plan=finished,
        coverage=cov,
        linked_target_count=targets,
        link_count=links,
    )

