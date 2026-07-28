# #673 `provider_address_mismatch` 실데이터 재기준화 (T-VN-H28A)

- 일시: 2026-07-29
- 실행: n150, `kor-travel-map-t176-ci:latest` + live `kor-travel-concierge`(12601) + live `kor-travel-geo`(12501)
- 경로: **운영과 동일한 코드** — live export → `kor_travel_concierge_items_to_bundles`(실 geo reverse
  주입) → `validate_feature_bundles_address`. 근사 재현이 아니다.
- 원본 manifest(380행, 비커밋): n150 `/home/digitie/h28a/h28a-final.json`
  (장소명·좌표 등 concierge 업무 데이터라 저장소에 넣지 않는다. 재생성 스크립트는 본 문서 §5.)

## 1. 재기준화 결과

이슈 등록 시점(2026-07-14) 수치와 현재를 나란히 둔다.

| 항목 | 2026-07-14 (#673) | 2026-07-29 (본 실측) |
| --- | --- | --- |
| upsert 후보 | 1,430 | **1,477** |
| `provider_address_mismatch` (error·drop) | 410 | **380** |
| `provider_address_partial_match` (warning) | 709 | **701** |
| 적재 | 1,020 | 1,097 |

현상은 **여전히 유효**하다. 후보 집합이 늘고 drop이 소폭 줄었을 뿐 성격은 같다.

## 2. 핵심 발견 — drop 380건은 **전부** 오탐이다

drop된 380건 각각에 대해 세 축을 독립적으로 확보해 대조했다.

1. provider payload의 authoritative 행정코드 (producer T-189이 주입)
2. 좌표를 **다시** reverse 지오코딩한 결과의 행정코드·이름·거리·후보집합
3. 현재 규칙(geo `sigungu_name`이 provider 주소 문자열의 부분문자열인가)의 판정

| 분류 | 건수 |
| --- | --- |
| `false_positive_code_same` — payload 시군구코드 == geo 시군구코드 | **380** |
| `true_positive_code_diff` — 좌표가 실제로 다른 행정구역 | **0** |

- **380/380이 payload에 `sigungu_code`와 `legal_dong_code`를 모두 보유**하고 있으며, 그 코드가
  좌표 reverse 결과와 **한 건도 빠짐없이 일치**한다.
- 후보 집합 전체(1,477건)로 넓혀도 payload 코드와 geo 코드가 **불일치하는 건은 0건**이다
  (일치 1,424 / 코드 없음 53).
- reverse 최근접 거리: `<10m` 210건, `<100m` 136건, `<1km` 34건. 좌표가 엉뚱한 곳을 가리키는
  것이 아니다.

즉 이 규칙은 현재 실데이터에서 **탐지력이 0인 채로 380건을 영구 파괴**하고 있다.

## 3. 규칙이 실제로 재고 있는 것

이름 substring 실패를 유형별로 분류했다.

| 건수 | 유형 | 예 |
| --- | --- | --- |
| 365 | 행정구역명이 없는 **짧은 주소** | `부산 기장 조방국밥` / `부산 광안리` (geo=기장군·수영구) |
| 9 | **접미사 차이** | `부산 기장 해동용궁사` vs `기장군` |
| 5 | 문자열에 **다른 시군구명**이 있음 | `서울 서대문구 통일로 251` vs geo=종로구 (payload 코드도 종로구) |
| 1 | 기타 | `대한민국 전라북도 전북` vs `정읍시` |

압도적 다수(365/380)가 **provider 주소 문자열의 완전성 부족**이다. 마케팅형 짧은 표기
(`부산 기장 해동용궁사`)를 "좌표-주소 불일치"로 분류하고 있는 것이지, 좌표가 틀린 것이 아니다.

5건짜리 "다른 시군구명" 유형조차 오탐이다 — `서울 서대문구 통일로 251`은 payload 코드가
`11110`(종로구)이고 geo도 `11110`이다. **주소 문자열 쪽이 틀렸고 코드 쪽이 맞다.**

## 4. 구조적 원인

`providers/kor_travel_concierge.py::_address`가 두 출처를 **병합**한다.

```
sigungu_code = payload 코드  or  geo 코드  or  bjd에서 유도   ← payload 우선
sigungu_name = geo 이름만                                    ← geo 전용
```

병합 결과 `Address` 하나에 **provider 권위 코드**와 **geo 유도 이름**이 나란히 담기고, 두 축의
독립성이 사라진다. `validation.py::_provider_address_match_issues`는 남은 유일한 "독립" 쌍인
*geo 이름 ↔ provider 주소 문자열*을 비교하는데, 이것이 가능한 조합 중 **가장 약한 신호**다.
권위 있는 대조 축(코드)은 같은 객체 안에 있는데도 쓰이지 않는다.

## 5. 재현

```bash
# n150. concierge/geo 키는 컨테이너 env에서 읽으며 출력하지 않는다.
scp h28a_final.py n150:/home/digitie/
# scratchpad h28a_final.py — live export → 실 파이프라인 → 분류
```

`h28a_final.py`는 export 전량을 페이징 수집하고, 운영과 같은 변환·검증을 돌린 뒤 error 후보만
독립 reverse로 재확인해 위 표를 만든다.

## 6. T-VN-H28B로 넘기는 결론

1. 현재 규칙의 severity를 `error`(영구 drop)로 두는 것은 **근거가 없다** — 실측 탐지력 0.
2. 대체 규칙은 payload 행정코드와 좌표 reverse 코드를 **코드 대 코드**로 비교해야 한다.
   그러려면 두 축이 병합되기 전에 독립적으로 보존돼야 한다(§4).
3. 380/380이 payload 코드를 갖고 있으므로 코드 기반 규칙의 적용률은 이 provider에서 100%다.
4. 불확실한 건은 영구 drop이 아니라 관측 가능한 상태로 남겨야 한다 — 지금은 run metadata에만
   남아 run이 사라지면 증거도 사라진다.
