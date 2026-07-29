# 공식 curation 링크 역반영 + 오링크 3건 (T-VN-H25B)

- 일시: 2026-07-29
- 대상: prod `krtour_map` (읽기 전용) + 공식 CSV 5종
- 재생성: `scripts/h25b_backfill_candidates.py`(후보 특정) ·
  `scripts/h25b_apply_verified_links.py`(승인분만 반영)

## 1. 배경

T-VN-H25A가 집계로 확인한 차이 — CSV `linked 217` vs DB `linked 225` — 를 항목 단위로 짚었다.
component 행이 `source_item_key`를 공유하므로 단건 조인 대신
`(collection_key, source_item_key)` 묶음의 **feature_id 집합**을 비교했다.

결과 **DB에만 있는 링크 8행**(고유 feature 6개), **CSV에만 있는 링크 0행**.

## 2. H25A의 권고는 틀렸다 — 8건 중 3건이 오링크다

H25A는 이 8건을 *"어느 문서에도 없던 확정 대상"*, *"즉시 실행 가능한 유일한 확정 작업"*이라고
적었다. **DB에 링크가 있다는 사실을 승인 근거로 삼은 것**이 오류였다.

각 대상 feature의 실제 주소·행정코드를 확인하고, 장소명을 **정지오코딩**해 독립적으로 대조했다.

| 장소 | 정지오코딩 (권위) | DB feature 위치 | 판정 |
| --- | --- | --- | --- |
| 청남대 | 충북 청주시 상당구 `43111` | 전남 영암군 `46830` | **오링크** |
| 남이섬 | 강원 춘천시 `51110` | 서울 중구 `11140` | **오링크** |
| 청풍호 | 충북 제천시 `43150` | 제천시 `43150` | 일치 |
| 국립세종수목원 | (정지오코딩 후보 없음) | 세종 `36110` | 이름·시도 정합 |
| 진해보타닉뮤지엄 | (정지오코딩 후보 없음) | 창원 진해구 `48129` | 이름·지역 정합 |

- **남이섬**(2행) — DB feature 주소가 `서울특별시 중구 남대문로9길 52 (무교동,101호(지상1층))`.
  관광지가 아니라 서울사무소로 보인다. 정지오코딩은 `강원특별자치도 춘천시 남이섬길`.
- **청남대**(1행) — DB feature 주소가 `전라남도 영암군 삼호읍 난전로 45`.
  정지오코딩은 `충청북도 청주시 상당구 청남대길`. 이름만 같은 다른 대상이다.

이름 일치로 링크된 전형적인 오탐이며, **좌표 근접이나 이름 일치만으로 승인하지 말라**는
task 요구가 실제로 값을 한 지점이다.

## 3. 반영한 것 / 보류한 것

**반영 5행** (`feature_id` 열만 변경):

| CSV | source_item_key | feature_id |
| --- | --- | --- |
| arboretum-garden-stamp-tour-2026 | `arboretum-2026-001` | 국립세종수목원 |
| arboretum-garden-stamp-tour-2026 | `arboretum-2026-063` | 진해보타닉뮤지엄 |
| korean-tourism-100-2023-2024 | `kt100-2023-2024-036` | 국립세종수목원 |
| korean-tourism-100-2025-2026 | `kt100-2025-2026-035` | 국립세종수목원 |
| korean-tourism-100-2025-2026 | `kt100-2025-2026-040` | 청풍호 |

**보류 3행** — 위 오링크. CSV는 미연결 상태를 유지한다(H24가 무손실 보존).

집계: CSV `linked 217 → 222` / `unresolved 269 → 264`. `manifest.json`의 파일별 수치와
`sha256`을 함께 갱신했다.

## 4. DB 쪽 오링크는 남아 있다

보류한 3행에 대응하는 **`feature.curation_items` 행은 여전히 잘못된 feature를 가리킨다**
(`status=included`, archived 아님). 즉 `/admin/curations` 계열 화면과 공개 projection은
남이섬 자리에 서울 중구 사무소를, 청남대 자리에 전남 영암 시설을 노출하고 있을 수 있다.

본 task는 CSV 정본만 다루므로 DB mutation은 하지 않았다. 별도 task로 분리한다 —
`T-VN-H33`.

## 5. 남은 것

H25A에서 인수한 매칭 재실행(기준선 `feature_match_confidence` review 183 / unmatched 86 대조,
괄호·`&` 복합명·포함 방향·`status` 범위 결함 수정, `metadata_json.region` 축, provider
provenance 조인, manifest JSON 커밋)은 아직이다. 위 3건이 보여주듯 **자동 승인은 금지**이며
후보 제시까지만 한다.
