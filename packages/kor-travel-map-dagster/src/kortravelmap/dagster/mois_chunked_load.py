"""MOIS 인허가 재개형 적재 — 업종별·chunk별 commit, 지오코딩 선조회, run 시간 상한 (ADR-108).

종전 MOIS 적재는 약 98만 행을 **한 transaction**으로 넣었다. 역지오코딩을 행마다 순서대로
(약 130ms) 부르면 35시간이 걸리는데 run 상한은 6시간이고, 늦은 실패 하나가 전부를
되감았으며, 재시도는 처음부터 다시 했다. 이 모듈은 그 셋을 함께 고친다.

**재개 키는 원천 내용 자체다.** 새 상태표·cursor를 두지 않는다. chunk마다 각 record의
``source_entity_id``(``{slug}::{mng_no}``)와 ``raw_payload_hash``를 지오코딩 **전에** 계산해
DB에 묻는다 — "이미 같은 payload로 적재돼 있고 primary feature가 active인가". 그런 record는
다시 적재해도 관측 시각 말고는 바뀌지 않으므로(``load_bundle``이 ``became_current=False``로
끝나는 조건) 변환·지오코딩을 건너뛰고 관측만 전진시킨다. 나머지만 변환·적재한다. 두 일은
chunk 하나의 transaction 안에서 끝난다. 그래서

- 중단된 run을 다시 돌리면 commit된 chunk는 전부 건너뛰고 끊긴 자리부터 이어 간다(중복 없음).
- 원천 snapshot이 바뀐 뒤의 run은 바뀐 행만 지오코딩한다(월간 갱신이 사실상 증분이 된다).
- 반쯤 쓰인 chunk는 없다 — commit된 chunk는 행이 전부 있고, 되돌린 chunk는 하나도 없다.

**run 하나는 시간 상한까지만 새 chunk를 시작한다.** 상한에 닿으면 정상 종료하고 run tag에
``budget_exhausted``를 남긴다. :data:`mois_load_continuation_sensor`가 그 run을 보고 같은
run_config로 다음 run을 띄운다. 모든 선택 업종을 끝까지 본 run만 ``complete``이고, 그것이
전 업종이면 그 run이 snapshot 전체를 확인한 것이므로 curation seal을 찍는다.

이 모듈은 ``assets``를 import하지 않는다(``assets``가 이것을 부른다). 그래서 Dagster
resource는 호출자가 꺼내 넘긴다.
"""

import math
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Final, cast

