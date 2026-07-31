"""T-VN-H34 — H25B 링크 근거를 한 DB snapshot에서 재현한다. **읽기 전용.**

이 도구는 링크를 자동 승인하지 않는다. 행정구역·카테고리·연결된 Feature 이름을 독립
반증 축으로 검사하고, 각 축에서 모순이 없다는 사실만 보고한다.

모집단은 명시적으로 분리한다.

- ``approved``: H25B에서 수동 승인한 5개 내부 항목
- ``public``: 공개 repository 정본
  ``list_feature_curation_groups(public_only=True)``가 반환하는 항목 전체

``public`` scope는 item ``source_present/included/unarchived``, collection
``published/public/unarchived``, public theme, ``feature.public_features``를 스크립트에서
다시 구현하지 않는다. 운영 REST와 같은 repository query를 그대로 사용한다.

모든 조회는 하나의 read-only repeatable-read transaction에서 실행한다. JSON 보고서는
모집단 정의·대상 수·PostgreSQL snapshot identity를 포함하므로 결과가 어느 상태를 감사한
것인지 식별할 수 있다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.address import normalize_korean_text
from kortravelmap.infra.curation_repo import list_feature_curation_groups
from kortravelmap.infra.db import make_async_engine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncConnection


AuditScope = Literal["approved", "public"]

_SIDO_CODE: Final[dict[str, str]] = {
    "서울": "11",
    "부산": "26",
    "대구": "27",
    "인천": "28",
    "광주": "29",
    "대전": "30",
    "울산": "31",
    "세종": "36",
    "경기": "41",
    "강원": "51",
    "충북": "43",
    "충남": "44",
    "전북": "52",
    "전남": "46",
    "경북": "47",
    "경남": "48",
    "제주": "50",
}

_TOURISM_PLAUSIBLE_MAJOR: Final[frozenset[str]] = frozenset(
    {
        "01",  # TOURISM
        "03",  # LODGING — 휴양림·리조트형 관광지 포함
        "04",  # HOT_SPRING_SPA
    }
)
_TOURISM_IMPLAUSIBLE_MAJOR: Final[frozenset[str]] = frozenset(
    {
        "02",  # FOOD
        "05",  # CONVENIENCE
        "06",  # TRANSPORT
        "07",  # MEDICAL
    }
)
_TOURISM_IMPLAUSIBLE_EXACT: Final[frozenset[str]] = frozenset(
    {
        "03050200",  # LODGING_PENSION_RURAL
    }
)
_TOURISM_CAMPAIGNS: Final[frozenset[str]] = frozenset(
    {
        "arboretum-garden-stamp-tour",
        "korean-tourism-100",
        "heritage-visit-campaign",
        "lighthouse-stamp-tour",
    }
)

_APPROVED: Final[tuple[tuple[str, str, str], ...]] = (
    ("arboretum-garden-stamp-tour:2026", "arboretum-2026-001", "primary"),
    ("arboretum-garden-stamp-tour:2026", "arboretum-2026-063", "primary"),
    ("korean-tourism-100:2023-2024", "kt100-2023-2024-036", "primary"),
    ("korean-tourism-100:2025-2026", "kt100-2025-2026-035", "primary"),
    ("korean-tourism-100:2025-2026", "kt100-2025-2026-040", "primary"),
)

_APPROVED_ROW_SQL: Final[str] = """
SELECT cc.collection_key,
       ci.external_item_id,
       ci.external_component_id,
       ci.place_name,
       ci.feature_id,
       ci.metadata ->> 'region' AS region,
       ci.metadata ->> 'feature_match_confidence' AS declared_confidence,
       f.name AS feature_name,
       f.category AS feature_category,
       f.status AS feature_status,
       f.address
  FROM feature.curation_items AS ci
  JOIN feature.curation_collections AS cc
    ON cc.collection_id = ci.collection_id
  LEFT JOIN feature.features AS f
    ON f.feature_id = ci.feature_id
 WHERE ci.archived_at IS NULL
   AND cc.collection_key = :collection_key
   AND ci.external_item_id = :external_item_id
   AND ci.external_component_id = :external_component_id
"""

_NAME_CANDIDATES_SQL: Final[str] = """
SELECT feature_id, name
  FROM feature.public_features
 WHERE lower(
           regexp_replace(
               btrim(normalize(name, NFKC)),
               '[[:space:]]+',
               ' ',
               'g'
           )
       ) = lower(:normalized_name)
 ORDER BY feature_id
