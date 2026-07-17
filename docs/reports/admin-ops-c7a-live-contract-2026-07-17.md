# admin ops C7A live 인증·무효화 계약

> 범위: `T-ADM-C7A`, 이슈 #685, ADR-064 보강
> 상태: 구현 기준 확정(2026-07-17)

## 1. 문제와 목표

브라우저는 REST를 same-origin Next.js BFF(`/api/proxy/*`)로 호출하지만 기존
`WS /v1/ops/live`는 FastAPI에 직접 연결했다. 이 경로는 admin session을 확인하지 않고
`accept()`부터 수행해 로그아웃 브라우저도 import job, update request, Dagster run
snapshot을 받을 수 있었다. 또한 기존 frontend live 훅은 transport 상태와 query-key
무효화를 한 파일에 섞고, 연결 실패를 `reconnecting` 하나로만 표시했다.

C7A는 다음 경계를 정본으로 만든다.

1. 로그인 session을 확인한 same-origin BFF만 짧은 수명의 live ticket을 발급한다.
2. FastAPI는 ticket 검증과 nonce 원자 소비가 끝나기 전에 어떤 운영 data도 보내지 않는다.
   서명·payload가 잘못된 ticket과 replay는 browser가 `4401`을 식별하도록
   data 없는 최소 handshake 직후 닫는다. 서명은 유효하지만 handshake 전 이미
   만료한 ticket은 data 0건 + `4408`로 구분한다.
3. transport와 도메인 무효화 라우팅을 분리하고, C4/C5 페이지는 adapter 계약으로 결선한다.
4. live 장애 중에도 화면별 TanStack Query polling이 계속 동작함을 명시적으로 표시한다.

## 2. 인증 handshake

```text
browser                 Next.js BFF                     FastAPI
   | POST /api/auth/live-ticket |                           |
   | cookie: httpOnly session   |                           |
   |--------------------------->| session+same-origin 검증  |
   |                            | HMAC ticket 발급           |
   |<---------------------------| protocol, expires_at       |
   | WS /v1/ops/live            |                           |
   | Sec-WebSocket-Protocol: ktm.ops-live.v1.<ticket>        |
   |------------------------------------------------------->|
   |                            HMAC 검증 + nonce 원자 소비  |
   |<-------------------------------------------------------|
   | hello -> subscribe ack -> snapshot -> update           |
```

- ticket payload는 `aud`, `v`, `sub`, `iat`, `exp`, `nonce`만 담는다. `sub`는 REST와
  같은 server-owned admin actor다.
- `nonce` 원문은 저장하지 않는다. SHA-256 hash를 전용
  `ops.ops_live_ticket_claims.nonce_hash` PK로 원자 insert해 한 번만 소비한다. 이 임시 보안
  상태는 로그인 감사 event와 분리하며 `expires_at` index와 claim당 최대 1,000건의 만료
  batch 정리로 retention을 유지한다. issuer·verifier·DB clock skew 경계에서 아직 유효한
  claim을 지우지 않도록 ticket 만료 뒤에도 60초 grace를 둔다. 같은 ticket의 순차·동시
  재사용은 snapshot을 보내기 전에 `4401`로 닫는다.
- 서명키는 양 서버가 공유하는 root 정본 `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` 하나다.
  launcher와 API container entrypoint는 앞뒤 공백이 없고 32자 이상인지 시작 전에
  검사한다. 원 secret은 응답, browser bundle, URL, query string에 들어가지 않는다.
- ticket은 발급 시각부터 60초인 연결 lease다. FastAPI는 claim의 DB connection pool 대기,
  snapshot 조회와 모든 frame 전송을 남은 lease로 제한한다. outer lease timeout이
  실제로 만료한 경우만 `4408`로 닫는다. DB driver·statement가 lease 내에
  독립적으로 발생시킨 `TimeoutError`와 기타 claim/snapshot 장애는 1초 상한 rollback 후
  1초 상한 `1013` close로 격리한다. claim helper는 자체 unbounded rollback을
  수행하지 않고 router의 공통 bounded 정리 경계에 일임한다. invalid/replay/만료/
  claim 장애의 handshake·close도 공통 bounded helper를 통해 data 0건을 보장한다.
  frame transport가 lease 내에 독립 `TimeoutError`를 발생시킨 경우도 `4408`로
  오인하지 않고 bounded `1013`으로 닫는다. send/receive의 `OSError`·`RuntimeError`도
  bounded rollback 후 `1013`으로 수렴하고 정상 disconnect는 조용히 종료한다.
  browser는 로그인 session으로 새 ticket을 받아 재연결한다. 따라서 logout event가
  유실돼도 만료 뒤 재발급이 `401`로 거절되어 연결이 무기한 남지 않는다.
