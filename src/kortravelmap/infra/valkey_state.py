"""``kortravelmap.infra.valkey_state`` — Valkey 세대 교체 상태 저장소 (ADR-114).

transport(이후 weather)의 **현재 상태**를 Valkey(Redis 호환)에 데이터셋별 **세대** 단위로 담는다.
쓰는 쪽은 Map Dagster run 프로세스, 읽는 쪽은 Map API 프로세스다 — 같은 저장소를 보는 두 프로세스.
키 설계·교체 순서·거부 기준의 정본은 ADR-114 "구현 설계 — 1단계" D2~D5이고, 이 모듈은 그 구현이다.

- 세대 키는 쓰고 나면 바꾸지 않는다. 바꾸는 것은 ``{ds}:current`` 포인터이고, 그것은 Lua 스크립트
  하나(:data:`_FLIP_SCRIPT`)가 compare-and-set과 개수 검사를 한 뒤에만 바꾼다. 읽는 쪽은 포인터를
  한 번 읽고 그 세대의 키만 읽으므로 옛 세대와 새 세대가 섞여 보이는 순간이 없다.
- **세대가 있다는 표지는 ``meta`` 하나다.** 0건·좌표 없는 세대에는 ``items``·``geo`` 키가 없다.
- 쓰는 동안의 새 키는 build TTL을 단다 — 적재가 죽으면 아무도 가리키지 않는 키가 저절로 사라진다
  (Valkey는 ``noeviction``이라 스스로 치워야 한다). 교체 때 새 키의 TTL을 지우고 옛 세대 키에
  grace TTL을 건다. grace 동안 진행 중인 페이지 순회는 옛 세대로 끝난다.
- 원천이 비정상적으로 작은 집합을 주면 교체하지 않는다(:func:`evaluate_shrink_guard`) — 2026-10-23
  KREX 빈 응답이 돌발 106건을 한 번에 닫은 사고가 출처다.
- 값은 이미 직렬화된 문자열(JSON)이다. 이 모듈은 값의 모양을 모른다(``dto.transport_state``가
  안다).

Valkey 오류는 :class:`StateStoreUnavailable`(연결·timeout — 재시도 가능)과
:class:`StateStoreOutOfMemory`(``noeviction`` 쓰기 거부 — 재시도로 안 풀림)로 올린다. 읽는 쪽은 둘
다 503이다. 메시지에 URL·비밀번호를 싣지 않는다.
"""

from __future__ import annotations

import inspect
import logging
import math
import secrets
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, TypeVar, cast

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import OutOfMemoryError, RedisError, ResponseError

from kortravelmap.settings import KorTravelMapSettings

__all__ = [
    "DEFAULT_BUILD_TTL_SECONDS",
    "DEFAULT_RETIRE_GRACE_SECONDS",
    "GEO_LAT_LIMIT",
    "RECENT_COUNTS_WINDOW",
    "STATE_KEY_NAMESPACE",
    "STATE_KEY_PREFIX",
    "GenerationMeta",
    "ShrinkGuard",
    "StateGenerationExpired",
    "StateItem",
    "StateNotLoaded",
    "StateStoreError",
    "StateStoreNotConfigured",
    "StateStoreOutOfMemory",
    "StateStoreUnavailable",
    "StateSwapConflict",
    "StateSwapRefused",
    "SwapResult",
    "ValkeyStateStore",
    "evaluate_shrink_guard",
    "make_valkey_client",
    "state_key",
]

_LOGGER = logging.getLogger(__name__)

STATE_KEY_NAMESPACE: Final[str] = "ktm:state"
"""모든 버전의 상태 키가 공유하는 이름공간. 다른 버전
정리(:meth:`ValkeyStateStore.retire_other_versions`)의 범위."""

STATE_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}:v1"
"""지금 버전의 키 접두사. ``v1``은 값 스키마 버전이다 — 값 모양이 바뀌면 올린다(ADR-114 D2)."""

DEFAULT_BUILD_TTL_SECONDS: Final[int] = 7_200
"""쓰는 중인 세대 키와 적재 잠금의 TTL. 적재 하나가 이보다 오래 걸리면 교체가 거부된다."""

DEFAULT_RETIRE_GRACE_SECONDS: Final[int] = 900
"""교체로 물러난 세대 키가 더 살아 있는 시간 — 진행 중인 읽기·페이지 순회가 끝날 시간."""

RECENT_COUNTS_WINDOW: Final[int] = 6
"""거부 기준으로 쓰는 최근 교체 개수(ADR-114 D4)."""