"""

_SNAPSHOT_SQL: Final[str] = """
SELECT txid_current_snapshot()::text AS transaction_snapshot,
       current_database() AS database_name,
       current_setting('transaction_isolation') AS isolation_level,
       current_setting('transaction_read_only') AS read_only,
       transaction_timestamp() AS transaction_started_at
"""

_POPULATION: Final[dict[AuditScope, dict[str, str]]] = {
    "approved": {
        "kind": "h25b-approved-internal",
        "definition": (
            "H25B 수동 승인 상수표의 collection_key/external_item_id/"
            "external_component_id 5개"
        ),
    },
    "public": {
        "kind": "public-curation-repository",
        "definition": (
            "list_feature_curation_groups(public_only=True): source_present + "
            "included + item/collection unarchived + collection published/public + "
            "theme public + feature.public_features"
        ),
    },
}


@dataclass(frozen=True)
class AuditTarget:
    collection_key: str
    external_item_id: str
    external_component_id: str
    place_name: str
    feature_id: str | None
    region: str | None
    declared_confidence: str | None
    feature_name: str | None
    feature_category: str | None
    feature_status: str | None
    feature_sido_code: str | None
    feature_sigungu_code: str | None
    feature_address: str


def _campaign(collection_key: str) -> str:
    return collection_key.split(":", 1)[0]


def _normalize_name(value: str | None) -> str | None:
    """양쪽 이름에 동일 적용하는 exact-name 정규화 정책."""

    normalized = normalize_korean_text(value)
    return normalized.casefold() if normalized is not None else None


def _judge(
    row: Mapping[str, Any],
    candidate_feature_ids: Sequence[str],
) -> dict[str, Any]:
    """반증 축과 링크에 결합된 exact-name evidence를 평가한다."""

    axes: dict[str, str] = {}
    reasons: list[str] = []

    region = str(row.get("region") or "").strip()
    feature_sido = str(row.get("feature_sido_code") or "").strip()
    expected_sido = _SIDO_CODE.get(region)
    if not region:
        axes["region"] = "n/a"
        reasons.append("curation metadata에 region이 없어 행정구역 축을 쓸 수 없다")
    elif expected_sido is None:
        axes["region"] = "n/a"
        reasons.append(f"region '{region}'이 시도 약칭표에 없다")
    elif not feature_sido:
        axes["region"] = "n/a"
        reasons.append("feature address에 sido_code가 없다")
    elif feature_sido == expected_sido:
        axes["region"] = "pass"
    else:
        axes["region"] = "fail"
        reasons.append(
            f"시도 불일치: curation region={region}({expected_sido}) vs "
            f"feature sido={feature_sido}"
        )

    category = str(row.get("feature_category") or "").strip()
    is_tourism_campaign = _campaign(str(row["collection_key"])) in _TOURISM_CAMPAIGNS
    if not category or not is_tourism_campaign:
        axes["category"] = "n/a"
    elif (
        category in _TOURISM_IMPLAUSIBLE_EXACT
        or category[:2] in _TOURISM_IMPLAUSIBLE_MAJOR
    ):
        axes["category"] = "fail"
        reasons.append(
            f"카테고리가 관광 대상으로 성립하지 않는다: feature category={category}"
        )
    elif category[:2] in _TOURISM_PLAUSIBLE_MAJOR:
        axes["category"] = "pass"
    else:
        axes["category"] = "n/a"

    normalized_place_name = _normalize_name(cast("str | None", row.get("place_name")))
    normalized_feature_name = _normalize_name(
        cast("str | None", row.get("feature_name"))
    )
    if normalized_place_name is None or normalized_feature_name is None:
        axes["linked_name"] = "n/a"
        reasons.append("curation 또는 linked feature 이름이 비어 있어 이름 축을 쓸 수 없다")
    elif normalized_place_name == normalized_feature_name:
        axes["linked_name"] = "pass"
    else:
        axes["linked_name"] = "fail"
        reasons.append(
            "연결된 feature 이름 불일치: "
            f"curation={row.get('place_name')!r} vs feature={row.get('feature_name')!r}"
        )

    linked_feature_id = cast("str | None", row.get("feature_id"))
    candidates = tuple(dict.fromkeys(candidate_feature_ids))
    if len(candidates) == 1 and candidates[0] == linked_feature_id:
        axes["linked_exact_name_candidate"] = "pass"
    elif not candidates:
        axes["linked_exact_name_candidate"] = "n/a"
        reasons.append("공개 exact-name feature 후보가 없다")
    elif linked_feature_id in candidates:
        axes["linked_exact_name_candidate"] = "n/a"
        reasons.append(
            f"공개 exact-name feature가 {len(candidates)}건이라 후보 축으로 확정할 수 없다"
        )
    else:
        axes["linked_exact_name_candidate"] = "n/a"
        reasons.append(
            "공개 exact-name 후보가 linked feature를 포함하지 않는다: "
            + ", ".join(candidates)
        )

    if any(
        axes.get(axis) == "fail"
        for axis in ("region", "category", "linked_name")
    ):
        verdict = "contradiction"
    elif all(value == "n/a" for value in axes.values()):
        verdict = "insufficient"
    else:
        verdict = "no_contradiction"

    return {
        "axes": axes,
        "verdict": verdict,
        "reasons": reasons,
        "evidence": {
            "normalized_place_name": normalized_place_name,
            "normalized_linked_feature_name": normalized_feature_name,
            "exact_name_candidate_feature_ids": list(candidates),
            "linked_feature_is_exact_name_candidate": linked_feature_id in candidates,
        },
    }


def _address_parts(address: object) -> tuple[str | None, str | None, str]:
    if not isinstance(address, Mapping):
        return None, None, ""
    sido_code = address.get("sido_code")
    sigungu_code = address.get("sigungu_code")
    display = address.get("road") or address.get("legal") or ""
    return (
        str(sido_code) if sido_code is not None else None,
        str(sigungu_code) if sigungu_code is not None else None,
        str(display),
    )


async def _approved_targets(session: AsyncSession) -> list[AuditTarget]:
    targets: list[AuditTarget] = []
    for collection_key, external_item_id, external_component_id in _APPROVED:
        rows = (
            (
                await session.execute(
                    text(_APPROVED_ROW_SQL),
                    {
                        "collection_key": collection_key,
                        "external_item_id": external_item_id,
                        "external_component_id": external_component_id,
                    },
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            sido_code, sigungu_code, address = _address_parts(row["address"])
            targets.append(
                AuditTarget(
                    collection_key=str(row["collection_key"]),
                    external_item_id=str(row["external_item_id"]),
                    external_component_id=str(row["external_component_id"]),
                    place_name=str(row["place_name"]),
                    feature_id=(
                        str(row["feature_id"])
                        if row["feature_id"] is not None
                        else None
                    ),
                    region=str(row["region"]) if row["region"] is not None else None,
                    declared_confidence=(
                        str(row["declared_confidence"])
                        if row["declared_confidence"] is not None
                        else None
                    ),
                    feature_name=(
                        str(row["feature_name"])
                        if row["feature_name"] is not None
                        else None
                    ),
                    feature_category=(
                        str(row["feature_category"])
                        if row["feature_category"] is not None
                        else None
                    ),
                    feature_status=(
                        str(row["feature_status"])
                        if row["feature_status"] is not None
                        else None
                    ),
                    feature_sido_code=sido_code,
                    feature_sigungu_code=sigungu_code,
                    feature_address=address,
                )
            )
    return targets


async def _public_targets(session: AsyncSession) -> list[AuditTarget]:
    """공개 repository의 page를 끝까지 읽어 audit target으로 평탄화한다."""

    targets: list[AuditTarget] = []
    cursor: str | None = None
    while True:
        groups, next_cursor = await list_feature_curation_groups(
            session,
            public_only=True,
            page_size=500,
            cursor=cursor,
        )
        for group in groups:
            sido_code, sigungu_code, address = _address_parts(group.address)
            for item in group.curations:
                targets.append(
                    AuditTarget(
                        collection_key=item.collection_key,
                        external_item_id=item.external_item_id,
                        external_component_id=item.external_component_id,
                        place_name=item.place_name,
                        feature_id=group.feature_id,
                        region=(
                            str(item.metadata["region"])
                            if item.metadata.get("region") is not None
                            else None
                        ),
                        declared_confidence=(
                            str(item.metadata["feature_match_confidence"])
                            if item.metadata.get("feature_match_confidence") is not None
                            else None
                        ),
                        feature_name=group.name,
                        feature_category=group.category,
                        feature_status=group.status,
                        feature_sido_code=sido_code,
                        feature_sigungu_code=sigungu_code,
                        feature_address=address,
                    )
                )
        if next_cursor is None:
            return targets
        cursor = next_cursor


async def _candidate_feature_ids(
    session: AsyncSession,
    *,
    place_name: str,
) -> tuple[str, ...]:
    normalized_name = normalize_korean_text(place_name)
    if normalized_name is None:
        return ()
    rows = (
        (
            await session.execute(
                text(_NAME_CANDIDATES_SQL),
                {"normalized_name": normalized_name},
            )
        )
        .mappings()
        .all()
    )
    expected = _normalize_name(place_name)
    return tuple(
        str(row["feature_id"])
        for row in rows
        if _normalize_name(str(row["name"])) == expected
    )


async def run(
    session: AsyncSession,
    *,
    scope: AuditScope,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    targets = (
        await _public_targets(session)
        if scope == "public"
        else await _approved_targets(session)
    )

    results: list[dict[str, Any]] = []
    for target in targets:
        row = asdict(target)
        if target.feature_id is None:
            results.append(
                {
                    **row,
                    "verdict": "unlinked",
                    "axes": {},
                    "reasons": ["curation item이 feature에 링크돼 있지 않다"],
                    "evidence": {
                        "exact_name_candidate_feature_ids": [],
                        "linked_feature_is_exact_name_candidate": False,
                    },
                }
            )
            continue
        candidate_ids = await _candidate_feature_ids(
            session,
            place_name=target.place_name,
        )
        results.append({**row, **_judge(row, candidate_ids)})

    verdict_counts = Counter(str(result["verdict"]) for result in results)
    return {
        "schema_version": 2,
        "scope": scope,
        "population": dict(_POPULATION[scope]),
        "target_count": len(results),
        "snapshot": dict(snapshot),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "results": results,
    }


async def _snapshot_metadata(connection: AsyncConnection) -> dict[str, Any]:
    row = (await connection.execute(text(_SNAPSHOT_SQL))).mappings().one()
    started_at = row["transaction_started_at"]
    return {
        "transaction_snapshot": str(row["transaction_snapshot"]),
        "database_name": str(row["database_name"]),
        "isolation_level": str(row["isolation_level"]),
        "read_only": str(row["read_only"]),
        "transaction_started_at": started_at.isoformat(),
    }


async def audit_database(dsn: str, *, scope: AuditScope) -> dict[str, Any]:
    engine = make_async_engine(dsn, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection, connection.begin():
            # 첫 query 전에 transaction 특성을 고정한다.
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            snapshot = await _snapshot_metadata(connection)
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
            ) as session:
                return await run(session, scope=scope, snapshot=snapshot)
    finally:
        await engine.dispose()


def _write_json_report(path: str, report: Mapping[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=("approved", "public"),
        default="approved",
        help="감사 모집단: H25B 승인 5건 또는 공개 curation repository 전체",
    )
    parser.add_argument("--json", type=str, default="", help="결과 JSON 출력 경로")
    args = parser.parse_args()

    report = await audit_database(
        os.environ["DSN"],
        scope=cast("AuditScope", args.scope),
    )
    results = cast("list[dict[str, Any]]", report["results"])

    print(
        f"검증 scope={report['scope']} 대상={report['target_count']}건 "
        f"snapshot={report['snapshot']['transaction_snapshot']}"
    )
    for verdict, count in cast(
        "dict[str, int]", report["verdict_counts"]
    ).items():
        print(f"  {verdict:<18} {count}")
    print()
    for result in results:
        mark = "  " if result["verdict"] == "no_contradiction" else "* "
        print(
            f"{mark}{result['collection_key']} / {result['external_item_id']}  "
            f"{result['place_name']}"
        )
        print(f"    verdict={result['verdict']}  axes={result.get('axes')}")
        if result.get("feature_id"):
            print(
                f"    feature={result['feature_id']} "
                f"[{result.get('feature_category')}] "
                f"{str(result.get('feature_address', ''))[:52]}"
            )
        for reason in result["reasons"]:
            print(f"    - {reason}")

    print(
        "\n주의: no_contradiction은 확인됨이 아니다. 현재 반증 축에서 모순을 찾지 "
        "못했다는 뜻이다."
    )

    if args.json:
        _write_json_report(args.json, report)
        print(f"\nJSON: {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
