#!/usr/bin/env python3
"""`T-VN-M01` 활성화 live gate의 **거부 축**을 실측한다 (설계 §1, §11 인증 행).

설계는 활성화 전 세 가지를 요구한다 — 전용 BFF 자격 성공, PinVi·일반 AdminBFF 거부,
DB zero-write smoke. 이 스크립트는 뒤의 둘을 담당한다.

**성공 축은 여기서 하지 않는다.** 성공하려면 실제 Feature를 프로덕션에 만들어야 하고,
그 경로는 `T-VN-41F1D-D2`의 acceptance 스펙이 fixture·cleanup·audit과 함께 이미 소유한다.
증거를 두 곳에서 만들면 정리 책임도 두 곳으로 갈라진다.

## 무엇을 하는가

1. 8관계 행 수를 센다.
2. `POST /v1/admin/features`를 **잘못된 자격 조합마다** 호출해 403을 확인한다.
   - 자격 없음
   - admin proxy secret만 (일반 AdminBFF — create token 없음)
   - create token만 (proxy secret 없음)
   - proxy secret + 틀린 create token
3. 8관계 행 수가 **하나도 변하지 않았음**을 확인한다.

거부 경로만 태우므로 성공 write가 없다. 그래서 활성화 직후 프로덕션에서 그대로 돌린다.

## 사용

    python3 scripts/m01_activation_live_gate.py [--json]

env: `E2E_BASE_URL`(admin UI가 아니라 **API** origin), `KOR_TRAVEL_MAP_PG_DSN`,
`KTM_ADMIN_PROXY_SECRET`, `KTM_ADMIN_FEATURE_CREATE_TOKEN`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from kortravelmap.infra.db import make_async_engine
from kortravelmap.settings import KorTravelMapSettings

ADMIN_PROXY_SECRET_HEADER = "X-Kor-Travel-Map-Admin-Proxy-Secret"
ADMIN_FEATURE_CREATE_TOKEN_HEADER = "X-Kor-Travel-Map-Admin-Feature-Create-Token"

#: §11 "8관계 zero-write". 거부된 요청은 이 중 어느 것도 늘리지 못한다.
WITNESS_RELATIONS = (
    "feature.features",
    "feature.feature_places",
    "feature.feature_state_transitions",
    "feature.manual_feature_identity_claims",
    "feature.feature_creation_origins",
    "ops.feature_overrides",
    "ops.domain_commands",
    "ops.domain_command_results",
)

#: 거부돼야 하므로 body가 유효할 필요는 없지만, **자격 때문에** 거부됐음을 보이려면
#: body 검증(422)보다 자격 검증(403)이 먼저 도는 것을 확인해야 한다. 그래서 유효한
#: 모양을 보낸다.
CREATE_BODY = {
    "category": "01070300",
    "coord": {"lat": 36.5, "lon": 127.5},
    "kind": "place",
    "lifecycle_state": "active",
    "marker_color": "P-02",
    "marker_icon": "marker",
    "name": "M01 activation live gate — must be rejected",
    "publication_state": "suppressed",
}


@dataclass(frozen=True)
class Attempt:
    name: str
    status: int
    expected: int

    @property
    def ok(self) -> bool:
        return self.status == self.expected


async def _counts(connection: AsyncConnection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relation in WITNESS_RELATIONS:
        schema_name, _, relation_name = relation.partition(".")
        counts[relation] = int(
            (
                await connection.execute(
                    text(f'SELECT count(*) FROM "{schema_name}"."{relation_name}"')
                )
            ).scalar_one()
        )
    return counts


async def _attempts(base_url: str, secret: str, token: str) -> list[Attempt]:
    cases: tuple[tuple[str, dict[str, str]], ...] = (
        ("no_credential", {}),
        ("admin_proxy_secret_only", {ADMIN_PROXY_SECRET_HEADER: secret}),
        ("create_token_only", {ADMIN_FEATURE_CREATE_TOKEN_HEADER: token}),
        (
            "proxy_secret_with_wrong_create_token",
            {
                ADMIN_PROXY_SECRET_HEADER: secret,
                ADMIN_FEATURE_CREATE_TOKEN_HEADER: "0" * len(token),
            },
        ),
    )
    attempts: list[Attempt] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        for name, headers in cases:
            response = await client.post(
                "/v1/admin/features", json=CREATE_BODY, headers=headers
            )
            attempts.append(Attempt(name, response.status_code, 403))
    return attempts


async def run() -> tuple[list[Attempt], dict[str, int], dict[str, int]]:
    settings = KorTravelMapSettings()
    pg_dsn = settings.pg_dsn
    if pg_dsn is None:
        raise RuntimeError("DSN이 없습니다: KOR_TRAVEL_MAP_PG_DSN")
    base_url = os.environ["E2E_BASE_URL"]
    secret = os.environ["KTM_ADMIN_PROXY_SECRET"]
    token = os.environ["KTM_ADMIN_FEATURE_CREATE_TOKEN"]

    engine = make_async_engine(pg_dsn)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET ROLE ktm_feature_schema_owner"))
            before = await _counts(connection)
        attempts = await _attempts(base_url, secret, token)
        async with engine.connect() as connection:
            await connection.execute(text("SET ROLE ktm_feature_schema_owner"))
            after = await _counts(connection)
    finally:
        await engine.dispose()
    return attempts, before, after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    attempts, before, after = asyncio.run(run())
    drift = {
        relation: after[relation] - before[relation]
        for relation in WITNESS_RELATIONS
        if after[relation] != before[relation]
    }
    rejected = all(attempt.ok for attempt in attempts)
    passed = rejected and not drift

    if arguments.json:
        json.dump(
            {
                "attempts": [
                    {"name": a.name, "status": a.status, "expected": a.expected, "ok": a.ok}
                    for a in attempts
                ],
                "zero_write": {"drift": drift, "ok": not drift},
                "result": "passed" if passed else "failed",
                "version": 1,
            },
            sys.stdout,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        for attempt in attempts:
            mark = "OK " if attempt.ok else "!! "
            print(f"{mark}{attempt.name}: status={attempt.status} expected={attempt.expected}")
        print(f"\nzero-write: {'OK' if not drift else f'!! drift={drift}'}")
        print("result:", "passed" if passed else "failed")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