_WRITE_BATCH: Final[int] = 500
"""pipeline 하나에 싣는 엔티티 수."""

GEO_LAT_LIMIT: Final[float] = 85.05112878
"""Valkey GEO가 받는 위도 절댓값 상한. 넘는 좌표는 GEO에 넣지 않는다(값에는 남는다)."""

_GEN_KEY_NAMES: Final[tuple[str, ...]] = ("meta", "items", "ids", "geo", "lookup")


_T = TypeVar("_T")


async def _resolve(value: Awaitable[_T] | _T) -> _T:
    """redis-py 일부 명령은 sync·async 겸용 타입(``Awaitable[T] | T``)으로 선언돼 있다.

    async client에서는 언제나 awaitable이지만 타입이 그것을 말하지 않아 ``await``를 거부한다.
    """
    if inspect.isawaitable(value):
        return cast("_T", await value)
    return value


# -- 오류 ----------------------------------------------------------------------


class StateStoreError(RuntimeError):
    """상태 저장소 실패의 공통 부모. ``failure_kind``·``retryable``은 provider 예외와 같은
    규약이다."""

    failure_kind: str = "state_store_error"
    retryable: bool = False


class StateStoreUnavailable(StateStoreError):
    """Valkey에 닿지 못했거나(연결·timeout·인증) 저장소 상태가 규약과 다르다."""

    failure_kind = "state_store_unavailable"
    retryable = True


class StateStoreNotConfigured(StateStoreUnavailable):
    """``KOR_TRAVEL_MAP_VALKEY_URL``이 없다. 설정을 넣어야 풀린다."""

    failure_kind = "state_store_not_configured"
    retryable = False


class StateStoreOutOfMemory(StateStoreUnavailable):
    """Valkey가 ``maxmemory``에 닿아 쓰기를 거부했다(``noeviction``). 기다려서는 풀리지 않는다."""

    failure_kind = "state_store_oom"
    retryable = False


class StateSwapRefused(StateStoreError):
    """새 집합이 비었거나 최근 세대보다 비정상적으로 작아 교체하지 않았다(ADR-114 D4)."""

    failure_kind = "state_swap_refused"

    def __init__(self, message: str, *, baseline: int | None, new_count: int) -> None:
        super().__init__(message)
        self.baseline = baseline
        self.new_count = new_count


class StateSwapConflict(StateStoreError):
    """교체 직전 검사가 어긋났다 — 포인터가 바뀌었거나(동시 교체) 새 세대 키가 빠졌다.

    포인터는 그대로이고 쓰던 키는 지운다(실패하면 build TTL로 사라진다). 다음 적재가 다시 한다.
    """

    failure_kind = "state_swap_conflict"


class StateNotLoaded(LookupError):
    """이 데이터셋은 아직 한 번도 교체되지 않았다(포인터가 없다)."""


class StateGenerationExpired(LookupError):
    """요청한 세대가 없다(교체 뒤 grace가 지났거나 받지 않는 세대다). 처음부터 다시 읽어야 한다."""


# -- 순수 판정 -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShrinkGuard:
    """비정상 집합 거부 기준(ADR-114 D4)."""

    min_ratio: float
    """기준(최근 최대) 대비 새 집합이 넘어야 하는 비율."""
    baseline_min: int
    """기준이 이 값 이상일 때만 비율을 본다 — 작은 집합의 자연 변동을 막지 않는다."""
    min_count: int = 0
    """절대 하한. 첫 적재·볼륨 유실 뒤에도 적용된다. 0이면 없음."""
    allow_empty_below_baseline: bool = False
    """기준이 ``baseline_min`` 미만이면 0건도 받는다(돌발처럼 0건이 정상일 수 있는 집합)."""

    def __post_init__(self) -> None:
        if not 0.0 < self.min_ratio <= 1.0:
            raise ValueError("min_ratio는 (0, 1] 범위여야 한다.")
        if self.baseline_min < 1 or self.min_count < 0:
            raise ValueError("baseline_min은 1 이상, min_count는 0 이상이어야 한다.")


