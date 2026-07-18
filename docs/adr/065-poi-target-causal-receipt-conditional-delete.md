# ADR-065: POI target mutation causal receipt와 ETag 조건부 삭제

- 상태: accepted
- 날짜: 2026-07-18
- 결정자: human, Codex

## 컨텍스트

`dataset_projection`은 여러 원본 table mutation이 공유하는 global revision topic이다. C7 live E2E가
POI target write 시각 이후 증가한 임의 revision을 원인 증거로 인정하면, socket 재연결 snapshot이나
동시 운영자 write만으로 테스트가 통과할 수 있다. 또한 자연키로 GET해 UUID와 body를 확인한 뒤 같은
자연키로 DELETE하면 두 요청 사이 다른 actor가 PUT으로 같은 UUID를 갱신하거나
delete/recreate한 새 target을 지울 수 있다. UUID만으로는 같은 row의 갱신을 구분하지 못한다.

## 결정

POI target PUT/DELETE는 source transaction 안에서 statement trigger 실행 뒤
`ops.ops_live_topic_revisions`의 `dataset_projection` revision을 읽어
`meta.dataset_projection_revision`으로 반환한다. Alembic 0058은 target에
`lock_version BIGINT NOT NULL DEFAULT 1 CHECK (lock_version >= 1)`을 추가하고 모든 UPDATE의
BEFORE trigger가 `OLD.lock_version + 1`을 강제한다. server canonical strong ETag는
`"{lowercase-canonical-uuid}:{positive-version}"`이며 단건·목록 body의 `entity_tag`와
GET/PUT/DELETE 응답 header가 octet-exact하게 같다.

DELETE는 `If-Match`를 필수화한다. active natural key를 `FOR UPDATE`로 잠근 뒤 UUID와 version을
비교하고, 일치할 때만 natural key+UUID+version predicate UPDATE를 실행한다. 첫 조회가 없으면
READ COMMITTED의 새 statement에서 한 번 더 잠금 조회해 concurrent recreate는 `412`, 실제 부재는
`404`로 구분한다. header 누락은 `428`, weak/wildcard/쉼표 결합 multiple/물리적 duplicate
line/noncanonical UUID 대소문자·0 또는 비정규 version·malformed 값은 `422`, UUID/version
mismatch는 `412`다.

executor link snapshot 교체는 대상 UUID를 정렬하고 모든 active parent를 먼저 `FOR KEY SHARE`로
잠근 뒤에만 link 비활성화/upsert를 실행한다. link도 `target_id, feature_id` 순서로 처리한다. parent
DELETE의 `FOR UPDATE`와 직렬화되며, delete가 먼저 끝난 inactive parent는 전체 link 갱신에서 빠진다.
두 경로의 잠금 순서는 항상 parent → link다.

## 근거

- topic poll은 여러 commit을 한 update frame으로 합칠 수 있다. 따라서 mutation 전에 이미 열린 같은
  socket의 `dataset_projection` **update** frame에서 `data.live_revision >= receipt`를 확인해야 한다.
  reconnect socket의 snapshot과 top-level fingerprint `revision`은 causal 증거가 아니다.
- `If-Match`는 HTTP 표준 조건부 mutation이며 별도 custom ownership header보다 의미가 명확하다.
- UUID는 row identity일 뿐 entity version이 아니다. server-owned BIGINT와 trigger가 모든 writer를
  포괄하므로 client가 version을 건너뛰거나 같은 UUID의 최신 PUT을 stale DELETE로 지울 수 없다.

## 결과(긍정)

- coalesced concurrent revision은 허용하면서 reconnect snapshot과 fingerprint가 C7 causal assertion을
  대신 통과하지 못한다.
- 확인 뒤 target이 PUT 또는 재생성돼도 stale ETag는 최신 target을 삭제하지 않는다.
- link reactivation과 soft-delete가 직렬화되어 삭제 완료 후 active link가 남지 않는다.
- admin UI와 자동화가 같은 ETag/If-Match 계약으로 안전하게 soft-delete한다.
- admin UI는 선택 객체를 복제해 보관하지 않고 target UUID로 최신 list row를 파생한다. `412`는
  list/nearby/dataset/pipeline projection을 모두 refetch하고 그동안 삭제 조작을 막으므로 다음 DELETE가
  새 opaque tag를 쓴다.

## 결과(부정)

- 모든 DELETE caller는 목록/단건 body의 `entity_tag`를 합성하지 않고 그대로 전달해야 한다.
- proxy와 생성 OpenAPI/type이 `If-Match`, ETag, mutation revision을 보존해야 한다.
- UPDATE마다 BIGINT version과 dataset projection revision이 증가해 쓰기 비용이 소폭 늘어난다.

## 후속

- C7 live E2E는 create PUT 전에 연 socket을 navigation 없이 유지한다. create PUT, update PUT,
  DELETE 각각 mutation 직전 frame cursor 이후의 `dataset_projection` update만 허용하고
  `data.live_revision >= mutation receipt`를 단언한다. snapshot과 top-level fingerprint revision은
  비교하지 않는다. DELETE는 update PUT 응답의 최신 `entity_tag`를 그대로 보내며 fresh GET으로
  대체하지 않는다.
