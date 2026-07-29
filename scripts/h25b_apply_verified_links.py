"""T-VN-H25B — 검증을 통과한 링크만 공식 CSV에 역반영한다.

DB에 링크가 있다는 사실만으로 승인하지 않는다. 정지오코딩으로 독립 확인한 결과
8건 중 3건이 오링크였다(남이섬 → 서울 중구 사무소, 청남대 → 전남 영암).
그 3건은 반영하지 않고 별도로 보고한다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import TypeAlias

DEFAULT_CSV_DIR = Path("resources/curations")

ApprovalKey: TypeAlias = tuple[str, str, str]

# DB active identity와 같은 (collection, item, component) -> feature_id.
APPROVED: dict[ApprovalKey, str] = {
    (
        "arboretum-garden-stamp-tour:2026",
        "arboretum-2026-001",
        "primary",
    ): "f_global_p_2eddbdc1ef5a0c00",
    (
        "arboretum-garden-stamp-tour:2026",
        "arboretum-2026-063",
        "primary",
    ): "f_4812914500_p_f0e7b045758b269a",
    (
        "korean-tourism-100:2023-2024",
        "kt100-2023-2024-036",
        "primary",
    ): "f_global_p_2eddbdc1ef5a0c00",
    (
        "korean-tourism-100:2025-2026",
        "kt100-2025-2026-035",
        "primary",
    ): "f_global_p_2eddbdc1ef5a0c00",
    (
        "korean-tourism-100:2025-2026",
        "kt100-2025-2026-040",
        "primary",
    ): "f_4315032041_p_12c53fe662dafc4f",
}

# key -> (confidence, reason).
#
# **5건 모두 `backfilled-db-review`다 — `verified`는 하나도 없다.** 가장 강한 근거를 가진
# 청풍호조차 정지오코딩이 시군구(제천 43150)까지만 지목해, 같은 시군구의 다른 대상
# (청풍호반케이블카 등)과 구분되지 않는다. 나머지 4건은 정지오코딩 후보 자체가 없어
# **"모순이 없음"에 그친다** — 확정이 아니다.
#
# 개별 근거의 강도 차이는 `reason` 문장에 남긴다. 등급을 나누면 `verified`가 "확인됨"으로
# 읽혀 실제보다 강한 주장이 되므로, 지금 데이터로 도달 가능한 최고 등급인 review로 통일한다.
EVIDENCE: dict[ApprovalKey, tuple[str, str]] = {
    (
        "arboretum-garden-stamp-tour:2026",
        "arboretum-2026-001",
        "primary",
    ): (
        "backfilled-db-review",
        "DB curation_items 링크를 역반영. 정지오코딩 후보가 없어 이름 정합만 확인했다 "
        "— 이 CSV에는 region 값이 없어 독립 축이 없다 (T-VN-H25B).",
    ),
    (
        "arboretum-garden-stamp-tour:2026",
        "arboretum-2026-063",
        "primary",
    ): (
        "backfilled-db-review",
        "DB curation_items 링크를 역반영. 정지오코딩 후보가 없어 이름 정합만 확인했다 "
        "— 이 CSV에는 region 값이 없어 독립 축이 없다 (T-VN-H25B).",
    ),
    (
        "korean-tourism-100:2023-2024",
        "kt100-2023-2024-036",
        "primary",
    ): (
        "backfilled-db-review",
        "DB curation_items 링크를 역반영. 정지오코딩 후보가 없어 이름·region(세종) 정합만 "
        "확인했다 — 좌표 대조로 확정한 것이 아니다 (T-VN-H25B).",
    ),
    (
        "korean-tourism-100:2025-2026",
        "kt100-2025-2026-035",
        "primary",
    ): (
        "backfilled-db-review",
        "DB curation_items 링크를 역반영. 정지오코딩 후보가 없어 이름·region(세종) 정합만 "
        "확인했다 — 좌표 대조로 확정한 것이 아니다 (T-VN-H25B).",
    ),
    (
        "korean-tourism-100:2025-2026",
        "kt100-2025-2026-040",
        "primary",
    ): (
        "backfilled-db-review",
        "DB curation_items 링크를 역반영. 정지오코딩이 충북 제천(43150)을 지목해 feature "
        "sigungu_code와 일치했으나, 같은 시군구의 다른 대상(청풍호반케이블카 등)과는 이 축으로 "
        "구분되지 않는다 — 확정이 아니다 (T-VN-H25B).",
    ),
}

# 반영하지 않는다 — 정지오코딩 결과 DB 링크가 다른 지역을 가리킨다.
REJECTED: dict[str, str] = {
    "kt100-2023-2024-025": "남이섬 → 서울 중구(11140). 정지오코딩은 강원 춘천(51110)",
    "kt100-2025-2026-024": "남이섬 → 서울 중구(11140). 정지오코딩은 강원 춘천(51110)",
    "kt100-2025-2026-036": "청남대 → 전남 영암(46830). 정지오코딩은 충북 청주(43111)",
}


def _identity(row: dict[str, str | None]) -> ApprovalKey:
    return (
        (row.get("collection_key") or "").strip(),
        (row.get("source_item_key") or "").strip(),
        (row.get("source_component_key") or "").strip(),
    )


def apply_verified_links(target: Path) -> int:
    """승인 identity 전체를 먼저 검증한 뒤 CSV와 manifest를 갱신한다."""

    datasets: list[
        tuple[Path, list[str], list[dict[str, str | None]]]
    ] = []
    occurrences: Counter[ApprovalKey] = Counter()
    errors: list[str] = []

    # 검증 단계에는 파일을 쓰지 않는다. 잘못된 기존 링크·중복·누락이 하나라도 있으면
    # manifest를 다시 서명하기 전에 전체를 fail-closed한다.
    for path in sorted(target.glob("*.csv")):
        if path.name == "template.csv":
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            rows = list(reader)
        datasets.append((path, fields, rows))

        for row in rows:
            key = _identity(row)
            if key not in APPROVED:
                continue
            occurrences[key] += 1
            current_feature_id = (row.get("feature_id") or "").strip()
            expected_feature_id = APPROVED[key]
            if current_feature_id and current_feature_id != expected_feature_id:
                errors.append(
                    f"{path.name}: {key!r} feature_id={current_feature_id!r}, "
                    f"expected={expected_feature_id!r}"
                )

    for key in APPROVED:
        count = occurrences[key]
        if count != 1:
            errors.append(f"승인 identity {key!r} 출현 {count}건 (정확히 1건이어야 함)")
    if errors:
        raise RuntimeError("승인 CSV identity 검증 실패:\n- " + "\n- ".join(errors))

    total = 0
    for path, fields, rows in datasets:
        changed = 0
        for row in rows:
            key = _identity(row)
            if key not in APPROVED:
                continue
            expected_feature_id = APPROVED[key]
            current_feature_id = (row.get("feature_id") or "").strip()
            if current_feature_id != expected_feature_id:
                row["feature_id"] = expected_feature_id
                changed += 1

            # metadata도 **같은 스크립트에서** 갱신한다. feature_id만 채우고 metadata를
            # 딴 데서 고치면 커밋된 파일을 이 스크립트로 재현할 수 없고, manifest sha256도
            # 유도 불가능해진다(H25A에서 지적받은 "산출물 ≠ 도구 출력" 결함).
            meta = json.loads(row.get("metadata_json") or "{}")
            conf, reason = EVIDENCE[key]
            meta["feature_match_status"] = "linked"
            meta["feature_match_confidence"] = conf
            meta["feature_match_reasons"] = [reason]
            expected_metadata = json.dumps(meta, ensure_ascii=False)
            if row.get("metadata_json") != expected_metadata:
                row["metadata_json"] = expected_metadata
                changed += 1
        if not changed:
            continue

        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"  {path.name}: {changed}행 역반영")
        total += changed

    refresh_manifest(target)
    return total


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV_DIR
    total = apply_verified_links(target)
    print(f"\n반영 {total}행 / 보류 {len(REJECTED)}행")
    for key, why in REJECTED.items():
        print(f"  보류 {key}: {why}")


def refresh_manifest(target: Path) -> None:
    """`manifest.json`의 sha256/rows를 실제 파일에서 다시 계산한다.

    `tests/unit/test_curation_resources.py`가 manifest의 sha256과 파일 실물을 대조한다.
    manifest를 손으로 유지하면 CSV·README를 고칠 때마다 어긋나는데, 실제로 어긋났다 —
    README를 고치고 sha256을 안 고쳐 게이트가 빨간불이 났다. 그러니 **파생시킨다**.

    manifest는 README.md처럼 CSV가 아닌 파일도 추적하므로 `rows`는 CSV에만 다시 센다.
    재현성 점검은 CSV만 임시 디렉터리에 풀어 돌리므로, manifest가 없으면 조용히 건너뛴다.
    """
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    touched = []
    for entry in manifest.get("files", []):
        path = target / entry["path"]
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = entry.get("rows")
        if path.suffix == ".csv" and rows is not None:
            with path.open(encoding="utf-8-sig", newline="") as fh:
                rows = sum(1 for _ in csv.DictReader(fh))
        if digest != entry["sha256"] or rows != entry.get("rows"):
            entry["sha256"] = digest
            if entry.get("rows") is not None:
                entry["rows"] = rows
            touched.append(entry["path"])

    if touched:
        # 개행을 LF로 고정한다. `write_text`는 Windows에서 CRLF로 번역해 같은 스크립트가
        # 플랫폼마다 다른 바이트를 내놓는다 — CSV writer에 `lineterminator="\n"`을 준 것과
        # 같은 이유다.
        with manifest_path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"manifest 갱신: {', '.join(touched)}")


if __name__ == "__main__":
    main()