from kortravelmap.client import AddressValidationFinding, AsyncKorTravelMapClient
from kortravelmap.core.exceptions import IntegrityFindingPersistenceError
from kortravelmap.core.ids import make_integrity_finding_key, make_source_record_key
from kortravelmap.dto import Coordinate, FeatureBundle
from kortravelmap.geocoding import PrefetchingReverseGeocoder, ReverseGeocoder
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    ProviderEntityReobservationConflict,
)
from kortravelmap.providers.mois import (
    PROMOTED_SERVICE_SLUGS,
    PROVIDER_NAME,
    license_record_payload_hash,
    license_records_to_bundles,
    license_reverse_geocode_coordinate,
    license_source_entity_id,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import (
    AssetExecutionContext,
    DagsterRunNotFoundError,
    DagsterRunStatus,
    DefaultSensorStatus,
    Failure,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    sensor,
)

from .etl import (
    FEATURE_ID_METADATA_LIMIT,
    DagsterFeatureLoadResult,
    _add_output_metadata,
    _dagster_run_id,
    _normalize_address_validation_mode,
    load_feature_bundles_for_dagster,
)
from .run_scope import map_owned_runs_filter
from .validation import validate_feature_bundles_address

__all__ = [
    "MOIS_LOAD_CHUNK_SIZE",
    "MOIS_LOAD_JOB_NAME",
    "MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED",
    "MOIS_LOAD_OUTCOME_COMPLETE",
    "MOIS_LOAD_OUTCOME_TAG",
    "MoisChunkedLoadOutcome",
    "MoisLoadPlan",
    "iter_slug_chunks",
    "load_mois_license_records_chunked",
    "mois_load_continuation_decision",
    "mois_load_continuation_sensor",
    "resolve_mois_load_plan",
]

MOIS_LOAD_CHUNK_SIZE: Final[int] = 500
"""commit 단위. 지오코딩 동시성 2에서 chunk 하나가 수십 초라 상한 판정이 거칠지 않다."""

MOIS_LOAD_JOB_NAME: Final[str] = "feature_place_mois_licenses_job"
"""MOIS 적재 job(= operation key). schedule spec·큐 runner와 같은 이름이다."""

MOIS_LOAD_OUTCOME_TAG: Final[str] = "kor_travel_map.mois_load.outcome"
"""run이 끝날 때 남기는 결과 tag. 이어 달리기 sensor가 이것만 본다."""

MOIS_LOAD_OUTCOME_COMPLETE: Final[str] = "complete"
MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED: Final[str] = "budget_exhausted"

MOIS_LOAD_CONVERTED_TAG: Final[str] = "kor_travel_map.mois_load.records_converted"
"""이번 run이 실제로 변환·적재한 행 수. 0이면 이어 달려도 전진하지 않는다."""

MOIS_LOAD_BUDGET_TAG: Final[str] = "kor_travel_map.mois_load.budget_seconds"
"""이번 run의 실제 시간 상한(초, run 상한 tag로 깎은 값)."""

MOIS_LOAD_AVAILABLE_TAG: Final[str] = "kor_travel_map.mois_load.budget_available_seconds"
"""적재 loop가 시작할 때 남아 있던 시간(초). step 재시도는 run 시작 기준이라 이것이 작다."""

MOIS_LOAD_GEOCODE_DEGRADED_TAG: Final[str] = "kor_travel_map.mois_load.geocode_degraded"
"""역지오코딩이 부분 장애로 보인 업종(쉼표 구분). 있으면 run은 봉인·sync 성공을 남기지 않는다."""

MOIS_LOAD_FULL_COVERAGE_TAG: Final[str] = "kor_travel_map.mois_load.full_coverage"
"""전 PROMOTED 업종 run인가. 연속 degraded 판정이 "봉인 자격이 있는 run"만 비교하게 한다."""

UNRESOLVABLE_MARKER_TYPE: Final[str] = "mois_reverse_geocode_unresolvable"
"""역지오코딩 불가 표식의 finding 종류(``ops.data_integrity_violations.violation_type``).

geo가 건강한데(chunk가 장애 판정 없이 commit됨) 빈 답을 받은 행을
``(slug::mng_no 의 dedupe key, payload.source_record_key)``로 남긴다. ``source_record_key``가
payload hash에서 파생되므로 payload가 바뀌면 표식이 저절로 맞지 않는다(ADR-108 §3a-3).
"""

UNRESOLVABLE_MARKER_RETRY_DAYS: Final[int] = 30
"""표식이 이보다 오래 다시 관측되지 않았으면 믿지 않고 다시 지오코딩한다(geo 데이터 갱신 반영)."""

GEOCODE_RATIO_MIN_SAMPLE: Final[int] = 50
"""degraded 비율을 재기 시작하는 **지오코더로 보낸 행** 수(업종·run 각각)."""

GEO_PASSING_TRIPS_DEGRADE: Final[int] = 3
"""같은 업종에서 "빈 답 문턱은 넘었지만 probe는 통과"가 이만큼 거듭되면 그 업종을 degraded로 본다.

probe는 다른 지역의 좋은 좌표를 묻기 때문에 시·도 하나의 layer만 빈 **지역 장애**를 가리지
못한다(최종 델타 리뷰 MED-1). ``mng_no``가 발급 지자체 순이라 그런 장애는 한 업종 안에서
연속된 문턱 초과로 나타난다.
"""

_LICENSE_ENTITY_TYPE: Final[str] = "license_place"
"""``providers.mois``가 ``SourceRecord.source_entity_type``으로 쓰는 값."""

LOSS_GUARD_MIN_SAMPLE: Final[int] = 200
"""업종 소실 하한을 재기 시작하는 최소 관측 행 수.

종전 하한(drop 비율 > 0.5)을 chunk마다 재면 1~3행짜리 꼬리 chunk의 한 행이 100% 소실이
되어 run이 영구히 실패했다(적대 리뷰 MED-1). 업종 누적으로 재고, 표본이 이만큼 모이기 전에는
판정하지 않는다 — 작은 업종의 drop은 행 단위 finding으로 남는다.
"""

LOSS_GUARD_DROP_RATIO: Final[float] = 0.5
"""업종 누적 **데이터 무효** drop 비율 상한(종전 ``_DATASET_LOSS_DROP_RATIO``와 같은 값)."""

GEO_OUTAGE_MIN_LOOKUPS: Final[int] = 20
"""geo 장애 판정을 시작하는 최근 조회 수."""

GEO_OUTAGE_EMPTY_RATIO: Final[float] = 0.8
"""최근 조회 중 법정동코드 없이 돌아온 비율이 이 이상이면 upstream 장애로 본다."""

GEO_PROBE_REFERENCE: Final[Coordinate] = Coordinate(
    lon=Decimal("126.9779692"), lat=Decimal("37.5662952")
)
"""장애 판정 probe의 기본 좌표(서울시청, 내륙). 이 run에서 답을 받은 좌표가 있으면 그것이 먼저다."""

REOBSERVATION_CONFLICT_RETRIES: Final[int] = 2
"""확인 뒤 entity가 바뀐 chunk를 run 안에서 다시 확인·적재하는 횟수."""

RUN_FINAL_MARGIN_SECONDS: Final[int] = 1_800
"""run 상한 앞에 남기는 여유 — 마지막 chunk·봉인 질의·sync 기록."""

_RUN_MAX_RUNTIME_TAG: Final[str] = "dagster/max_runtime"

_GEOCODE_DROP_CODES: Final[frozenset[str]] = frozenset({"reverse_geocode_failed"})
"""drop 사유 중 지오코더가 답을 못 낸 것. 나머지 drop 사유는 원천 데이터 무효다."""


@dataclass(frozen=True)
class MoisLoadPlan:
    """run 하나의 적재 범위와 손잡이. run_config(업종 선택)와 settings(나머지)에서 온다."""

    service_slugs: tuple[str, ...]
    """이번 run이 볼 업종(정렬). 비어 있지 않다."""
    full_coverage: bool
    """전 PROMOTED 업종인가 — 그래야 완료 run이 snapshot 전체를 봉인할 수 있다."""
    source_db_path: str | None
    geocode_concurrency: int
    run_budget_seconds: int
    geocode_degraded_ratio: float = 0.05
    """업종(관측 200행 이상)·run의 역지오코딩 빈 답 비율 상한. 넘으면 run은 degraded다."""


_MIN_RUN_BUDGET_SECONDS: Final[int] = 60
_MAX_RUN_BUDGET_SECONDS: Final[int] = 19_800


def resolve_mois_load_plan(
    settings: KorTravelMapSettings,
    service_slugs: Iterable[str] = (),
    *,
    run_budget_seconds: int | None = None,
) -> MoisLoadPlan:
    """run_config의 업종 선택을 검증해 plan으로 만든다. 빈 선택은 전 업종이다.

    PROMOTED 밖의 이름은 조용히 버리지 않고 거부한다 — 오타 하나가 "0건 적재 성공"이 되면
    검증 run이 아무것도 검증하지 않은 채 초록이 된다. ``run_budget_seconds``는 검증 run이
    상한 정지·이어 달리기를 작은 업종으로 시험할 수 있게 하는 run 단위 override다(settings와
    같은 범위).
    """
    budget = (
        settings.mois_load_run_budget_seconds
        if run_budget_seconds is None
        else run_budget_seconds
    )
    if not _MIN_RUN_BUDGET_SECONDS <= budget <= _MAX_RUN_BUDGET_SECONDS:
        raise ValueError(
            f"MOIS run 시간 상한은 {_MIN_RUN_BUDGET_SECONDS}~{_MAX_RUN_BUDGET_SECONDS}초다: "
            f"{budget}"
        )
    requested = tuple(str(slug).strip() for slug in service_slugs if str(slug).strip())
    unknown = sorted(set(requested) - PROMOTED_SERVICE_SLUGS)
    if unknown:
        raise ValueError(f"MOIS 적재 업종 선택에 PROMOTED가 아닌 이름이 있다: {unknown}")
    selected = tuple(sorted(set(requested) or PROMOTED_SERVICE_SLUGS))
    return MoisLoadPlan(
        service_slugs=selected,
        full_coverage=set(selected) == PROMOTED_SERVICE_SLUGS,
        source_db_path=settings.mois_source_db_path,
        geocode_concurrency=settings.mois_geocode_concurrency,
        run_budget_seconds=budget,
        geocode_degraded_ratio=settings.mois_geocode_degraded_ratio,
    )


def iter_slug_chunks(records: Iterable[Any], size: int) -> Iterator[list[Any]]:
    """``(service_slug, mng_no)`` 순 stream을 **업종 경계에서 끊기는** chunk로 나눈다.

    chunk 하나는 언제나 한 업종이다 — 업종별 진행을 정확히 보고하고, 업종 하나가 끝나면
    그 업종의 마지막 chunk가 곧바로 commit된다.
    """
    if size <= 0:
        raise ValueError("chunk size must be positive")
    chunk: list[Any] = []
    for record in records:
        if chunk and (
            len(chunk) >= size or record.service_slug != chunk[0].service_slug
        ):
            yield chunk
            chunk = []
        chunk.append(record)
    if chunk:
        yield chunk


@dataclass(frozen=True)
class MoisChunkedLoadOutcome:
    """run 하나의 결과 — 적재 결과와 재개에 필요한 사실."""

    result: DagsterFeatureLoadResult
    complete: bool
    """선택 업종을 끝까지 다 봤는가(상한으로 멈추지 않았는가)."""
    full_coverage: bool
    slugs_completed: tuple[str, ...]
    stopped_in_slug: str | None
    records_seen: int
    records_unchanged: int
    records_converted: int
    chunks_committed: int
    reverse_geocode_live_calls: int
    reverse_geocode_cache_hits: int
    reverse_geocode_prefetch_failures: int
    dropped_count: int
    geocode_empty: int = 0
    """역지오코딩이 빈 답을 낸 행 수.

    이 행들은 적재하지 않는다(모든 검증 모드) — 다음 run이 다시 한다.
    """
    geocode_degraded_slugs: tuple[str, ...] = ()
    geo_probes: int = 0
    geo_probe_passes: int = 0
    geocoded_rows: int = 0
    """지오코더로 보낸 행 수(이미 적재된 행·원천 법정동 코드 행·역지오코딩 불가 표식 행 제외)."""
    known_unresolvable: int = 0
    """역지오코딩 불가 표식이 현재 payload와 맞아 조회하지 않은 행 수."""

    @property
    def outcome(self) -> str:
        return MOIS_LOAD_OUTCOME_COMPLETE if self.complete else MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED

    @property
    def authoritative(self) -> bool:
        """전 업종을 이 run 안에서 끝까지 확인했는가 — curation seal의 조건.

        본 record가 0건이면 봉인하지 않는다. 빈 원천(sync 실패로 비어 버린 SQLite 등)을
        "snapshot 전체를 확인했다"로 승격하면 그 빈 관측이 curation의 기준이 된다.
        """
        return (
            self.complete
            and self.full_coverage
            and self.records_seen > 0
            and not self.geocode_degraded_slugs
        )

    def as_metadata(self) -> dict[str, object]:
        return {
            "mois_load_outcome": self.outcome,
            "mois_load_full_coverage": self.full_coverage,
            "mois_load_slugs_completed": list(self.slugs_completed),
            "mois_load_stopped_in_slug": self.stopped_in_slug or "",
            "mois_load_records_seen": self.records_seen,
            "mois_load_records_unchanged": self.records_unchanged,
            "mois_load_records_converted": self.records_converted,
            "mois_load_chunks_committed": self.chunks_committed,
            "mois_reverse_geocode_live_calls": self.reverse_geocode_live_calls,
            "mois_reverse_geocode_cache_hits": self.reverse_geocode_cache_hits,
            "mois_reverse_geocode_prefetch_failures": self.reverse_geocode_prefetch_failures,
            "mois_reverse_geocode_empty": self.geocode_empty,
            "mois_geocode_degraded": bool(self.geocode_degraded_slugs),
            "mois_geocode_degraded_slugs": list(self.geocode_degraded_slugs),
            "mois_geo_probes": self.geo_probes,
            "mois_geo_probe_passes": self.geo_probe_passes,
            "mois_geocoded_rows": self.geocoded_rows,
            "mois_known_unresolvable": self.known_unresolvable,
        }


class _ChunkMetadataSink:
    """chunk 적재 함수가 싣는 metadata를 가로채 run 끝에 한 번만 싣게 하는 context 대리.

    ``load_feature_bundles_for_dagster``는 호출마다 그 chunk의 metadata를 싣는다. chunk가
    2,000개면 마지막 chunk 값이 run 결과처럼 남는다. 그래서 chunk 호출에는 이 대리를 넘기고,
    버린 행 수만 모아 둔다. 그 밖의 속성(run_id·log·instance 등)은 원래 context로 간다.
    """

    def __init__(self, context: Any) -> None:
        self._context = context
        self.dropped = 0

    def add_output_metadata(self, metadata: Mapping[str, object]) -> None:
        dropped = metadata.get("address_validation_dropped_count", 0)
        if isinstance(dropped, int):
            self.dropped += dropped

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)


