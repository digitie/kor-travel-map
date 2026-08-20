"""T-VN-41C GC 검증용 cache-target snapshot 시딩.

GC 삭제 조건은 두 개다 — ``expires_at <= now()``이고
``ops.poi_cache_target_reconciliation_requests``가 그 snapshot을 참조하지 않을 것.
그래서 세 부류를 심어 **지워야 할 것만 지우는지**를 대조군과 함께 본다.

  A. expired + 미참조   -> backlog. GC가 전부 지워야 한다.
  B. expired + 참조됨    -> 보존. reconciliation이 아직 쓰므로 지우면 안 된다.
  C. 미만료 + 미참조     -> 보존. 아직 유효하다.

B가 없으면 "만료된 것을 전부 지운다"는 잘못된 구현도 통과한다. C가 없으면
"전부 지운다"가 통과한다. 두 대조군은 생략 가능한 장식이 아니다.

usage: tvn41c_gc_seed.py <dbname> <systems> <snapshots_per_system> <items_per_snapshot> [tag]
연결 자격증명은 ``KTM_GC_VERIFY_PG_*`` 환경변수로 받는다(인자로 받으면 ps에 남는다).
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from typing import Final

import psycopg

_KIND_EXPIRED_REFERENCED: Final = "B_expired_referenced"
_KIND_LIVE: Final = "C_live"
_KIND_EXPIRED_UNREFERENCED: Final = "A_expired_unreferenced"
#: `0230` 뒤에만 존재하는 부류 — receipt 둘이 material 하나를 공유하고, 그중 하나가
#: 아직 살아 있다. 새 `eligible_items` 셈이 바로 이 경우를 위해 다시 쓰였다.
_KIND_SHARED: Final = "D_shared_live"


def _fingerprint(seed: str) -> str:
    """CHECK 제약이 요구하는 64자 소문자 hex."""
    return hashlib.sha256(seed.encode()).hexdigest()


def _dsn(dbname: str) -> str:
    host = os.environ.get("KTM_GC_VERIFY_PG_HOST", "127.0.0.1")
    port = os.environ.get("KTM_GC_VERIFY_PG_PORT", "12700")
    user = os.environ.get("KTM_GC_VERIFY_PG_USER", "kor_travel_map")
    password = os.environ["KTM_GC_VERIFY_PG_PASSWORD"]
    return f"host={host} port={port} user={user} password={password} dbname={dbname}"


def _classify(index: int) -> tuple[str, str]:
    """snapshot 순번을 네 부류로 나눈다.

    비율보다 **네 부류가 다 나오는 것**이 중요하다. `D_shared_live`는 `0230` 뒤에만
    존재한다 — receipt 둘이 material 하나를 공유하고 그중 하나가 살아 있어서, "붙잡은
    receipt가 하나라도 살아 있으면 그 item은 적격이 아니다"라는 새 셈을 실제로 시험한다.
    """
    if index % 7 == 3:
        return _KIND_EXPIRED_REFERENCED, "now() - interval '1 hour'"
    if index % 7 == 5:
        return _KIND_LIVE, "now() + interval '1 day'"
    if index % 7 == 6:
        return _KIND_SHARED, "now() - interval '1 hour'"
    return _KIND_EXPIRED_UNREFERENCED, "now() - interval '1 hour'"


def main() -> int:
    dbname, systems, snapshots, items = (
        sys.argv[1],
        int(sys.argv[2]),
        int(sys.argv[3]),
        int(sys.argv[4]),
    )
    tag = sys.argv[5] if len(sys.argv) > 5 else "gcv"

    made = dict.fromkeys(
        (
            _KIND_EXPIRED_UNREFERENCED,
            _KIND_EXPIRED_REFERENCED,
            _KIND_LIVE,
            _KIND_SHARED,
        ),
        0,
    )
    items_made = 0
    with psycopg.connect(_dsn(dbname), autocommit=False) as conn, conn.cursor() as cur:
        for system_index in range(systems):
            system = f"{tag}-sys-{system_index:02d}"
            # snapshot.external_system은 poi_cache_target_streams를 FK로 참조한다.
            cur.execute(
                """
                INSERT INTO ops.poi_cache_target_streams (
                  external_system, consumer_id, restore_epoch, control_version,
                  status, consumer_enabled
                ) VALUES (%s, %s, 1, 1, 'ready', true)
                ON CONFLICT DO NOTHING
                """,
                (system, f"{tag}-consumer"),
            )
            for snapshot_index in range(snapshots):
                kind, expires_expression = _classify(snapshot_index)
                snapshot_id = str(uuid.uuid4())
                # `0230`: receipt마다 자기 material을 만든다. 같은 identity를 두 번
                # 주면 살아 있는 material은 identity마다 하나라는 partial unique에
                # 걸리므로 material watermark를 `snapshot_index`로 벌린다.
                material_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO ops.poi_cache_target_snapshot_materials (
                      material_id, external_system, restore_epoch,
                      material_high_watermark_relay_order,
                      safe_high_watermark_relay_order,
                      item_count, merkle_root, materialized_at
                    ) VALUES (
                      %s, %s, 1, %s, %s, %s, %s, now() - interval '2 hour'
                    )
                    """,
                    (
                        material_id,
                        system,
                        snapshot_index,
                        snapshot_index,
                        items,
                        _fingerprint(f"root:{snapshot_id}"),
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO ops.poi_cache_target_snapshots (
                      snapshot_id, material_id, receipt_kind, external_system,
                      created_at, expires_at
                    ) VALUES (
                      %s, %s, 'generic', %s,
                      now() - interval '2 hour', {expires_expression}
                    )
                    """,  # noqa: S608 — expires 표현식은 _classify가 만드는 리터럴이다.
                    (snapshot_id, material_id, system),
                )
                if kind == _KIND_SHARED:
                    # `0230`의 핵심은 receipt N개가 material 하나를 공유한다는 것이고,
                    # 새 `eligible_items` 셈은 바로 그 경우를 위해 다시 쓰였다. 공유를
                    # 한 번도 만들지 않으면 옛 셈과 새 셈이 수치상 같아 게이트가 그
                    # 이유를 검증하지 않는다(적대 리뷰 지적).
                    #
                    # **살아 있는** receipt를 하나 더 붙인다. 그러면 이 material의 item은
                    # 적격이 아니다 — 옛 셈이라면 만료된 쪽을 세어 과다 계상한다.
                    cur.execute(
                        """
                        INSERT INTO ops.poi_cache_target_snapshots (
                          snapshot_id, material_id, receipt_kind, external_system,
                          created_at, expires_at
                        ) VALUES (
                          %s, %s, 'generic', %s,
                          now() - interval '1 hour', now() + interval '2 hour'
                        )
                        """,
                        (str(uuid.uuid4()), material_id, system),
                    )
                if items:
                    cur.executemany(
                        """
                        INSERT INTO ops.poi_cache_target_snapshot_material_items (
                          material_id, row_number, target_key,
                          state, source_generation, source_payload_fingerprint
                        ) VALUES (%s, %s, %s, 'active', 1, %s)
                        """,
                        [
                            (
                                material_id,
                                row,
                                f"{tag}-target-{row}",
                                _fingerprint(f"{snapshot_id}:{row}"),
                            )
                            for row in range(1, items + 1)
                        ],
                    )
                    items_made += items
                if kind == _KIND_EXPIRED_REFERENCED:
                    _seed_reconciliation_reference(cur, system=system, snapshot_id=snapshot_id)
                made[kind] += 1
        conn.commit()

    print(f"  시딩 완료 systems={systems} items={items_made}")
    for kind, count in made.items():
        print(f"    {kind}: {count}")
    return 0


def _seed_reconciliation_reference(cur: psycopg.Cursor, *, system: str, snapshot_id: str) -> None:
    """B 부류의 보존 근거인 reconciliation request를 만든다.

    lifecycle CHECK는 ``succeeded``에 started_at/completed_at과 expected/actual merkle
    root를 모두 요구한다(일치했으므로 succeeded다). request는 ops.domain_commands를
    FK로 참조하고 command_id는 GENERATED ALWAYS identity라 값을 넣지 말고 받아야 한다.
    """
    root = _fingerprint(f"root:{snapshot_id}")
    cur.execute(
        """
        INSERT INTO ops.domain_commands (
          actor, operation, idempotency_key, fingerprint_version, request_fingerprint
        ) VALUES ('tvn41c-gc-verify', 'cache-target.reconciliation.seed', %s, 1, %s)
        RETURNING command_id
        """,
        (str(uuid.uuid4()), _fingerprint(f"cmd:{snapshot_id}")),
    )
    row = cur.fetchone()
    assert row is not None
    cur.execute(
        """
        INSERT INTO ops.poi_cache_target_reconciliation_requests
          (request_id, external_system, command_id, reason, status, snapshot_id,
           expected_merkle_root, actual_merkle_root, started_at, completed_at)
        VALUES (%s, %s, %s, 'tvn41c-gc-verify', 'succeeded', %s, %s, %s,
                now() - interval '90 minutes', now() - interval '80 minutes')
        """,
        (str(uuid.uuid4()), system, row[0], snapshot_id, root, root),
    )


if __name__ == "__main__":
    raise SystemExit(main())
