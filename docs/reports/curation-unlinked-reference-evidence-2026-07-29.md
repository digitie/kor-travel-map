# 공식 curation 미연결 reference 증거 (T-VN-H25A)

- 일시: 2026-07-29
- 대상: prod `krtour_map`(1,030,508 features) + T-VN-47 격리 clone `kor_travel_map_clone`
  + 체크포인트 `ktm_checkpoint_7692354f865e7f9ed278f911` (각 1,030,487)
- **읽기 전용** — CSV·DB를 바꾸지 않았다(task 문구 준수).
- 원본 manifest(269 entries, 비커밋): n150 `/home/digitie/h25a/h25a-unlinked-manifest.json`
  재생성: `scripts/h25a_unlinked_manifest.py`

## 1. task 전제는 재현되지 않는다

`docs/tasks.md`의 T-VN-H25 전제:

> T-VN-47 격리 실데이터 clone에서 공식 CSV의 고유 `feature_id` 158개 중 54개가 현재
> `feature.features`에 존재하지 않았다.

**세 DB 모두에서 재현되지 않았다.**

| DB | 고유 feature_id | 존재 | 부재 |
| --- | --- | --- | --- |
| prod `krtour_map` | 158 | **158** (전부 `active`) | **0** |
| T-VN-47 clone | 158 | **158** | **0** |
| 체크포인트 | 158 | **158** | **0** |

전제가 인용한 **바로 그 clone에서도** 부재가 0이다. CSV 쪽 변경 가능성도 배제했다 —
`baf40a04`("separate curation component identity") **이전** 시점(`2d77ec31`)의 CSV로 다시
돌려도 158/158 존재였다. 즉 "54개 부재"는 현재 어떤 데이터셋으로도 재현되지 않는다.

DB 측 참조도 깨끗하다.

| 테이블 | 행 | dangling(feature 없음) | `feature_id` NULL |
| --- | --- | --- | --- |
| `feature.curated_features` | 3,044 | **0** | 0 |
| `feature.curation_items` | 3,530 | **0** | **261** |

## 2. 실제로 존재하는 문제 — stale reference가 아니라 **미매칭**

`dangling` 참조는 0건이고, 남아 있는 것은 **애초에 연결된 적 없는 항목**이다.

- 공식 CSV 486행 중 **269행이 `feature_id` 없음**
- DB `curation_items` 3,530행 중 **261행이 `feature_id` NULL** (H24가 무손실 보존 중인
  미연결 membership)

두 수치의 차(269 vs 261)는 CSV 행과 DB item의 집계 단위 차이로 보이며 H25B에서 확인 대상이다.

## 3. 미연결 269건의 후보 등급

이름 완전일치(공백 정규화 후)를 1차 축, `address_hint`를 보조 축으로 삼았다.
**좌표 근접만으로는 어떤 항목도 승인하지 않았다**(task 요구).

| 등급 | 건수 | 의미 |
| --- | --- | --- |
| `high` (자동 승인 가능) | **0** | 이름 완전일치 + 주소 단서 일치 |
| `review` | 15 | 이름은 완전일치하나 `address_hint`가 비어 확정 불가 |
| `low` | 63 | 이름 부분일치만 |
| `none` | 191 | 이름으로 active feature를 찾지 못함 |

**자동 승인 가능한 항목이 0건**이다. 미연결 CSV 행 269건 중 `address_hint`가 채워진 행이
없어 이름 일치를 교차 확인할 축이 없다. H25B의 "승인된 high-confidence만 반영"은 현재
**적용 대상이 없다**.

## 4. `none` 191건은 매칭 버그가 아니라 실제 부재다

처음에는 provider 미적재를 의심했다가, `수목원` 포함 active feature가 199개 있고
`python-krforest-api`가 385 entity를 적재한 것을 보고 **매칭 정규화 실패**로 판단했다.
공백 정규화를 넣어 다시 돌리니 191건으로 줄었을 뿐(199→191) 대부분 남았다.

개별 확인 결과 남은 것은 **실제 부재**다.

- `푸른수목원` / `홍천무궁화수목원` — DB에 없음
- DB의 199개 `수목원`은 `국립수목원`·`화명수목원`·`인천수목원`·`한밭수목원` 등 **다른 기관**

즉 krforest 계열이 부분적으로만 적재돼 있고, 공식 CSV가 지목하는 개별 수목원·정원 상당수가
아직 Feature로 존재하지 않는다. 이는 매칭 규칙으로 풀 문제가 아니라 **provider 적재 범위**
문제다.

## 5. H25B로 넘기는 결론

1. **stale reference 해소 작업은 필요 없다** — dangling 0건. task 제목과 전제를 정정해야 한다.
2. H25B의 원래 정의(승인된 high-confidence를 CSV `feature_id`에 반영)는 **대상이 0건**이라
   그대로는 수행할 것이 없다.
3. 실제로 가치 있는 후속은 둘로 갈린다.
   - `review` 15건: `address_hint`를 채우거나 다른 축(provider provenance·좌표)으로 확정하는
     **검토 절차**. 자동 승인은 금지.
   - `none` 191건: **provider 적재 범위 확대**(krforest 등)가 선행되어야 하며 curation
     매칭 작업으로는 해소되지 않는다.
4. 미연결 상태 자체는 H24가 무손실 보존하므로 **데이터 손실 위험은 없다**. 급히 mutation할
   이유가 없다.
