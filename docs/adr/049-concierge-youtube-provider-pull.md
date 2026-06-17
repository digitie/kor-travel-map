# ADR-049: TripMate-agent YouTube 장소 후보는 `kor-travel-concierge-youtube` provider로 pull한다

### 상태

Accepted (2026-06-10), provider identity/name은 ADR-053으로 superseded

### 배경

TripMate-agent는 YouTube 여행 콘텐츠에서 장소 후보, 영상·채널·플레이리스트 근거,
외부 geocoding evidence를 만든다. 그러나 kor-travel-map feature schema와 `feature_id`
생성 책임은 `kor-travel-map`에 있다. TripMate-agent가 kor-travel-map DB나
`FeatureBundle` schema에 직접 쓰면 ADR-045의 독립 프로그램 경계와 owner 책임이 흐려진다.

### 결정

- canonical provider name은 `kor-travel-concierge-youtube`로 둔다.
- dataset_key는 `youtube_place_candidates`, source_entity_type은
  `extracted_place_candidate`를 기본값으로 둔다.
- TripMate-agent는 snapshot/changes REST export를 제공한다. 외부 호출이므로
  TripMate-agent ADR-24의 `X-API-Key` 인증을 그대로 사용한다.
  (경로는 ADR-050에서 `/api/v1/features/{snapshot,changes}`로 보정 — downstream
  이름을 path에 넣지 않는다.)
- kor-travel-map Dagster는 이 export를 HTTP로 pull하고, `providers.kor_travel_concierge`의
  순수 변환 함수가 export item JSON을 `FeatureBundle`로 바꾼다.
- 최종 `feature_id`, `SourceRecord.source_record_key`, `SourceLink` 생성과 PostGIS
  적재는 kor-travel-map 책임이다.
- `operation=upsert`만 즉시 `FeatureBundle`로 적재한다. `reject`/`tombstone`은
  적재형 bundle로 표현하지 않고 export ledger/cursor 영속화 후속에서 별도 상태 전이로
  처리한다.

### 근거

- TripMate-agent는 외부 app provider이고, kor-travel-map은 feature owner다.
- full snapshot과 incremental changes를 모두 pull할 수 있어 재동기화와 운영 효율을
  분리할 수 있다.
- provider wrapper/adapter 금지(ADR-006)를 지키기 위해 kor-travel-map에는 client facade가
  아니라 fetcher resource와 순수 변환 함수만 둔다.

### 결과

- `core.providers.CANONICAL_PROVIDER_NAMES`에 `kor-travel-concierge-youtube`를 추가한다.
- Dagster resource는 `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL`과
  `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY`를 사용한다. API key 값은 TripMate-agent 운영
  `API_KEYS` 중 하나여야 한다.
- 실제 TripMate-agent export API 구현(T-066)이 배포되기 전까지 kor-travel-map live smoke는
  fake response/계약 테스트로 제한된다.
