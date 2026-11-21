#!/usr/bin/env python3
"""Map API 읽기 경로 HTTP probe — 읽기 성능 계획 T-READ-01.

PinVi와 같은 모양의 HTTP 요청을 Map API에 보내 요청마다 ``meta.duration_ms``(서버가 잰 시간)와
전체 시간(client 왕복)을 모으고, 묶음(case)마다 ``/proc/pressure/io``의 ``some avg60``을 적는다.
호스트(n150)에서 돈다.

- **DB 연결이 없다.** HTTP만 쓴다(표준 라이브러리 ``urllib``). 이 모듈은 ``kortravelmap``·
  ``sqlalchemy``·``asyncpg``를 import하지 않는다(시험이 강제한다).
- **service token은 실행할 때 읽고 출력하거나 파일에 쓰지 않는다.** ``--token-file`` 경로 또는
  ``KOR_TRAVEL_MAP_PROBE_SERVICE_TOKEN`` env에서 읽어 ``X-Kor-Travel-Map-Service-Token`` 헤더로만
  보낸다. 공개 route도 그 token을 받는다(``api/auth.py``). 보고서에는 token의 존재 여부도 쓰지
  않는다.
- 결과는 ``--output <파일>``(``.safe.json``)과 stdout. URL host가 loopback이 아니면 보고서에는
  ``<non-loopback>``으로만 적는다(사설 IP를 문서로 옮기지 않는다).

운영에서 돌리는 것은 소유자가 승인한 조용한 창에서만 한다(계획 §8.1, 2026-11-18 결정).

- **재기 전에 case마다 warm-up을 보낸다(T-READ-12).** asyncpg는 SQL을 연결마다 prepared
  statement로 재사용하고, PostgreSQL ``plan_cache_mode=auto``는 한 연결에서 6번째 실행부터 generic
  plan을 고를 수 있다. 그래서 연결이 막 열린 API와 오래 돈 API의 숫자가 다를 수 있다(zoom 7 집계가
  150 → 630 ms로 바뀐 적이 있다). ``--warmup-per-case``(기본 6 × (pool_size 5 + max_overflow 10)
  = 90)만큼 먼저 보내 버리고 결과를 분위에 넣지 않는다. 요청은 하나씩 가므로 pool(FIFO)이 쉬는
  연결을 돌려 가며 내준다 — 각 연결이 6번을 넘긴 정상상태에서 잰다. ``0``이면 끈다.

사용법::

    python scripts/read_path_probe.py --base-url http://127.0.0.1:12701 \\
        --token-file /path/to/token --iterations 30 --output /tmp/read-probe.safe.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

#: ``kortravelmap.api.auth.SERVICE_TOKEN_HEADER``와 같아야 한다(시험이 대조한다). import하면
#: API 패키지와 DB 드라이버가 따라오므로 문자열로 둔다.
SERVICE_TOKEN_HEADER: Final[str] = "X-Kor-Travel-Map-Service-Token"
TOKEN_ENV: Final[str] = "KOR_TRAVEL_MAP_PROBE_SERVICE_TOKEN"
_PSI_IO_PATH: Final[Path] = Path("/proc/pressure/io")
_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "localhost", "::1"})

#: PinVi 지도 기본 kind와 in-bounds 기본 건수(``PIN:apps/web``·``app/clients/kor_travel_map.py``).
_PINVI_KINDS: Final[tuple[str, ...]] = ("place", "event", "notice", "price")
_PINVI_MAX_ITEMS: Final[int] = 500
_SEOUL_Z12: Final[tuple[float, float, float, float]] = (126.758, 37.456, 127.198, 37.677)
_SEOUL_Z13: Final[tuple[float, float, float, float]] = (126.868, 37.51125, 127.088, 37.62175)
_SEOUL_Z14: Final[tuple[float, float, float, float]] = (126.923, 37.53888, 127.033, 37.59413)
_NATION_Z7: Final[tuple[float, float, float, float]] = (124.5, 33.0, 131.0, 38.7)
_CAPITAL_Z10: Final[tuple[float, float, float, float]] = (126.6, 37.3, 127.4, 37.8)
#: API 엔진 pool 기본값(``kortravelmap.infra.db.make_async_engine``: pool_size 5, max_overflow 10)과
#: PostgreSQL이 generic plan을 고려하기 시작하는 실행 횟수(``plan_cache_mode=auto``의 6번째).
_API_POOL_CONNECTIONS: Final[int] = 5 + 10
_GENERIC_PLAN_AFTER_EXECUTIONS: Final[int] = 6
DEFAULT_WARMUP_PER_CASE: Final[int] = _GENERIC_PLAN_AFTER_EXECUTIONS * _API_POOL_CONNECTIONS


@dataclass(frozen=True, slots=True)
class ProbeCase:
    """PinVi가 보내는 요청 하나의 모양. ``path``는 query 없는 경로."""

    name: str
    path: str
    query: tuple[tuple[str, str], ...] = ()


def _in_bounds(name: str, bbox: tuple[float, float, float, float], zoom: int) -> ProbeCase:
    min_lon, min_lat, max_lon, max_lat = bbox
    query: list[tuple[str, str]] = [
        ("min_lon", str(min_lon)),
        ("min_lat", str(min_lat)),
        ("max_lon", str(max_lon)),
        ("max_lat", str(max_lat)),
        ("zoom", str(zoom)),
        ("max_items", str(_PINVI_MAX_ITEMS)),
    ]
    query.extend(("kind", kind) for kind in _PINVI_KINDS)
    return ProbeCase(name=name, path="/v1/features/in-bounds", query=tuple(query))


def _search(name: str, q: str) -> ProbeCase:
    return ProbeCase(
        name=name,
        path="/v1/features/search",
        query=(("q", q), ("page_size", "50")),
    )


#: 고정 case. 상세 1건은 zoom 14 응답의 첫 Feature로 실행 때 만든다(``DETAIL_CASE_NAME``).
PROBE_CASES: Final[tuple[ProbeCase, ...]] = (
    _in_bounds("in-bounds 전국 시도 집계(zoom 7)", _NATION_Z7, 7),
    _in_bounds("in-bounds 수도권 시군구 집계(zoom 10)", _CAPITAL_Z10, 10),
    _in_bounds("in-bounds 서울시청 읍면동 집계(zoom 12, PinVi 기본 화면)", _SEOUL_Z12, 12),
    _in_bounds("in-bounds 서울시청 읍면동 집계(zoom 13)", _SEOUL_Z13, 13),
    _in_bounds("in-bounds 서울 개별 행(zoom 14)", _SEOUL_Z14, 14),
    _search("검색 상용어 카페", "카페"),
    _search("지역 검색(좁은 지역) 부산 맛집", "부산 맛집"),
    _search("지역 검색(넓은 지역) 서울 맛집", "서울 맛집"),
)
DETAIL_SOURCE_CASE_NAME: Final[str] = "in-bounds 서울 개별 행(zoom 14)"
DETAIL_CASE_NAME: Final[str] = "상세 1건"


@dataclass(frozen=True, slots=True)
class ProbeResponse:
    status: int
    body: bytes


Fetch = Callable[[str, Mapping[str, str], float], ProbeResponse]


def _urllib_fetch(url: str, headers: Mapping[str, str], timeout: float) -> ProbeResponse:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return ProbeResponse(status=int(response.status), body=response.read())
    except urllib.error.HTTPError as exc:
        return ProbeResponse(status=int(exc.code), body=exc.read() or b"")


def read_service_token(token_file: Path | None, environ: Mapping[str, str]) -> str | None:
    """token을 파일(우선) 또는 env에서 읽는다. 앞뒤 공백을 걷는다. 없으면 ``None``."""

    if token_file is not None:
        value = token_file.read_text(encoding="utf-8").strip()
        return value or None
    value = environ.get(TOKEN_ENV, "").strip()
    return value or None


def read_psi_io_some_avg60(path: Path = _PSI_IO_PATH) -> float | None:
    """``/proc/pressure/io``의 ``some avg60``. 파일이 없거나(비 Linux) 모양이 다르면 ``None``."""

    try:
        text = path.read_text(encoding="ascii")
    except OSError:
        return None
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] != "some":
            continue
        for field in fields[1:]:
            key, _, value = field.partition("=")
            if key == "avg60":
                try:
                    return float(value)
                except ValueError:
                    return None
    return None


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def _server_duration_ms(body: bytes) -> int | None:
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    value = meta.get("duration_ms") if isinstance(meta, dict) else None
    return int(value) if isinstance(value, int | float) else None


def _first_feature_id(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("feature_id"), str):
            return str(item["feature_id"])
    return None


def _target_label(base_url: str) -> str:
    host = urllib.parse.urlsplit(base_url).hostname or ""
    return base_url.rstrip("/") if host in _LOOPBACK_HOSTS else "<non-loopback>"


def _url(base_url: str, case: ProbeCase) -> str:
    query = urllib.parse.urlencode(case.query)
    return base_url.rstrip("/") + case.path + (f"?{query}" if query else "")


def _measure_case(
    case: ProbeCase,
    *,
    base_url: str,
    headers: Mapping[str, str],
    iterations: int,
    timeout: float,
    fetch: Fetch,
    psi: Callable[[], float | None],
    warmup: int = 0,
) -> tuple[dict[str, Any], bytes | None]:
    """case 하나를 ``warmup``번 버리고 ``iterations``번 잰다.

    (보고서 항목, 마지막 200 응답 본문)을 돌려준다.
    """

    url = _url(base_url, case)
    warmup_statuses: dict[str, int] = {}
    warmup_errors: dict[str, int] = {}
    for _ in range(warmup):
        try:
            warm = fetch(url, headers, timeout)
        except (OSError, TimeoutError) as exc:
            warmup_errors[type(exc).__name__] = warmup_errors.get(type(exc).__name__, 0) + 1
            continue
        warmup_statuses[str(warm.status)] = warmup_statuses.get(str(warm.status), 0) + 1
    psi_before = psi()
    wall_ms: list[float] = []
    server_ms: list[float] = []
    statuses: dict[str, int] = {}
    errors: dict[str, int] = {}
    last_ok_body: bytes | None = None
    for _ in range(iterations):
        started = time.perf_counter()
        try:
            response = fetch(url, headers, timeout)
        except (OSError, TimeoutError) as exc:
            # 예외 문구에는 URL이 들어갈 수 있다 — 종류만 센다.
            errors[type(exc).__name__] = errors.get(type(exc).__name__, 0) + 1
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        statuses[str(response.status)] = statuses.get(str(response.status), 0) + 1
        if response.status == 200:
            # 200만 분위에 넣는다 — 401·5xx가 빠른 기준선처럼 보이지 않게.
            wall_ms.append(elapsed_ms)
            last_ok_body = response.body
            duration = _server_duration_ms(response.body)
            if duration is not None:
                server_ms.append(float(duration))
    entry: dict[str, Any] = {
        "name": case.name,
        "path": case.path,
        "iterations": iterations,
        "warmup": {"requests": warmup, "statuses": warmup_statuses, "errors": warmup_errors},
        "statuses": statuses,
        "errors": errors,
        "psi_io_some_avg60_before": psi_before,
        "psi_io_some_avg60_after": psi(),
        "wall_p50_ms": round(_nearest_rank(wall_ms, 0.5), 1) if wall_ms else None,
        "wall_p95_ms": round(_nearest_rank(wall_ms, 0.95), 1) if wall_ms else None,
        "server_p50_ms": round(_nearest_rank(server_ms, 0.5), 1) if server_ms else None,
        "server_p95_ms": round(_nearest_rank(server_ms, 0.95), 1) if server_ms else None,
        "response_bytes": len(last_ok_body) if last_ok_body is not None else None,
    }
    return entry, last_ok_body


def run_probe(
    *,
    base_url: str,
    token: str | None,
    iterations: int,
    timeout: float = 15.0,
    fetch: Fetch = _urllib_fetch,
    psi: Callable[[], float | None] = read_psi_io_some_avg60,
    cases: Sequence[ProbeCase] = PROBE_CASES,
    warmup: int = 0,
) -> dict[str, Any]:
    """case마다 (warm-up 뒤) 재고 보고서 dict를 돌려준다. token은 헤더로만 쓴다."""

    headers = {"Accept": "application/json"}
    if token is not None:
        headers[SERVICE_TOKEN_HEADER] = token
    entries: list[dict[str, Any]] = []
    detail_id: str | None = None
    for case in cases:
        entry, body = _measure_case(
            case,
            base_url=base_url,
            headers=headers,
            iterations=iterations,
            timeout=timeout,
            fetch=fetch,
            psi=psi,
            warmup=warmup,
        )
        entries.append(entry)
        if case.name == DETAIL_SOURCE_CASE_NAME and body is not None:
            detail_id = _first_feature_id(body)
    if detail_id is not None:
        detail_case = ProbeCase(
            name=DETAIL_CASE_NAME,
            path="/v1/features/" + urllib.parse.quote(detail_id, safe=""),
        )
        entry, _body = _measure_case(
            detail_case,
            base_url=base_url,
            headers=headers,
            iterations=iterations,
            timeout=timeout,
            fetch=fetch,
            psi=psi,
            warmup=warmup,
        )
        # 상세 경로의 feature id는 공개 값이지만 보고서는 경로 틀만 남긴다.
        entry["path"] = "/v1/features/{feature_id}"
        entries.append(entry)
    return {
        "schema": "kor-travel-map.read-path-probe.v1",
        "target": _target_label(base_url),
        "iterations": iterations,
        "warmup_per_case": warmup,
        "started_at_unix": None,
        "cases": entries,
        "detail_measured": detail_id is not None,
    }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다.")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("0 이상의 정수여야 합니다.")
    return parsed


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:12701")
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help=f"service token 파일. 없으면 env {TOKEN_ENV}. 값은 출력하지 않는다.",
    )
    parser.add_argument("--iterations", type=_positive_int, default=30)
    parser.add_argument(
        "--warmup-per-case",
        type=_non_negative_int,
        default=DEFAULT_WARMUP_PER_CASE,
        help=(
            "case마다 재기 전에 버리는 요청 수(기본 6 × API pool 15 = 90). "
            "연결 나이(prepared statement의 generic plan 전환)에 결과가 "
            "흔들리지 않게 한다. 0이면 끈다."
        ),
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    token = read_service_token(args.token_file, os.environ if environ is None else environ)
    started = time.time()
    report = run_probe(
        base_url=args.base_url,
        token=token,
        iterations=args.iterations,
        timeout=args.timeout,
        warmup=args.warmup_per_case,
    )
    report["started_at_unix"] = int(started)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    # 200이 아닌 응답이나 전송 오류가 하나라도 있으면 실패로 끝난다(잘못된 token 등).
    failed = any(
        case.get("errors") or set(case.get("statuses", {})) - {"200"}
        for case in report.get("cases", [])
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
