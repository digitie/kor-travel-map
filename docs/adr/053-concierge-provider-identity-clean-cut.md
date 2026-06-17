# ADR-053: `kor-travel-concierge` provider identity를 clean cut한다

### 상태

Accepted (2026-06-12) — ADR-049/050의 provider 명칭 설명을 supersede한다.
export 경로(`/api/v1/features/{snapshot|changes}`), cursor/envelope,
검수 통과만 export, `reject`/`tombstone` → inactive 라이프사이클은 ADR-050을 유지한다.
본 ADR의 `kor-travel-concierge` 코드/provider/env 이름은
후속 clean cut 전 현재 구현값을 가리킨다.

### 배경

`kor-travel-concierge`는 본 레포가 YouTube/AI 후보 export를 provider로 정규화·적재하는
대상이며, canonical 이름은 `kor-travel-concierge`다. 로컬 체크아웃 경로는
`F:\dev\kor-travel-concierge`다. provider canonical name(`kor-travel-concierge-youtube`)과
env/module 이름 전환은 별도 코드 clean cut에서 처리한다.

### 결정

- canonical provider name은 `kor-travel-concierge-youtube`다. 구
  `kor-travel-concierge-youtube` alias나 호환 shim은 만들지 않는다.
- Python 변환 모듈은 `kortravelmap.providers.kor_travel_concierge`, 주 변환 함수는
  `kor_travel_concierge_items_to_bundles`, inactive helper는
  `kor_travel_concierge_inactive_entity_ids`다.
- Dagster resource/asset/schedule 이름은 `kor_travel_concierge_youtube_features`,
  `feature_place_kor_travel_concierge_youtube`,
  `feature_place_kor_travel_concierge_youtube_daily_schedule`로 둔다.
- kor-travel-map 설정/env는 `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_*`를 사용한다. 구
  `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_*`는 읽지 않는다.
- export item의 provider 기본값은 `kor-travel-concierge-youtube`, dataset_key는 기존
  `youtube_place_candidates`, source_entity_type은 기존
  `extracted_place_candidate`를 유지한다.
- Feature detail 원본 payload key는 `detail.payload.kor_travel_concierge`로 저장한다.
  출처 UX가 읽는 평면 key는 계속 `detail.facility_info`를 우선한다.
- YouTube 후보는 kor-travel-map feature로 정규화된 뒤 외부 경계인 kor-travel-map
  OpenAPI를 통해서만 외부 소비자에 도달한다.

### 근거

- provider identity를 외부 소비자 이름에 묶어 두면 직접 관계가 있는 것처럼
  오해된다.
- clean cut을 택해야 provider canonical name, feature_id/source_record 자연키,
  Dagster resource, env 이름이 영구 호환 매핑 없이 같은 어휘를 공유한다(ADR-046).
- 실운영 데이터 적재 전 변경이므로 구 provider name 데이터는 재적재로 정리하는 편이
  장기 유지비가 낮다.

### 결과

- 기존 개발 DB에 `kor-travel-concierge-youtube` feature가 있으면 삭제 후
  `kor-travel-concierge-youtube` snapshot을 다시 적재한다. provider name이
  `feature_id`/source 자연키에 들어가므로 자동 rename migration은 만들지 않는다.
- T-224에서 코드/문서 clean cut을 수행하고, T-212e closure 재검증(T-225)에서 새
  provider/env 이름 기준 실데이터 pull 여부를 다시 확인한다.
