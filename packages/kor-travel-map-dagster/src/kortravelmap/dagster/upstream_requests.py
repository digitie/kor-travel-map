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

**빈 문맥에서는 아무것도 하지 않는다.** 계수기를 열지 않은 경로(단위 테스트, 수동
호출)에서 :func:`note_upstream_request`는 무해한 no-op이고
:func:`observed_upstream_requests`는 ``None``을 돌려준다 — "0번 요청했다"와 "세지
않았다"는 다른 사실이라 metadata에도 그 둘을 섞지 않는다.
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

#: 열려 있으면 ``[count]``, 아니면 ``None``. 가변 리스트를 담는 이유는 generator가
#: 자기 문맥에서 값을 **올릴 수 있어야** 하기 때문이다 — 정수를 담으면 ``set``이
#: 필요하고 그것은 호출자 문맥에 보이지 않는다.
_COUNTER: Final[ContextVar[list[int] | None]] = ContextVar(
    "kortravelmap_upstream_requests", default=None
)


@contextmanager
def counting_upstream_requests() -> Iterator[list[int]]:
    """이 블록 안에서 일어난 upstream 요청을 센다. asset 경계가 연다.

    중첩을 허용한다 — 안쪽 블록이 자기 계수기를 열고 나가면 바깥 것이 복원된다.
    안쪽 수가 바깥으로 합산되지는 않는다(그럴 일이 없고, 합산하면 이중 계수가 난다).
    """

    counter = [0]
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


def observed_upstream_requests() -> int | None:
    """이 문맥에서 관측된 요청 수. 계수기가 열려 있지 않으면 ``None``."""

    counter = _COUNTER.get()
    return None if counter is None else counter[0]
