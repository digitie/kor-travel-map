# ADR-121 — MCST 테마 목록은 독립 Feature가 아니라 장소 속성이다

- 상태: **accepted** (2026-11-10 제안, 같은 날 소유자 결정 D1~D3으로 accepted — Map #1468 항목 A).
  설계 정본은 [`docs/architecture/place-theme-attributes.md`](../architecture/place-theme-attributes.md).
  구현은 R1(migration·붙임 엔진)·R3(API) → R2 운영 dry-run 보고 → 소유자 확인 → R4 전환 순서다.
- 관련: ADR-009(자연키 `::`), ADR-012(공간 술어), ADR-048 #11(`feature_id` 값 불변),
  ADR-067(공개 projection), ADR-092(큐레이션 membership·후보 분리), ADR-098(UUID
  feature_id), ADR-111·115(쓰기 gate·잠금 순서), ADR-116(geo 재사용)

## 컨텍스트

`providers/mcst.py`는 MCST 파일데이터 13개 목록의 행마다 place Feature를 만든다. 식별
seed에 `source_type = "python-mcst-api:mcst_<slug>"`가 들어가고(`mcst.py:709-715`), 운영
식별 앵커 `provider_feature_identities`도 `(provider_dataset_id, kind, natural_key)`라
**같은 장소가 목록마다 다른 Feature가 된다.** 2026-11-10 중복 조사(#1468): 무장애↔가족/영유아
8,036, 박물관 표준↔MCST 반려동물 769(박물관 표준의 73%), 서울 서점↔MCST 서점 목록.
반려동물·무장애·가족 목록은 "이 장소는 반려동물 동반 가능"이라는 **사실(속성)**의
목록이지 장소 디렉터리가 아니다. 그런데도 Feature가 되어 지도에 같은 장소 marker가 여럿
겹치고, 검색은 같은 장소를 여러 번 돌려주며, 속성으로 거를 방법은 없다.

## 결정

1. **13개 목록을 세 갈래로 나눈다.**
   - *속성 목록*(반려동물 동반·무장애·가족/영유아, 서점 유형·세계음식은 장소 목록이면서
     속성도 낸다): 행은 장소의 속성 관측이다. 맞는 master Feature(MOIS·박물관 표준·TourAPI
     등)가 있으면 **속성으로 붙고** 독립 Feature를 만들지 않는다.
   - *master가 없는 행*(소유자 결정 D1 = b): 목록과 무관한 **MCST 장소 Feature 하나**가 된다.
     여러 목록의 같은 장소는 그 Feature 하나에 모이고 속성만 늘어난다. 나중에 master가 생기면
     그 master로 병합된다.
   - *촬영지*(소유자 결정 D3): 속성이 아니다. 행은 장소로 붙거나 MCST 장소 Feature가 되고,
     "영상 촬영지"라는 사실은 기존 **큐레이션** `media-places` 테마의 후보 → 운영자 승격 →
     collection 공개로만 드러난다(ADR-092 자동 공개 승격 금지 그대로).
   - *반려 업종 행*(소유자 결정 D2): 반려동물 목록의 동물약국·반려동물용품·동물병원·미용·
     위탁관리(약 20,396)는 **적재하지 않는다**(장소도 속성도 아님). 이 행으로 이미 만들어진
     운영 Feature는 R4 퇴역 계획에 들어간다.
2. **속성은 별도 상태를 두지 않고 source link에서 유도한다.** 속성 = 그 Feature에 걸린
   `primary`/`enrichment` source link의 (dataset, entity 유형)이 속성 catalog에 묶여 있는가. 새
   표는 catalog 두 개(`feature.place_attributes`, `feature.dataset_place_attributes`)와
   붙임 판정 기록뿐이다. Feature 행에 tags 배열을 복제하지 않는다 — merge·link 이동·퇴역이 이미
   link를 다루므로 속성은 따라온다.
3. **붙임은 적재 시점의 결정적 규칙(`theme-attach-v1`)이다.** 거리(`coord_5179` 열끼리,
   입력 점은 한 번만 변환) + 정규화 이름 유사도 + 목록별 분류 호환. 2위와 점수 차가 작으면
   `ambiguous`로 보류한다. 같은 장소의 여러 MCST 목록 행이 한 Feature로 모이는 것도 이 규칙
   (tier 2 후보)이 한다. dedup 병합 큐를 거치지 않는다.
4. **병합 경로 보강**(리뷰 필수): `apply_feature_merge`는 master에 이미 primary가 있으면 옮겨
   오는 primary link를 enrichment로 강등한다. snapshot 부재 퇴역 SQL은 다른 primary가 남은
   Feature를 퇴역시키지 않는다. 병합으로 퇴역한 Feature를 가리키는 식별 claim은 병합 이력을
   따라 **생존자로** 이어진다(붙임 엔진에서; 퇴역 Feature를 되살리거나 재claim하지 않는다).
5. **공개 API**: 목록·검색·in-bounds·nearby에 반복 `attribute` 필터(AND), 상세에
   `attributes[]`, 요약에 `attribute_codes[]`, 공개 catalog `GET /v1/place-attributes`.
   검색 cursor는 version을 올리지 않고 필터가 있을 때만 fingerprint에 넣는다. 이름 검색(`q`)은
   속성어를 해석하지 않는다. service batch trip card는 바꾸지 않는다.
6. **기존 MCST Feature 전환**은 dry-run 계획표(R2) → 소유자 확인 → dataset별 실행(R4)이다.
   붙는 행은 master로 병합, MCST끼리 중복은 생존자 하나로 병합, 남는 Feature는 `feature_id`를
   그대로 둔다. 반려 업종 Feature는 퇴역한다. 퇴역마다 PinVi 참조 정리(M05 `rebind`/`detach`)
   사건을 남긴다. 퇴역 id는 재사용하지 않고 redirect·alias shim은 만들지 않는다(ADR-092 §4).
7. **모드**: 붙임 엔진은 `off`(현행 적재)·`dry_run`(현행 적재 + 판정만 기록·보고)·`apply`(새
   경로) 세 모드이고 기본 `off`다. `apply`는 R4 전환과 같은 운영 창에서만 켠다 — 전환 전에
   켜면 옛 목록별 Feature와 새 경로가 섞인다.

## 근거

- 한 물리 장소에 Feature 하나라는 불변식을 원천 목록 개수와 무관하게 지킨다.
- 속성을 link에서 유도하면 정본이 하나다. tags 배열·payload 복제는 merge/퇴역/재적재마다
  동기화해야 하고 어긋남을 검사하는 장치가 또 필요해진다.
- 2026-11-10 실측에서 속성 목록 행의 비MCST master 일치율은 4~13%다(업종 master 미적재). D1-b는
  이 공백을 데이터 손실로 바꾸지 않고, master가 생기면 수렴한다.
- 촬영지는 장소의 지속 속성이라기보다 편집 가치가 있는 묶음이라 큐레이션이 맞다. 큐레이션은
  공개에 운영자 승인을 요구한다.
- 공개 계약 변경은 필드·필터 추가뿐이며 기존 `feature_id` 값은 바꾸지 않는다(ADR-048 #11).

## 결과

- (+) 겹친 marker·중복 검색 결과가 사라지고 "반려동물 동반"·"무장애" 같은 필터가 생긴다.
- (+) 박물관·관광지 master가 MCST 속성을 얻는다(박물관 표준↔반려동물 769 등).
- (−) 반려 업종 약 2만 건과 병합 패자가 퇴역한다 — PinVi 참조는 M05 사건으로 정리되며,
  소비자가 꺼져 있으면 기존처럼 `retired` + snapshot 대체로 보인다.
- (−) 촬영지는 운영자가 승격·공개하기 전까지 "촬영지"로 드러나지 않는다(장소 자체는 보인다).
- (−) OpenAPI(user·admin) 변경 → Map API PR 머지 뒤 PinVi 재vendor 머지가 회전보다 먼저다.
- (−) 붙임 품질은 임계값에 달렸다 — dry-run 표본 정밀도 측정이 R4의 전제다.

## 후속

설계 문서 §10 rollout. #1468 C 담당은 MCST 관련 쌍 규칙을 범위에서 뺐다(2026-11-10, 리뷰 큐만).
