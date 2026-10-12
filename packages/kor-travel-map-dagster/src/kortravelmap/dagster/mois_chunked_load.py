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

import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final, cast

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.dto import FeatureBundle
from kortravelmap.geocoding import PrefetchingReverseGeocoder, ReverseGeocoder
from kortravelmap.infra.feature_repo import FeatureLoadResult
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
    DagsterRunStatus,
    DefaultSensorStatus,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    sensor,
)

from .etl import (
    FEATURE_ID_METADATA_LIMIT,
    DagsterFeatureLoadResult,
    _add_output_metadata,
    load_feature_bundles_for_dagster,
)
from .run_scope import map_owned_runs_filter

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

_LICENSE_ENTITY_TYPE: Final[str] = "license_place"
"""``providers.mois``가 ``SourceRecord.source_entity_type``으로 쓰는 값."""


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


def resolve_mois_load_plan(
    settings: KorTravelMapSettings, service_slugs: Iterable[str] = ()
) -> MoisLoadPlan:
    """run_config의 업종 선택을 검증해 plan으로 만든다. 빈 선택은 전 업종이다.

    PROMOTED 밖의 이름은 조용히 버리지 않고 거부한다 — 오타 하나가 "0건 적재 성공"이 되면
    검증 run이 아무것도 검증하지 않은 채 초록이 된다.
    """
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
        run_budget_seconds=settings.mois_load_run_budget_seconds,
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

    @property
    def outcome(self) -> str:
        return MOIS_LOAD_OUTCOME_COMPLETE if self.complete else MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED

    @property
    def authoritative(self) -> bool:
        """전 업종을 이 run 안에서 끝까지 확인했는가 — curation seal의 조건.

        본 record가 0건이면 봉인하지 않는다. 빈 원천(sync 실패로 비어 버린 SQLite 등)을
        "snapshot 전체를 확인했다"로 승격하면 그 빈 관측이 curation의 기준이 된다.
        """
        return self.complete and self.full_coverage and self.records_seen > 0

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
    clock: Callable[[], float] = time.monotonic,
    convert: Callable[..., Awaitable[list[FeatureBundle]]] = license_records_to_bundles,
) -> MoisChunkedLoadOutcome:
    """선택 업종의 영업중 record를 chunk 단위로 commit하며 적재한다(재개형).

    ``records``는 ``(service_slug, mng_no)`` 순 stream이다(provider가 그 순서를 보장).
    ``clock``·``convert``는 테스트가 시간과 변환을 대신하기 위한 자리다.
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
    sink = _ChunkMetadataSink(context)
    started = clock()
    deadline = started + plan.run_budget_seconds

    merged: DagsterFeatureLoadResult | None = None
    slugs_completed: list[str] = []
    current_slug: str | None = None
    stopped_in_slug: str | None = None
    records_seen = records_unchanged = records_converted = chunks = 0
    complete = True

    for chunk in iter_slug_chunks(records, MOIS_LOAD_CHUNK_SIZE):
        slug = str(chunk[0].service_slug)
        if slug != current_slug:
            if current_slug is not None:
                slugs_completed.append(current_slug)
                context.log.info(f"MOIS 업종 {current_slug} 완료 ({len(slugs_completed)}개째)")
            current_slug = slug
        # 상한 판정은 chunk **사이**에서만 한다 — 시작한 chunk는 끝까지 commit한다. 첫
        # chunk는 언제나 시작하므로 run마다 최소 한 chunk는 전진한다(무한 이어 달리기 방지).
        if chunks > 0 and clock() >= deadline:
            complete = False
            stopped_in_slug = slug
            break

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
        if prefetcher is not None and to_convert:
            await prefetcher.prefetch(
                coord
                for record in to_convert
                if (coord := license_reverse_geocode_coordinate(record)) is not None
            )
        bundles = await convert(
            to_convert,
            fetched_at=fetched_at,
            dataset_key=dataset_key,
            reverse_geocoder=prefetcher if prefetcher is not None else reverse_geocoder,
        )
        reobserved = {key: payload_hashes[key] for key in unchanged}

        async def _load_chunk(
            batch: list[FeatureBundle], reobserved: dict[str, str] = reobserved
        ) -> FeatureLoadResult:
            return await client.load_feature_bundles_reobserving(
                batch,
                provider=PROVIDER_NAME,
                dataset_key=dataset_key,
                source_entity_type=_LICENSE_ENTITY_TYPE,
                reobserved_payload_hashes=reobserved,
                observed_at=observed_at,
            )

        chunk_result = await load_feature_bundles_for_dagster(
            context=cast(AssetExecutionContext, sink),
            client=client,
            bundles=bundles,
            provider=PROVIDER_NAME,
            dataset_key=dataset_key,
            strict_address=strict_address,
            authoritative_snapshot_complete=False,
            load_all=_load_chunk,
            loss_guard_observations=len(chunk),
        )
        merged = _cap_feature_ids(chunk_result if merged is None else merged.merge(chunk_result))
        chunks += 1
        records_seen += len(chunk)
        records_unchanged += len(unchanged)
        records_converted += len(to_convert)

    if complete and current_slug is not None:
        slugs_completed.append(current_slug)
        context.log.info(f"MOIS 업종 {current_slug} 완료 ({len(slugs_completed)}개째)")

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
    _tag_run_outcome(context, outcome.outcome)
    return outcome


async def _empty_load() -> FeatureLoadResult:
    return FeatureLoadResult()


def _tag_run_outcome(context: Any, outcome: str) -> None:
    """이어 달리기 sensor가 읽을 결과 tag. 실제 Dagster run 밖(직접 호출)에서는 생략한다."""
    instance = getattr(context, "instance", None)
    try:
        run_id = context.run_id
    except Exception:  # noqa: BLE001 — 직접 호출 context에는 run이 없다
        return
    add_run_tags = getattr(instance, "add_run_tags", None)
    if run_id and callable(add_run_tags):
        add_run_tags(run_id, {MOIS_LOAD_OUTCOME_TAG: outcome})


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
    runs = context.instance.get_runs(
        filters=map_owned_runs_filter(
            job_name=MOIS_LOAD_JOB_NAME,
            tags={"kor_travel_map.operation_key": MOIS_LOAD_JOB_NAME},
        ),
        limit=1,
    )
    if not runs:
        return SkipReason("MOIS 적재 run이 아직 없다")
    last = runs[0]
    if not last.is_finished:
        return SkipReason(f"MOIS 적재 run {last.run_id}이 진행 중이다({last.status.value})")
    if last.status != DagsterRunStatus.SUCCESS:
        return SkipReason(
            f"마지막 MOIS 적재 run {last.run_id}이 {last.status.value}로 끝났다 — "
            "원인을 본 뒤 수동으로 다시 띄운다(이어서 적재된다)"
        )
    if last.tags.get(MOIS_LOAD_OUTCOME_TAG) != MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED:
        return SkipReason(f"마지막 MOIS 적재 run {last.run_id}이 선택 범위를 끝냈다")
    return RunRequest(
        run_key=f"mois-continue:{last.run_id}",
        run_config=dict(last.run_config or {}),
        tags=dict(_CONTINUATION_TAGS),
    )