def evaluate_shrink_guard(
    recent_counts: Sequence[int],
    new_count: int,
    guard: ShrinkGuard,
    *,
    allow_shrink: bool = False,
) -> str | None:
    """교체를 거부할 이유를 돌려준다. 받아들이면 ``None``.

    ``recent_counts``는 최근 교체된 세대들의 개수다(비면 첫 적재). 기준은 그 **최대값**이다 — 직전
    하나와만 비교하면 106 → 27 → 7 → 0처럼 나눠 줄어드는 것을 막지 못한다. ``allow_shrink``(운영자
    run config)는 모든 거부를 넘긴다.
    """
    if new_count < 0:
        raise ValueError("new_count는 음수일 수 없다.")
    if allow_shrink:
        return None
    if new_count < guard.min_count:
        return f"새 집합 {new_count}건이 절대 하한 {guard.min_count}건 미만이다."
    baseline = max(recent_counts, default=0)
    if new_count == 0:
        if guard.allow_empty_below_baseline and baseline < guard.baseline_min:
            return None
        return f"새 집합이 0건이다(최근 최대 {baseline}건)."
    if baseline >= guard.baseline_min:
        floor = math.ceil(baseline * guard.min_ratio)
        if new_count < floor:
            return (
                f"새 집합 {new_count}건이 최근 최대 {baseline}건의 {guard.min_ratio:.0%}"
                f"({floor}건) 미만이다."
            )
    return None


# -- 모양 ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StateItem:
    """세대에 넣을 엔티티 하나."""

    id: str
    value: str
    coord: tuple[float, float] | None = None
    """``(lon, lat)``. 있고 GEO 범위 안이면 GEO 인덱스에 넣는다."""
    lookup_keys: tuple[str, ...] = ()
    """보조 키(예: 휴게소 유가 매칭 키) → ``id``. 같은 보조 키는 먼저 온 엔티티가 갖는다."""


@dataclass(frozen=True, slots=True)
class GenerationMeta:
    """세대 하나의 신선도·크기(ADR-114 D5)."""

    dataset: str
    generation: str
    count: int
    geo_count: int
    lookup_count: int
    duplicates: int
    source_collected_at: datetime | None
    loaded_at: datetime
    run_id: str | None
    guard_override: bool
    source_status: str | None = None
    """원천이 알린 집합 상태(weather ``ok``·``stale``, ADR-114 2단계 W4). 1단계 세대와 원천이
    알리지 않는 데이터셋은 ``None``."""


@dataclass(frozen=True, slots=True)
class SwapResult:
    meta: GenerationMeta
    previous_generation: str | None
    baseline: int | None
    """거부 검사에 쓴 기준(최근 최대). 첫 적재면 ``None``."""


def state_key(dataset: str, *parts: str) -> str:
    """``ktm:state:v1:{dataset}:{parts...}``. 비었거나 ``:``가 든 성분은 받지 않는다."""
    if not dataset or ":" in dataset or any(not part or ":" in part for part in parts):
        raise ValueError(f"상태 키 성분이 비었거나 ':'를 포함한다: {dataset!r} {parts!r}")
    return ":".join((STATE_KEY_PREFIX, dataset, *parts))


def _key_version(key: str) -> int | None:
    """``ktm:state:v{N}:…``의 N. 형식이 다르면 ``None``(건드리지 않는다)."""
    head = f"{STATE_KEY_NAMESPACE}:v"
    if not key.startswith(head):
        return None
    digits = key[len(head) :].split(":", 1)[0]
    return int(digits) if digits.isdigit() else None


def _gen_keys(dataset: str, generation: str) -> dict[str, str]:
    return {name: state_key(dataset, generation, name) for name in _GEN_KEY_NAMES}


def _geo_ok(coord: tuple[float, float]) -> bool:
    lon, lat = coord
    return (
        math.isfinite(lon)
        and math.isfinite(lat)
        and -180.0 <= lon <= 180.0
        and -GEO_LAT_LIMIT <= lat <= GEO_LAT_LIMIT
    )


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("상태 메타 시각에는 timezone이 있어야 한다.")
    return value.astimezone(UTC).isoformat()


