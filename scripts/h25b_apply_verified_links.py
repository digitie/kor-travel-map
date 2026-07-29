"""T-VN-H25B — 검증을 통과한 링크만 공식 CSV에 역반영한다.

DB에 링크가 있다는 사실만으로 승인하지 않는다. 정지오코딩으로 독립 확인한 결과
8건 중 3건이 오링크였다(남이섬 → 서울 중구 사무소, 청남대 → 전남 영암).
그 3건은 반영하지 않고 별도로 보고한다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

CSV_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "resources/curations")

# (source_item_key) -> feature_id. 정지오코딩으로 지역 정합을 확인한 것만 넣는다.
APPROVED: dict[str, str] = {
    "arboretum-2026-001": "f_global_p_2eddbdc1ef5a0c00",  # 국립세종수목원 (세종 36110)
    "arboretum-2026-063": "f_4812914500_p_f0e7b045758b269a",  # 진해보타닉뮤지엄 (창원 진해 48129)
    "kt100-2023-2024-036": "f_global_p_2eddbdc1ef5a0c00",  # 국립세종수목원
    "kt100-2025-2026-035": "f_global_p_2eddbdc1ef5a0c00",  # 국립세종수목원
    "kt100-2025-2026-040": "f_4315032041_p_12c53fe662dafc4f",  # 청풍호 (제천 43150)
}

# 반영하지 않는다 — 정지오코딩 결과 DB 링크가 다른 지역을 가리킨다.
REJECTED: dict[str, str] = {
    "kt100-2023-2024-025": "남이섬 → 서울 중구(11140). 정지오코딩은 강원 춘천(51110)",
    "kt100-2025-2026-024": "남이섬 → 서울 중구(11140). 정지오코딩은 강원 춘천(51110)",
    "kt100-2025-2026-036": "청남대 → 전남 영암(46830). 정지오코딩은 충북 청주(43111)",
}


def main() -> None:
    total = 0
    for path in sorted(CSV_DIR.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            rows = list(reader)

        changed = 0
        for r in rows:
            key = (r.get("source_item_key") or "").strip()
            if key in APPROVED and not (r.get("feature_id") or "").strip():
                r["feature_id"] = APPROVED[key]
                changed += 1
        if not changed:
            continue

        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"  {path.name}: {changed}행 역반영")
        total += changed

    print(f"\n반영 {total}행 / 보류 {len(REJECTED)}행")
    for key, why in REJECTED.items():
        print(f"  보류 {key}: {why}")


if __name__ == "__main__":
    main()
