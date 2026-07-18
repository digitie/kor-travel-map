# ADR-065: POI target mutation causal receipt와 ETag 조건부 삭제

- 상태: accepted
- 날짜: 2026-07-18
- 결정자: human, Codex

## 컨텍스트

`dataset_projection`은 여러 원본 table mutation이 공유하는 global revision topic이다. C7 live E2E가
POI target write 시각 이후 증가한 임의 revision을 원인 증거로 인정하면, socket 재연결 snapshot이나
동시 운영자 write만으로 테스트가 통과할 수 있다. 또한 자연키로 GET해 UUID와 body를 확인한 뒤 같은
자연키로 DELETE하면 두 요청 사이 다른 actor가 delete/recreate한 새 target을 지울 수 있다.

## 결정

POI target PUT/DELETE는 source transaction 안에서 statement trigger 실행 뒤
`ops.ops_live_topic_revisions`의 `dataset_projection` revision을 읽어
`meta.dataset_projection_revision`으로 반환한다. GET/PUT은 target UUID를 strong ETag로 반환한다.
DELETE는 `If-Match`를 필수화하고 natural key와 expected target UUID를 같은 UPDATE predicate에
결박한다. mismatch는 삭제 없이 `412`, active target 부재는 `404`다.

## 근거

- mutation receipt와 WebSocket update revision의 exact equality가 있어야 source write와 UI 갱신의
  인과를 기계적으로 증명할 수 있다.
- `If-Match`는 HTTP 표준 조건부 mutation이며 별도 custom ownership header보다 의미가 명확하다.
- 기존 topic revision trigger와 immutable target UUID가 이미 필요한 clock/version을 제공하므로 새
  DB column이나 credential/schema를 추가할 이유가 없다.

## 결과(긍정)

- concurrent global revision과 reconnect snapshot이 C7 causal assertion을 대신 통과하지 못한다.
- 소유권 확인 뒤 target이 재생성돼도 새 UUID는 삭제되지 않는다.
- admin UI와 자동화가 같은 ETag/If-Match 계약으로 안전하게 soft-delete한다.

## 결과(부정)

- 모든 DELETE caller는 먼저 받은 ETag를 전달해야 한다.
- proxy와 생성 OpenAPI/type이 `If-Match`, ETag, mutation revision을 보존해야 한다.

## 후속

- C7 live E2E는 같은 기존 socket의 `dataset_projection` update frame만 허용하고 mutation receipt
  revision과 exact equality를 단언한다.
