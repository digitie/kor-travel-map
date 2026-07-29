# 공식 curation 미연결 reference 증거 (T-VN-H25A)

- 일시: 2026-07-29
- 대상 DB: prod `krtour_map` (`select current_database()`로 확인, feature 1,030,508)
- **읽기 전용** — CSV·DB를 바꾸지 않았다.
- 재생성: `scripts/h25a_reference_baseline.py`(존재 여부) · `scripts/h25a_decisive.py`(lifecycle·범위 정합)
  · `scripts/h25a_unlinked_manifest.py`(후보 manifest)

> **1차 초안 정정** — 이 리포트의 첫 판은 적대 리뷰 2건에서 여러 근거가 무효로 판정돼 다시 썼다.
> 무엇이 왜 틀렸는지는 §6에 남긴다. 아래 §1~§5는 정정 후 근거만 담는다.

## 1. task 전제는 재현되지 않는다

전제(`docs/tasks.md` T-VN-H25): *"공식 CSV의 고유 `feature_id` 158개 중 54개가 현재
`feature.features`에 존재하지 않았다."*

| 확인 항목 | 결과 |
| --- | --- |
| CSV 고유 `feature_id` | 158 |
| prod에 존재 | **158** |
| `status` 분포 | `active` 158 (전부) |
| curation이 링크 가능한(usable) 건수 | **158** — `deleted`/`hidden`/soft-delete 0건 |
| `created_at` 범위 | **2026-06-29 ~ 2026-07-03** |

`created_at`이 전부 **7월 3일 이전**이므로 "전제 측정 이후에 새로 적재돼서 지금은 보이는 것"이라는
양립 가설도 배제된다. 158개는 측정 시점에도 이미 존재했다.

**중요**: usable 판정은 curation 코드 경로와 같은 술어를 쓴다 —
`curation_repo.py`의 item create/patch/commit은 `status NOT IN ('deleted','hidden')`을 요구한다.
1차 초안은 이 필터 없이 "존재"만 봤는데, merge로 밀려난 loser는 soft-delete되어 그 질의를
통과하면서도 curation 대상으로는 부재다 — 즉 "stale"의 정의 그 자체였다. 위 표는 좁은 술어로 다시 잰 값이다.

## 2. NULL 261건은 cascade로 지워진 링크가 아니다

`feature.curation_items.feature_id`는 **`ON DELETE SET NULL`**이다. 따라서 "dangling 0건"은
발견이 아니라 FK 정의의 재진술이고, `feature_id IS NULL`만으로는 *애초에 미연결*과
*cascade로 지워진 링크*를 구분할 수 없다. 1차 초안은 이를 구분하지 않고 전자로 단정했다.

lifecycle 축을 실제로 조회해 판별했다.

| 확인 | 결과 | 의미 |
| --- | --- | --- |
| `ops.feature_merge_history` 총 행 | **0** | merge가 한 번도 기록된 적 없다 |
| 158개 중 merge loser 이력 | **0** | 밀려난 Feature 없음 |
| NULL 261건 중 `source_record_key` 보유 | **0** | 지워진 링크가 남길 provenance 흔적 없음 |

세 축 모두 음성이므로 261건은 **미연결이 맞다**. (1차 초안의 결론과 같지만, 이번에는 근거가 있다.)

## 3. 269 vs 261 — 같은 모집단이며, DB가 8건 앞서 있다

공식 collection으로 범위를 좁혀 재측정했다(1차 초안은 전 collection 합계를 CSV와 나란히 놓아
비교 불가능한 수치를 병치했다).

| | linked | unresolved | 합 |
| --- | --- | --- | --- |
| CSV 486행 | 217 | 269 | 486 |
| DB(공식 collection 한정) | **225** | **261** | 486 |

collection별 총계가 CSV 파일별 행수와 정확히 일치한다(72 / 110 / 114 / …). 즉 **같은 모집단**이고,
차이는 **DB에서는 링크됐지만 CSV에는 비어 있는 8건**이다. 이 8건은 H25B에서 CSV로 역반영할
대상이다 — 현재 문서 어디에도 기록돼 있지 않다.

## 4. 미연결 261건의 분포 — 등대가 지배적이다

