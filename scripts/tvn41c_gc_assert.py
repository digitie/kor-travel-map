"""T-VN-41C GC 검증 단언 — 수동 GC 처리량과 referenced alert 발화/침묵.

`scripts/verify-tvn41c-cache-target-gc.sh`가 호출한다. 두 모드를 갖는다.

``drain``
    Dagster op이 감싸는 것과 같은 함수(`client.drain_expired_cache_target_snapshots`)를
    직접 부르고 전후 count를 대조한다. **적격만 사라지고 보존 대조군은 그대로**여야 한다.
    "적격이 0이 됐다"만 보면 전부 지우는 구현도 통과하므로 대조군 불변을 같이 단언한다.

``alert``
    referenced 보존 ceiling과 증가율 alert를 **양방향**으로 본다 — 조인 임계치에서는
    반드시 켜지고, 기본 임계치에서는 반드시 꺼져야 한다. 한쪽만 보면 상수를 반환하는
    alert와 구별되지 않는다. 증가율은 개수 ceiling을 넉넉히 둔 채로 따로 터뜨려
    발화 사유가 증가율이라는 것까지 분리한다.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Final

from sqlalchemy import text

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.db import make_async_engine

_COUNTS_SQL: Final = text(
    """
    SELECT
      (SELECT count(*) FROM ops.poi_cache_target_snapshots) AS headers,
      (SELECT count(*) FROM ops.poi_cache_target_snapshot_items) AS items,
      (SELECT count(*) FROM ops.poi_cache_target_snapshots s
         LEFT JOIN ops.poi_cache_target_reconciliation_requests r
           ON r.snapshot_id = s.snapshot_id
         WHERE s.expires_at <= now() AND r.request_id IS NULL) AS eligible_headers,
      (SELECT count(*) FROM ops.poi_cache_target_snapshot_items i
         JOIN ops.poi_cache_target_snapshots s ON s.snapshot_id = i.snapshot_id
         LEFT JOIN ops.poi_cache_target_reconciliation_requests r
           ON r.snapshot_id = s.snapshot_id
         WHERE s.expires_at <= now() AND r.request_id IS NULL) AS eligible_items,
      (SELECT count(*) FROM ops.poi_cache_target_snapshots s
         JOIN ops.poi_cache_target_reconciliation_requests r
           ON r.snapshot_id = s.snapshot_id) AS referenced_headers,
      (SELECT count(*) FROM ops.poi_cache_target_snapshots
         WHERE expires_at > now()) AS live_headers
    """
)

# growth baseline 자격은 최소 간격 1초(테이블 CHECK의 하한)를 요구한다. 연속 실행이
# 1초 안에 끝나면 baseline이 무효화돼 증가율이 "관측 불가"로 빠지므로 간격을 벌린다.
_GROWTH_SETTLE_SECONDS: Final = 2.0

_WATCHED_ALERT_KEYS: Final = (
    "referenced_alert",
    "referenced_alert_reasons",
    "referenced_observation_available",
    "referenced_observation_headers",
    "referenced_observation_items",
    "referenced_growth_rate_observed",
    "referenced_growth_unobserved_reason",
    "referenced_headers_growth_baseline_delta",
    "referenced_headers_growth_per_hour",
)


async def _counts(engine: Any) -> dict[str, int]:
    async with engine.connect() as conn:
        return dict((await conn.execute(_COUNTS_SQL)).mappings().one())


async def _drain(dsn: str) -> list[str]:
    engine = make_async_engine(dsn)
    try:
        before = await _counts(engine)
        print("  before:", json.dumps(before))
        started = time.monotonic()
        async with AsyncKorTravelMapClient(engine) as client:
            result = await client.drain_expired_cache_target_snapshots(
                max_batches=2_000,
                max_seconds=300,
                item_limit=1_000,
                header_limit=100,
                observation_run_id=f"tvn41c-manual-gc-{os.getpid()}-{int(started)}",
            )
        elapsed = max(time.monotonic() - started, 1e-6)
        after = await _counts(engine)
        print("  after :", json.dumps(after))
        print(
            "  result:",
            json.dumps(
                {
                    "acquired": result.acquired,
                    "skipped": result.skipped,
                    "batches": result.batches,
                    "deleted_items": result.deleted_items,
                    "deleted_headers": result.deleted_headers,
                    "remaining_items": result.remaining_items,
                    "remaining_headers": result.remaining_headers,
                    "elapsed_seconds": round(elapsed, 3),
                }
            ),
        )
        print(
            f"  처리량: items {result.deleted_items / elapsed:,.0f}/s, "
            f"headers {result.deleted_headers / elapsed:,.0f}/s"
        )
    finally:
        await engine.dispose()

    problems: list[str] = []
    if not result.acquired:
        problems.append("GC가 mutex를 잡지 못했다(acquired=False)")
    if after["eligible_headers"]:
        problems.append(f"적격 header가 남았다: {after['eligible_headers']}")
    if after["eligible_items"]:
        problems.append(f"적격 item이 남았다: {after['eligible_items']}")
    if result.remaining_headers or result.remaining_items:
        problems.append(
            f"remaining backlog가 0이 아니다: headers={result.remaining_headers} "
            f"items={result.remaining_items}"
        )
    for key, label in (("referenced_headers", "참조된"), ("live_headers", "미만료")):
        if after[key] != before[key]:
            problems.append(f"{label} snapshot이 지워졌다: {before[key]} -> {after[key]}")
    for key, deleted in (
        ("eligible_headers", result.deleted_headers),
        ("eligible_items", result.deleted_items),
    ):
        if deleted != before[key]:
            problems.append(f"삭제 수 불일치 {key}: deleted={deleted} expected={before[key]}")
    return problems


def _alert(seed_command: str) -> list[str]:
    """세 번의 job 실행으로 alert를 양방향 + 사유 분리까지 확인한다."""
    from tvn41c_gc_defs import defs  # noqa: PLC0415 — DAGSTER_HOME 설정 뒤에 import한다.

    job = defs.get_job_def("cache_target_snapshot_gc")
    node = "drain_expired_cache_target_snapshots"

    def run(label: str, config: dict[str, object]) -> dict[str, Any]:
        metadata = job.execute_in_process(
            run_config={"ops": {node: {"config": config}}}, raise_on_error=True
        ).output_for_node(node)
        picked = {k: metadata.get(k) for k in _WATCHED_ALERT_KEYS if k in metadata}
        print(f"  [{label}] " + json.dumps(picked, ensure_ascii=False, default=str))
        return metadata

    tight = run(
        "조인 임계치",
        {
            "referenced_header_ceiling": 10,
            "referenced_item_ceiling": 10,
            "referenced_header_growth_ceiling_per_hour": 1,
            "referenced_item_growth_ceiling_per_hour": 1,
            "referenced_growth_min_interval_seconds": 1,
        },
    )
    time.sleep(_GROWTH_SETTLE_SECONDS)
    loose = run("기본 임계치", {"referenced_growth_min_interval_seconds": 1})

    # 증가율만 조인다 — 개수 ceiling은 기본값이라 발화 사유가 증가율로 분리된다.
    if os.system(seed_command):  # noqa: S605 — 호출자가 만든 고정 커맨드다.
        return ["증가율 관측용 추가 시딩이 실패했다"]
    time.sleep(_GROWTH_SETTLE_SECONDS)
    growth = run(
        "증가율만 조임",
        {
            "referenced_header_growth_ceiling_per_hour": 1,
            "referenced_item_growth_ceiling_per_hour": 1,
            "referenced_growth_min_interval_seconds": 1,
        },
    )

    problems: list[str] = []
    if not tight.get("referenced_observation_available"):
        problems.append("referenced 관측 자체가 안 됐다 — alert 판정이 무의미하다")
    if not tight.get("referenced_alert"):
        problems.append("조인 임계치인데 alert가 꺼져 있다")
    tight_reasons = tight.get("referenced_alert_reasons") or []
    for reason in ("referenced_header_ceiling", "referenced_item_ceiling"):
        if reason not in tight_reasons:
            problems.append(f"보존 ceiling 사유 {reason} 없음: {tight_reasons}")
    if loose.get("referenced_alert"):
        problems.append(f"기본 임계치인데 alert가 켜졌다: {loose.get('referenced_alert_reasons')}")
    if not growth.get("referenced_growth_rate_observed"):
        problems.append(
            f"증가율이 관측되지 않았다: {growth.get('referenced_growth_unobserved_reason')}"
        )
    growth_reasons = growth.get("referenced_alert_reasons") or []
    for reason in ("referenced_header_growth", "referenced_item_growth"):
        if reason not in growth_reasons:
            problems.append(f"증가율 사유 {reason} 없음: {growth_reasons}")
    for reason in ("referenced_header_ceiling", "referenced_item_ceiling"):
        if reason in growth_reasons:
            problems.append(f"개수 ceiling이 같이 터졌다({reason}) — 증가율 분리 증명이 안 된다")
    return problems


def main() -> int:
    mode = sys.argv[1]
    if mode == "drain":
        problems = asyncio.run(_drain(os.environ["KOR_TRAVEL_MAP_PG_DSN"]))
        passed = "적격만 전부 지우고 보존 대상은 그대로"
    elif mode == "alert":
        problems = _alert(sys.argv[2])
        passed = "보존 ceiling·증가율이 각각 독립 발화하고 기본값에서는 침묵"
    else:  # pragma: no cover - 호출자 오류
        raise SystemExit(f"알 수 없는 모드: {mode!r}")

    print()
    if problems:
        print("RESULT: FAIL")
        for problem in problems:
            print("  !", problem)
        return 4
    print(f"RESULT: PASS — {passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