- UI logout은 logout POST나 redirect보다 먼저 현재 탭 local event를 발행해 열린
  live client와 ticket 대기 상태를 즉시 종료한다. `BroadcastChannel` 생성·listener
  등록·`postMessage`·close 실패는 현재 탭 event와 logout redirect를 막지 않는
  best-effort 경계다.
- topic은 query string으로 받지 않고, browser가 연결 후 `replace` command의 JSON 문자열
  배열로 구독한다. frontend effect dependency도 sort·dedupe한 canonical JSON 배열이므로
  comma가 든 opaque Dagster run ID를 join/split하지 않는다. 지원 command는
  `subscribe`/`unsubscribe`/`replace`뿐이며 UI가 쓰지 않는 `ping`/`pong`과 그에 따른 강제
  snapshot 경로는 두지 않는다. `poll_interval_ms`만 query로
  유지하고 ticket은 WebSocket subprotocol에만 실린다.
- BFF는 `Origin`과 `Sec-Fetch-Site: same-origin`이 모두 있어야 session 검증으로
  진행한다. header 누락·불일치 `403`, session 없음 `401`, server secret 미설정 `503`으로
  fail-closed하며 응답에 `Cache-Control: no-store`를 붙인다.
- 유효하지 않은 ticket은 HTTP upgrade 거절로 browser에 불투명한 `1006`을 남기지
  않는다. 서버는 subprotocol data를 전혀 보내지 않는 최소 handshake 뒤 `4401`로 닫고,
  frontend는 이를 로그인 만료로 취급해 재시도를 중단한다.

## 3. transport 상태 모델

| 상태 | 의미 | 화면 동작 |
|---|---|---|
| `connecting` | 첫 ticket/handshake 진행 | 기존 query 데이터 유지 + REST polling |
| `live` | snapshot/update 또는 heartbeat 수신 | event 기반 무효화 |
| `reconnecting` | 일시 장애 후 1~2번째 backoff | polling 유지 |
| `polling` | 3회 이상 연속 실패, background 재연결 계속 | polling fallback임을 표시 |
| `unauthorized` | ticket BFF가 401/403 또는 WebSocket이 `4401` | live·polling 재시도 중단, 로그인 필요 표시 |
| `unavailable` | browser WebSocket 미지원 | polling 전용 |
| `disabled` | topic 없음 또는 kill-switch | 기존 polling 정책 유지 |

backoff는 `1s, 2s, 5s, 10s, 30s` 상한이며 `hello`와 `subscribed` ack는 handshake frame일 뿐
성공으로 간주하지 않는다. 요청과 문자열 타입·중복 없음·동일 원소인 exact topic set ack 뒤
v1·단조 safe-integer sequence·요청 topic·revision·object data를 검증한 snapshot/update 또는
같은 topic set heartbeat를 받아야 healthy로
전이하고 attempt를 0으로 초기화한다. healthy 연결의 만료(`4408`)만 정상
lease rotation으로 즉시 재연결한다. healthy 전 `4408`과 hello 직후 `1013`은
일반 실패와 동일하게 backoff하며 3회 연속이면 `polling`으로 전이한다.
ticket fetch, pre-healthy handshake, healthy frame inactivity watchdog은 close event가 유실된
연결도 직접 분리하고 backoff 재연결한다. wire 배열 순서는 표시용이며, 형식 오류와 거절된
replace가 발생한 socket은 handler를 분리한 뒤 즉시 폐기한다. 새 ticket/socket이 exact
`replace`를 다시 보내고 유효 snapshot 또는 heartbeat를 받아야 `live`로 복귀한다.

C4 데이터셋 화면은 `polling` mode에서 active 여부와 관계없이 grid와 선택
상세 REST를 5초 주기로 재조회하고, 실행 중 항목은 기존 2초 주기를 유지한다.
화면 badge는 `실시간 갱신` / `REST 폴링 갱신` / `로그인 필요`를 실제 transport 상태와
같이 표시한다.

## 4. query invalidation 라우팅

live frame payload는 화면 데이터 정본이 아니라 event signal이다. 공용 router는 topic을
아래 event로 정규화하고 callback adapter를 호출한다.