def _cap_feature_ids(result: DagsterFeatureLoadResult) -> DagsterFeatureLoadResult:
    if len(result.feature_ids) <= FEATURE_ID_METADATA_LIMIT:
        return result
    return replace(
        result,
        feature_ids=result.feature_ids[:FEATURE_ID_METADATA_LIMIT],
        feature_ids_complete=False,
    )


@dataclass(frozen=True)
class _Unresolvable:
    """역지오코딩 불가 표식 후보 한 행."""

    source_entity_id: str
    source_record_key: str
    lon: float | None
    lat: float | None


@dataclass(frozen=True)
class _ChunkLoad:
    """chunk 하나를 commit한 결과."""

    result: DagsterFeatureLoadResult
    unchanged: int
    converted: int
    geocode_empty: int
    invalid_drops: int
    passing_trip: bool
    geocoded: int
    known_unresolvable: int
    empties: tuple["_Unresolvable", ...]
    """이 chunk에서 빈 답을 받은 행(표식 후보). 쓸지는 run 끝에 업종 상태를 보고 정한다."""


def _run_clock_start(context: Any, fallback: float) -> float:
    """run이 **시작한** 시각(epoch 초). 직접 호출·테스트면 ``fallback``.

    step 시작이 아니라 run 시작이다 — resource init의 Phase A sync(실측 약 24분)와 step
    재시도가 이미 쓴 시간을 run 상한에서 빼야 한다(적대 리뷰 MED-3).
    """
    instance = getattr(context, "instance", None)
    try:
        run_id = context.run_id
    except Exception:  # noqa: BLE001 — 직접 호출 context에는 run이 없다
        return fallback
    get_record = getattr(instance, "get_run_record_by_id", None)
    if not run_id or not callable(get_record):
        return fallback
    record = get_record(run_id)
    start_time = getattr(record, "start_time", None)
    if isinstance(start_time, bool) or not isinstance(start_time, int | float):
        return fallback
    started = float(start_time)
    # 0·음수·무한·미래 시각은 run 시작으로 믿지 않는다 — 상한 계산을 망가뜨린다.
    if not math.isfinite(started) or started <= 0 or started > fallback:
        return fallback
    return started


def _run_max_runtime_seconds(context: Any) -> int | None:
    """이 run에 걸린 Dagster run 상한(``dagster/max_runtime`` tag), 없으면 ``None``."""
    try:
        tags = context.run.tags
    except Exception:  # noqa: BLE001 — 직접 호출 context에는 run이 없다
        return None
    raw = tags.get(_RUN_MAX_RUNTIME_TAG) if isinstance(tags, Mapping) else None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def effective_run_budget_seconds(plan_budget: int, run_max_runtime: int | None) -> int:
    """plan 상한을 run 상한 - 여유(``RUN_FINAL_MARGIN_SECONDS``) 안으로 깎는다."""
    if run_max_runtime is None:
        return plan_budget
    return max(0, min(plan_budget, run_max_runtime - RUN_FINAL_MARGIN_SECONDS))


