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
``metadata_json.region``(**115/264 보유**)을 쓰며, 비교는 ``features.sigungu_code`` 앞 2자리
(시도코드)와 한다. region 문자열을 주소에 포함시켜 보면 약칭·정식명 차이로 6개 시도가
통째로 깨진다.
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
from h33_mislink_detect import region_to_code

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


async def candidates(
    conn: asyncpg.Connection, row: dict
) -> tuple[list[dict], int]:
    """이름 변형 × 양방향 포함으로 후보를 모은다. 승인은 하지 않는다."""
    found: dict[str, dict] = {}
    truncated_total = 0
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
        # 시도는 **코드로** 비교한다. ``region in address``로 하면 약칭(``충북``)이
        # 정식명(``충청북도``)에 포함되지 않아 충북·충남·전북·전남·경북·경남 6개 시도가
        # 통째로 mismatch가 된다 — 그 시도에서는 어떤 exact 매칭도 high에 도달할 수 없다.
        want = region_to_code(region)
        if not want:
            region_state = "unknown"
        elif not c["sigungu_code"]:
            region_state = "unknown"
        else:
            region_state = "match" if c["sigungu_code"][:2] == want else "mismatch"
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
    ranked = sorted(scored, key=lambda c: order[c["grade"]])
    # 상위 2건만 남긴다 — manifest를 저장소에 커밋해 검토 가능하게 유지하기 위한 상한.
    # 잘린 사실을 감추지 않도록 **전체 수를 함께 돌려준다**(silent cap 금지).
    return ranked[:2], len(ranked)


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
            cands, total = await candidates(conn, row)
            top = cands[0]["grade"] if cands else "none"
            entries.append(
                {
                    **row,
                    "top_grade": top,
                    "candidates_total": total,
                    "candidates_shown": len(cands),
                    "candidates": cands,
                    # **어떤 등급도 자동 승인이 아니다.** high에도 오탐이 있다
                    # (`대관령` → 동명 상점). 이 필드를 null로 두면 소비자가
                    # `unresolved_reason is None`으로 걸러 자동 수용한다.
                    "unresolved_reason": (
                        "후보 없음"
                        if top == "none"
                        else "검토 필요 — 자동 승인 대상 아님 (high에도 오탐 존재)"
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
                    "database": db,
                    "unlinked_rows": len(rows),
                    "baseline": dict(Counter(str(r["baseline"]) for r in rows)),
                    "matcher": dict(mine),
                    # AC "차이를 설명한다" — 기준선×자체 교차표를 산출물에 남긴다.
                    # 콘솔에만 찍으면 검토자가 재현 없이는 볼 수 없다.
                    "baseline_vs_matcher": {
                        f"{base}|{got}": n for (base, got), n in sorted(cross.items())
                    },
                    "region_axis_coverage": sum(1 for r in rows if r["region"]),
                    "candidates_truncated_to": 2,
                    "auto_approvable": 0,
                },
                "notes": (
                    "자동 승인 대상은 0건이다 — high 등급에도 오탐이 있다(대관령 → 동명 상점). "
                    "등급은 검토 우선순위일 뿐 승인 신호가 아니며, 모든 entry의 "
                    "unresolved_reason이 채워져 있다. 후보는 상위 2건만 실었고 전체 수는 "
                    "candidates_total에 있다."
                ),
                "entries": entries,
            },
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\nmanifest 저장: {OUT} ({len(entries)} entries)")


if __name__ == "__main__":
    asyncio.run(main())