def _text(value: Any) -> str:
    # 깨진 바이트도 예외 없이 문자열로 — 없는 세대 이름이 되어 정상 경로(409·503)로 떨어진다.
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _parse_meta(dataset: str, generation: str, raw: dict[Any, Any]) -> GenerationMeta:
    fields = {_text(key): _text(value) for key, value in raw.items()}
    try:
        source = fields.get("source_collected_at") or ""
        run_id = fields.get("run_id") or ""
        loaded_at = datetime.fromisoformat(fields["loaded_at"])
        source_at = datetime.fromisoformat(source) if source else None
        if any(
            value is not None and value.utcoffset() is None for value in (loaded_at, source_at)
        ):
            raise ValueError("timezone이 없는 시각")
        return GenerationMeta(
            dataset=dataset,
            generation=generation,
            count=int(fields["count"]),
            geo_count=int(fields["geo_count"]),
            lookup_count=int(fields["lookup_count"]),
            duplicates=int(fields.get("duplicates", "0")),
            source_collected_at=source_at,
            loaded_at=loaded_at,
            run_id=run_id or None,
            guard_override=fields.get("guard_override") == "1",
            source_status=fields.get("source_status") or None,
        )
    except (KeyError, ValueError) as exc:
        raise StateStoreUnavailable(
            f"상태 메타가 깨졌다: {dataset}/{generation} ({type(exc).__name__})"
        ) from exc


# KEYS[1]=current KEYS[2]=previous KEYS[3]=recent_counts
# KEYS[4..8]=새 세대 meta·items·ids·geo·lookup, KEYS[9..]=물러날 직전 세대 키.
# ARGV[1]=기대하는 지금 세대(''=없음) ARGV[2]=새 세대 ARGV[3]=grace 초 ARGV[4]=recent 창 크기
# ARGV[5]='1'이면 recent_counts를 비우고 새 개수 하나로 시작한다
#   (운영자 allow_shrink — 한 번이면 충분해야 한다).
# 반환: {1, 직전} 교체됨 · {0, 지금 포인터} 포인터가 바뀌었다 ·
#   {-1, 어긋난 키 이름} 새 세대 검사 실패.
_FLIP_SCRIPT: Final[str] = """
local current = redis.call('GET', KEYS[1])
if not current then current = '' end
if current ~= ARGV[1] then return {0, current} end
if redis.call('EXISTS', KEYS[4]) == 0 then return {-1, 'meta'} end
local count = tonumber(redis.call('HGET', KEYS[4], 'count'))
local geo = tonumber(redis.call('HGET', KEYS[4], 'geo_count'))
local lookup = tonumber(redis.call('HGET', KEYS[4], 'lookup_count'))
if count == nil or geo == nil or lookup == nil then return {-1, 'meta'} end
if redis.call('HLEN', KEYS[5]) ~= count then return {-1, 'items'} end
if redis.call('ZCARD', KEYS[6]) ~= count then return {-1, 'ids'} end
if redis.call('ZCARD', KEYS[7]) ~= geo then return {-1, 'geo'} end
if redis.call('HLEN', KEYS[8]) ~= lookup then return {-1, 'lookup'} end
for i = 4, 8 do redis.call('PERSIST', KEYS[i]) end
redis.call('SET', KEYS[1], ARGV[2])
if current ~= '' then redis.call('SET', KEYS[2], current) else redis.call('DEL', KEYS[2]) end
if ARGV[5] == '1' then redis.call('DEL', KEYS[3]) end
redis.call('LPUSH', KEYS[3], count)
redis.call('LTRIM', KEYS[3], 0, tonumber(ARGV[4]) - 1)
for i = 9, #KEYS do redis.call('EXPIRE', KEYS[i], tonumber(ARGV[3])) end
return {1, current}
"""

_RELEASE_LOCK_SCRIPT: Final[str] = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


# -- client --------------------------------------------------------------------


def make_valkey_client(settings: KorTravelMapSettings) -> Redis:
    """settings로 async client를 만든다. 연결은 첫 명령 때 맺는다(지연).

    URL이 비어 있으면 :class:`StateStoreNotConfigured`. 재시도는 끈다 — redis-py 기본 재시도는
    연결 상한을 몇 배로 늘려 "Valkey가 꺼지면 곧바로 503"을 깬다(ADR-114 D6). 응답은 bytes로
    받는다.
    """
    secret = settings.valkey_url
    url = secret.get_secret_value().strip() if secret is not None else ""
    if not url:
        raise StateStoreNotConfigured(
            "상태 저장소에는 KOR_TRAVEL_MAP_VALKEY_URL이 필요하다(ADR-114)."
        )
    try:
        return Redis.from_url(
            url,
            socket_connect_timeout=settings.valkey_connect_timeout_seconds,
            socket_timeout=settings.valkey_socket_timeout_seconds,
            decode_responses=False,
            retry=Retry(NoBackoff(), 0),
        )
    except ValueError:
        # 파서 메시지에 URL 조각(비밀번호 일부)이 실릴 수 있다 — 원 예외를 잇지 않는다.
        raise StateStoreNotConfigured(
            "KOR_TRAVEL_MAP_VALKEY_URL 형식이 올바르지 않다(redis://:password@host:port/db)."
        ) from None


