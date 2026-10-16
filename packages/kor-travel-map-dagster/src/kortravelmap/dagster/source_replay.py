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
  거짓이다. sync state(성공 cursor)도, curation seal(``authoritative_snapshot_complete``)도 쓰지
  않는다(:func:`is_replay`) — 쓰면 seal 영수증의 ``observed_at``이 provider 관측처럼 남는다.
- **같은 payload만 적재한다.** 변환기가 낸 ``raw_payload_hash``가 저장된 current hash와 다르면
  (``from_raw``가 1:1이 아니면) **commit 전에** :class:`ReplayPayloadDrift`로 실패한다 — 그대로
  두면 새 source record가 current가 되어 provider가 주지 않은 값을 관측으로 적는다. 검사는 변환
  뒤다(hash 입력은 변환기 안에서 만들어진다): 목록 적재는 쓰기 전에, 표준데이터 batch 적재는 한
  transaction 안 batch마다라 실패하면 그 transaction 전체가 롤백된다.
- **빠짐없이.** 읽은 건수가 그 dataset의 active entity 수와 다르거나(빈 읽기 포함), 변환 결과가
  읽은 레코드를 다 덮지 않으면 :class:`ReplayIncomplete`로 실패한다(#1333 리뷰 R1) — 부분 replay가
  성공으로 끝나면 계획은 그 dataset을 다 했다고 본다.
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
    "ReplayIncomplete",
    "ReplayPayloadDrift",
    "ReplayRecordStream",
    "apply_replay_provenance",
    "ensure_replay_complete",
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


class ReplayIncomplete(RuntimeError):
    """replay가 dataset 전부를 덮지 않았다 — 읽기가 모자라거나 변환이 레코드를 잃었다."""


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
        self.matched: set[tuple[str, str]] = set()
        self._records: list[CurrentSourceRecord] | None = None

    async def prefetch(self) -> int:
        """current 원본을 전부 읽어 둔다(한 번만). 읽은 건수를 돌려준다.

        읽은 건수가 그 dataset의 active entity 수와 다르면(0건 포함) :class:`ReplayIncomplete`다.
        """
        if self._records is None:
            records, expected = await self._client.read_current_source_records(
                provider=self.provider, dataset_key=self.dataset_key
            )
            if len(records) != expected:
                raise ReplayIncomplete(
                    f"{self.provider}/{self.dataset_key} replay: current 원본 {len(records)}건을 "
                    f"읽었는데 active entity는 {expected}건이다 — head·record 누락이거나, 건수를 "
                    "센 transaction과 페이지 읽기 사이에 같은 dataset이 바뀐 경쟁일 수 있다"
                    "(그 경우 재시도로 해소된다). 부분 replay로 계획을 끝내지 않는다."
                )
            self._records = records
            self.provenance = {
                (record.source_entity_type, record.source_entity_id): record
                for record in records
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
    repeated: list[str] = []
    replayed: list[FeatureBundle] = []
    for bundle in bundles:
        source = bundle.source_record
        key = (source.source_entity_type, source.source_entity_id)
        stored = value.provenance.get(key)
        if stored is None or stored.raw_payload_hash != source.raw_payload_hash:
            drifted.append(source.source_entity_id)
            continue
        if key in value.matched:
            repeated.append(source.source_entity_id)
            continue
        value.matched.add(key)
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
    if repeated:
        raise ReplayIncomplete(
            f"{value.provider}/{value.dataset_key} replay: 같은 entity의 bundle이 두 번 나왔다"
            f"(예: {sorted(repeated)[:3]})."
        )
    return replayed


def ensure_replay_complete(value: object) -> None:
    """replay면 변환된 bundle이 읽은 레코드를 전부(정확히 한 번씩) 덮었는지 본다. fetch면 통과.

    asset이 모든 batch를 넘긴 뒤 — 적재 transaction이 끝나기 전 — 부른다.
    """
    if not isinstance(value, ReplayRecordStream):
        return
    missing = set(value.provenance) - value.matched
    if missing:
        sample = sorted(entity_id for _, entity_id in missing)[:3]
        raise ReplayIncomplete(
            f"{value.provider}/{value.dataset_key} replay: current 원본 "
            f"{len(value.provenance)}건 중 {len(missing)}건이 변환 결과에 없다"
            f"(예: {sample}) — 부분 replay로 끝내지 않는다."
        )