| collection | unresolved |
| --- | --- |
| lighthouse-stamp-tour (6 시즌 합) | **103** |
| korean-tourism-100 2023-2024 | 58 |
| korean-tourism-100 2025-2026 | 54 |
| arboretum-garden-stamp-tour | 28 |
| heritage-visit-campaign (10 route 합) | 18 |

등대 6개 시즌은 **105개 중 2개만 링크**됐다. 1차 초안은 미연결을 수목원/krforest 적재 범위로
설명했으나, 등대 103건은 krforest와 무관하며 ADR-034 9단계 provider 순서에 등대를 공급하는
provider가 없다. 미연결의 지배적 원인은 **등대 데이터 공급원 부재**다.

## 5. 후보 등급은 CSV 자체 판정과 대조해야 한다

`resources/curations/manifest.json`은 이미 파일별 `linked_rows`/`unresolved_rows`를 선언하고 있고
(합계 217/269), 각 행의 `metadata_json.feature_match_confidence`에 **운영 DB 대조로 만든 사전
판정**이 들어 있다.

| 출처 | review | unmatched |
| --- | --- | --- |
| CSV `metadata_json` (기존, 운영 DB 대조) | **183** | 86 |
| 1차 초안의 자체 matcher | 15 | 191 |

**168행 차이가 이 데이터셋에서 가장 강한 신호**이며, 자체 matcher가 훨씬 약하다는 뜻이다.
1차 초안은 이 필드를 읽지 않고 자체 수치를 근거로 H25B 재정의를 제안했다 — 무효다.
자체 matcher의 알려진 결함은 §6에 정리했다.

## 6. 1차 초안에서 무효로 판정된 근거 (재발 방지용 기록)

| 무효 근거 | 왜 틀렸나 |
| --- | --- |
| "dangling 0건 → 애초에 미연결" | `ON DELETE SET NULL`이라 dangling은 구조적으로 불가능. FK 정의의 재진술이었다 |
| lifecycle/merge 대조했다 | `feature.feature_merges` / `feature.source_links`는 **존재하지 않는 테이블**(실제는 `ops.feature_merge_history` / `provider_sync.source_links`). 예외를 삼켰고, 게다가 **빈 배열**에 바인딩돼 어떤 결과도 낼 수 없었다 |
| "자동 승인 가능 high 0건" | `high` 조건이 `address_hint` 일치를 요구하는데 이 열은 **486행 전부 비어 있다**. 도달 불가 분기였고, 0은 데이터가 아니라 채점 함수의 성질이었다 |
| "전제가 인용한 바로 그 clone에서도 0" | clone 신원 미확인. 기록상 T-VN-47 clone은 1,030,469이고 삭제됐다. 사용한 clone(1,030,487)은 **prod에서 다시 뜬 것**일 가능성이 크다. 본 정정판은 prod 단일 DB만 근거로 쓴다 |
| "baf40a04 이전 CSV로도 158/158 → CSV 변경 배제" | 두 리비전의 `feature_id` **집합이 동일**하다. 재실행은 결과가 보장된 공허한 대조였다 |
| "미연결 269 vs DB 261" | 전 collection 합계와 공식 CSV를 병치한 비교 불가 수치. §3에서 범위를 좁혀 해소 |
| "none 191건은 실제 부재" | matcher가 괄호·`&` 복합명·포함 방향·`status='active'` 한정에서 실패한다. 269건 중 최소 89건이 이 형태다 |

교훈은 T-VN-H28과 같다 — **결론을 내기 전에 그 근거가 독립적으로 유도된 값과 대조되는지,
그리고 그 조건이 애초에 만족 가능한지를 먼저 확인한다.**

## 7. H25B로 넘기는 것

1. **stale reference 해소는 대상이 없다.** 전제를 정정해야 한다(§1·§2).
2. **CSV 역반영 8건** — DB에서 링크됐으나 CSV가 비어 있는 항목(§3). 즉시 실행 가능한 유일한
   확정 작업이다.
3. **매칭 재실행** — CSV의 `feature_match_confidence`(review 183 / unmatched 86)를 기준선으로
   삼고, 괄호·복합명·포함 방향·status 범위를 고친 matcher로 대조해 **차이를 설명**한다.
   자체 수치를 기준으로 삼지 않는다.
4. **등대 공급원 부재**(§4, 103건)는 curation 매칭이 아니라 provider 적재 범위 문제다. 별도 task.
