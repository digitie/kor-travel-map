"""T-VN-H34 — H25B 승인 링크의 근거를 재현 가능하게 검증한다. **읽기 전용.**

H25B는 승인 5건을 ``h25b_apply_verified_links.py``의 **손으로 친 상수표**로만 남겼다.
등급(``backfilled-db-review``)과 사유 문장은 있으나 **그 판정을 다시 돌려볼 수단이 없었다** —
"정지오코딩으로 확인했다"는 주장의 재현 경로가 저장소에 없었다. 이 도구가 그 구멍을 메운다.

## 판정 축 세 개

1. **행정구역 일치** — curation item의 ``metadata.region``(시도 약칭)과 링크된 feature의
   ``sido_code``를 **코드로** 대조한다. 문자열로 비교하면 ``충북`` vs ``충청북도``에서 축이
   통째로 깨진다(H25B 리뷰 지적, ``h33_mislink_detect.py``와 같은 처리).
2. **카테고리 정합성** — 링크된 feature의 category 대분류가 캠페인 성격과 맞는지 본다.
   **T-VN-H34에서 새로 추가한 축이다.** 실측으로 승인 5건 중 2건이 이 축에서만 걸린다:
   ``진해보타닉뮤지엄``(수목원 캠페인)이 ``02020100 FOOD_CAFE_COFFEE``에,
   ``청풍호``(호수)가 ``03050200 LODGING_PENSION_RURAL``에 붙어 있다.
   **두 건 다 행정구역 축은 통과한다** — 시군구 축만으로는 잡히지 않는다.
3. **동명 유일성** — 같은 이름의 active feature가 몇 개인지 센다. 유일하면 *다른 장소에
   붙었을* 가능성이 낮다는 약한 근거이고, 여럿이면 이름 축이 판정에 못 쓰인다.

## 이 도구가 증명하지 못하는 것 (천장)

- **시군구까지 내려가도 같은 시군구 안의 다른 대상은 구분되지 않는다.** 청풍호(제천 43150)와
  청풍호반케이블카가 그 예다. 행정구역 축은 *기각*에는 쓸 수 있어도 *확정*의 충분조건이 아니다.
- 카테고리 축은 **원천 provider의 분류를 신뢰**한다. provider가 틀리게 분류했으면 이 축도 틀린다.
  실제로 위 2건은 "장소는 맞고 카테고리가 틀린" 경우로 보인다 — 링크를 끊을 근거가 아니라
  **카테고리를 고칠 근거**다.
- ``metadata.region``이 없는 행은 축 1이 통째로 없다. 실측상 공식 CSV 486행 중 ``region``
  보유는 일부뿐이다.

그래서 출력의 ``verdict``는 ``confirm``이 아니라 ``no_contradiction``/``contradiction``/
``insufficient`` 셋이다. **"모순 없음"을 "확인됨"으로 읽지 않게** 하려는 것이다.

기본은 승인 5건만 본다. ``--all``이면 링크된 공식 curation 전체를 훑는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any, Final

import asyncpg

# 시도 약칭 → 시도코드. `h33_mislink_detect.py`와 같은 표를 쓴다.
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

# 관광 캠페인 대상으로 **정당한** category 대분류(앞 2자리).
#
# 처음에는 `01`(TOURISM)만 허용했는데 전수 실행에서 오탐이 나왔다 — `장태산자연휴양림`·
# `거창 항노화힐링랜드`는 `03030000 LODGING_RECREATION_FOREST`이고, 숙박을 갖춘 휴양림이
# 그렇게 분류되는 것은 **정당하다**. 대상이 관광지라는 것과 원천 provider가 그것을 숙박으로
# 등록하는 것은 모순이 아니다.
#
# 그래서 축을 뒤집었다 — "관광이어야 한다"가 아니라 **"명백히 대상일 수 없는 유형인가"** 를 본다.
_TOURISM_PLAUSIBLE_MAJOR: Final[frozenset[str]] = frozenset(
    {
        "01",  # TOURISM — 관광지 그 자체
        "03",  # LODGING — 휴양림·리조트형 관광지가 여기 온다
        "04",  # HOT_SPRING_SPA — 온천 관광지
    }
)

# 관광 캠페인 대상에 붙으면 **거의 확실히 잘못된 링크**인 대분류.
#
# 실측 근거(전수 222건): `태화강국가정원`·`반디랜드`·`김해가야테마파크`가 각각
# `06010000 TRANSPORT_PARKING`에 붙어 있다 — 관광지 이름으로 검색해 **그 관광지의 주차장**
# feature를 잡은 것으로 보인다. 이름도 좌표도 근처라 행정구역·이름 축으로는 전부 통과한다.
# `진해보타닉뮤지엄`은 `02020100 FOOD_CAFE_COFFEE`, `청풍호`는 `03050200 LODGING_PENSION_RURAL`.
#
# `03`은 위에서 허용하지만 `03050200`(농어촌펜션)만은 예외로 둔다 — 호수 자체가 펜션일 수 없다.
_TOURISM_IMPLAUSIBLE_MAJOR: Final[frozenset[str]] = frozenset(
    {
        "02",  # FOOD — 음식점/카페
        "05",  # CONVENIENCE
        "06",  # TRANSPORT — 주차장 등
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

_ROW_SQL: Final[str] = """
SELECT cc.collection_key,
       ci.external_item_id,
       ci.place_name,
       ci.feature_id,
       ci.metadata ->> 'region' AS region,
       ci.metadata ->> 'feature_match_confidence' AS declared_confidence,
       f.name AS feature_name,
       f.category AS feature_category,
       f.status AS feature_status,
       f.address ->> 'sido_code' AS feature_sido_code,
       f.address ->> 'sigungu_code' AS feature_sigungu_code,
       COALESCE(f.address ->> 'road', f.address ->> 'legal', '') AS feature_address
  FROM feature.curation_items ci
  JOIN feature.curation_collections cc ON cc.collection_id = ci.collection_id
  LEFT JOIN feature.features f ON f.feature_id = ci.feature_id
 WHERE ci.archived_at IS NULL
   AND cc.collection_key = $1
   AND ci.external_item_id = $2
