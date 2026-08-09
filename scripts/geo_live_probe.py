"""geo live 모드를 선언했으면 정말 live인지 확인한다.

``tests/integration/test_dedup_with_kraddr_geo_live.py``는 geo가 도달 불가하면
**조용히 skip**한다(CI가 그렇다). 그래서 로컬 게이트가 "n150 터널로 실제 실행"이라
적어 놓고 터널이 끊겨 5건이 skip돼도 로그만 보면 통과처럼 보인다 — 2026-08-09에
실제로 그렇게 적었다.

``LIVE_KOR_TRAVEL_GEO_BASE_URL``이 터널 포트를 가리키면 그 포트가 정말 열려 있는지
본다. 아니면 exit 96으로 게이트를 시끄럽게 실패시킨다. skip 모드(도달 불가 주소)면
아무것도 하지 않는다 — 그때는 CI와 같은 판정이 의도된 것이다.
"""

from __future__ import annotations

import os
import socket
import sys
from urllib.parse import urlparse

_SKIP_MODE_PORT = 1


def main() -> int:
    raw = os.environ.get("LIVE_KOR_TRAVEL_GEO_BASE_URL", "")
    if not raw:
        return 0
    parsed = urlparse(raw)
    port = parsed.port
    if port is None or port == _SKIP_MODE_PORT:
        # 의도된 skip 모드. CI와 같은 판정을 재현하는 중이다.
        return 0
    host = parsed.hostname or "127.0.0.1"
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError as exc:
        print(
            f"FATAL: geo live 모드({raw})인데 터널이 닿지 않는다 — "
            f"geo 5건이 조용히 skip된다: {exc}",
            file=sys.stderr,
        )
        return 96
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