@asynccontextmanager
async def _unavailable_on_error(what: str) -> AsyncIterator[None]:
    """Valkey 오류를 상태 저장소 오류로 바꾼다. URL·비밀번호는 메시지에 싣지 않는다."""
    try:
        yield
    except ResponseError as exc:
        # redis-py는 "OOM …" 응답을 OutOfMemoryError로 올리며 접두사를 떼어 낸다.
        if isinstance(exc, OutOfMemoryError) or str(exc).startswith("OOM"):
            raise StateStoreOutOfMemory(
                f"Valkey {what} 실패: maxmemory 도달(noeviction 쓰기 거부)"
            ) from exc
        # 그 밖의 응답 오류(WRONGTYPE·NOSCRIPT·인자 오류)는 기다려도 풀리지 않는다.
        raise StateStoreError(f"Valkey {what} 실패: {type(exc).__name__}") from exc
    except (RedisError, OSError) as exc:
        raise StateStoreUnavailable(f"Valkey {what} 실패: {type(exc).__name__}") from exc


class ValkeyStateStore:
    """세대 단위 상태 저장소. 한 인스턴스를 여러 요청이 같이 써도 된다(client가 pool을 갖는다)."""

    def __init__(
        self,
        client: Redis,
        *,
        build_ttl_seconds: int = DEFAULT_BUILD_TTL_SECONDS,
        retire_grace_seconds: int = DEFAULT_RETIRE_GRACE_SECONDS,
        write_batch: int = _WRITE_BATCH,
    ) -> None:
        if build_ttl_seconds < 1 or retire_grace_seconds < 1 or write_batch < 1:
            raise ValueError("TTL·batch는 1 이상이어야 한다.")
        self._client = client
        self._build_ttl = build_ttl_seconds
        self._grace = retire_grace_seconds
        self._batch = write_batch

    @property
    def client(self) -> Redis:
        return self._client

    async def ping(self) -> None:
        """연결·인증 확인. 실패하면 :class:`StateStoreUnavailable`."""
        async with _unavailable_on_error("ping"):
            await _resolve(self._client.ping())

    # -- 읽기 ------------------------------------------------------------------

    async def _pointer(self, dataset: str, name: str) -> str | None:
        async with _unavailable_on_error("포인터 읽기"):
            raw = await self._client.get(state_key(dataset, name))
        return _text(raw) if raw else None

    async def current_generation(self, dataset: str) -> str | None:
        return await self._pointer(dataset, "current")

    async def generation_meta(self, dataset: str, generation: str) -> GenerationMeta:
        """세대 메타. 세대가 없으면 :class:`StateGenerationExpired`."""
        async with _unavailable_on_error("메타 읽기"):
            raw = cast(
                "dict[Any, Any]",
                await _resolve(self._client.hgetall(state_key(dataset, generation, "meta"))),
            )
        if not raw:
            raise StateGenerationExpired(f"{dataset} 세대 {generation}가 없다.")
        return _parse_meta(dataset, generation, raw)

    async def current_meta(self, dataset: str) -> GenerationMeta:
        """지금 세대의 메타. 포인터가 없으면 :class:`StateNotLoaded`."""
        generation = await self.current_generation(dataset)
        if generation is None:
            raise StateNotLoaded(f"{dataset}는 아직 적재되지 않았다.")
        try:
            return await self.generation_meta(dataset, generation)
        except StateGenerationExpired as exc:
            # 포인터가 가리키는 세대가 없다 — 교체 규약상 생기지 않는 상태(수동 삭제 등)다.
            raise StateStoreUnavailable(
                f"{dataset} 포인터가 없는 세대 {generation}를 가리킨다."
            ) from exc

    async def readable_meta(self, dataset: str, generation: str) -> GenerationMeta:
        """cursor가 가리키는 세대의 메타. ``current``나 ``previous``가 아닌 세대는 받지
        않는다(D6)."""
        try:
            state_key(dataset, generation)
        except ValueError as exc:
            raise StateGenerationExpired(f"{dataset} 세대 이름이 올바르지 않다.") from exc
        async with _unavailable_on_error("포인터 읽기"):
            # 두 포인터를 한 번에 읽는다 — 사이에 교체가 끼면 멀쩡한 cursor를 거부한다.
            raw = cast(
                "list[bytes | None]",
                await _resolve(
                    self._client.mget(
                        [state_key(dataset, "current"), state_key(dataset, "previous")]
                    )
                ),
            )
        allowed = {_text(value) for value in raw if value}
        if generation not in allowed:
            raise StateGenerationExpired(f"{dataset} 세대 {generation}는 읽을 수 없다.")
        return await self.generation_meta(dataset, generation)

    async def get_values(
        self, dataset: str, generation: str, ids: Sequence[str]
    ) -> list[bytes | None]:
        if not ids:
            return []
        async with _unavailable_on_error("값 읽기"):
            return cast(
                "list[bytes | None]",
                await _resolve(
                    self._client.hmget(state_key(dataset, generation, "items"), list(ids))
                ),
            )

    async def page_ids(
        self, dataset: str, generation: str, *, after: str | None, limit: int
    ) -> tuple[list[str], bool]:
        """``id`` 사전순 keyset 페이지. ``after``는 직전 페이지 마지막 id(그 다음부터)."""
        if limit < 1:
            raise ValueError("limit은 1 이상이어야 한다.")
        start = f"({after}" if after else "-"
        async with _unavailable_on_error("목록 읽기"):
            raw = cast(
                "list[bytes]",
                await self._client.zrangebylex(
                    state_key(dataset, generation, "ids"), start, "+", start=0, num=limit + 1
                ),
            )
        ids = [_text(value) for value in raw]
        return ids[:limit], len(ids) > limit

    async def nearby(
        self,
        dataset: str,
        generation: str,
        *,
        lon: float,
        lat: float,
        radius_m: float,
        count: int,
    ) -> list[tuple[str, float]]:
        """``(id, 거리 m)``를 가까운 순으로 최대 ``count``건."""
        async with _unavailable_on_error("근처 검색"):
            raw = cast(
                "list[list[Any]]",
                await self._client.geosearch(
                    state_key(dataset, generation, "geo"),
                    longitude=lon,
                    latitude=lat,
                    radius=radius_m,
                    unit="m",
                    sort="ASC",
                    count=count,
                    withdist=True,
                ),
            )
        return [(_text(member), float(distance)) for member, distance in raw]

    async def within_box(
        self,
        dataset: str,
        generation: str,
        *,
        center_lon: float,
        center_lat: float,
        width_m: float,
        height_m: float,
        count: int,
    ) -> list[str]:
        """중심 기준 상자 안 ``id``를 중심에서 가까운 순으로 최대 ``count``건."""
        async with _unavailable_on_error("영역 검색"):
            raw = cast(
                "list[bytes]",
                await self._client.geosearch(
                    state_key(dataset, generation, "geo"),
                    longitude=center_lon,
                    latitude=center_lat,
                    width=width_m,
                    height=height_m,
                    unit="m",
                    sort="ASC",
                    count=count,
                ),
            )
        return [_text(member) for member in raw]

    async def lookup(
        self, dataset: str, generation: str, keys: Sequence[str]
    ) -> list[str | None]:
        """보조 키 → ``id``. 없는 키는 ``None``."""
        if not keys:
            return []
        async with _unavailable_on_error("보조 키 읽기"):
            raw = cast(
                "list[bytes | None]",
                await _resolve(
                    self._client.hmget(state_key(dataset, generation, "lookup"), list(keys))
                ),
            )
        return [_text(value) if value is not None else None for value in raw]

    async def recent_counts(self, dataset: str) -> list[int]:
        async with _unavailable_on_error("최근 개수 읽기"):
            raw = cast(
                "list[bytes]",
                await _resolve(self._client.lrange(state_key(dataset, "recent_counts"), 0, -1)),
            )
        try:
            return [int(_text(value)) for value in raw]
        except ValueError as exc:
            raise StateStoreUnavailable(f"{dataset} recent_counts가 깨졌다.") from exc

    # -- 쓰기 ------------------------------------------------------------------

    @asynccontextmanager
    async def load_lock(
        self, dataset: str, *, ttl_seconds: int | None = None
    ) -> AsyncIterator[bool]:
        """데이터셋 적재 잠금(D3-1). 이미 잡혀 있으면 ``False``를 내고 아무것도 하지 않는다.

        ``ttl_seconds``는 적재 run의 상한에 맞춘다 — 죽은 run의 잠금이 그 뒤 run들을 오래 막지 않게.
        """
        key = state_key(dataset, "lock")
        token = secrets.token_hex(16)
        ttl = ttl_seconds if ttl_seconds is not None else self._build_ttl
        async with _unavailable_on_error("잠금"):
            acquired = bool(await self._client.set(key, token, nx=True, ex=ttl))
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    async with _unavailable_on_error("잠금 해제"):
                        await _resolve(self._client.eval(_RELEASE_LOCK_SCRIPT, 1, key, token))
                except StateStoreError:
                    _LOGGER.warning("%s 적재 잠금을 풀지 못했다 — TTL로 풀린다.", dataset)

    async def swap(
        self,
        dataset: str,
        items: Sequence[StateItem],
        *,
        guard: ShrinkGuard,
        source_collected_at: datetime | None,
        loaded_at: datetime,
        run_id: str | None = None,
        allow_shrink: bool = False,
        source_status: str | None = None,
    ) -> SwapResult:
        """새 세대를 쓰고 포인터를 원자적으로 바꾼다(ADR-114 D3).

        거부(:class:`StateSwapRefused`)·충돌(:class:`StateSwapConflict`)·Valkey 실패 어느 경우에도
        포인터는 그대로다. 같은 id는 원천 순서의 첫 엔티티만 남기고 나머지 수를
        ``meta.duplicates``에 적는다.
        """
        unique: dict[str, StateItem] = {}
        for item in items:
            if not item.id:
                raise ValueError("상태 id가 비었다.")
            unique.setdefault(item.id, item)
        duplicates = len(items) - len(unique)

        previous_generation = await self.current_generation(dataset)
        if previous_generation is not None:
            # 포인터가 있는데 메타가 없으면 저장소가 깨진 것이다 — 첫 적재로 취급하지 않는다.
            await self.current_meta(dataset)
        recent = await self.recent_counts(dataset)
        baseline = max(recent) if recent else None
        reason = evaluate_shrink_guard(recent, len(unique), guard, allow_shrink=allow_shrink)
        if reason is not None:
            raise StateSwapRefused(
                f"{dataset} 교체 거부: {reason}", baseline=baseline, new_count=len(unique)
            )

        generation = f"{loaded_at.astimezone(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
        keys = _gen_keys(dataset, generation)
        try:
            geo_count, lookup_count = await self._write_generation(
                keys, list(unique.values())
            )
            meta_fields = {
                "count": str(len(unique)),
                "geo_count": str(geo_count),
                "lookup_count": str(lookup_count),
                "duplicates": str(duplicates),
                "source_collected_at": (
                    _iso(source_collected_at) if source_collected_at is not None else ""
                ),
                "loaded_at": _iso(loaded_at),
                "run_id": run_id or "",
                "guard_override": "1" if allow_shrink else "0",
                "source_status": source_status or "",
            }
            async with (
                _unavailable_on_error("메타 쓰기"),
                self._client.pipeline(transaction=False) as pipe,
            ):
                pipe.hset(keys["meta"], mapping=meta_fields)
                pipe.expire(keys["meta"], self._build_ttl)
                await pipe.execute()
            await self._flip(
                dataset, keys, previous_generation, generation, reset_recent=allow_shrink
            )
        except BaseException:
            await self._discard_unless_current(dataset, keys, generation)
            raise
        return SwapResult(
            meta=_parse_meta(dataset, generation, cast("dict[Any, Any]", meta_fields)),
            previous_generation=previous_generation,
            baseline=baseline,
        )

    async def _flip(
        self,
        dataset: str,
        keys: dict[str, str],
        previous_generation: str | None,
        generation: str,
        *,
        reset_recent: bool = False,
    ) -> None:
        retiring = (
            list(_gen_keys(dataset, previous_generation).values())
            if previous_generation is not None
            else []
        )
        flip_keys = [
            state_key(dataset, "current"),
            state_key(dataset, "previous"),
            state_key(dataset, "recent_counts"),
            *(keys[name] for name in _GEN_KEY_NAMES),
            *retiring,
        ]
        async with _unavailable_on_error("포인터 교체"):
            outcome = cast(
                "list[Any]",
                await _resolve(
                    self._client.eval(
                        _FLIP_SCRIPT,
                        len(flip_keys),
                        *flip_keys,
                        previous_generation or "",
                        generation,
                        self._grace,
                        RECENT_COUNTS_WINDOW,
                        "1" if reset_recent else "0",
                    )
                ),
            )
        status = int(outcome[0])
        detail = _text(outcome[1]) if len(outcome) > 1 else ""
        if status == 0:
            raise StateSwapConflict(
                f"{dataset} 포인터가 교체 직전에 바뀌었다(기대 {previous_generation!r}, "
                f"지금 {detail!r}) — 동시 교체."
            )
        if status != 1:
            raise StateSwapConflict(
                f"{dataset} 새 세대 {detail} 검사가 어긋났다(빠졌거나 개수가 다르다 — build TTL "
                f"{self._build_ttl}초 초과 또는 부분 쓰기)."
            )

    async def _discard_unless_current(
        self, dataset: str, keys: dict[str, str], generation: str
    ) -> None:
        """교체하지 못한 새 세대 키를 지운다(최선).

        교체 스크립트의 응답만 잃은 경우(스크립트는 돌았는데 연결이 끊겼다)에는 그 세대가 이미
        ``current``다 — 그때 지우면 포인터가 없는 세대를 가리킨다. 그래서 ``current``가 이 세대가
        **아님을 확인했을 때만** 지운다. 확인하지 못하면 남겨 둔다: 교체됐다면 TTL이 없어 그대로
        쓰이고, 교체되지 않았다면 build TTL이 치운다.
        """
        try:
            if await self.current_generation(dataset) == generation:
                return
            async with _unavailable_on_error("새 세대 정리"):
                await self._client.unlink(*keys.values())
        except StateStoreError:
            _LOGGER.warning("교체하지 못한 세대 키를 정리하지 못했다 — build TTL로 사라진다.")

    async def _write_generation(
        self, keys: dict[str, str], items: list[StateItem]
    ) -> tuple[int, int]:
        geo_count = 0
        lookup_seen: set[str] = set()
        async with _unavailable_on_error("세대 쓰기"):
            for offset in range(0, len(items), self._batch):
                chunk = items[offset : offset + self._batch]
                touched = [keys["items"], keys["ids"]]
                async with self._client.pipeline(transaction=False) as pipe:
                    pipe.hset(keys["items"], mapping={item.id: item.value for item in chunk})
                    pipe.zadd(keys["ids"], {item.id: 0 for item in chunk})
                    geo_values: list[Any] = []
                    for item in chunk:
                        if item.coord is not None and _geo_ok(item.coord):
                            geo_values.extend((item.coord[0], item.coord[1], item.id))
                    if geo_values:
                        pipe.geoadd(keys["geo"], geo_values)
                        geo_count += len(geo_values) // 3
                        touched.append(keys["geo"])
                    lookup: dict[str, str] = {}
                    for item in chunk:
                        for lookup_key in item.lookup_keys:
                            if lookup_key and lookup_key not in lookup_seen:
                                lookup_seen.add(lookup_key)
                                lookup[lookup_key] = item.id
                    if lookup:
                        pipe.hset(keys["lookup"], mapping=lookup)
                        touched.append(keys["lookup"])
                    for key in touched:
                        pipe.expire(key, self._build_ttl)
                    await pipe.execute()
        return geo_count, len(lookup_seen)

    async def retire_other_versions(self, dataset: str) -> int:
        """이 데이터셋의 **옛** 스키마 버전 만료 없는 키에 grace TTL을 건다(D2). 건 개수를 돌려준다.

        데이터셋마다 자기 교체가 성공한 뒤에만 자기 옛 키를 거둔다 — 한 데이터셋의 첫 새 버전 교체가
        아직 새 버전으로 적재되지 않은 다른 데이터셋의 옛 키까지 거두면 그 데이터셋이 다음 적재까지
        비어 보인다.

        새 버전의 교체가 성공한 뒤에 부른다 — 옛 버전 ``current``와 교체된 세대는 만료가 없어 이
        정리가 없으면 ``noeviction`` 아래 영구히 남는다.
        """
        own_version = _key_version(f"{STATE_KEY_PREFIX}:")
        assert own_version is not None  # STATE_KEY_PREFIX는 ktm:state:v{N} 꼴이다.
        retired = 0
        async with _unavailable_on_error("옛 버전 정리"):
            pattern = f"{STATE_KEY_NAMESPACE}:v*:{dataset}:*"
            async for raw in self._client.scan_iter(match=pattern, count=500):
                key = _text(raw)
                version = _key_version(key)
                # 옛 버전만 거둔다 — 새 버전과 옛 버전이 잠시 함께 돌 때(롤링·롤백) 서로의 키를
                # 번갈아 만료시키지 않게 한다.
                if version is None or version >= own_version:
                    continue
                if int(await self._client.ttl(key)) == -1:
                    await self._client.expire(key, self._grace)
                    retired += 1
        return retired
