"""T-VN-H33 — 오링크 해제가 공개 표면에 반영됐는지 **반증 가능하게** 확인한다. 읽기 전용.

초안 확인 스크립트는 `/v1/curations/features/{feature_id}`만 호출하고 "노출 0건"을 보고했다.
**그 측정은 반증 불가능했다**(적대 리뷰 지적). 이 엔드포인트는 curation이 하나도 없으면
200에 빈 배열이 아니라 **404**를 낸다(`get_feature_curation_group`가 None → 라우터가 404).
초안은 `curl -s`로 status를 버리고 에러 본문을 파싱해 `data`가 없으니 "0건"을 출력했다 —
**존재하지도 않는 feature_id를 넣어도 바이트 단위로 같은 출력이 나온다.** 오타·삭제·401·500이
전부 "성공적으로 해소됨"으로 읽혔다.

그래서 여기서는 세 가지를 지킨다.

1. **HTTP status를 버리지 않는다.** 404와 "200 + 0건"을 구분해 출력한다.
2. **negative control**을 넣는다 — 존재하지 않는 id도 같이 호출해, 대상 feature의 응답이
   그것과 *구별되는지* 보여준다. 구별되지 않으면 그 축은 증거로 쓸 수 없다.
3. **반증 가능한 표면을 함께 본다.** 컬렉션 상세(`/v1/curations/collections/{id}`)는 item이
   살아 있으면 200으로 그 item을 돌려주므로, "item은 그대로 있고 feature 링크만 끊겼다"를
   *양성 대조와 함께* 보일 수 있는 유일한 표면이다. 해제가 item을 지운 게 아님도 여기서 확인된다.

`/v1/curations/*`는 익명 공개가 아니라 `RoutePolicy.PUBLIC_KEYED`다 — public API key(또는
service token) 보유자에게 열린 표면이라는 뜻이다. "공개 노출"은 그 한정 아래 읽어야 한다.

[T-VN-32C 값 전환 주의 — legacy-표기 고정] 이 스크립트의 prod f_* 하드코딩과
응답 feature_id 대조 로직은 값 전환(PR-2) 이전 표면 기준이다. 재실행 시 응답의
feature_id는 UUID 정본이므로 대조 로직을 재작성해야 한다(일회성 스크립트 —
기록 보존용으로만 유지).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("API_BASE", "http://127.0.0.1:12701")

TARGET_FEATURES = {
    "f_1114010100_p_a11c2e739c5676d2": "남이섬(서울 중구 사무소 — 오링크 대상)",
    "f_4683025328_p_a45038d401d8d1bd": "청남대(전남 영암 — 오링크 대상)",
}
# negative control. 이 id의 응답과 위 응답이 구별되지 않으면 이 축은 증거가 못 된다.
BOGUS_FEATURE = "f_0000000000_p_ffffffffffffffff"

TARGET_ITEMS = {
    "korean-tourism-100:2023-2024": {
        ("kt100-2023-2024-025", "primary"),
    },
    "korean-tourism-100:2025-2026": {
        ("kt100-2025-2026-024", "primary"),
        ("kt100-2025-2026-036", "primary"),
    },
}


def get(path: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"X-Kor-Travel-Map-Service-Token": os.environ["SERVICE_TOKEN"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            try:
                return resp.status, json.loads(resp.read().decode())
            except json.JSONDecodeError:
                return resp.status, {}
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode())
        except Exception:  # noqa: BLE001
            return exc.code, {}


def main() -> int:
    failures: list[str] = []

    print("=== 1. feature별 curation 조회 (반증 가능성 점검) ===")
    status_bogus, _ = get(f"/v1/curations/features/{BOGUS_FEATURE}")
    print(f"  negative control (없는 id): HTTP {status_bogus}")
    if status_bogus != 404:
        failures.append(f"negative control: HTTP {status_bogus}, expected 404")
    for fid, label in TARGET_FEATURES.items():
        status, body = get(f"/v1/curations/features/{fid}")
        raw_group = body.get("data")
        group = raw_group if isinstance(raw_group, dict) else {}
        curations = group.get("curations")
        n = len(curations) if isinstance(curations, list) else 0
        print(f"  {label}: HTTP {status}, curation {n}건")
        if status not in {200, 404}:
            failures.append(f"{fid}: unexpected HTTP {status}")
        elif status == status_bogus and status != 200:
            print(
                "    ⚠ 없는 id와 같은 status다 — 이 축만으로는 '해소됨'을 주장할 수 없다."
                " 아래 컬렉션 표면을 근거로 쓴다."
            )
        elif status == 200:
            if not isinstance(raw_group, dict) or not isinstance(curations, list):
                failures.append(f"{fid}: 200 응답 body shape가 올바르지 않다")
            elif n:
                failures.append(f"{fid}: 아직 curation {n}건이 붙어 있다")

    print("\n=== 2. 컬렉션 상세 (반증 가능한 표면) ===")
    status, body = get("/v1/curations/collections?page_size=500")
    if status != 200:
        failures.append(f"컬렉션 목록: unexpected HTTP {status}")
    data = body.get("data") or []
    if isinstance(data, dict):
        data = data.get("collections") or data.get("items") or []
    if not isinstance(data, list):
        failures.append("컬렉션 목록: 200 응답 body shape가 올바르지 않다")
        data = []
    by_key = {
        c["collection_key"]: c
        for c in data
        if isinstance(c, dict) and isinstance(c.get("collection_key"), str)
    }

    for key, item_identities in TARGET_ITEMS.items():
        col = by_key.get(key)
        if col is None:
            failures.append(f"{key}: 공개 컬렉션 목록에 없다")
            continue
        st, detail = get(f"/v1/curations/collections/{col['collection_id']}")
        raw_detail = detail.get("data")
        detail_data = raw_detail if isinstance(raw_detail, dict) else {}
        items = detail_data.get("items") or []
        print(f"  {key}: HTTP {st}, item {len(items)}건 (item_count={col.get('item_count')})")
        if st != 200:
            failures.append(f"{key}: 상세 unexpected HTTP {st}")
            continue
        if not isinstance(raw_detail, dict) or not isinstance(items, list):
            failures.append(f"{key}: 상세 200 응답 body shape가 올바르지 않다")
            continue
        if not items:
            failures.append(f"{key}: 상세 positive control item이 비어 있다")
            continue
        found = {
            (item["external_item_id"], item["external_component_id"])
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("external_item_id"), str)
            and isinstance(item.get("external_component_id"), str)
        } & item_identities
        missing = item_identities - found
        if missing:
            # item이 사라졌다면 해제가 아니라 삭제를 한 것이다 — 그건 실패다.
            failures.append(
                f"{key}: item/component가 응답에서 사라졌다 {sorted(missing)}"
            )
        for item in items:
            if not isinstance(item, dict):
                failures.append(f"{key}: 상세 item shape가 올바르지 않다")
                continue
            item_key = item.get("external_item_id")
            component_key = item.get("external_component_id")
            identity = (item_key, component_key)
            if identity not in item_identities:
                continue
            if "feature_id" not in item:
                failures.append(
                    f"{item_key}/{component_key}: feature_id 필드가 없다"
                )
                continue
            fid = item["feature_id"]
            if fid is not None and not isinstance(fid, str):
                failures.append(
                    f"{item_key}/{component_key}: feature_id 타입이 올바르지 않다"
                )
                continue
            mark = "링크 없음(기대)" if fid is None else f"★ 아직 링크됨 {fid}"
            print(
                f"    {item_key}/{component_key} "
                f"{item.get('place_name')}: {mark}"
            )
            if fid is not None:
                failures.append(
                    f"{item_key}/{component_key}: 아직 {fid}에 링크됨"
                )

    print("\n=== 3. 이름 검색에 오링크 feature가 남아 있는가 ===")
    for q, fid in (("남이섬", "f_1114010100_p_a11c2e739c5676d2"),):
        st, body = get(f"/v1/curations?q={urllib.parse.quote(q)}")
        groups = body.get("data") or []
        if isinstance(groups, dict):
            groups = groups.get("groups") or groups.get("items") or []
        if not isinstance(groups, list):
            failures.append(f"q={q}: 200 응답 body shape가 올바르지 않다")
            groups = []
        valid_groups = [
            group
            for group in groups
            if isinstance(group, dict)
            and isinstance(group.get("feature"), dict)
            and isinstance(group["feature"].get("feature_id"), str)
        ]
        if len(valid_groups) != len(groups):
            failures.append(f"q={q}: group shape가 올바르지 않다")
        ids = {group["feature"]["feature_id"] for group in valid_groups}
        # 양성 대조: q 검색이 결과를 내놓긴 하는지 먼저 확인한다.
        print(f"  q={q}: HTTP {st}, group {len(valid_groups)}건 (양성 대조)")
        if st != 200:
            failures.append(f"q={q}: unexpected HTTP {st}")
            continue
        if not valid_groups:
            failures.append(f"q={q}: positive control 결과가 비어 있다")
            continue
        if fid in ids:
            failures.append(f"q={q} 결과에 오링크 feature {fid}가 아직 있다")

    print()
    if failures:
        for f in failures:
            print(f"★ 실패: {f}")
        return 1
    print("모두 기대대로: item은 공개 응답에 남아 있고 feature 링크만 끊겼다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