async def load_mois_license_records_chunked(
    *,
    context: AssetExecutionContext,
    client: AsyncKorTravelMapClient,
    records: Iterable[Any],
    plan: MoisLoadPlan,
    fetched_at: datetime,
    dataset_key: str,
    strict_address: bool | str,
    reverse_geocoder: ReverseGeocoder | None,
    clock: Callable[[], float] = time.time,
    convert: Callable[..., Awaitable[list[FeatureBundle]]] = license_records_to_bundles,
) -> MoisChunkedLoadOutcome:
    """선택 업종의 영업중 record를 chunk 단위로 commit하며 적재한다(재개형).

    ``records``는 ``(service_slug, mng_no)`` 순 stream이다(provider가 그 순서를 보장).
    ``clock``(epoch 초)·``convert``는 테스트가 시간과 변환을 대신하기 위한 자리다.
    시간 상한은 **run 시작**부터 재고, run 상한 tag(``dagster/max_runtime``)에서
    ``RUN_FINAL_MARGIN_SECONDS``를 뺀 값을 넘지 않는다.
    """
    from .mois_source_sync import read_mois_source_synced_at  # schedules→assets 순환 회피

    snapshot_at = read_mois_source_synced_at(plan.source_db_path)
    # 같은 snapshot을 다시 돌린 run은 이 시각보다 이미 새로 관측된 행을 다시 쓰지 않는다.
    # marker가 없으면(로컬·테스트) run 시각을 쓴다 — 매 run 재관측하지만 틀리지는 않다.
    observed_at = snapshot_at or fetched_at
    prefetcher = (
        PrefetchingReverseGeocoder(reverse_geocoder, concurrency=plan.geocode_concurrency)
        if reverse_geocoder is not None
        else None
    )
    mode = _normalize_address_validation_mode(strict_address)
    sink = _ChunkMetadataSink(context)
    effective_budget = effective_run_budget_seconds(
        plan.run_budget_seconds, _run_max_runtime_seconds(context)
    )
    deadline = _run_clock_start(context, clock()) + effective_budget
    # 0행 정지 규칙은 "상한을 거의 다 쓰고도 전진하지 못한" run에만 적용해야 한다. 늦은 실패
    # 뒤의 step 재시도는 run 시작 기준 상한이 이미 지나 한 chunk만 하고 멈추므로, 그 run을 보고
    # 멈추면 한 달짜리 정체가 된다(적대 리뷰 MED-1) — 남은 시간을 tag로 남긴다.
    budget_available = max(0, int(deadline - clock()))

    async def _load_chunk(chunk: list[Any], slug_seen: int, slug_invalid: int) -> _ChunkLoad:
        payload_hashes = {
            license_source_entity_id(record): license_record_payload_hash(record)
            for record in chunk
        }
        unchanged = await client.find_unchanged_active_source_entities(
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            source_entity_type=_LICENSE_ENTITY_TYPE,
            payload_hashes=payload_hashes,
        )
        to_convert = [
            record for record in chunk if license_source_entity_id(record) not in unchanged
        ]
        known = await _known_unresolvable(
            client,
            dataset_key=dataset_key,
            records=[r for r in to_convert if license_reverse_geocode_coordinate(r) is not None],
            payload_hashes=payload_hashes,
        )
        if known:
            # 같은 payload로 최근 빈 답을 받은 행 — 조회하지 않고 적재하지도 않는다
            # (빈 답 행과 같다).
            to_convert = [r for r in to_convert if license_source_entity_id(r) not in known]
        geocoded = sum(
            1 for record in to_convert if license_reverse_geocode_coordinate(record) is not None
        )
        if prefetcher is not None and to_convert:
            await prefetcher.prefetch(
                coord
                for record in to_convert
                if (coord := license_reverse_geocode_coordinate(record)) is not None
            )
            passing_trip = await _raise_if_geo_outage(prefetcher, slug=str(chunk[0].service_slug))
        else:
            passing_trip = False
        bundles = await convert(
            to_convert,
            fetched_at=fetched_at,
            dataset_key=dataset_key,
            reverse_geocoder=prefetcher if prefetcher is not None else reverse_geocoder,
        )
        geocode_empty_ids, invalid_drops = _classify_drops(bundles, mode=mode)
        empty_bundles = [b for b in bundles if b.feature.feature_id in geocode_empty_ids]
        if geocode_empty_ids and mode == "off":
            # off 모드는 원래 전부 적재한다. 그러나 빈 bjd로 commit하면 payload가 같은 한 다음
            # run이 "그대로"로 건너뛰고, 같은 payload의 재적재는 feature 본문을 다시 쓰지 않아
            # 빈 bjd가 영원히 남는다(최종 델타 리뷰 MED-1 ③). 그래서 MOIS 적재기는 모드와 무관하게
            # 지오코더가 빈 답을 낸 행을 적재하지 않는다 — 다음 run이 다시 조회한다. 단 geo가
            # 건강했던 업종의 행은 run 끝에 표식이 남아 같은 payload면 30일 뒤에 다시 조회한다.
            bundles = [b for b in bundles if b.feature.feature_id not in geocode_empty_ids]
        _raise_if_slug_lost(
            slug=str(chunk[0].service_slug),
            seen=slug_seen + len(chunk),
            invalid=slug_invalid + invalid_drops,
        )
        result = await load_feature_bundles_for_dagster(
            context=cast(AssetExecutionContext, sink),
            client=client,
            bundles=bundles,
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            strict_address=strict_address,
            authoritative_snapshot_complete=False,
            load_all=_chunk_loader(
                client,
                dataset_key=dataset_key,
                reobserved={key: payload_hashes[key] for key in unchanged},
                observed_at=observed_at,
            ),
            enforce_loss_guard=False,
        )
        # 이번에 풀린 행에 열려 있던 표식은 더는 참이 아니다 — 닫는다(open 표식이 쌓이지 않게).
        resolved_ids = [
            b.source_record.source_entity_id
            for b in bundles
            if b.admin_evidence is not None
            and b.admin_evidence.reverse_attempted
            and b.admin_evidence.obs_code is not None
        ]
        if resolved_ids:
            try:
                await client.resolve_open_findings_by_key(
                    violation_type=UNRESOLVABLE_MARKER_TYPE,
                    dedupe_keys=[_unresolvable_marker_key(dataset_key, i) for i in resolved_ids],
                    reason="reverse geocode resolved",
                )
            except IntegrityFindingPersistenceError as exc:
                # 표식을 못 닫으면 열린 표식이 남을 뿐이다(그 행은 이미 적재돼 다음 run이 건너뛴다).
                # 결합된 transaction까지 되감았다면 적재가 사라진 것이라 삼킬 수 없다.
                if exc.transaction_destroyed:
                    raise
                context.log.warning(f"MOIS 역지오코딩 불가 표식 닫기 실패(무해): {exc}")
        return _ChunkLoad(
            result=result,
            unchanged=len(unchanged),
            converted=len(to_convert),
            geocode_empty=len(geocode_empty_ids),
            invalid_drops=invalid_drops,
            passing_trip=passing_trip,
            geocoded=geocoded,
            known_unresolvable=len(known),
            empties=tuple(
                _Unresolvable(
                    source_entity_id=b.source_record.source_entity_id,
                    source_record_key=b.source_record.source_record_key,
                    lon=float(b.feature.coord.lon) if b.feature.coord else None,
                    lat=float(b.feature.coord.lat) if b.feature.coord else None,
                )
                for b in empty_bundles
            ),
        )

    merged: DagsterFeatureLoadResult | None = None
    slugs_completed: list[str] = []
    current_slug: str | None = None
    stopped_in_slug: str | None = None
    records_seen = records_unchanged = records_converted = chunks = 0
    slug_seen = slug_invalid = slug_geocode_empty = slug_passing_trips = slug_geocoded = 0
    run_geocode_empty = run_geocoded = run_known_unresolvable = 0
    degraded: list[str] = []
    slug_geocoded_totals: dict[str, int] = {}
    """업종별 조회 행 수 — 표본(``GEOCODE_RATIO_MIN_SAMPLE``)에 못 미친 업종을 가린다."""
    marker_candidates: dict[str, list[_Unresolvable]] = {}
    """업종별 표식 후보. 문턱 초과(probe 통과) chunk의 빈 답은 넣지 않는다 — 지역 장애일 수 있다."""

    def _mark_degraded(slug: str, reason: str) -> None:
        if slug in degraded:
            return
        degraded.append(slug)
        context.log.warning(
            f"MOIS 업종 {slug} 역지오코딩 부분 장애로 보인다({reason}) — "
            "이 업종의 빈 답 행은 적재하지 않았고 표식도 남기지 않으므로 다음 run이 다시 조회한다. "
            "이 run은 봉인·sync 성공을 남기지 않는다."
        )

    complete = True

    for chunk in iter_slug_chunks(records, MOIS_LOAD_CHUNK_SIZE):
        slug = str(chunk[0].service_slug)
        if slug != current_slug:
            if current_slug is not None:
                slugs_completed.append(current_slug)
                context.log.info(f"MOIS 업종 {current_slug} 완료 ({len(slugs_completed)}개째)")
            current_slug = slug
            slug_seen = slug_invalid = slug_geocode_empty = slug_passing_trips = slug_geocoded = 0
        # 상한 판정은 chunk **사이**에서만 한다 — 시작한 chunk는 끝까지 commit한다. 첫
        # chunk는 언제나 시작하므로 run마다 최소 한 chunk는 전진한다(무한 이어 달리기 방지).
        if chunks > 0 and clock() >= deadline:
            complete = False
            stopped_in_slug = slug
            break

        attempt = 0
        while True:
            try:
                loaded = await _load_chunk(chunk, slug_seen, slug_invalid)
                break
            except ProviderEntityReobservationConflict as exc:
                # 확인과 기록 사이에 dedup·관리자 변경이 끼었다. chunk는 통째로 되돌아갔으므로
                # 그 chunk만 다시 확인해 적재한다(지오코딩은 run 캐시에서 나온다).
                attempt += 1
                if attempt > REOBSERVATION_CONFLICT_RETRIES:
                    raise
                context.log.warning(
                    f"MOIS 업종 {slug} chunk 재확인({attempt}/"
                    f"{REOBSERVATION_CONFLICT_RETRIES}): {exc}"
                )
        merged = _cap_feature_ids(
            loaded.result if merged is None else merged.merge(loaded.result)
        )
        chunks += 1
        records_seen += len(chunk)
        records_unchanged += loaded.unchanged
        records_converted += loaded.converted
        slug_seen += len(chunk)
        slug_invalid += loaded.invalid_drops
        slug_geocode_empty += loaded.geocode_empty
        run_geocode_empty += loaded.geocode_empty
        slug_geocoded += loaded.geocoded
        run_geocoded += loaded.geocoded
        run_known_unresolvable += loaded.known_unresolvable
        slug_geocoded_totals[slug] = slug_geocoded_totals.get(slug, 0) + loaded.geocoded
        if not loaded.passing_trip:
            marker_candidates.setdefault(slug, []).extend(loaded.empties)
        if loaded.passing_trip:
            slug_passing_trips += 1
            if slug_passing_trips >= GEO_PASSING_TRIPS_DEGRADE:
                _mark_degraded(slug, f"probe 통과 뒤에도 빈 답 문턱 초과 {slug_passing_trips}회")
        # 분모는 **지오코더로 보낸 행**이다 — 이미 적재돼 건너뛴 행으로 희석하면 정상 상태의
        # 지역 장애가 보이지 않는다(델타 리뷰 LOW-1).
        if (
            slug_geocoded >= GEOCODE_RATIO_MIN_SAMPLE
            and slug_geocode_empty > slug_geocoded * plan.geocode_degraded_ratio
        ):
            _mark_degraded(slug, f"빈 답 {slug_geocode_empty}/{slug_geocoded}건 조회")

    if complete and current_slug is not None:
        slugs_completed.append(current_slug)
        context.log.info(f"MOIS 업종 {current_slug} 완료 ({len(slugs_completed)}개째)")
    # run 전체 상한 — 업종마다 표본이 모자라 업종 판정을 피한 작은 업종들의 빈 답도 센다.
    # 다른 업종이 이미 degraded여도 **언제나** 잰다 — 같은 지역 장애의 작은 업종들이 숨지 않게.
    if (
        run_geocoded >= GEOCODE_RATIO_MIN_SAMPLE
        and run_geocode_empty > run_geocoded * plan.geocode_degraded_ratio
    ):
        _mark_degraded("(run)", f"빈 답 {run_geocode_empty}/{run_geocoded}건 조회")
    # 표식은 run 끝에 한 번 쓴다 — degraded 업종(그리고 run 전체가 degraded면 전부)은 쓰지 않는다.
    # 표식이 생기면 다음 run이 그 행을 보지 않아 degraded가 사라지고 봉인·sync 성공이 남는다
    # (최종 리뷰 MED-1). 실패로 여기까지 오지 못한 run은 아무것도 쓰지 않는다 — 다시 조회할 뿐이다.
    # 무엇이든 degraded면 표본이 모자라 스스로 판정받지 못한 업종도 믿지 않는다 — 같은 지역 장애의
    # 작은 업종일 수 있다(narrow 리뷰 MED-1). 그 업종의 빈 답은 표식 없이 다음 run이 다시 조회한다.
    if "(run)" not in degraded:
        await _record_unresolvable_markers(
            context,
            client,
            dataset_key=dataset_key,
            rows=[
                row
                for slug_name, rows in marker_candidates.items()
                if slug_name not in degraded
                and (
                    not degraded
                    or slug_geocoded_totals.get(slug_name, 0) >= GEOCODE_RATIO_MIN_SAMPLE
                )
                for row in rows
            ],
        )

    if merged is None:
        # 선택 업종에 영업중 record가 하나도 없다. 빈 load로 같은 모양의 결과를 만든다.
        merged = await load_feature_bundles_for_dagster(
            context=cast(AssetExecutionContext, sink),
            client=client,
            bundles=[],
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            strict_address=strict_address,
            authoritative_snapshot_complete=False,
            load_all=lambda _batch: _empty_load(),
        )

    outcome = MoisChunkedLoadOutcome(
        result=merged,
        complete=complete,
        full_coverage=plan.full_coverage,
        slugs_completed=tuple(slugs_completed),
        stopped_in_slug=stopped_in_slug,
        records_seen=records_seen,
        records_unchanged=records_unchanged,
        records_converted=records_converted,
        chunks_committed=chunks,
        reverse_geocode_live_calls=prefetcher.live_calls if prefetcher is not None else 0,
        reverse_geocode_cache_hits=prefetcher.cache_hits if prefetcher is not None else 0,
        reverse_geocode_prefetch_failures=(
            prefetcher.prefetch_failures if prefetcher is not None else 0
        ),
        dropped_count=sink.dropped,
        geocode_empty=run_geocode_empty,
        geocode_degraded_slugs=tuple(degraded),
        geo_probes=prefetcher.probes if prefetcher is not None else 0,
        geo_probe_passes=prefetcher.probe_passes if prefetcher is not None else 0,
        geocoded_rows=run_geocoded,
        known_unresolvable=run_known_unresolvable,
    )

    if outcome.authoritative:
        # 이 run이 전 업종의 모든 행을 확인했다(건너뛴 행도 "이미 그대로 있다"를 확인한
        # 것이다). 그래서 지금 DB image가 이 snapshot이고, 그것을 봉인한다 — 빈 적재
        # transaction 안에서 seal만 읽는다.
        seal = await client.load_feature_bundles(
            [], curation_dataset=(PROVIDER_NAME, dataset_key)
        )
        outcome = replace(
            outcome,
            result=replace(
                outcome.result, load=outcome.result.load.merge(seal)
            ).complete_authoritative_snapshot(),
        )

    metadata = outcome.result.as_metadata()
    metadata.update(outcome.as_metadata())
    if outcome.dropped_count:
        metadata["address_validation_dropped_count"] = outcome.dropped_count
    _add_output_metadata(context, metadata)
    _tag_run_outcome(
        context,
        {
            MOIS_LOAD_OUTCOME_TAG: outcome.outcome,
            MOIS_LOAD_CONVERTED_TAG: str(outcome.records_converted),
            MOIS_LOAD_BUDGET_TAG: str(int(effective_budget)),
            MOIS_LOAD_AVAILABLE_TAG: str(budget_available),
            MOIS_LOAD_FULL_COVERAGE_TAG: "true" if outcome.full_coverage else "false",
            **(
                {MOIS_LOAD_GEOCODE_DEGRADED_TAG: ",".join(outcome.geocode_degraded_slugs)}
                if outcome.geocode_degraded_slugs
                else {}
            ),
        },
    )
    if outcome.geocode_degraded_slugs and outcome.complete and outcome.full_coverage:
        previous = _degraded_full_run_since_last_complete(context)
        previous_degraded = (
            previous.tags.get(MOIS_LOAD_GEOCODE_DEGRADED_TAG) if previous is not None else None
        )
        if previous_degraded:
            # 두 번 연속이면 일시적 흔들림이 아니다 — 붉은 run으로 드러낸다. outcome은 이미
            # complete로 tag됐으므로 이어 달리기 사슬을 막지 않고, 재시도는 같은 결과라 끈다.
            raise Failure(
                description=(
                    "MOIS 역지오코딩이 연속 두 전체 run에서 부분 장애로 보인다 — 이번 "
                    f"{list(outcome.geocode_degraded_slugs)}, 직전 run {previous.run_id} "
                    f"[{previous_degraded}]. 빈 답 행은 적재하지 않았고 봉인·sync 성공도 없다. "
                    "kor-travel-geo 데이터(해당 지역 layer)를 확인할 것."
                ),
                metadata={
                    "mois_geocode_degraded_slugs": list(outcome.geocode_degraded_slugs),
                    "mois_previous_degraded_run": previous.run_id,
                },
                allow_retries=False,
            )
    return outcome


