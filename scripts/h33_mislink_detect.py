"""T-VN-H33 — curation 링크 오탐 전수 탐지. **읽기 전용.**

H25B에서 확인된 오탐 유형을 재현 가능한 질의로 전수화한다.

확인된 사례 — 남이섬(서울 중구), 청남대(전남 영암).

**이 도구의 결론**: 이 축으로 잡히는 오링크는 **3건**이며 추가 사례가 없다. 초안은 여기에
*"오탐이 계통적이니 유형 전수를 대상으로 하라"*고 적었으나 **철회했다** — 호미곶·오륙도는
그 이름의 서울 소재 feature가 *존재할 뿐* curation에 링크돼 있지 않다. *실제 오링크*(고칠
데이터)와 *매칭 함정*(방어할 대상)은 다르다.

**커버리지 한계**: `region`이 있는 행만 본다(DB 링크 3,269건 중 112건, 3%). `sido_code`가
NULL이면 건너뛰고, `features`와 inner join이라 **존재하지 않는 feature를 가리키는 링크는
아예 세지 않는다**. 시도는 맞고 시군구만 다른 오링크도 이 축으로는 안 잡힌다.
"3건"은 부재의 증명이 아니다.

탐지 축은 curation item의 ``metadata_json.region``(시도 약칭)과 링크된 feature의
``sido_code``다. **시도 약칭↔정식명 정규화가 없으면 6개 시도에서 축이 통째로 깨진다**
(``충북`` vs ``충청북도`` — H25B 리뷰 지적). 여기서는 코드로 비교해 그 문제를 없앤다.

[T-VN-32C 값 전환 주의 — legacy-표기 고정] 이 스크립트의 prod f_* 하드코딩과
응답 feature_id 대조 로직은 값 전환(PR-2) 이전 표면 기준이다. 재실행 시 응답의
feature_id는 UUID 정본이므로 대조 로직을 재작성해야 한다(일회성 스크립트 —
기록 보존용으로만 유지).
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import Counter
from pathlib import Path

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "/workspace/resources/curations"))
DSN = os.environ["DSN"].replace("+asyncpg", "")
OUT = os.environ.get("OUT", "/out/h33-mislink.json")

# 시도 약칭·정식명 → 2자리 시도코드. region 문자열을 코드로 바꿔 비교한다.
#
# 2026-07-29 prod 실측으로 17개 코드 전수 확인함(강원 51 / 전북 52 — 특별자치도 전환 후 값,
# 제주 50, 세종 36). 이름이 아니라 **코드로** 비교하는 이유가 데이터에 그대로 있다 —
# 코드 46의 주소 표기가 ``전남광주통합특별시 목포시``인 행이 실재해서, 시도명 문자열
# 대조였다면 그 구간이 통째로 깨진다.
SIDO_CODE: dict[str, str] = {
    "서울": "11", "서울특별시": "11",
    "부산": "26", "부산광역시": "26",
    "대구": "27", "대구광역시": "27",
    "인천": "28", "인천광역시": "28",
    "광주": "29", "광주광역시": "29",
    "대전": "30", "대전광역시": "30",
    "울산": "31", "울산광역시": "31",
    "세종": "36", "세종특별자치시": "36",
    "경기": "41", "경기도": "41",
    "강원": "51", "강원도": "51", "강원특별자치도": "51",
    "충북": "43", "충청북도": "43",
    "충남": "44", "충청남도": "44",
    "전북": "52", "전라북도": "52", "전북특별자치도": "52",
    "전남": "46", "전라남도": "46",
    "경북": "47", "경상북도": "47",
    "경남": "48", "경상남도": "48",
    "제주": "50", "제주도": "50", "제주특별자치도": "50",
}


def region_to_code(region: str) -> str | None:
    return SIDO_CODE.get((region or "").strip())


def linked_rows() -> list[dict]:
    """CSV에서 feature_id와 region을 모두 가진 행."""
    rows: list[dict] = []
    for path in sorted(CSV_DIR.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                fid = (r.get("feature_id") or "").strip()
                if not fid:
                    continue
                try:
                    meta = json.loads(r.get("metadata_json") or "{}")
                except Exception:  # noqa: BLE001
                    meta = {}
                rows.append(
                    {
                        "csv": path.name,
                        "collection_key": r.get("collection_key"),
                        "source_item_key": r.get("source_item_key"),
                        "place_name": (r.get("place_name") or "").strip(),
                        "feature_id": fid,
                        "region": str(meta.get("region") or "").strip(),
                    }
                )
    return rows


async def main() -> None:
    rows = linked_rows()
    with_region = [r for r in rows if region_to_code(r["region"])]
    print(f"링크된 CSV 행 {len(rows)} | region 코드화 가능 {len(with_region)}")
    unknown = {r["region"] for r in rows if r["region"] and not region_to_code(r["region"])}
    if unknown:
        print(f"  ★ 코드화 못한 region: {sorted(unknown)}")

    conn = await asyncpg.connect(DSN)
    try:
        db = await conn.fetchval("select current_database()")
        print(f"DB={db}")

        # (1) CSV 링크: region 코드 vs feature sido_code
        feats = {
            r["feature_id"]: r
            for r in await conn.fetch(
                """
                select feature_id, name, sido_code, sigungu_code,
                       coalesce(address->>'road', address->>'legal', '') as addr
                from feature.features where feature_id = any($1::text[])
                """,
                [r["feature_id"] for r in with_region],
            )
        }
        csv_bad = []
        for r in with_region:
            f = feats.get(r["feature_id"])
            if f is None or not f["sido_code"]:
                continue
            want = region_to_code(r["region"])
            if want != f["sido_code"]:
                csv_bad.append(
                    {
                        **r,
                        "expected_sido": want,
                        "feature_name": f["name"],
                        "feature_sido": f["sido_code"],
                        "feature_sigungu": f["sigungu_code"],
                        "feature_address": f["addr"],
                    }
                )

        # (2) DB 링크 전수: curation_items ↔ feature 시도 불일치
        db_rows = await conn.fetch(
            """
            select cc.collection_key, ci.external_item_id, ci.place_name,
                   ci.feature_id, ci.metadata, f.name as feature_name,
                   f.sido_code, f.sigungu_code,
                   coalesce(f.address->>'road', f.address->>'legal', '') as addr
            from feature.curation_items ci
            join feature.curation_collections cc on cc.collection_id = ci.collection_id
            join feature.features f on f.feature_id = ci.feature_id
            where ci.feature_id is not null
            """
        )
        # region을 코드로 바꿀 수 있는 DB 링크 수. 커버리지 주장("3,269건 중 N건")의 근거라
        # 산출물에 같이 남긴다 — 리포트에만 적고 아티팩트에 없으면 검증할 수가 없다.
        db_codeable = 0
        db_bad = []
        for r in db_rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:  # noqa: BLE001
                    meta = {}
            region = str((meta or {}).get("region") or "").strip()
            want = region_to_code(region)
            if want:
                db_codeable += 1
            if not want or not r["sido_code"] or want == r["sido_code"]:
                continue
            db_bad.append(
                {
                    "collection_key": r["collection_key"],
                    "source_item_key": r["external_item_id"],
                    "place_name": r["place_name"],
                    "feature_id": r["feature_id"],
                    "feature_name": r["feature_name"],
                    "region": region,
                    "expected_sido": want,
                    "feature_sido": r["sido_code"],
                    "feature_sigungu": r["sigungu_code"],
                    "feature_address": r["addr"],
                }
            )
    finally:
        await conn.close()

    print(f"\n=== CSV 링크 시도 불일치: {len(csv_bad)}건 ===")
    for r in csv_bad[:15]:
        print(
            f"  {r['place_name']} (region={r['region']}→{r['expected_sido']}) "
            f"→ {r['feature_name']} sido={r['feature_sido']} | {r['feature_address'][:38]}"
        )

    print(f"\n=== DB 링크 시도 불일치: {len(db_bad)}건 ===")
    for r in db_bad[:15]:
        print(
            f"  {r['place_name']} (region={r['region']}→{r['expected_sido']}) "
            f"→ {r['feature_name']} sido={r['feature_sido']} | {r['feature_address'][:38]}"
        )
    print("\n불일치 시도 분포:", dict(Counter(r["feature_sido"] for r in db_bad)))

    with open(OUT, "w", encoding="utf-8") as f:  # noqa: ASYNC230  # 1회성 증거 산출
        json.dump(
            {
                "summary": {
                    "database": db,
                    "csv_linked_rows": len(rows),
                    "csv_region_codeable": len(with_region),
                    "csv_sido_mismatch": len(csv_bad),
                    "db_linked_rows": len(db_rows),
                    "db_region_codeable": db_codeable,
                    "db_sido_mismatch": len(db_bad),
                },
                "csv_mismatches": csv_bad,
                "db_mismatches": db_bad,
            },
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
