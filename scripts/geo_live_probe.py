"""geo live 모드를 선언했으면 정말 live인지, 그리고 실제로 돌았는지 확인한다.

``tests/integration/test_dedup_with_kraddr_geo_live.py``는 geo가 도달 불가하면
**조용히 skip**한다(CI가 그렇다). 그래서 로컬 게이트가 "n150 터널로 실제 실행"이라
적어 놓고 터널이 끊겨 5건이 skip돼도 로그만 보면 통과처럼 보인다 — 2026-08-09에
실제로 그렇게 적었고, 그 다음 실행에서 이 스크립트가 잡았다.

두 가지 방식으로 쓴다.

``python scripts/geo_live_probe.py``
    pytest **전에** 돈다. ``LIVE_KOR_TRAVEL_GEO_BASE_URL``이 터널을 가리키면
    테스트와 **같은 판정식**으로 도달성을 본다. TCP만 보면 안 된다 — 포트는 열려
    있는데 ``/v1/healthz``가 404인 상태에서 probe는 통과하고 테스트는 skip하는
    구멍이 생긴다(9라운드 적대 리뷰 F6).

``python scripts/geo_live_probe.py --assert-ran <pytest 로그>``
    pytest **뒤에** 돈다. probe는 한 번만 도는데 integration은 20~50분이라, 그
    사이 ssh가 끊기면 여전히 조용한 skip이 된다. 사후에 로그로 못을 박는다.

skip 모드(도달 불가 주소)면 둘 다 아무것도 하지 않는다 — 그때는 CI와 같은 판정이
의도된 것이다.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

_SKIP_MODE_PORT = 1
_UNREACHABLE = 96
_SILENTLY_SKIPPED = 95


def _live_base_url() -> str | None:
    """live 모드면 base URL, skip 모드면 ``None``."""

    raw = os.environ.get("LIVE_KOR_TRAVEL_GEO_BASE_URL", "")
    if not raw:
        return None
    port = urlparse(raw).port
    if port is None or port == _SKIP_MODE_PORT:
        return None
    return raw


def _is_reachable(base_url: str) -> bool:
    """``test_dedup_with_kraddr_geo_live._is_reachable``과 **같은 판정식**.

    두 판정이 갈리면 probe가 통과한 뒤 테스트가 skip한다 — 그게 정확히 이
    스크립트가 막으려는 것이다.
    """

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1.5):
            pass
    except OSError:
        return False
    try:
        with httpx.Client(base_url=base_url, timeout=3.0) as http:
            return http.get("/v1/healthz").status_code == 200
    except httpx.HTTPError:
        return False


def _assert_ran(log_path: Path) -> int:
    """pytest 로그에 skip이 남아 있으면 실패시킨다."""

    if not log_path.exists():
        print(f"FATAL: pytest 로그가 없다: {log_path}", file=sys.stderr)
        return _SILENTLY_SKIPPED
    text = log_path.read_text(encoding="utf-8", errors="replace")
    skipped = re.search(r"(\d+) skipped", text)
    if skipped is not None and skipped.group(1) != "0":
        print(
            f"FATAL: geo live 모드인데 {skipped.group(1)}건이 skip됐다 — "
            "터널이 실행 도중 끊겼을 가능성이 크다. 결과를 live로 셀 수 없다.",
            file=sys.stderr,
        )
        return _SILENTLY_SKIPPED
    return 0


def main(argv: list[str]) -> int:
    base_url = _live_base_url()
    if base_url is None:
        # 의도된 skip 모드. CI와 같은 판정을 재현하는 중이다.
        return 0
    if "--assert-ran" in argv:
        return _assert_ran(Path(argv[argv.index("--assert-ran") + 1]))
    if not _is_reachable(base_url):
        print(
            f"FATAL: geo live 모드({base_url})인데 테스트 판정식으로 도달 불가다 — "
            "geo 5건이 조용히 skip된다(TCP는 열려 있어도 /v1/healthz가 200이 "
            "아니면 테스트는 skip한다).",
            file=sys.stderr,
        )
        return _UNREACHABLE
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