def _degraded_full_run_since_last_complete(context: Any) -> Any:
    """직전 완료 전체 run까지(포함) 거슬러 올라가며 degraded였던 전체 run을 찾는다. 없으면 ``None``.

    이어 달리기 사슬의 ``budget_exhausted`` run도 비교한다 — 사슬 중간 run이 degraded였는데
    마지막 run만 비교하면 두 번째 degraded를 놓친다(최종 리뷰 MED-1).
    """
    instance = getattr(context, "instance", None)
    get_runs = getattr(instance, "get_runs", None)
    try:
        run_id = context.run_id
    except Exception:  # noqa: BLE001 — 직접 호출 context에는 run이 없다
        return None
    if not run_id or not callable(get_runs):
        return None
    runs = get_runs(
        filters=map_owned_runs_filter(
            job_name=MOIS_LOAD_JOB_NAME,
            tags={
                "kor_travel_map.operation_key": MOIS_LOAD_JOB_NAME,
                MOIS_LOAD_FULL_COVERAGE_TAG: "true",
            },
        ),
        limit=_CHAIN_LOOKBACK_LIMIT,
    )
    for run in runs:
        if run.run_id == run_id:
            continue
        if run.tags.get(MOIS_LOAD_GEOCODE_DEGRADED_TAG):
            return run
        if run.tags.get(MOIS_LOAD_OUTCOME_TAG) == MOIS_LOAD_OUTCOME_COMPLETE:
            return None
    if len(runs) >= _CHAIN_LOOKBACK_LIMIT:
        # 완료 run까지 닿지 못했다 — 사슬 안의 degraded를 확인할 수 없으므로 닫힌 쪽(degraded).
        context.log.warning(
            f"MOIS 연속 degraded 판정이 {_CHAIN_LOOKBACK_LIMIT}개 run 안에서 직전 완료 run에 닿지 "
            "못했다 — degraded 여부를 알 수 없으므로 degraded로 본다."
        )
        return SimpleNamespace(
            run_id=f"(완료 run이 최근 {_CHAIN_LOOKBACK_LIMIT}개 run 밖)",
            tags={MOIS_LOAD_GEOCODE_DEGRADED_TAG: "unknown"},
        )
    return None