"""

_ALL_SQL: Final[str] = """
SELECT cc.collection_key,
       ci.external_item_id,
       ci.place_name,
       ci.feature_id,
       ci.metadata ->> 'region' AS region,
       ci.metadata ->> 'feature_match_confidence' AS declared_confidence,
       f.name AS feature_name,
       f.category AS feature_category,
       f.status AS feature_status,
       f.address ->> 'sido_code' AS feature_sido_code,
       f.address ->> 'sigungu_code' AS feature_sigungu_code,
       COALESCE(f.address ->> 'road', f.address ->> 'legal', '') AS feature_address
  FROM feature.curation_items ci
  JOIN feature.curation_collections cc ON cc.collection_id = ci.collection_id
  JOIN feature.features f ON f.feature_id = ci.feature_id
 WHERE ci.archived_at IS NULL
   AND ci.feature_id IS NOT NULL
   AND cc.collection_key NOT LIKE 'legacy:%'
 ORDER BY cc.collection_key, ci.external_item_id
"""

_SAMENAME_SQL: Final[str] = """
SELECT count(*)
  FROM feature.features
 WHERE lower(name) = lower($1)
   AND deleted_at IS NULL
   AND status NOT IN ('deleted', 'hidden')
"""


def _campaign(collection_key: str) -> str:
    return collection_key.split(":", 1)[0]


def _judge(row: Any, same_name_count: int) -> dict[str, Any]:
    """세 축을 각각 평가한다. 축마다 ``pass``/``fail``/``n/a``를 따로 낸다."""
    axes: dict[str, str] = {}
    reasons: list[str] = []

    # 축 1 — 행정구역
    region = (row["region"] or "").strip()
    feature_sido = (row["feature_sido_code"] or "").strip()
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
            f"시도 불일치: curation region={region}({expected_sido}) vs feature sido={feature_sido}"
        )

    # 축 2 — 카테고리 정합성 (T-VN-H34 신규)
    #
    # "관광이어야 한다"가 아니라 **"명백히 대상일 수 없는 유형인가"** 를 본다.
    # 좁게 잡으면 휴양림 같은 정당한 분류가 오탐이 된다(위 상수 주석 참조).
    category = (row["feature_category"] or "").strip()
    is_tourism_campaign = _campaign(row["collection_key"]) in _TOURISM_CAMPAIGNS
    if not category or not is_tourism_campaign:
        axes["category"] = "n/a"
    elif category in _TOURISM_IMPLAUSIBLE_EXACT or category[:2] in _TOURISM_IMPLAUSIBLE_MAJOR:
        axes["category"] = "fail"
        reasons.append(
            f"카테고리가 관광 대상으로 성립하지 않는다: feature category={category}"
        )
    elif category[:2] in _TOURISM_PLAUSIBLE_MAJOR:
        axes["category"] = "pass"
    else:
        axes["category"] = "n/a"

    # 축 3 — 동명 유일성.
    #
    # **이 축은 확증 전용이고 반증에는 쓰지 않는다.** 동명 feature가 여럿이라는 것은
    # "링크가 틀렸다"는 증거가 아니라 *이 축으로 확정할 수 없다*는 뜻이다. 처음에는 이걸
    # `fail`로 두고 모순으로 셌는데, 그러면 전수 222건 중 30건이 모순으로 잡히고 그중
    # 20건이 이 축 단독이었다 — 링크가 멀쩡한데 "모순"으로 보고하는 것이라 잘못이다.
    # 반증 축은 region·category 둘뿐이다.
    if same_name_count == 1:
        axes["name_unique"] = "pass"
    elif same_name_count == 0:
        axes["name_unique"] = "n/a"
        reasons.append("이름이 일치하는 feature가 없다(이름이 변형됐거나 feature가 사라졌다)")
    else:
        axes["name_unique"] = "n/a"
        reasons.append(
            f"같은 이름 feature가 {same_name_count}건이라 이름 축으로는 확정할 수 없다"
            " (반증은 아니다)"
        )

    # 반증 축(region·category)에서만 모순을 판정한다.
    if any(axes.get(axis) == "fail" for axis in ("region", "category")):
        verdict = "contradiction"
    elif all(v == "n/a" for v in axes.values()):
        verdict = "insufficient"
    else:
        # 어떤 반증 축도 모순되지 않았다는 뜻일 뿐 **확인됨이 아니다**.
        verdict = "no_contradiction"

    return {"axes": axes, "verdict": verdict, "reasons": reasons}


async def run(conn: Any, *, check_all: bool) -> list[dict[str, Any]]:
    rows: list[Any]
    if check_all:
        rows = list(await conn.fetch(_ALL_SQL))
    else:
        rows = []
        for collection_key, item_key, _component in _APPROVED:
            rows.extend(await conn.fetch(_ROW_SQL, collection_key, item_key))

    results: list[dict[str, Any]] = []
    for row in rows:
        if row["feature_id"] is None:
            results.append(
                {
                    "collection_key": row["collection_key"],
                    "external_item_id": row["external_item_id"],
                    "place_name": row["place_name"],
                    "feature_id": None,
                    "verdict": "unlinked",
                    "axes": {},
                    "reasons": ["curation item이 feature에 링크돼 있지 않다"],
                }
            )
            continue
        same = await conn.fetchval(_SAMENAME_SQL, row["place_name"])
        judged = _judge(row, same)
        results.append(
            {
                "collection_key": row["collection_key"],
                "external_item_id": row["external_item_id"],
                "place_name": row["place_name"],
                "feature_id": row["feature_id"],
                "feature_name": row["feature_name"],
                "feature_category": row["feature_category"],
                "feature_address": row["feature_address"],
                "region": row["region"],
                "declared_confidence": row["declared_confidence"],
                "same_name_features": same,
                **judged,
            }
        )
    return results


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="승인 5건이 아니라 링크된 공식 curation 전체를 검증한다",
    )
    parser.add_argument("--json", type=str, default="", help="결과 JSON 출력 경로")
    args = parser.parse_args()

    dsn = os.environ["DSN"].replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        results = await run(conn, check_all=args.all)
    finally:
        await conn.close()

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    print(f"검증 대상 {len(results)}건")
    for verdict, n in sorted(counts.items()):
        print(f"  {verdict:<18} {n}")
    print()
    for r in results:
        mark = "  " if r["verdict"] == "no_contradiction" else "* "
        print(f"{mark}{r['collection_key']} / {r['external_item_id']}  {r['place_name']}")
        print(f"    verdict={r['verdict']}  axes={r.get('axes')}")
        if r.get("feature_id"):
            print(
                f"    feature={r['feature_id']} [{r.get('feature_category')}] "
                f"{r.get('feature_address', '')[:52]}"
            )
        for reason in r["reasons"]:
            print(f"    - {reason}")

    print(
        "\n주의: no_contradiction은 **확인됨이 아니다** — 어떤 축도 모순되지 않았다는 뜻이다.\n"
        "같은 시군구 안의 다른 대상은 이 도구로 구분되지 않는다(청풍호 vs 청풍호반케이블카)."
    )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:  # noqa: ASYNC230  # 1회성 증거 산출
            json.dump(results, handle, ensure_ascii=False, indent=1)
        print(f"\nJSON: {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
