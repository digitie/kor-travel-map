"""records resource의 ``source_mode=replay`` (ADR-109 결정 7, T-GR-08).

geo만 바뀐 릴리스에서 쿼터 민감 dataset을 provider HTTP로 다시 받지 않는다. 대신 entity
head의 current ``source_records.raw_data``를 읽어
(:meth:`AsyncKorTravelMapClient.read_current_source_records`) **같은 record 모델**로
되살리고(``from_raw``), asset은 **같은 변환기**로 다시 적재한다 — 변환·지오코딩·스탬프는
fetch와 한 경로다.

replay가 지키는 것:

- **provider 호출 0회.** replay resource는 provider client를 만들지 않는다(자격증명도 읽지 않는다).
- **관측을 꾸미지 않는다.** 되살린 bundle의 ``fetched_at``은 원 레코드 값, ``imported_at``(= head의
  관측 시각 입력)은 head의 ``observed_at`` 그대로다 — head가 전진하지 않고 ``became_current``는
  거짓이다. sync state(성공 cursor)도 쓰지 않는다(:func:`is_replay`).
- **같은 payload만 적재한다.** 변환기가 낸 ``raw_payload_hash``가 저장된 current hash와 다르면
  (``from_raw``가 1:1이 아니면) 아무것도 쓰기 전에 :class:`ReplayPayloadDrift`로 실패한다 — 그대로
  두면 새 source record가 current가 되어 provider가 주지 않은 값을 관측으로 적는다.
- **되살리지 않는다.** primary Feature가 retired인 entity는 읽지 않는다(infra 술어).
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from dagster import Enum, EnumValue
from dagster import Field as DagsterField

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient
    from kortravelmap.dto import FeatureBundle
    from kortravelmap.infra.source_replay_repo import CurrentSourceRecord

__all__ = [
    "SOURCE_MODE_CONFIG_SCHEMA",
    "ReplayPayloadDrift",
    "ReplayRecordStream",
    "apply_replay_provenance",
    "datagokr_model_from_raw",
    "is_replay",
    "prefetch_replay",
    "raw_mapping_from_raw",
    "source_mode",
]

SOURCE_MODE_FETCH: Final = "fetch"
SOURCE_MODE_REPLAY: Final = "replay"

SOURCE_MODE_CONFIG_SCHEMA: Final[dict[str, DagsterField]] = {
    "source_mode": DagsterField(
        Enum(
            "KorTravelMapSourceMode",
            [EnumValue(SOURCE_MODE_FETCH), EnumValue(SOURCE_MODE_REPLAY)],
        ),
        default_value=SOURCE_MODE_FETCH,
        is_required=False,
        description=(
            "fetch = provider에서 받는다(기본). replay = 저장된 current 원본"
            "(source_records.raw_data)을 다시 변환한다 — provider 호출 0회, geo 릴리스 재지오코딩용"
            "(ADR-109 결정 7)."
        ),
    )
}


def source_mode(resource_config: Mapping[str, Any] | None) -> str:
    """resource config의 ``source_mode``(없으면 fetch)."""
    return str((resource_config or {}).get("source_mode") or SOURCE_MODE_FETCH)


class ReplayPayloadDrift(RuntimeError):
    """되살린 record의 변환 결과가 저장된 current 원본과 같은 payload가 아니다."""


def datagokr_model_from_raw(model_name: str) -> Callable[[dict[str, Any]], Any]:
    """``raw_data`` → python-datagokr-api 표준데이터 모델(필드명 그대로, ``populate_by_name``).

    provider 패키지는 fetcher와 같이 호출 시점에 import한다(ADR-044 — hard import 아님).
    """

    def _from_raw(raw_data: dict[str, Any]) -> Any:
        datagokr = importlib.import_module("datagokr")
        return getattr(datagokr, model_name).model_validate(raw_data)

    return _from_raw


def raw_mapping_from_raw(raw_data: dict[str, Any]) -> Any:
    """data.go.kr fileData — 변환기가 원본 row mapping을 그대로 받는다(``raw_data`` = row)."""
    return raw_data


class ReplayRecordStream:
    """replay records resource 값 — current 원본을 record 모델로 되살려 낸다.

    읽기는 **적재 전에 한 번에 끝낸다**(:meth:`prefetch`). Dagster client는 연결 한 개(pool 1)이고
    snapshot 적재는 batch stream을 한 transaction 안에서 소비하므로, 적재 도중 읽으면 그 연결과
    경합한다. asset은 적재 호출 전에 :func:`prefetch_replay`를 부른다(부르지 않았으면 첫 순회가
    읽는다). 되살린 record의 출처(``fetched_at``·``observed_at``·hash)는 :attr:`provenance`에
    남고, asset이 변환 뒤 :func:`apply_replay_provenance`로 bundle에 되돌린다.
    """

    def __init__(
        self,
        client: AsyncKorTravelMapClient,
        *,
        provider: str,
        dataset_key: str,
        from_raw: Callable[[dict[str, Any]], Any],
    ) -> None:
        self._client = client
        self.provider = provider
        self.dataset_key = dataset_key
        self._from_raw = from_raw
        self.provenance: dict[tuple[str, str], CurrentSourceRecord] = {}
        self._records: list[CurrentSourceRecord] | None = None

    async def prefetch(self) -> int:
        """current 원본을 전부 읽어 둔다(한 번만). 읽은 건수를 돌려준다."""
        if self._records is None:
            self._records = await self._client.read_current_source_records(
                provider=self.provider, dataset_key=self.dataset_key
            )
            self.provenance = {
                (record.source_entity_type, record.source_entity_id): record
                for record in self._records
            }
        return len(self._records)

    async def __aiter__(self) -> AsyncIterator[Any]:
        await self.prefetch()
        for record in self._records or ():
            yield self._from_raw(record.raw_data)


async def prefetch_replay(value: object) -> None:
    """replay면 current 원본을 지금 읽는다(적재 transaction 전에). fetch면 아무것도 안 한다."""
    if isinstance(value, ReplayRecordStream):
        await value.prefetch()


def is_replay(value: object) -> bool:
    """records resource 값이 replay인가 — asset이 sync state 기록을 건너뛸지 정한다."""
    return isinstance(value, ReplayRecordStream)


def apply_replay_provenance(
    value: object, bundles: Sequence[FeatureBundle]
) -> list[FeatureBundle]:
    """replay면 bundle의 원본 시각을 저장값으로 되돌리고 payload 동일을 확인한다(fetch면 그대로).

    hash가 다르거나 출처를 모르는 bundle이 하나라도 있으면 아무것도 고치지 않고
    :class:`ReplayPayloadDrift`다 — 적재 전에 실패해야 한다.
    """
    if not isinstance(value, ReplayRecordStream):
        return list(bundles)
    drifted: list[str] = []
    replayed: list[FeatureBundle] = []
    for bundle in bundles:
        source = bundle.source_record
        stored = value.provenance.get((source.source_entity_type, source.source_entity_id))
        if stored is None or stored.raw_payload_hash != source.raw_payload_hash:
            drifted.append(source.source_entity_id)
            continue
        replayed.append(
            bundle.model_copy(
                update={
                    "source_record": source.model_copy(
                        update={
                            "fetched_at": stored.fetched_at,
                            "imported_at": stored.observed_at,
                        }
                    )
                }
            )
        )
    if drifted:
        raise ReplayPayloadDrift(
            f"{value.provider}/{value.dataset_key} replay: {len(drifted)}건의 변환 payload가 "
            f"저장된 current 원본과 다르다(예: {sorted(drifted)[:3]}) — raw_data → record "
            "복원이 1:1이 아니다. 이 dataset은 fetch 모드로 돌려야 한다."
        )
    return replayed
