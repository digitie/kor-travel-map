"""T-VN-H25B — 미연결 항목 매칭 재실행 + 기준선 대조. **읽기 전용.**

H25A에서 인수한 미충족 AC를 여기서 채운다.

기준선은 **CSV 자체 판정**(`metadata_json.feature_match_confidence`, 운영 DB 대조로 만든
사전 판정)이다. 자체 matcher 수치를 기준선으로 삼지 않는다 — H25A 1차 초안이 그렇게 해서
183 vs 15라는 12배 차이를 "내 수치가 맞다"로 읽었다.

H25A matcher의 확인된 결함을 고친다.
  1. 괄호 — ``영월동서강정원(연당원)``. Python 쪽만 벗기고 SQL에는 원문을 넘겼다.
  2. ``&`` 복합명 — ``만천하스카이워크&단양강 잔도``. 한 Feature가 두 장소명을 갖지 않는다.
  3. 포함 방향 — DB이름 ⊇ CSV이름만 봤다. ``강릉 선교장``(CSV) vs ``선교장``(DB)을 놓친다.
  4. ``status='active'`` 한정 — 로더는 ``deleted``/``hidden``만 배제한다.

축은 실제로 존재하는 것만 쓴다 — ``address_hint``는 486행 전부 비어 있으므로
``metadata_json.region``(118/269 보유)과 ``features.sigungu_code``를 쓴다.
provider provenance 축은 아직 잇지 않았다 — ``curation_items.source_record_key``가
미연결 261건에서 **전부 NULL**이라(H25A §2) 조인할 값이 없다. CSV의 ``provider``/
``dataset_key``/``source_item_key``는 후보 entry에 그대로 실어 둔다.

**자동 승인하지 않는다.** 후보와 근거만 낸다 — H25B 역반영에서 DB 링크 8건 중 3건이
오링크였던 것이 그 이유다.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "/workspace/resources/curations"))
DSN = os.environ["DSN"].replace("+asyncpg", "")
OUT = os.environ.get("OUT", "/out/h25b-match-manifest.json")

_PAREN = re.compile(r"[（(][^)）]*[)）]")
_SPLIT = re.compile(r"\s*[&＆]\s*|\s*,\s*")
# 로더와 같은 범위(curation_repo: deleted/hidden 배제). 'active' 한정이 아니다.
_LINKABLE = ("deleted", "hidden")


def norm(value: object) -> str:
    return "".join(_PAREN.sub("", str(value or "")).split()).lower()


def name_variants(raw: str) -> list[str]:
    """``만천하스카이워크&단양강 잔도`` → 두 후보명. 괄호 안 별칭도 후보로 본다."""
    out: list[str] = []
    for part in _SPLIT.split(raw or ""):
        part = part.strip()
        if not part:
            continue
        out.append(part)
        bare = _PAREN.sub("", part).strip()
        if bare and bare != part:
            out.append(bare)
        for alias in re.findall(r"[（(]([^)）]*)[)）]", part):
            alias = alias.strip()
            if alias:
                out.append(alias)
    seen: set[str] = set()
    return [v for v in out if not (v in seen or seen.add(v))]


def load_unlinked() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(CSV_DIR.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("feature_id") or "").strip():
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
                        "source_component_key": r.get("source_component_key"),
                        "provider": r.get("provider"),
                        "dataset_key": r.get("dataset_key"),
                        "place_name": (r.get("place_name") or "").strip(),
                        "region": str(meta.get("region") or "").strip(),
                        "baseline": meta.get("feature_match_confidence"),
                        "baseline_reasons": meta.get("feature_match_reasons"),
                    }
                )
    return rows


async def candidates(conn: asyncpg.Connection, row: dict) -> list[dict]:
    """이름 변형 × 양방향 포함으로 후보를 모은다. 승인은 하지 않는다."""
    found: dict[str, dict] = {}
    for variant in name_variants(row["place_name"]):
        v = norm(variant)
        if len(v) < 2:
            continue
        hits = await conn.fetch(
            """
            select feature_id, name, status, sigungu_code,
                   coalesce(address->>'road', address->>'legal', '') as addr
            from feature.features
            where status <> all($2::text[])
              and (
                -- DB이름 ⊇ CSV이름
                replace(lower(name), ' ', '') like '%' || $1 || '%'
                -- CSV이름 ⊇ DB이름 (강릉 선교장 vs 선교장)
                or $1 like '%' || replace(lower(name), ' ', '') || '%'
              )
              and length(name) >= 2
            limit 15
            """,
            v,
            list(_LINKABLE),
        )
        for h in hits:
            found.setdefault(
                h["feature_id"],
                {
                    "feature_id": h["feature_id"],
                    "name": h["name"],
                    "status": h["status"],
                    "sigungu_code": h["sigungu_code"],
                    "address": h["addr"],
                    "matched_variant": variant,
                },
            )

    region = row["region"]
    scored = []
    for c in found.values():
        exact = norm(c["name"]) == norm(row["place_name"]) or any(
            norm(c["name"]) == norm(v) for v in name_variants(row["place_name"])
        )
        region_state = (
            "unknown"
            if not region
            else ("match" if region in (c["address"] or "") else "mismatch")
        )
        c["exact_name"] = exact
        c["region_state"] = region_state
        scored.append(c)

    exacts = [c for c in scored if c["exact_name"]]
    for c in scored:
        if c["exact_name"] and len(exacts) == 1 and c["region_state"] == "match":
            c["grade"] = "high"
        elif c["exact_name"] and c["region_state"] == "mismatch":
            c["grade"] = "low"
        elif c["exact_name"]:
            c["grade"] = "review"
        else:
            c["grade"] = "low"
    order = {"high": 0, "review": 1, "low": 2}
    return sorted(scored, key=lambda c: order[c["grade"]])[:5]


async def main() -> None:
    rows = load_unlinked()
    print(f"미연결 {len(rows)}행")
    print("CSV 자체 판정(기준선):", dict(Counter(r["baseline"] for r in rows)))

    conn = await asyncpg.connect(DSN)
    entries = []
    try:
        db = await conn.fetchval("select current_database()")
        print(f"DB={db}")
        for i, row in enumerate(rows):
            cands = await candidates(conn, row)
            top = cands[0]["grade"] if cands else "none"
            entries.append(
                {
                    **row,
                    "top_grade": top,
                    "candidate_count": len(cands),
                    "candidates": cands,
                    "unresolved_reason": (
                        None
                        if top == "high"
                        else "후보 없음"
                        if top == "none"
                        else "자동 승인 불가 — 검토 필요"
                    ),
                }
            )
            if (i + 1) % 50 == 0:
                print(f"  ... {i + 1}/{len(rows)}")
    finally:
        await conn.close()

    mine = Counter(e["top_grade"] for e in entries)
    print("\n=== 자체 matcher 등급 ===")
    for k in ("high", "review", "low", "none"):
        if mine.get(k):
            print(f"  {mine[k]:4d}  {k}")

    print("\n=== 기준선 vs 자체 (교차표) ===")
    cross = Counter((str(e["baseline"]), e["top_grade"]) for e in entries)
    for (base, got), n in sorted(cross.items()):
        print(f"  baseline={base:<10} matcher={got:<7} {n}")

    with open(OUT, "w", encoding="utf-8") as f:  # noqa: ASYNC230  # 1회성 증거 산출
        json.dump(
            {
                "summary": {
                    "unlinked_rows": len(rows),
                    "baseline": dict(Counter(str(r["baseline"]) for r in rows)),
                    "matcher": dict(mine),
                },
                "entries": entries,
            },
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\nmanifest 저장: {OUT} ({len(entries)} entries)")


if __name__ == "__main__":
    asyncio.run(main())