| event | 입력 topic | C4/C5 adapter 대상 |
|---|---|---|
| `operation` | `import_jobs`, `import_job:*`, `feature_update_requests`, `feature_update_request:*`, `offline_uploads`, `offline_upload:*` | pipeline overview/executions/detail/events, 관련 dataset grid/detail |
| `provider_dataset` | `provider_sync`, `dataset_projection`, update request topic | dataset grid/detail, pipeline overview/executions |
| `dagster_run` | `dagster_runs`, `dagster_run:*` | pipeline overview/runs/detail/executions |
| `schedule` | `dagster_schedules` | pipeline schedules/overview, dataset schedule projection |

`provider_sync`, `dataset_projection`, `dagster_schedules` snapshot revision은 source
transaction과 함께 증가하는 `ops.ops_live_topic_revisions`의 topic clock을 포함한다.
provider state/policy, data integrity issue/POI cache target, schedule override는 statement 단위
INSERT/UPDATE/DELETE/TRUNCATE, C5 audit/claim resolution은 INSERT가 각각 clock을 올린다.
rollback은 clock도 함께 되돌아가고, 같은 topic의 동시 writer는 PK row lock으로 직렬화되므로
늦게 commit한 변경도 revision에 남는다. `dagster_schedules`는 clock 외에
C5가 만드는
`ops.dagster_schedule_audit_events.event_id` tail과
`ops.dagster_schedule_claim_resolutions.resolution_id` tail을 포함한다. 따라서 enable/disable,
materialize, override reset처럼 override row가 바뀌지 않는 schedule command도 C7A를
다시 수정하지 않고 live invalidation을 발생시킨다. 세 relation은 하나의 SQL
snapshot으로 읽는다. C7A는 C5 migration이 먼저 적용된 strict schema를 전제하며,
`to_regclass`로 누락 table을 숨기지 않는다. 배포 순서는 C5 머지·migration 적용 후 C7A다.

`OpsLiveInvalidationAdapter` callback이 live transport와 화면 query key를 분리한다.
C4 `/ops/datasets`는 `provider_sync`와 `dataset_projection`을 전역 구독하고 dataset grid/detail helper에
연결했다. C5 `/ops/pipeline`의 operation/provider/Dagster run/schedule query helper 연결은
C5 merge 후 C7A rebase에서 반드시 완료한다. 이 분리는 live transport가 화면 모듈에
역의존하는 것을 막는다.

## 5. 검증 경계

C7A 단위/통합 테스트는 다음을 고정한다.

- `Origin`/Fetch Metadata/session 없는 ticket 발급 거절, 로그인 session의 actor-bound
  ticket 발급, secret 미설정 fail-closed
- ticket 없음·변조·future `iat`·잘못된 audience/TTL은 data 0건 + `4401`,
  유효한 서명이 handshake 전 만료하면 data 0건 + `4408`, nonce 동시 재사용은
  한 건만 성공
- claim cleanup의 만료 후 60초 grace 경계와 hash PK 동시 replay
- 60초 outer lease 경계에서 claim/snapshot 조회·frame 전송 중단과 `4408`,
  내부 `TimeoutError`·DB 예외의 bounded rollback + `1013`, accept/close/rollback timeout 격리
- 유효 ticket의 `hello -> subscribed -> snapshot -> update`
- ticket/secret/query-string 미노출
- fake WebSocket timer로 reconnect backoff, 3회 실패 polling fallback, healthy 후 `4408` 즉시
  rotation과 healthy 전 `4408` backoff, hello 직후 실패 count 보존,
  BFF `401`/WS `4401` 재시도 중단, ticket fetch/handshake/inactivity watchdog,
  비 BMP 순서 차이를 포함한 exact topic set ack, malformed/비단조 frame 거절,
  rejected replace의 socket 폐기·새 socket exact replace, replace payload, topic 변경,
  active/pending logout, unmount socket/timer cleanup
- comma opaque run ID canonical 배열 보존, event별 adapter 호출과 C4 결선/C5 결선 대상
  누락 방지
- 실제 PostgreSQL에서 source별 statement trigger mapping·rollback 불변·topic row lock wait·
  late commit 2회 증가와 `collect_live_topic_snapshots` clock 반영. integrity issue와 POI target의
  다른 tab/process 변경도 `dataset_projection` event로 inactive grid/detail을 무효화

최종 n150의 실제 Chrome 검증은 없음/변조 ticket에서 종료 전 data frame
0건과 `CloseEvent.code === 4401`, 서명된 만료 ticket에서 data frame 0건과 `4408`
후 backoff fresh ticket 재연결, healthy lease `4408` 후 즉시 rotation을 각각 증거로
남긴다. 로그인 후 event 수신, logout 즉시 종료,
외부 실행 완료 뒤 열린 C4/C5 화면 자동 갱신까지 `T-ADM-C7`에서 수행한다.