_CHAIN_LOOKBACK_LIMIT: Final[int] = 500
"""사슬을 거슬러 볼 최대 run 수. 4시간 run 하나가 수만 행이라 98만 행 첫 적재도 수십 run이다."""


def _unresolvable_marker_key(dataset_key: str, source_entity_id: str) -> str:
    return make_integrity_finding_key(
        provider=PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=_LICENSE_ENTITY_TYPE,
        source_entity_id=source_entity_id,
        violation_type=UNRESOLVABLE_MARKER_TYPE,
    )


async def _known_unresolvable(
    client: AsyncKorTravelMapClient,
    *,
    dataset_key: str,
    records: Sequence[Any],
    payload_hashes: Mapping[str, str],
) -> frozenset[str]:
    """같은 payload로 최근(``UNRESOLVABLE_MARKER_RETRY_DAYS``) 빈 답 표식이 있는 행의 entity id."""
    if not records:
        return frozenset()
    by_marker: dict[str, str] = {}
    expected: dict[str, str] = {}
    for record in records:
        entity_id = license_source_entity_id(record)
        marker = _unresolvable_marker_key(dataset_key, entity_id)
        by_marker[marker] = entity_id
        expected[marker] = make_source_record_key(
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            source_entity_type=_LICENSE_ENTITY_TYPE,
            source_entity_id=entity_id,
            raw_payload_hash=payload_hashes[entity_id],
        )
    fresh = await client.find_fresh_open_findings(
        violation_type=UNRESOLVABLE_MARKER_TYPE,
        expected_source_record_keys=expected,
        max_age_days=UNRESOLVABLE_MARKER_RETRY_DAYS,
    )
    return frozenset(by_marker[marker] for marker in fresh)


