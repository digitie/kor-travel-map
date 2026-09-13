"""이 run이 upstream에 몇 번 요청했는지 센다 — 분자.

**왜 이 모듈이 따로 있나.** 분모는 2026-09-13에 실측했다(오퍼레이션당 500~10,000,
``docs/etl/upstream-quota.md``). 분자는 그때 KMA 격자 job에만 있었다 — 나머지
provider는 fetcher가 **generator**라서, 요청을 세는 자리(페이지 루프)와 그 수를
내보내는 자리(asset의 output metadata) 사이에 값을 흘릴 배선이 없었다. 그래서
"우리가 한도의 몇 %를 쓰는가"를 bulk/페이지네이션 경로에 대해 대답할 수 없었다.

**배선 대신 실행 문맥을 쓴다.** :class:`contextvars.ContextVar`는 generator 안에서도
호출자의 문맥이 보인다 — fetcher가 몇 겹의 generator를 지나도 asset 경계가 연 계수기에
닿는다. 함수 시그니처를 하나도 바꾸지 않으므로 provider fetcher 19곳을 건드리지 않는다.

**세는 것은 요청이 아니라 요청의 하한이다.** 이름에 ``_min``이 붙는 이유다:

- 페이지 하나를 가져오는 콜백이 **내부에서 재시도**하면 그 재시도는 보이지 않는다
  (``upstream_retry``의 외부 attempts, provider client의 내부 retries).
- provider lib이 한 번의 호출 안에서 여러 요청을 보내는 자리가 있다
  (krex ``latest_weather``의 lookback 루프 — 그래서 그쪽은 lookback 상한을 따로 선언한다).
- 캐시/스킵으로 호출이 아예 없었던 구간은 0이다.

즉 이 수는 **"적어도 이만큼은 썼다"**이고, 한도와 비교할 때 그 방향으로만 안전하다.

**"세지 않았다"는 값을 내지 않는다.** 계수기가 열려 있어도 **한 번도 기록되지
않았으면** :func:`observed_upstream_requests`가 ``None``을 돌려준다 — 그때 metadata에는
key 자체가 실리지 않는다.

이 구분이 없으면 **계측되지 않은 fetcher가 "0번 요청했다"고 보고한다.** 2026-09-13
적대 리뷰가 정확히 그것을 잡았다: 계수기는 asset 35개 전부에서 열리는데 세는 자리는
셋뿐이었고, 그래서 OpiNet처럼 수천 건을 쓰는 경로가 0을 냈다 — 하필 분모를 실측한
유일한 provider였다. 운영자가 그 0을 "캐시/skip으로 요청이 없었다"로 읽으면(문서가
그렇게 읽으라고 적었다) 정반대 결론에 이른다.

대가는 **진짜로 0번 요청한 run도 key가 없다는 것**이다. 그 편이 낫다 — 없는 값은
읽는 사람을 멈추게 하고, 틀린 0은 멈추지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

__all__ = [
    "UPSTREAM_REQUESTS_METADATA_KEY",
    "counting_upstream_requests",
    "note_upstream_request",
    "observed_upstream_requests",
]

#: asset output metadata에 실리는 이름. 리터럴이어야 로그에서 grep되고, 이 축이
#: 사라지는 것을 정적 검사가 볼 수 있다.
UPSTREAM_REQUESTS_METADATA_KEY: Final[str] = "upstream_requests_min"

#: 열려 있으면 ``[요청 수, 기록 횟수]``, 아니면 ``None``.
#:
#: **가변 리스트**인 이유는 generator가 자기 문맥에서 값을 올릴 수 있어야 하기
#: 때문이다 — 정수를 담으면 ``set``이 필요하고, 문맥이 복사되는 경계
#: (``asyncio.to_thread``/``create_task``)에서 그 ``set``은 호출자에게 보이지 않는다.
#: 리스트는 복사돼도 **같은 객체**라 안쪽 증가가 바깥에 보인다(실측).
#:
#: **두 번째 칸**이 "세지 않았다"와 "0번 요청했다"를 가른다.
_COUNTER: Final[ContextVar[list[int] | None]] = ContextVar(
    "kortravelmap_upstream_requests", default=None
)


@contextmanager
def counting_upstream_requests() -> Iterator[list[int]]:
    """이 블록 안에서 일어난 upstream 요청을 센다. asset 경계가 연다.

    중첩을 허용한다 — 안쪽 블록이 자기 계수기를 열고 나가면 바깥 것이 복원된다.
    안쪽 수가 바깥으로 합산되지는 않는다(그럴 일이 없고, 합산하면 이중 계수가 난다).
    """

    counter = [0, 0]
    token = _COUNTER.set(counter)
    try:
        yield counter
    finally:
        _COUNTER.reset(token)


def note_upstream_request(count: int = 1) -> None:
    """upstream 요청 ``count``건을 기록한다. 계수기가 없으면 no-op."""

    counter = _COUNTER.get()
    if counter is not None:
        counter[0] += count
        counter[1] += 1


def observed_upstream_requests() -> int | None:
    """이 문맥에서 관측된 요청 수.

    계수기가 열려 있지 않거나 **한 번도 기록되지 않았으면** ``None``이다 —
    계측되지 않은 fetcher가 "0번 요청했다"고 보고하지 않게 한다.
    """

    counter = _COUNTER.get()
    if counter is None or counter[1] == 0:
        return None
    return counter[0]
