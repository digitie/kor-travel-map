# ADR-121 — MCST 테마 목록은 독립 Feature가 아니라 장소 속성이다

- 상태: proposed (2026-11-10, Map #1468 항목 A — 소유자 묶음 승인). 설계 정본은
  [`docs/architecture/place-theme-attributes.md`](../architecture/place-theme-attributes.md).
  구현·운영 dry-run 실측·전환 뒤 accepted로 올린다.
- 관련: ADR-009(자연키 `::`), ADR-012(공간 술어), ADR-048 #11(`feature_id` 값 불변),
  ADR-067(공개 projection), ADR-092(큐레이션 membership·후보 분리), ADR-098(UUID
  feature_id), ADR-111·115(쓰기 gate·잠금 순서), ADR-116(geo 재사용)

## 컨텍스트

`providers/mcst.py`는 MCST 파일데이터 13개 목록의 행마다 place Feature를 만든다. 식별
seed에 `source_type = "python-mcst-api:mcst_<slug>"`가 들어가고(`mcst.py:709-715`), 운영
식별 앵커 `provider_feature_identities`도 `(provider_dataset_id, kind, natural_key)`라
**같은 장소가 목록마다 다른 Feature가 된다.** 2026-11-10 중복 조사(#1468): 무장애↔가족/영유아
8,036, 박물관 표준↔MCST 반려동물 769(박물관 표준의 73%), 서울 서점↔MCST 서점 목록.
반려동물·무장애·가족·촬영지 목록은 "이 장소는 반려동물 동반 가능"이라는 **사실(속성)**의
목록이지 장소 디렉터리가 아니다. 그런데도 Feature가 되어 지도에 같은 장소 marker가 여럿
겹치고, 검색은 같은 장소를 여러 번 돌려주며, 속성으로 거를 방법은 없다.

## 결정

1. **13개 목록을 두 갈래로 나눈다.**
   - *속성 목록*(반려동물·무장애·가족/영유아·촬영지): 행은 장소의 속성 관측이다. 맞는
     master Feature(MOIS·박물관 표준·TourAPI 등)에 **속성으로 붙고** 독립 Feature를 만들지
     않는다.
   - *장소 목록*(서점 4종·세계음식·레저활동·레저강습·캠핑·골프): 행은 장소다. master가
     있으면 붙고, 없을 때만 MCST Feature가 된다. 그 Feature의 식별은 **목록과 무관**하다
     (MCST 공용 식별 namespace + 정규화 `이름::주소`).
2. **속성은 별도 상태를 두지 않고 source link에서 유도한다.** 속성 = 그 Feature에 걸린
   `primary`/`enrichment` source link의 dataset이 속성 catalog에 묶여 있는가. 새 표는
   catalog 두 개(`feature.place_attributes`, `provider_sync.dataset_place_attributes`)와
   붙임 판정 기록(`provider_sync.theme_attach_decisions`)뿐이다. Feature 행에 tags 배열을
   복제하지 않는다 — merge·link 이동·퇴역이 이미 link를 다루므로 속성은 따라온다.
   큐레이션(`curated_themes`·collection/item)은 재사용하지 않는다 — 운영자가 고르는 편집
   membership이고 ADR-092가 자동 승격을 금한다.
3. **붙임은 적재 시점의 결정적 규칙(`theme-attach-v1`)이다.** 거리(`coord_5179`
   열끼리, 입력 점은 staging에서 한 번만 변환) + 정규화 이름 유사도 + 목록별 분류 호환.
   2위와 점수 차가 작으면 `ambiguous`로 보류한다. 붙은 판정은 master가 살아 있고 행이
   의미 있게 바뀌지 않는 한 유지된다(sticky). MCST Feature로 남은 행은 매 MCST 적재마다 master를
   다시 찾고, 생기면 그 master로 병합된다. dedup 병합 큐를 거치지 않는다. 이 과정에서
   `apply_feature_merge`는 옮겨 오는 primary link를 enrichment로 강등하도록 바뀐다(master에
   primary 둘 금지).
4. **공개 API**: 목록·검색·in-bounds·nearby에 반복 `attribute` 필터(AND), 상세에
   `attributes[]`, 요약에 `attribute_codes[]`, 공개 catalog `GET /v1/place-attributes`.
   검색 cursor는 version을 올리지 않고 필터가 있을 때만 fingerprint에 넣는다. 이름 검색(`q`)은
   속성어를 해석하지 않는다.
5. **기존 MCST Feature 전환**은 dry-run 계획표 → 소유자 확인 → dataset별 실행 순서다.
   붙는 행은 master로 병합(link는 `enrichment`로 강등), MCST끼리 중복은 생존자 하나로
   병합, 남는 장소 목록 Feature는 `feature_id`를 **그대로 두고** 식별 앵커만 공용
   namespace로 옮긴다. 퇴역하는 Feature는 PinVi 참조 정리(M05 `rebind`/`detach`) 사건을
   남긴다. 퇴역 id는 재사용하지 않고 redirect·alias shim은 만들지 않는다(ADR-092 §4와 같음).
6. **속성 목록에서 비MCST master를 못 찾은 행의 처리는 소유자 결정이다**(설계 문서 §9 D1).
   2026-11-10 운영 실측에서 속성 목록 행의 비MCST master 일치율은 4~13%다(업종 master 미적재).
   권고는 "목록 무관 MCST 장소 하나로 남기고 master가 생기면 재판정이 병합"(D1-b), 대안은
   "공개 Feature 없이 보류"(D1-a, 근사로 공개 장소 약 2만 1천~2만 2천 개 감소 — R2 dry-run이
   v1 규칙으로 확정). 반려동물 목록의 반려 업종 행(약국·
   병원·용품·미용·위탁 20,396)은 장소 목록으로 다루고 `pet_friendly`를 붙이지 않는 것이 기본안이다(D2).

## 근거

- 한 물리 장소에 Feature 하나라는 불변식을 원천 목록 개수와 무관하게 지킨다.
- 속성을 link에서 유도하면 정본이 하나다. tags 배열·payload 복제는 merge/퇴역/재적재마다
  동기화해야 하고 어긋남을 검사하는 장치가 또 필요해진다.
- 적재 시점 붙임은 운영에서 0건 병합 상태인 dedup 큐(#1468 B)에 의존하지 않는다.
- 공개 계약 변경은 필드·필터 추가뿐이며 기존 `feature_id` 값은 바꾸지 않는다(ADR-048 #11).

## 결과

- (+) 겹친 marker·중복 검색 결과가 사라지고 "반려동물 동반"·"무장애" 같은 필터가 생긴다.
- (+) 박물관·관광지 master가 MCST 속성을 얻는다(박물관 표준↔반려동물 769 등).
- (−) 공개 Feature 수가 줄고 일부 MCST Feature가 퇴역한다 — PinVi 참조는 M05 사건으로
  정리되며, 소비자가 꺼져 있으면 기존처럼 `retired` + snapshot 대체로 보인다.
- (−) OpenAPI(user·admin) 변경 → PinVi 재vendor가 회전보다 먼저다.
- (−) 붙임 품질은 임계값에 달렸다 — dry-run 표본 정밀도 측정이 enforce의 전제다.

## 후속

설계 문서 §10 rollout(R1~R6). #1468 C의 MCST 관련 쌍 규칙(캠핑 MOIS↔MCST, 세계음식↔MOIS,
박물관 표준↔MCST)은 이 붙임 규칙이 대신하므로 C 담당과 범위를 맞춘다.