async def _record_unresolvable_markers(
    context: Any,
    client: AsyncKorTravelMapClient,
    *,
    dataset_key: str,
    rows: Sequence[_Unresolvable],
) -> None:
    """빈 답 행에 표식을 남긴다(이미 있으면 ``last_seen_at``·payload가 전진). 실패는 무해하다.

    표식을 못 남기면 다음 run이 그 행을 다시 지오코딩할 뿐이다 — 적재를 멈출 이유가 아니다.
    """
    for start in range(0, len(rows), _MARKER_WRITE_BATCH):
        await _record_marker_batch(
            context, client, dataset_key=dataset_key, rows=rows[start : start + _MARKER_WRITE_BATCH]
        )


_MARKER_WRITE_BATCH: Final[int] = 1000


async def _record_marker_batch(
    context: Any,
    client: AsyncKorTravelMapClient,
    *,
    dataset_key: str,
    rows: Sequence[_Unresolvable],
) -> None:
    findings = tuple(
        AddressValidationFinding(
            dedupe_key=_unresolvable_marker_key(dataset_key, row.source_entity_id),
            violation_type=UNRESOLVABLE_MARKER_TYPE,
            severity="info",
            message=(
                "좌표가 kor-travel-geo에서 법정동으로 풀리지 않는다(해상·매립지·좌표 오류 추정). "
                f"같은 payload는 {UNRESOLVABLE_MARKER_RETRY_DAYS}일 동안 다시 조회하지 않는다."
            ),
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            linked=False,
            payload={
                "source_record_key": row.source_record_key,
                "source_entity_id": row.source_entity_id,
                "lon": row.lon,
                "lat": row.lat,
            },
        )
        for row in rows
    )
    try:
        await client.record_address_validation_findings(
            findings,
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            run_id=_dagster_run_id(context),
        )
    except IntegrityFindingPersistenceError as exc:
        # 결합된 transaction까지 되감았다면 삼킬 수 없다 — 적재가 사라진 것이다(etl과 같은 규칙).
        if exc.transaction_destroyed:
            raise
        context.log.warning(f"MOIS 역지오코딩 불가 표식 {len(findings)}건 기록 실패(무해): {exc}")


def _classify_drops(
    bundles: Sequence[FeatureBundle], *, mode: str
) -> tuple[frozenset[str], int]:
    """(지오코더가 빈 답을 낸 행의 feature id, drop 모드의 데이터 무효 drop 수).

    빈 답 행은 **모드와 무관하게** 센다 — drop은 적재 함수가 버리고, off는 호출자가 빼고, strict는
    run을 멈춘다. 데이터 무효(위치 단서 없음)는 drop 모드에서만 버려지므로 그때만 센다.
    """
    if not bundles:
        return frozenset(), 0
    validation = validate_feature_bundles_address(bundles)
    geocode = frozenset(
        issue.feature_id for issue in validation.issues if issue.code in _GEOCODE_DROP_CODES
    )
    if mode != "drop":
        return geocode, 0
    invalid = {
        issue.feature_id
        for issue in validation.blocking_issues
        if issue.code not in _GEOCODE_DROP_CODES
    }
    return geocode, len(invalid - geocode)


def _raise_if_slug_lost(*, slug: str, seen: int, invalid: int) -> None:
    """업종 누적 데이터 무효 drop이 하한을 넘으면 그 chunk를 commit하기 **전에** 멈춘다."""
    if seen < LOSS_GUARD_MIN_SAMPLE or invalid / seen <= LOSS_GUARD_DROP_RATIO:
        return
    raise Failure(
        description=(
            f"MOIS 업종 {slug}: 관측 {seen}건 중 {invalid}건이 위치 단서 없는 데이터 무효로 "
            "버려진다 — 적재가 아니라 소실이다. provider payload가 바뀌었는지 확인할 것."
        ),
        metadata={
            "mois_load_loss_slug": slug,
            "mois_load_loss_seen": seen,
            "mois_load_loss_invalid": invalid,
            "mois_load_loss_ratio_limit": LOSS_GUARD_DROP_RATIO,
        },
    )


async def _raise_if_geo_outage(prefetcher: PrefetchingReverseGeocoder, *, slug: str) -> bool:
    """최근 조회 대부분이 빈 답이고 **알려진 좋은 좌표도** 빈 답이면 upstream 장애로 멈춘다.

    빈 답 비율만으로 멈추면 재개 run이 영구히 막힌다(적대 리뷰 HIGH-1): drop 모드에서 정상적으로
    빈 답을 받는 좌표(바다·경계)의 행은 적재되지 않으므로 다음 run마다 다시 변환되고, 이미 적재된
    행은 건너뛰므로 그 행들이 조회의 대부분이 된다. 그래서 비율이 문턱을 넘으면 probe 한 번으로
    가른다 — 좋은 좌표가 답을 내면 geo는 건강하고 그 빈 답은 행 단위 사실이다(창을 비우고 계속).
    """
    if (
        prefetcher.recent_lookups < GEO_OUTAGE_MIN_LOOKUPS
        or prefetcher.recent_empty_ratio < GEO_OUTAGE_EMPTY_RATIO
    ):
        return False
    lookups, ratio = prefetcher.recent_lookups, prefetcher.recent_empty_ratio
    if await prefetcher.probe_healthy(GEO_PROBE_REFERENCE):
        # 문턱은 넘었지만 probe는 통과 — 행 단위 빈 답이거나 지역 장애다. 호출자가 센다.
        return True
    raise Failure(
        description=(
            f"kor-travel-geo 역지오코딩이 최근 {lookups}건 중 {ratio:.0%}를 빈 결과로 돌려주고 "
            "알려진 좋은 좌표 probe도 빈 결과다 — upstream 장애로 보고 "
            f"업종 {slug} 적재를 멈춘다(행을 버리지 않는다). 재시도·재실행은 이어서 적재한다."
        ),
        metadata={
            "mois_geo_outage_recent_lookups": lookups,
            "mois_geo_outage_empty_ratio": ratio,
        },
    )


def _chunk_loader(
    client: AsyncKorTravelMapClient,
    *,
    dataset_key: str,
    reobserved: Mapping[str, str],
    observed_at: datetime,
) -> Callable[[Sequence[FeatureBundle]], Awaitable[FeatureLoadResult]]:
    """chunk 하나의 transaction — 미변경 재관측 + 변경분 적재를 함께 commit한다."""

    async def _load(batch: Sequence[FeatureBundle]) -> FeatureLoadResult:
        return await client.load_feature_bundles_reobserving(
            batch,
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            source_entity_type=_LICENSE_ENTITY_TYPE,
            reobserved_payload_hashes=reobserved,
            observed_at=observed_at,
        )

    return _load


async def _empty_load() -> FeatureLoadResult:
    return FeatureLoadResult()


def _tag_run_outcome(context: Any, tags: Mapping[str, str]) -> None:
    """이어 달리기 sensor가 읽을 결과 tag. 실제 Dagster run 밖(직접 호출)에서는 생략한다."""
    instance = getattr(context, "instance", None)
    try:
        run_id = context.run_id
    except Exception:  # noqa: BLE001 — 직접 호출 context에는 run이 없다
        return
    add_run_tags = getattr(instance, "add_run_tags", None)
    if not run_id or not callable(add_run_tags):
        return
    try:
        add_run_tags(run_id, dict(tags))
    except DagsterRunNotFoundError:
        # ``build_asset_context``는 instance에 없는 run id(``EPHEMERAL``)를 준다 — 직접 호출이다.
        return


_ACTIVE_RUN_STATUSES: Final[tuple[DagsterRunStatus, ...]] = (
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.MANAGED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
    DagsterRunStatus.CANCELING,
)

_CONTINUATION_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.operation_key": MOIS_LOAD_JOB_NAME,
    "kor_travel_map.trigger_kind": "sensor",
    "kor_travel_map.timezone": "Asia/Seoul",
}


@sensor(
    name="feature_place_mois_licenses_continuation_sensor",
    job_name=MOIS_LOAD_JOB_NAME,
    minimum_interval_seconds=300,
    default_status=DefaultSensorStatus.STOPPED,
    description=(
        "MOIS 재개형 적재(ADR-108) 이어 달리기 — 마지막 run이 시간 상한으로 멈췄으면 같은 "
        "run_config로 다음 run을 띄운다. 실패한 run은 이어 달리지 않는다(사람이 본다)."
    ),
)
def mois_load_continuation_sensor(
    context: SensorEvaluationContext,
) -> RunRequest | SkipReason:
    """가장 최근 MOIS 적재 run 하나만 보고 판단한다.

    - 진행 중이면 기다린다(겹쳐 띄우지 않는다).
    - 실패·취소면 멈춘다 — 같은 실패를 자동으로 되풀이하지 않는다. 재개형이라 사람이
      원인을 고친 뒤 다시 띄우면 그 자리부터 이어진다.
    - 성공했고 ``budget_exhausted``면 같은 run_config(업종 선택 포함)로 다음 run을 요청한다.
      ``run_key``가 직전 run id라 같은 run에 대해 두 번 요청하지 않는다.
    """
    owned = {"kor_travel_map.operation_key": MOIS_LOAD_JOB_NAME}
    # 마지막 run만 보면 schedule tick이 막 띄운 run(아직 목록 맨 앞이 아닌 queued)을 놓칠 수
    # 있다. 미종료 run이 하나라도 있으면 띄우지 않는다. 둘이 겹쳐 떠도 GEO_HEAVY pool(limit 1,
    # run 단위)이 실행을 직렬화하고 재개형이라 뒤 run은 건너뛰기만 한다 — 이것은 낭비 방지다.
    active = context.instance.get_runs(
        filters=map_owned_runs_filter(
            job_name=MOIS_LOAD_JOB_NAME, statuses=_ACTIVE_RUN_STATUSES, tags=owned
        ),
        limit=1,
    )
    if active:
        return SkipReason(f"MOIS 적재 run {active[0].run_id}이 아직 끝나지 않았다")
    runs = context.instance.get_runs(
        filters=map_owned_runs_filter(job_name=MOIS_LOAD_JOB_NAME, tags=owned),
        limit=1,
    )
    return mois_load_continuation_decision(runs[0] if runs else None)


def _had_most_of_its_budget(tags: Mapping[str, str]) -> bool:
    """run이 상한의 절반 이상을 받고 시작했는가. tag가 없거나 깨졌으면 아니다(이어 달린다).

    아니면 0행은 "전진할 수 없다"가 아니라 "시간을 못 받았다"이다 — step 재시도가 run 시작
    기준 상한을 넘겨 한 chunk만 하고 멈춘 경우다. 다음 run은 상한 전체를 받는다.
    """
    try:
        budget = int(tags[MOIS_LOAD_BUDGET_TAG])
        available = int(tags[MOIS_LOAD_AVAILABLE_TAG])
    except (KeyError, TypeError, ValueError):
        return False
    return budget > 0 and available * 2 >= budget


def mois_load_continuation_decision(last: Any) -> RunRequest | SkipReason:
    """가장 최근 MOIS 적재 run(``DagsterRun`` 또는 ``None``)으로 이어 달릴지 정한다."""
    if last is None:
        return SkipReason("MOIS 적재 run이 아직 없다")
    if not last.is_finished:
        return SkipReason(f"MOIS 적재 run {last.run_id}이 진행 중이다({last.status.value})")
    if last.status != DagsterRunStatus.SUCCESS:
        return SkipReason(
            f"마지막 MOIS 적재 run {last.run_id}이 {last.status.value}로 끝났다 — "
            "원인을 본 뒤 수동으로 다시 띄운다(이어서 적재된다)"
        )
    if last.tags.get(MOIS_LOAD_OUTCOME_TAG) != MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED:
        return SkipReason(f"마지막 MOIS 적재 run {last.run_id}이 선택 범위를 끝냈다")
    if last.tags.get(MOIS_LOAD_CONVERTED_TAG) == "0" and _had_most_of_its_budget(last.tags):
        # 상한까지 건너뛰기만 하다 멈췄다 — 같은 run_config로 다시 띄워도 같은 자리에서 멈춘다.
        return SkipReason(
            f"마지막 MOIS 적재 run {last.run_id}이 새 행을 하나도 적재하지 못하고 상한에 "
            "닿았다 — 이어 달려도 전진하지 않는다. 시간 상한을 늘리거나 원인을 본다."
        )
    return RunRequest(
        run_key=f"mois-continue:{last.run_id}",
        run_config=dict(last.run_config or {}),
        tags=dict(_CONTINUATION_TAGS),
    )
