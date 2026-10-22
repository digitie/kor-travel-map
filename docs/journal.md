## 2026-10-22 — T-LOAD-LOCK-WAIT 1안: 적재가 fence를 길게 기다린다: 브랜치 `fix/load-curation-lock-wait`

- 증상: n150에서 동시 적재 다섯(seoul_bookstores·krforest_arboretums·standard_tourist_attractions·krforest_dulle_trails·
  visitkorea_enrichment)이 `feature-curation-write`를 Dagster 엔진 `lock_timeout=30000` 안에 못 얻어 55P03으로 3회 재시도 끝에
  실패했다. 매 재시도가 fetch·역지오코딩(약 5분)을 다시 하고 30초 만에 죽는다.
- 1안(소유자 결정): client 적재 transaction의 **첫 fence 획득 한 문장만** `lock_timeout`을 900초(env, 0=끔)로, 필요하면
  `statement_timeout`을 +60초로, `client_connection_check_interval`을 10초로 `SET LOCAL`하고 직후 되돌린다. 늘리기만 한다.
  무장 대상은 단위 검사의 분류표가 정본이다(적재 12개 무장, 정리·관리·offline upload·MOIS CLI 11개 비무장).
- 적대 리뷰 2명: HIGH 없음. MED — FIFO 잠금 줄이라 적재가 이어 잡으면 단건 writer·root 완결의 틈이 준다(문서화),
  900초는 아래 실측 보유를 못 덮는다(문서화), 무장 범위 검사가 둘뿐(→ 분류표). LOW 반영: 실패 로그, 연결 확인, 통합 holder 회수.
- 2안 입력(읽기 전용 실측, 공용 PG `pg_locks`·Dagster event log): 07:11~ 표본에서 fence 보유자는
  `standard_parking_lots`(run `71f21b6a`) — transaction 06:06:05 시작, 80분 넘게 `idle in transaction`. 스트리밍 snapshot
  경로(`_load_snapshot_batches` → `load_feature_bundle_batches`)가 100건 batch마다 upstream fetch와 역지오코딩을 **열린
  transaction 안에서** 한다(batch 사이 공백 최대 85초, DB 쓰기는 몇 초). 같은 경로가 8개 asset. 그 동안
  `finalize_provider_curation_root`가 30초마다 fence에서 55P03. 2안은 fetch·지오코딩을 transaction 밖으로 빼고 쓰기만 짧게.
- 검사(n150 일회용 컨테이너): 새 단위·통합 초록(40초 holder: 무장 성공·끈 쪽 30초 55P03·5초 writer 5초), api 1251·dagster 826·
  관련 통합 23 초록, mypy·lint-imports 초록. 변이 검사와 unit 세션 main 대조는 PR 본문.
- 문서 한도: acceptance §T-GR-03을 아카이브로 옮겼다(도구 검산 53건 보존).
## 2026-10-22 — prod 첫 적재 실패 2건: 브랜치 `fix/highway-evidence-krheritage-address`

- prod(Map `edffdc8a`)에서 한 번도 성공하지 못한 job 둘을 고쳤다. migration·API·OpenAPI 변화 없음.
- **고속도로 돌발**(`feature_notice_transport_highway_incidents_job`, 10분): 317건 중 231건이 `reverse_geocode_failed`로
  drop되고 손실 하한(#1253)이 run을 실패시켰다. 10분 경로는 일부러 geocoder를 결선하지 않는데(#667), krex 변환이
  `admin_evidence`를 싣지 않아 validator가 "evidence 없음 + 좌표 + bjd 없음"을 reverse 실패로 봤다. mois 패턴대로
  `AdminEvidence(obs_code=reverse bjd, reverse_attempted=좌표 있고 geocoder 결선)`을 싣는다. 미시도는
  `reverse_geocode_not_attempted` warning으로 적재되고, geocoder가 결선됐는데 결과가 없으면 여전히 error다(대조군 검사).
- **국가유산 행사**(`feature_event_krheritage_events_job`): 5306/5306 `missing_address`. provider가 실제 응답 필드
  (`seqNo`·`sDate`·`sido`·`gugun` …) 대신 없는 이름을 파싱해 `sn`·`address`·`starts_on`이 전부 비었다(provider 수정은
  python-krheritage-api에서 별도 진행). Map 쪽 보완: `address`가 비면 `sido`+`gugun`을 `Address.legal`로 쓴다(좌표는
  만들지 않는다). 값은 속성(`getattr`)을 먼저, 없으면 원 payload 키를 본다 — provider bump 전후로 같은 값이 나온다.
- 자연키: 종전 fallback `title::""::""`은 같은 제목의 다른 행사를 한 feature로 접었다. 실 응답에서 `seqNo`는 회차 id가
  **아니다**(같은 응답에 `15720`이 08-29~와 10-17 두 행) — `sn` 단독이면 회차가 접힌다. 그래서 `sn::시작일::종료일`(날짜가
  없으면 `sn`)로 바꿨다 — provider 수정본의 `occurrence_key`와 같은 모양이다. `sn`·시작일도 원 payload `seqNo`·`sDate`로 보충하므로 provider bump 전후 키가 같다. 이 dataset은
  한 번도 적재된 적이 없어 계보 이전이 필요 없다.
- 적대 리뷰 2회(읽기 전용). A(고속도로): HIGH/MED 없음. LOW — 좌표 row마다 `reverse_geocode_not_attempted` warning
  finding이 10분마다 갱신된다(dedupe·stale close로 증식 없음), 돌발은 bjd 없이 적재된다(#667 설계 그대로).
  B(행사): HIGH — 상세(시작/종료일·장소·전화)가 provider 수정 전엔 비고, bump 뒤에도 raw가 같아 payload hash가
  안 바뀌므로 feature가 다시 쓰이지 않는다 → `sDate`/`eDate`/`subDesc`/`contact`/`mainImageTemp`도 같은 방식(속성 →
  원 키)으로 채웠다. MED — `(seqNo, sDate)` 유일성 미확인, provider 수정본은 `(seqNo, sDate, eDate)`로 실측 유일 →
  자연키를 `occurrence_key`와 같은 `sn::시작일::종료일`로 맞췄다. LOW — fallback 키의 place가 bump 전후 달라짐(원
  `subDesc`를 쓰게 해 해소), 세종처럼 sido·gugun 중복 결합(provider와 같은 결합이라 일관, 무해).
- provider 핀 bump: python-krheritage-api `be3a1a28` → `e1b346f7`(provider #12 머지, 0.1.1). provider는 `seqNo`를
  프로그램 id로 보고(실측 2,006행 중 1,378행 공유) `occurrence_key = {sn}::{starts_on}::{ends_on}`을 낸다. Map 자연키를
  그 정의와 글자 그대로 맞췄다 — 날짜가 비어도 `sn::::`(앞 판의 "날짜 없으면 `sn`"은 어긋났다). 표시명 fallback은
  자연키 대신 `sn`. surface manifest 재생성(event 멤버 `occurrence_key`·`sido`·`gugun` 등 추가). n150에서 핀된 실제
  provider 모델로 fixture XML을 파싱해 Map 자연키 == `occurrence_key`, `missing_address` 0을 확인했다.
- 이 엔트리로 journal이 220 KiB를 넘어(`test_every_docs_markdown_stays_within_readable_limit`) 2026-09-26~27 14건을
  `archive/journal-2026-09f.md`로 옮겼다(tasks-rule §8). 섹션 본문은 바이트 그대로(원문 부분 문자열 대조), 상대 링크 없음.

## 2026-10-21 — T-RECONCILE-RETRY 하위 단계 2: reconcile sensor 결정 1~7(ADR-112 accepted): 브랜치 `feat/reconcile-retry-alert-close`

- 소유자가 O2~O5를 권고대로 수락했다(15분·40초 예산·시계당 한 시간 1행·물러섬 없음, 표지, SUCCESS root `failed` 닫기,
  O5(i) acceptance 문구 수정·(ii) log 한 행 = 잃지 않음). 같은 날 sensor `lock_timeout` 상한을 5초로 정했다.
- 구현: Dagster page는 (a)(b)(c)일 때만 지나가고 아니면 머리 시계, tick 40초(page 20/40초, 닫기·알림 몫 6초), 트랜잭션마다
  `set_config` 서버 쪽 상한(SERIALIZABLE은 isolation 다음, 보조 트랜잭션·상태 sensor 포함), storage 1-slot, 모든 분기
  commit, `head`·`db_watch` cursor 선택 키(비면 바이트 동일), `reconcile_stalled` 한 시간 1행, CLOSABLE만 abandon(다섯
  분기 + run 없음 → NULL), `ktmctl reconcile-abandon`, sweep `client_connection_check_interval=10s`.
- kor-travel-common: 핀을 `a960bdb1` → `e746e4b8`(#42·#43)로 올리고 `call_with_deadline`(slots)·`pg_error_info`·
  `StallClock`을 거기서 쓴다. 트랜잭션 SQL·CLOSABLE·표지·cursor 키는 Map에 둔다. migration·OpenAPI 변화 없음.
- 적대 코드 리뷰 2회: A(sensor) HIGH 3 — 실패 호출이 lock_timeout까지 가면 알림이 시간 부족으로 굶음(→ 닫기·알림 몫
  6초), `db_watch` 넘기기가 같은 root로 되돌아감(→ 그 tick 실패 목록의 다음 root에게), active run의 root 가리킨 conflict를
  root 없음으로 봄. MED: 머리 `run_active`는 지나감, storage 실패가 머리 시계를 재시작, quarantine root 로그 문구,
  다중 statement 상한(문서화). B(DB/client) MED: 상태 sensor에 상한 없음(→ 20초 예산), 다중 statement 상한; LOW: gate 표지가
  sweep에서만 쓰임(→ sweep 실패 로그에 분류), 검사 보강(client 메서드별 상한 단위 검사, NULL root 재읽기), CLI 방어.
- delta 리뷰(수정분만): MED — 닫기 실패 뒤 알림이 다시 굶음(→ 머리 닫기·알림은 tick 예산, DB page 몫 13초, 닫기는
  마감 − 5초), 깨진 cursor 시계가 sensor를 영구히 세움(→ 시계만 버림). LOW — 혼자 실패하는 root가 15분마다 알림(→ 시계
  유지), CLI 연결 오류.
- 검사: 해제 조건 줄마다 단위·통합 검사. 변이 21종(22검사)이 모두 결박한 검사를 빨갛게 만들었다 — (b) 느슨하게,
  statement_timeout 제거, isolation 앞 상한, reconcile 상한 누락, lock 상한 30초, 모든 55P03을 gate로(단위·통합), 서명
  변경 시 시계 리셋, 빈 키 쓰기, tick 시작 시각, DB 목록 실패 시 commit 생략, membership 닫기, root 없음 conflict, NULL
  상태 엄격 읽기, storage가 머리 시계 리셋, active conflict, 넘기기 없음, 머리 알림 page 마감, 닫기 전체 마감, 혼자 root
  시계 버림, 깨진 시계 엄격, 상태 sensor 상한 없음(n150 일회용 컨테이너).
- **배포 영향**: Map Dagster code location·API 이미지 재배포(common 핀 변경). migration 없음, Map admin OpenAPI 변화 없음 →
  PinVi 재vendor 불필요. 되돌릴 때는 선택 키(`head`·`db_watch`)를 뺀 cursor를 `dagster sensor cursor --set`으로 먼저 쓴다.
  n150 공용 Dagster daemon은 소유자가 멈춰 둔 상태 그대로다(켜지 않았다).

## 2026-10-20 — T-RECONCILE-RETRY 하위 단계 1: 완결을 sensor 밖으로(ADR-112 결정 0-1): 브랜치 `feat/finalize-out-of-sensor`

- 소유자가 O1 권고를 수락했다(세대 0 root도 tick 6~8초, tick p99 12초). 그래서 결정 1~7보다 먼저 SUCCESS root 완결을
  sensor tick 밖으로 뺐다. O2~O5는 열려 있다.
- 자리는 별도 job `feature_operation_completion`의 sweep run이다. sensor는 SUCCESS에 ensure만 하고, 완결은 sweep이 기존
  reconcile 함수로 한다. repo·SQL·migration·API는 그대로다. "SUCCESS인데 root가 active"가 곧 완결 대기이므로 새 상태가 없다.
- 설계 적대 리뷰 1회에서 초안(root마다 run 하나, 대상 tag, 동시 상한 2, 5분 재시도)이 무너졌다. DB page만 요청하면
  Dagster page 실패가 모든 완결을 세운다(H1). 동시 상한 2는 lineage lock 대기 실패만 만든다(M1). SERIALIZABLE 경쟁은
  `blocked`가 아니라 40001이다(H2). 그래서 sweep 하나 + pool 직렬화 + success sensor 1차 요청 + DB page 15분 뒷받침으로
  줄였다. 결과가 초안보다 단순하다.
- 남는 것: 완결은 여전히 lineage lock을 쥔 채 돈다(큰 완결 동안 run 안 member 완료가 `lock_timeout`에 걸릴 수 있다).
  고칠 수 없는 root의 알림·닫기는 결정 3·4 몫이다.

## 2026-10-20 — weather 잔재 정리 2건(T-WX-NOTICE-CLOSE·T-WX-VNEXT-FREEZE): 브랜치 `chore/wx-notice-close-vnext-freeze`

- 소유자 지시("4 진행"). `close_notice_features`(client·repo)와 그 함수만 쓰던 통합 테스트 1건을 지웠다. 공유 헬퍼
  `_persist_notice_lineage_events`·`_reconcile_persisted_notice_scope`는 event-bundle 경로가 계속 쓴다.
- vNext 동결 계약은 재동결하지 않고 rev 300 당시 기록으로 둔다(ADR-105 후속 한 줄, freeze 테스트 docstring 범위 절).

## 2026-10-20 — T-RECONCILE-RETRY 설계안 ADR-112(doc-only): 브랜치 `docs/t-reconcile-retry`

- 항목 이름이 "설계"이고 #1319가 세 판의 코드에서 매번 새 구멍을 냈다. 그래서 이번에는 코드보다 설계를 먼저 냈다. 이
  PR은 ADR-112(proposed)만 싣고 코드는 바꾸지 않는다. 항목은 열린 채로 둔다. 소유자가 O1~O5를 승인한 뒤 같은 항목에서 구현한다.
- 핵심은 지나가는 규칙 하나다. Dagster watermark는 panel-only run이거나, **tick이 끝났을 때 root가 있는** run이거나,
  내구성 있는 `reconcile_abandoned` 기록을 남긴 run(닫기와 관측 오류)만 지나간다. 그 밖이면 머리에서 멈춘다. 원래 있던 DB page sweep이
  root 있는 run의 재시도 큐 노릇을 하므로 parking 표가 필요 없다.
- 멈춤은 횟수가 아니라 시계로 잰다. 머리는 cursor `head`, DB page의 실패 root 하나는 `db_watch`를 쓰고, 둘 다 처음 본 실패 시각부터 잰다.
  15분이 지나면 알리고, 닫을 수 있는 실패(class 22·23502·23514·invariant conflict)면 그때 닫는다. root 없는 머리는
  system log 한 행을 남기고 지나간다. gate 경합은 기존 message 표지로 가른다(migration 없음). tick 예산은 고정 40초이고,
  상한은 서버 쪽 `SET LOCAL statement_timeout`·`lock_timeout`으로 건다.
- 적대 리뷰 1회에서 HIGH 넷이 나왔고 모두 반영했다. client만 끊는 timeout은 서버의 완결을 멈추지 못했다. 완결은 취소
  coordinator도 부르므로 전용 SQLSTATE가 API를 깨뜨렸다. 항목별 시간 창이 방문 주기와 겹쳐 알림이 영원히 발화하지 않을
  수 있었다. `end_time` 시계가 첫 실패를 이미 15분 지난 것으로 만들었다. 결과적으로 설계가 시계 둘과 cursor 선택 키 셋으로 줄었다.
- 2차 리뷰에서 HIGH 셋이 더 나왔다. 첫째, 서버 쪽 상한이 오래 걸리는 완결을 영영 못 끝내게 한다. 그래서 **구현 전제로
  prod 완결 소요를 먼저 잰다**(결정 0, O1). 둘째, `db_watch` 슬롯 하나를 고칠 수 없는 root가 계속 잡는다. 알림을 낸 뒤
  슬롯을 넘기도록 했다. 셋째, SERIALIZABLE에서 `set_config`를 isolation 문보다 먼저 두면 25001이 난다. 순서를 고정했다.
  MED로 나온 것도 반영했다. 23514는 constraint 다섯으로 좁혔다(membership은 운영자가 dataset을 끄면 나므로 뺐다).
  관측 오류도 머리 시계를 탄다. 알림 throttle은 시계마다 둔다. 실패 횟수 예산은 없앴다.
- 리뷰가 매번 새 구멍을 낸다는 점은 #1319와 같다. 다만 이번에는 문서 단계에서 잡혔다. 구현 전에 한 번 더 적대 리뷰를 받는다.
- #1319 최종 리뷰의 L1~L4는 저장소 어디에도 내용이 적혀 있지 않아 대응 표에서 뺐다.

## 2026-10-20 — T-TEST-PLANNER-INDEX 원장 이관(doc-only)

- PR #1336(`e937b38d`, main 반영 완료)이 통합 planner flake 고정(REINDEX in test txn + 25k draft rows + lock_timeout 30s,
  20/20 n150 연속 통과)을 실었으나 `tasks.md`→`tasks-done.md` 이관이 그 PR을 못 탔다. 이번 doc-only PR이 그 이관을
  싣는다 — 코드 변경 없음, acceptance §T-TEST-PLANNER-INDEX는 그대로 둔다.

## 2026-10-19 — production MapLibre worker asset 누락 복구 (PR #1340)

- **실측 원인.** 인증된 live UI가 `/maplibre/maplibre-gl-worker.mjs`를 404 HTML로 받았다. Map 화면 코드는 worker가 없으면 GeoJSON source가 로드되지 않아 고배율 marker를 표시하지 못한다. Docker runtime stage가 `.next/standalone`과 `.next/static`만 복사하고 `public`은 누락했다.
- **수정.** frontend image에 builder의 `public`을 같은 standalone package 경로로 복사하고, live UI가 worker/shared 두 파일의 HTTP 200·JavaScript content type·비어 있지 않은 본문을 검사한다. marker 시나리오는 데이터가 있는 좌표-bearing `place`에서 실행하고, viewport 안정화는 외부 타일의 무한 `idle` 대기를 피하도록 bounded로 바꿨다.
- **검증.** `docker build -f docker/frontend.Dockerfile` 성공, 결과 이미지에서 worker 19 KB와 shared 502 KB 확인, E2E `tsc` 성공. 운영 UI 반영과 live 브라우저 검증은 PR CI 후 진행한다. Dagster를 import하는 Python unit test는 로컬 개발 환경에 Dagster가 없어 수집 단계에서 실행하지 못했으며, PR CI가 해당 게이트를 담당한다.

## 2026-10-19 MOIS 장애 격리 수용

PR1340: 실제 SYN DROP/native retry 기본값으로 FAILURE308.365초(<1440), 복구500행·재수집HTTP0 PASS. REST/prefetch/loader173검사와 namespace4검사 PASS. 운영 전체job/실DB 검증은 아니며 daemonOFF 유지. [범위와 한계](reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — MOIS 연결 실패 조기 전파

- 500행 typed 오류 선조회 지연을 재현하고 실행중 task 취소·회수를 보강했다. 관련89회귀 PASS이며 실제 네트워크/native retry 수용은 준비 중이다. [근거](reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — T-MAP-02 현재 설치 세대 수용

- T-MAP-02 — timeout 구현523d98cc가 포함된 e937b38d의 API/CS 설치3파일 hash와
  현재 image/CID/StartedAt을 확인했다. 과거 첫 generation UUID는 미회수이며
  현재 설치세대 묶음으로 수용한다. 불필요 재배포·운영 변경0.
  Map API/CS·PinVi API 실제 기존 키 reverse3/3 PASS, PinVi CS 직접 역할은 제외.
  [범위와 증거](reports/2026-10-19-installed-timeout-acceptance.md).
  전원단절 drill·자동 실행·운영 변경토큰 전량 수용은 별도다.

## 2026-10-18 — Geo 기준점 실제 UI 수용

- 실제 관리자 UI 8/8 PASS: 최초 baseline plan 1/상세 items 0, 동일 토큰 감지에서 같은 기준점 유지.
- 실행 중 세 이미지의 revision label e937b38d와 DB head 409를 관찰했다.
- daemon OFF·현재 run/물리 worker 0·컨테이너 lifecycle 유지. 실제 변경 토큰 replay/resume·자동 실행은 미검증.
- [검증 기록](reports/2026-10-18-geo-baseline-live.md). 문서만 변경하며 사용자 지시로 CI를 생략한다.

## 2026-10-17 — T-MAP-02 timeout 설명 정합(문서만): 브랜치 docs/track2-http-timeout-contract-20261017

- tasks.md의 낡은 connect 2 s를 실제 기본 4 s로 정정했다. read·write·pool 기본은 geo 10 s·transport 30 s다
  (settings.py, geocoding.geo_http_timeout, dagster/provider_fetchers.transport_http_timeout).
- transport의 요청 재시도는 upstream_retry.DEFAULT_UPSTREAM_ATTEMPTS=2·
  PROVIDER_BOUNDARY_BASE_DELAY_SECONDS=15.0 및 run 예산을 따르며, 이 숫자들은 요청 전체 deadline이 아니다.
- 구현 커밋 523d98ccf36f90aaead9ac33ab353a0839293621(#1325)은 최신 main
  e937b38d176cfeb759daca629395f51c1a6a4d5f(#1336)의 조상이다. 제품 중복 패치는 하지 않았다.
- 실제 배포·장애 drill은 수행하지 않았다. T-MAP-02는 acceptance의 첫 prod 배포 generation 근거를 확인할 때까지 열린다.

## 2026-10-17 — 통합 planner flake 결정화(T-TEST-PLANNER-INDEX): 브랜치 `fix/t-test-planner-index`

- **원인(실측).** keyset 쿼리에 같은 열의 인덱스가 둘이다 — partial `idx_features_updated_keyset`과 술어 없는 admin
  `idx_features_admin_updated_keyset`. 공개 행만 있는 seed에서 partial의 이점은 Filter 비용 하나(약 0.19)라, 인덱스 크기가
  갈리면 뒤집힌다. 크기를 가르는 것은 **LP_DEAD 비대칭**이었다 — admin 목록처럼 admin 인덱스만 훑은 쿼리가 죽은 항목에
  표시를 남기면 다음 insert가 admin 쪽에서만 자리를 다시 쓴다(n150 재현 partial 622~744 page vs admin 127 page, plan은
  CI 실패와 같은 `Index Scan using idx_features_admin_updated_keyset … Filter`).
- **고정.** 테스트 transaction 안 `REINDEX`(keyset 쌍 두 벌, 롤백) + 같은 수의 비공개 행(더 새 `updated_at`, 일부 같은
  이름) + 실패 시 plan 전문. 재시도·skip 없음. 고정을 되돌리면 같은 순서에서 2/2 빨강, 고정 판은 20회 연속 초록.

## 2026-10-16 — geo 릴리스 재지오코딩 구현 반영 문서(T-GR-07, doc-only): 브랜치 `docs/t-gr-07-geo-release-docs`

- **무엇.** ADR-109 accepted(구현 기록 표·열린 결정 13개 결론), runbook `geo-release-regeocode.md` 신규, 정본 문서의
  "ADR-109 proposed, 미구현" 표식 제거, T-GR-01~06·08 `tasks-done.md` 이관(T-GR-07은 머지가 조건).
- **문서가 코드와 달랐던 자리.** `address-geocoding.md` §5의 센서 위치(`sensors.py` → `geo_release_sensor.py`)·커서(없음 —
  기준선은 계획 표 행)·`kor_travel_geo_client` resource(만들지 않음 — `open_geo_client`)·run_key 다섯째 칸(`provider_dataset_id`
  → `position`)·상수 이름, ADR-108의 "릴리스 센서가 MOIS 이어 달리기를 대신한다"(MOIS는 이제 센서가 내지 않는다).
  geo ADR-069는 그 저장소에서 2026-10-13 accepted(GitHub 원문 확인).

## 2026-10-16 — admin UI geo 릴리스 화면(T-GR-06, ADR-109 결정 8): 브랜치 `feat/t-gr-06-geo-releases-ui`

- **무엇.** `/admin/ops/geo-releases` — 현재 geo 데이터셋(`data_token` 없음 = 빨간 상태 + 센서 Skip 사유), 계획 목록, 계획 상세
  (커버리지 게이지·항목 표·Dagster run 링크·건너뛰기·다시 계획), "지금 감지". 기존 Rail-Workbench 체계(AdminShell·SectionCard·
  DataTable·StatStrip·확인 dialog)를 그대로 쓴다. nav "수집 파이프라인"에 넣었고, nav 거울 표(`home-nav.spec`)가 그동안 빠뜨린
  `수동/provider 판정`도 같이 맞췄다.
- **MOIS 문구.** API 사유 값은 하나라 replay 미지원과 MOIS(센서 수동)를 가르지 못한다 — enum을 바꾸면 PinVi 재vendor라
  화면이 operation key로 "수동 실행 후 skip 필요"를 보인다. API 필드에는 docstring이 아니라 주석을 달았다(모델 docstring은
  OpenAPI description이 된다).
- **격리 스택 e2e.** n150에 PostGIS(배포 bootstrap → head 409)·가짜 geo(토큰 전환 제어)·실 API·prod frontend를 띄워, 기준선
  기록 → 토큰 전환 → 실제 계획 생성 → MOIS 안내 → 건너뛰기를 실 API로 돌렸다. mock 스펙은 skip·detect 1회·게이지 수치·
  no_token·replan 확인·375px 가로 넘침 0.

## 2026-10-16 — records resource replay 모드(T-GR-08, ADR-109 결정 7): 브랜치 `feat/t-gr-08-replay-mode`

- **무엇.** 쿼터 민감 records resource에 `source_mode=replay` — 저장된 current 원본을 provider 모델로 되살려 같은 변환기로
  다시 적재한다(provider HTTP 0회). `SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS`를 채워 릴리스 센서가 replay 항목을 낸다.
- **MOIS는 golden에서 떨어졌다.** MOIS `raw_data`는 payload hash 입력용 21개 필드뿐이고 변환기는 우편번호·건물관리번호·
  업종별 시설 필드 24개를 더 읽는다 — 되살린 bundle의 `facility_info`·주소가 달라진다. 결정 7의 가정대로 MOIS는 replay
  목록에서 빼고 fetch로 낸다(로컬 SQLite라 data.go.kr 쿼터 없음). acceptance의 MOIS 술어(N `not_called`·reverse 0·
  `unstamped` 0·두 번째 변환 0)는 fetch 경로 통합 테스트로 확인했다.
- **설계에 없던 것 셋.** (1) `fetched_at`만으로는 부족하다 — head 관측 입력은 `imported_at`이라 replay가 head를 전진시켜
  관측을 꾸민다. 저장된 `observed_at`을 되돌려 head 갱신 자체가 일어나지 않게 했다. (2) Dagster client는 연결 1개이고
  표준데이터 snapshot 적재는 batch stream을 한 transaction 안에서 소비한다 — 적재 중 읽으면 그 연결과 경합하므로 읽기를
  적재 전에 끝낸다(`prefetch_replay`). (3) provider 라이브러리는 CI에 없다(`providers` extra) — 실모델 golden은 설치된
  환경에서만 돌고(importorskip), CI에는 "변환기가 raw에 있는 필드만 읽는다"는 구조 golden lint를 두었다(MOIS 대조군 포함).
  런타임 backstop은 hash 불일치 시 적재 전 실패다.
- **#1333 리뷰 2인 반영.** (R2) 차단이 풀린 MOIS를 센서가 full fetch로 자동 launch하면 전국 Phase A·50만 행 변환·예정
  밖 은퇴가 일어난다 — `SENSOR_MANUAL_OPERATION_KEYS`로 막고 운영자 수동으로(사유 값 재사용, OpenAPI 불변). (R1) 빈·부분
  replay가 성공으로 끝나던 것 — 읽은 건수를 같은 술어의 active entity 수와, 변환 결과를 읽은 레코드와 대조해
  `ReplayIncomplete`. seal 영수증 `observed_at`이 replay에서도 찍히던 것 — replay는 authoritative를 주장하지 않는다
  (operation 경로 통합 테스트). "MOIS fetch는 쿼터 0"은 TTL 안에서만 참이라 문서를 고쳤다. launchable은 replay 목록에서
  파생, 복원 함수는 `REPLAY_FROM_RAW` 하나, CI dagster job에 `python-datagokr-api` 설치(public 핀)로 golden이 CI에서 돈다.
  drift 검사는 hash가 변환기 안에서 나오므로 변환 뒤 — 문서를 "commit 전 실패"로 맞췄다.

## 2026-10-16 — geo 릴리스 센서(T-GR-05, ADR-109 결정 5): 브랜치 `feat/t-gr-05-geo-release-sensor`

- **무엇.** `kor_travel_geo_release_sensor`(기본 STOPPED, 300초) — 공용 계획 함수로 감지·계획하고, 항목(run 단위)을
  하나씩 전용 job으로 낸다. 전이(완료·MOIS 이어 달리기·1회 재요청·무run 3 tick)와 완료 호출(sigungu resolver는 tick의 geo
  client). repo·client에 항목 전이 셋(`mark_item_requested`·`settle_item`·`requeue_item`).
- **판정을 새로 만들지 않았다.** 기준선·멱등·끝난 토큰·롤백 정리는 #1331 함수 그대로라, 센서 테스트는 "공용 함수의 결과를
  따르는가"만 본다. 커서도 쓰지 않는다(기준선이 DB 행).
- **원장 분리.** `tasks-acceptance.md`가 220 KiB 상한을 넘어(226,696 bytes) 닫힌 절 `T-MAP-01`·`T-GR-00-LEDGER`를
  `scripts/archive_task_ledger_section.py`로 `docs/archive/`에 옮겼다(체크박스 다중집합 검산 통과, 221,385 bytes).
- **replay 게이트가 지금은 계획 완료를 막는다.** replay 항목(MOIS·datagokr fileData·standard_data)은 T-GR-08 전까지 내지
  않으므로 그 항목이 남은 계획은 `running`으로 남는다 — Skip 사유가 막힌 항목과 이유를 말한다.

## 2026-10-16 — geo 릴리스 계획 표·계획 함수·admin API(T-GR-04, ADR-109 결정 5·8): 브랜치 `feat/t-gr-04-geo-release-plan`

- **무엇.** migration 408(계획·항목 표), `plan_geo_release`(센서·`/detect` 단일 정본), 항목 생성(core 상수 + DB 정본),
  `coverage()`, skip·replan·완료(1회 sweep → 링크 재동기화), client 래퍼, admin API 5 operation, core 상수와 Dagster 정의의
  동등 lint.
- **실측이 설계를 고친 자리.** (1) 항목 입력의 kind — 설계는 `feature_load`인데 head DB에 그 kind 행이 0건이었다(통합 DB
  덤프로 확인). job을 dataset에 결박하는 것은 `refresh`다. (2) MCST는 job 하나에 dataset 13개라 항목 13개가 run 하나를 나눠
  써야 한다 — T-GR-05 몫으로 기록. (3) prod 활성 cache target은 0개(전체 4, 전부 삭제) — 링크 재동기화의 stream 이벤트를
  지금 만들지 않은 근거. (4) 기준선은 센서 커서가 아니라 DB 행이어야 `/detect`도 같은 판단을 한다 — 상태 `baseline`.
- **적대 리뷰 2인(#1331) 반영.** 끝난 계획이 잔여를 남기면 감지마다 다시 계획해 쿼터를 사이클마다 쓰는 결함(최신 행이 이
  토큰의 `done`이면 멈춤), 롤백 시 B 계획이 활성으로 남는 결함(잔여 0 응답 전에 supersede), 옛 토큰·기준선 replan 허용,
  resolver 없는 완료가 도중에 롤백되던 것(사전 검사)을 고쳤다. 항목은 run 단위(`provider_dataset_ids`)로 바꿨다 —
  MCST 13 dataset이 항목 1개라 센서가 단순하다. replay 게이트는 메모가 아니라 core 상수와 `launch_blocked_reason`이다.
- **lint의 유도.** geo 의존을 `reverse_geocoder=`의 존재로 세면 돌발정보 notice(`=None`)가 들어오고, 함수 본문 전체의 이름을
  보면 price asset이 `deps=[place asset]` 데코레이터 때문에 geo 의존으로 잘못 잡힌다(첫 시제품에서 실제로 났다). None 상수
  제외 + 본문만 + 모듈 횡단 전이로 바꿨다.

## 2026-10-16 — 적재 경로의 geo 재해석(T-GR-03, ADR-109 결정 4·6): 브랜치 `feat/t-gr-03-stale-stamps`

- **무엇.** `load_bundle`이 `GeoLoadContext`를 받아 스탬프·stale 분기·값 동일 무쓰기·빈 답 가드·override finding을 한다.
  MOIS "그대로" 판정에 스탬프 토큰 조건, 행 evidence, 표식 토큰. concierge 토큰 신뢰 규칙·해시 제외. 비-MOIS run 빈 답 가드.
  변환 함수 단위 geo 소비 lint. T-GR-02 이월 넷(client·repo 전달, run 가드, MOIS 배선, price 스탬프 0) 포함.
- **#1327 최종 리뷰 HARD 요구 — 토큰은 지오코딩 전에.** `_load` 경로는 변환이 끝난 뒤 wrapper로 들어가 토큰을 그때 처음
  읽었다 — 전환 run이 옛 데이터를 새 토큰으로 봉인할 수 있었다. 역지오코더를 감싸 처음 불릴 때 handle을 먼저 읽게 했고
  (MOIS·concierge는 run 시작에), 응답이 다른 토큰을 내면 그 적재는 스탬프·stale 분기를 하지 않는다(이중 방어).
- **설계를 고친 자리.** run 빈 답 가드의 분자를 endpoint 빈 답에서 **행 단위 최종 빈 답**으로 — reverse가 비고 region fallback이
  채우는 산악 centroid run이 정상인데 실패할 뻔했다(테스트로 결박). concierge `current_data_token=None`은 acceptance대로 종전
  동작(설계 §4 문구와 모순). 해시 자체 계산은 payload에 토큰이 있을 때만(롤아웃이 전 행을 흔들지 않게). override 테스트에서
  `core.address` jsonb에도 코드가 들어 있어 열 하나의 override로는 "값 동일"이 되지 않는다는 것을 확인했다(문서화).
- **2차 적대 리뷰(같은 날) 반영.** MOIS 롤아웃이 수십만 행이라 행마다 stale·저장값·스탬프를 따로 묻던 것을 chunk 단위로
  바꿨다(선읽기 두 문장 + 스탬프 한 문장; 같은 Feature가 두 번이면 두 번째는 행 단위). concierge 해시에서 최상위
  `updated_at`·`operation`도 뺐다 — producer가 토큰만 바뀌어도 `updated_at`을 새로 찍어 전 행이 매 릴리스 "바뀜"이 될
  뻔했다. stale 분기에서 같은 법정동인데 geo 전용 필드만 사라진 답은 저장값을 지킨다(`geo_partial_kept`). 빈 답 가드가
  `address` override 값을 provider base로 옮겨 적지 않게, 관측 집합이 없으면 토큰을 닫게(fail closed) 했다. 문서는
  포인터가 아니라 본문을 고쳤다(`address-geocoding.md` §4 run 가드 분자·concierge 기본, ADR-109 결정 4).
- **실측은 격리 스택에서.** n150에 별도 PostGIS 컨테이너를 띄우고 배포 bootstrap 경로로 올린 DB에서 MOIS 루프 그대로
  12,000행을 돌렸다(일괄/행 단위 번갈아 2회). 롤아웃 101~103초 대 116~117초. 첫 정상 run이 17초로 튀어 계획을 의심했지만
  EXPLAIN은 스탬프 PK 인덱스(chunk당 9ms)였고 두 번째 run부터 1.1초 — 대량 쓰기 직후 hint bit 비용이었다.
- **게이트·빨강.** 통합 23건(새 파일) + 기존 스탬프 22건. 의도적 빨강 11종을 n150에서 확인(빈 답 가드 끔·판정 집합에 legal·
  override 열 비교·토큰을 해시에·전환 관측 무시·CTE 조건 제거·표식 조건 무시·값 동일 재쓰기·concierge 신뢰 무시·토큰 선행
  제거·run 가드 분자를 endpoint로) — 각각 그 테스트만 빨갰다. 롤아웃 비용 프록시(통합 DB, 300행): 첫 적재 8.31 s, geo 없는
  재적재 2.40 s, 스탬프 롤아웃 재적재 2.04 s(값 동일 무쓰기 300·스탬프 300) — 행당 추가 비용은 잡음 수준.

## 2026-10-16 — `docker-buildx.sh`의 `$!` 경주(고아 tar writer): 브랜치 `fix/buildx-archive-pid-race`

- **무엇이었나.** `test_buildx_cleans_partial_archive_when_materialization_is_terminated`가 n150에서 멈췄다 — 테스트의
  가짜 `git archive`(무한 루프)가 고아로 남아 97% CPU로 2시간 49분 돌았다. **flake가 아니라 경주다.**
  `git archive … &`가 fork된 직후 `archive_pid="$!"`가 실행되기 전에 TERM이 오면 trap이 먼저 돌고, 그때 변수가 비어
  있어 정리가 writer를 죽이지 못한다. 부하가 큰 n150에서만 그 창이 열렸다. #1325~#1327 PR 본문에서 이 실패를
  "n150 부하성 flake"로 부른 것은 틀렸다(각 PR에 정정 코멘트). 같은 실행에서 함께 실패한
  `test_lifecycle_preserves_signal_exit_status[INT-130]`은 다른 원인이다 — 하네스를 `nohup … &`로 띄워 SIGINT가
  ignored-at-entry로 상속됐고 bash는 그 신호를 다시 trap하지 못한다(이 저널의 기존 "환경 실패" 판정이 맞다).
- **고친 것.** 정리는 `$!`를 담은 변수가 아니라 bash job 표(`jobs -p`)로 writer를 찾는다 — job 표는 fork와 같은
  명령 안에서 채워지고 trap은 명령 사이에서만 돌므로 창이 없다. 테스트의 가짜 writer는 부모가 사라지거나 30초가
  지나면 스스로 끝나고, 그렇게 끝났으면(아무도 죽이지 않았으면) 표식을 남겨 테스트가 **고아였음**을 단언한다.
  `pytest-timeout`을 dev 의존성에 더하고 두 테스트에 `timeout(60)`을 건다.
- **결정적 재현.** 스크립트 사본에서 fork 줄 바로 뒤에 `kill -TERM $$`를 넣어 경주 창을 매번 연다
  (`test_buildx_reaps_the_writer_even_when_term_lands_before_the_pid_is_recorded`). 옛 정리로 돌리면 빨갛다.

## 2026-10-16 — run-scoped geo 현재 토큰 resource·`geo_applied` 배선(T-GR-02): 브랜치 `feat/t-gr-02-geo-dataset-resource`

- **무엇.** 팩토리 `fetch_current_dataset`(geocoding — CLI가 dagster를 import할 수 없어 여기), Dagster resource
  `kor_travel_geo_dataset`(asset·큐 runner 공통 키), offline upload·CLI의 같은 팩토리 호출, asset 21곳 + MCST 1곳의
  `geo_applied` 리터럴과 적재 wrapper 메타(`geo_*`, 불일치 WARNING 1건). 적재·스탬프 동작은 바뀌지 않는다.
- **범위를 자른 자리.** client·infra 적재 함수로 `current_dataset`·`geo_applied`를 넘기는 것과 빈 답 비율 가드, MOIS 배선은
  T-GR-03이다 — 지금 넘기면 받는 쪽이 아무것도 하지 않는 인자다. acceptance의 "(T-GR-03 뒤)" 항목도 그때 판정한다.
  설계의 경량 `kor_travel_geo_client` resource는 센서(T-GR-05)가 쓸 때 더한다.
- **#1326 델타 리뷰 후속(이 PR에 함께).** `tasks-rule.md` §8의 아카이브 복구 예외에 "충돌 마커 줄 자체의 삭제"를 정식으로
  더했다(T-GR-01 journal의 '§8 복구 예외' 인용이 가리킬 조문). 마커 lint는 CRLF·CR 줄끝과 첫 줄 UTF-8 BOM을 정규화한 뒤
  보고, `=======`는 같은 파일에 시작·기준·끝 마커가 있을 때만 센다(홀로 있는 setext 제목 밑줄은 통과). CRLF·BOM 임시
  파일로 빨강을 확인했다. `address-geocoding.md` §7 e2e 행을 acceptance와 같은 "첫 tick이 기준선을 기록한 뒤"로.
- **리뷰 A·B 반영.** resource를 lazy handle(`GeoDatasetHandle.current()`, 처음 쓰일 때 1회·동시 호출 1회)로 바꿨다 —
  geo 콜러블이 없는 run(price/notice·visitkorea·MOIS)은 odroid가 꺼져도 connect 상한을 기다리지 않고, sync 초기화의 별도
  loop·무기한 `thread.join()`도 사라졌다. 경고 경로: 팩토리는 `logger=`를 받아 resource는 managed logger
  (`kortravelmap.dagster.resources`), offline upload은 `context.log`로, 불일치 경고는 wrapper가 넘기는 `context.log`로 낸다
  (모듈 logger는 `managed_python_loggers`에 없어 event stream에 닿지 않는다 — 실제 resource 경로를 돌려 managed logger가
  받는지 보는 테스트를 더했다). API key 미설정은 "base URL 미설정"이 아니라 그 원인으로 경고한다. 키 미배선 context는
  WARNING. lint는 `None`이 아닌 `reverse_geocoder=` 인자도 reverse 사용으로 센다. 실제 역지오코더의 `stats`가 wrapper까지
  가는 테스트. T-GR-03·T-GR-05 acceptance와 tasks.md에 이월 항목(client·repo 전달, run 빈 답 가드·MOIS 공유 상수, MOIS 배선,
  price 경로 스탬프 0 검사, 경량 client resource)을 적었다.
- **`test_archive_markdown_relative_links_resolve` 실패의 실제 원인.** 링크가 아니었다 — 로그의 오류는
  `PytestUnraisableExceptionWarning`(앞선 subprocess 테스트가 남긴 `Popen`·`FileIO`가 이 테스트 도중 GC되며 잡힘)이었고,
  n150 clone 두 곳의 `git status --porcelain --ignored docs/archive`는 비어 있다(낯선 아카이브 파일 없음). 격리 재실행은 초록.
- **게이트.** 단위: 팩토리 성공·지문 없음(경고 0)·전송/5xx/키 거부/계약/`available=false`/client 없음(경고 정확히 1건),
  불일치 판정 5분기. dagster: 메타 4키·불일치 WARNING 1건·현재 토큰 None이면 불일치 아님, resource가 base URL 없으면 None,
  있으면 `/v2/dataset/version` 1회. lint: run 함수의 실제 콜러블(`_reverse_geocoder(context)`·`address_resolver=`) ==
  `geo_applied` 리터럴(asset 하나를 False로 바꾸면 빨갛다), 팩토리 호출 지점 3곳·`dataset_version()` 직접 호출 0곳.

## 2026-10-15 — 지오코딩 스탬프 표·geo 데이터셋 토큰(T-GR-01, ADR-109 결정 1~3): 브랜치 `feat/t-gr-01-geocode-stamps`

- **무엇.** migration 407 `feature.feature_geocode_stamps`, DTO `DatasetRef`·`GeoApplied`·`GeoAttemptEvidence`, 스탬프 repo
  (`upsert_stamps`·`is_stale`·`select_stale_feature_ids`·`decide_outcome`), geo client `dataset_version()`·응답 `dataset` 선택
  파싱·`GeoCallStats.empty`/`observed_data_tokens`. 적재 경로 배선은 T-GR-02/03이다 — 이 PR은 아무 행도 스탬프하지 않는다.
- **현실 확인.** odroid geo는 v2 응답 최상위에 `dataset{version_token, data_token}`을 싣는다(geo #573); n150 geo는 토큰을
  가진 적이 없다. 그래서 파싱은 선택이고(없음 → None), 소유자 결정(2026-10-15)으로 '없음 → 첫 토큰'은 기준선이다 —
  ADR-109 결정 5에 기록(구현 T-GR-04/05).
- **설계와 다르게 쓴 것.** acceptance §T-GR-01 "구현 메모" 7항 — `decide_outcome`의 `legal_dong_code_present` 입력,
  `GeoAttemptEvidence`(AdminEvidence diff 0), `upsert_stamps`가 토큰 없음 = 0건을 강제, `coverage()`는 T-GR-04로,
  토큰 형식 CHECK, endpoint 단위 빈 답 계수. 407은 forward-only다 — 처음에 실제 downgrade와 왕복 테스트를
  넣었으나 `alembic/env.py`가 모든 downgrade를 해석 전에 거부해(ADR-021·102) 빨갰다. 정책을 따르고 왕복은 scratch
  DB에서 손으로 확인했다(PR 본문).
- **리뷰 반영(1·2차, main `6e1eb9ed` 위로 리베이스).** ADR-109의 자기모순(결과 "부정·비용"의 롤아웃 첫 tick 전량 계획,
  열린 결정 8)을 소유자 결정(첫 토큰 = 기준선)으로 고쳤고 커서 정의를 "계획했거나 기준선으로 기록한 토큰"으로,
  ADR-110 결정 6·단계 9의 "풀로드 → 센서 계획 1건"을 "커서가 비면 기준선·0건, 그 뒤의 풀로드만 계획"으로 고쳤다.
  `select_stale_feature_ids`에 keyset 커서 `after`(호출자가 geo 의존 dataset으로 한정 — T-GR-04), `GeoAttemptEvidence`의
  `geocode_attempted` 삭제('받았다'가 '시도했다'를 함의 — 판정에 안 쓰이는 필드), `address-geocoding.md` §2 시그니처를
  구현에 맞춤, T-GR-04 acceptance 수정 파일에 스탬프 repo(`coverage()`). 테스트: ①→② 순서·④의 geocode run 조건·
  덮어쓰기의 version token·keyset 페이지.
- **충돌 마커 정리·가드(별도 커밋).** main에 몇 주 전 리베이스가 남긴 `|||||||` 줄 둘(`docs/archive/journal-2026-08d.md`
  `## 2026-08-31 — head 값 고정을…` 앞, `docs/tasks-done.md` `## 2026-08-30 — T-VN-M05-MANAGER-PIN-ROTATION…` 앞)을
  지웠다 — 마커 줄 하나씩만(98 B·121 B), 앞뒤 절은 저장소에 각각 1회뿐이라 중복 본문은 없다. 아카이브는 읽기 전용이지만
  마커는 본문이 아니라 깨진 이관의 잔재라 규약 §8의 복구 예외로 본다. 같은 날 이 PR과 #1325의 리베이스도 journal·
  resume에 같은 줄을 남겼다(리뷰가 잡음). `tests/lint/test_docs_have_no_conflict_markers.py`가 docs·루트 Markdown의
  줄머리 마커를 막는다(UTF-16 보고서 하나는 BOM으로 읽는다) — 정리 전 main에서는 빨갛다.
- **3차 리뷰 반영.** ADR-109 규칙 ②·acceptance §T-GR-03 수정 파일을 `geocode_obtained_code`(시도 필드 없음)로 맞췄고,
  `address-geocoding.md`의 커서 정의·롤아웃 문단(backfill 뒤 첫 토큰 = 기준선, '순서와 무관하게 1회' 문장 삭제)과 §7 센서
  행·acceptance §T-GR-05에 기준선 케이스(빈 커서 + 토큰 → 커서 기록·계획 0)를 더했다. keyset 질의는 첫 페이지와 다음
  페이지를 다른 문장으로 나눴다(`(:after IS NULL OR …)`는 generic plan에서 범위 스캔을 잃을 수 있다).
- **게이트.** 통합: NULL·형식 위반 토큰은 outcome 셋 모두 DB가 거부, 토큰 없음 = 0건, stale 5분기와 "현재 토큰 None →
  0건", primary 링크·활성·dataset 범위, 런타임 role 쓰기·읽기, CASCADE. 단위: 응답 `dataset`
  있음/없음/형식 위반, `dataset_version()` 경로·본문 `{}`·`available=false`·계약 위반 typed 오류, 빈 답 계수(reverse 6 =
  정상 3·빈 답 2·전송 실패 1 → calls 6·failures 1·empty 2), 판정 표 전 행.

## 2026-10-15 — geo·transport client connect timeout 분리(T-MAP-02, ADR-110 결정 3): 브랜치 `feat/t-map-02-connect-timeout`

- **왜 지금.** geo·weather·transport가 2026-10-14~15 odroid로 옮겨졌다(ADR-110 사실 갱신 절). 같은 호스트의
  피호출자가 죽으면 커널이 즉시 RST를 주지만, 다른 호스트가 꺼지면 SYN이 응답 없이 timeout까지 간다. Map geo client는
  timeout 하나(10 s)라 연결 수립에도 그만큼을 썼고, admin 이슈 액션 2곳은 timeout 인자가 없었으며(httpx 기본 5 s)
  offline upload·CLI 2곳은 `10.0` 하드코딩이었다. 원래 순서는 "transport 플립 전 배포"였으나 플립이 먼저 일어났다 —
  소유자 결정(2026-10-15)으로 해제 조건은 "머지 뒤 첫 prod 배포"다.
- **바꾼 것.** 설정 필드 2개(connect, 기본 4 s — 첫 판은 2 s였으나 리뷰에서 올렸다: Linux SYN 재전송이 약 1 s·3 s라
  2 s는 첫 재전송만 기다리고, geo `_post`는 재시도가 없어 과부하 odroid의 느린 수립 한 번이 MOIS run 전체를 죽인다;
  Manager compose는 이 env를 넘기지 않으므로 기본값이 운영 값이다), 팩토리 둘(`geocoding.geo_http_timeout`·`provider_fetchers.
  transport_http_timeout`), geo 8곳·transport 3곳이 팩토리를 쓴다. `httpx.Timeout(connect=…, read=…)` 둘만 주는 꼴은
  httpx 0.28이 `ValueError`로 거부하므로 첫 위치 인자(기존 timeout)가 read·write·pool을 덮는다. 문구: `GEO_HEAVY_POOL`
  근거('n150 디스크 대기' → 'odroid geo CPU 보호'), `mois_geocode_concurrency` 설명, transport base URL 설명,
  `.env.example`의 standalone 주석과 새 키 2개.
- **게이트.** (1) 팩토리 값(필드를 바꾸면 빨강), (2) accept 큐를 미리 채운 `listen(0)` 서버로 SYN을 드롭시켜 geo client와
  실제 transport fetcher가 connect + 0.5 s 안에 실패하는지(전제 — 새 connect가 매달리는지 — 를 먼저 확인), (3) lint:
  `KorTravelGeoRestClient(`·`_transport_connection(`을 부르는 함수 안의 모든 `httpx.AsyncClient(`가 `timeout=<팩토리
  호출>`이 아니면 빨강(리터럴·부재·settings float 직접 전달·그 함수 밖에서 만든 client). 낡은 대역 하나
  (`test_resources.py`의 `http.timeout == 2.5`)를 새 계약으로 고쳤다.
- **관찰(범위 밖).** 2026-10-15 08:3xZ odroid geo `/v2/reverse`가 Map 컨테이너에서 세 번 약 9 s 뒤 504였다가 다음 호출
  1.0 s 200. connect가 아니라 응답 지연이라 이 변경과 무관하고 read 상한(10 s)은 task 범위대로 그대로 뒀다.

## 2026-10-15 — ADR-110 사실 갱신: geo·weather·transport가 실제로 odroid로 갔다: 브랜치 `docs/adr-110-odroid-facts`

- **무엇이 바뀌었나.** ADR-110 초안(2026-10-13)은 "포트·URL 동일, 호스트만 이전"을 전제했지만 소유자가 2026-10-14~15
  Manager ADR-58 "잠정 시행"으로 세 스택을 먼저 옮기고 odroid 소비자 포트를 통일했다 — geo `12501`(UI `12505`), weather
  `12201`, transport **API gateway `12301`**(odroid backend `12302`·frontend `12303`). Map 소비자 값은 Manager #476/#479의
  compose 기본값으로 옮겨졌다(Map 저장소 변경 0 — ADR-110 결정 1이 맞았다). n150 공용 workspace는 concierge·map·pinvi
  세 location, geo Dagster는 odroid 자체 plane.
- **확인한 방법**(2026-10-15 08:34~08:40Z, n150 읽기 전용, 상태 코드만 출력): Map api·code-server env의 geo/transport base가
  odroid; Map API 컨테이너에서 odroid geo `/v2/reverse`·`/v2/dataset/version` 200; code-server에서 transport gateway export
  토큰 200·무토큰 404; n150에 transport·weather 컨테이너 0개, geo-api·ui는 남아 있음(Manager `map → geo` depends_on 때문,
  workspace에는 없음); chain t1015d(Map `4931f9c0` + PinVi `44d8ecc8`) D1 11 passed·D2 `phase=passed`.
- **관찰 하나.** 같은 확인 직전 odroid geo `/v2/reverse`가 세 번 약 9 s 뒤 504였다가 다음 호출은 1.0 s에 200. 원인은 보지
  않았다 — Map 단일 timeout 10 s에 가깝다는 점만 적는다(T-MAP-02가 다루는 것은 connect이지 이 read 지연이 아니다).
- **결정과 어긋난 순서.** T-MAP-02(connect 분리)는 "transport 플립 전 배포"였는데 플립이 먼저 일어났다. 소유자가
  2026-10-15 해제 조건을 "머지 뒤 첫 prod 배포"로 바꿨다(acceptance §T-MAP-02).
- **리뷰 반영.** odroid geo는 2026-10-12 n150 백업의 dump 복원(`pg_restore` rc=0, alembic `0029`)이고 `data_token`은 그
  위에서 처음 저장됐다. Map geo 키는 복원으로 보존됐다(활성 label `kor-travel-map`, 재발급 없음) — geo ADR-070 "실행 기록"
  (geo PR #575). 소유자 결정: '없음 → 첫 data_token'은 기준선이지 재계획이 아니다(ADR-109 역포인터; 구현은 T-GR-04/05).
- **문서.** ADR-110 머리말·"사실 갱신(2026-10-15)" 절 신설·컨텍스트/결정 5/후속의 포트·머지 상태 갱신(교차 ADR 셋은
  2026-10-13 main에 proposed로 머지돼 있었다), `integration-map.md` §1(transport·geo 행, Manager 행의 낡은 관측 포트
  12401/12301/12205 → 12102/12103/12104)·§2(그림의 transport 포트, LAN 단락)·§3(transport export 행)·§4(geocoding 행),
  CLAUDE.md geocoding 줄, ADR README 두 줄, ADR-109 역포인터. T-GR-00-LEDGER(#1323) `[x]`·이관.

## 2026-10-15 — journal·tasks-done 다음 경계 분리(T-GR-00-LEDGER): 브랜치 `docs/t-gr-00-ledger`

- **분리.** `journal.md` 209,356 B에서 가장 오래된 묶음 2026-09-20~25 8건(27,260 B)을 `docs/archive/journal-2026-09e.md`로,
  `tasks-done.md` 200,699 B에서 가장 오래된 두 절(2026-08-05 일괄 아카이브 110,174 B + 2026-08-04 889 B, 합 111,063 B)을
  `docs/archive/tasks-done-2026-08a.md`로 옮겼다. 경계는 fence 밖 `## ` 줄에서만 잡았다(두 경계 모두 fence 홀짝 0).
- **바이트 보존 검산**(분리 스크립트가 assert): journal 209,356 = 잔여 182,096 + 이동 27,260; tasks-done 200,699 = 잔여
  89,636 + 이동 111,063. 아카이브 본문은 이동 바이트와 같고 예외는 둘뿐이다 — tasks-done 쪽 상대 링크 4개(`tasks-done.md`,
  `runbooks/h35-prod-migration-cutover.md` ×2, `reports/h33-mislink-2026-07-29.json`)를 `../`로 재기준화(+12 B, 규약 §8의
  허용 예외)했고, 각 파일 끝 구분 빈 줄 1 B를 뗐다(앞선 아카이브와 같은 끝맺음). 머리말은 journal 161 B·tasks-done 166 B.
- **이름.** acceptance 초안은 `journal-2026-09c.md`라고 적었지만 09c(chain17 B 단계 수정 PR, 09-14~15)와 09d(#1319, 09-16~19)가 이미
  있어 규약 §8의 다음 글자 `09e`를 썼다. tasks-done 아카이브는 08월 첫 파일이라 `2026-08a`.
- **종결 이관.** T-GR-00(#1315 `f7affea8`)·T-MAP-01(#1316 `463453bf`)은 2026-10-13 머지·main lint.yml 초록을 `gh`로 확인하고
  `[x]`로 tasks-done에 옮겼다 — 두 절 모두 이 PR을 종결 소유자로 지정했다. T-GR-00-LEDGER 자신의 `[x]`는 머지가 조건이라
  다음 doc-only PR(ADR-110 사실 갱신)이 싣는다.
- **크기**(분리·이 항목 반영 뒤, 커밋 직전 `wc -c`): `journal.md` 184,071 B · `tasks-done.md` 91,029 B — 둘 다 ≤ 200,000 B.

## 2026-10-14 — D2 fixture `Alembic revision confirmation mismatch`: 확인 키를 repin이 API 이미지 head에서 유도: 브랜치 `fix/d2-fixture-alembic-head`

- 증상: Map 4931f9c0(#1319, head `406_feature_write_gate`) 배포 뒤 chain16 H(unit `d2-adr111h`)의 D2가
  `fixture-seed-failed`로 BLOCKED. `direct-seed.json.stderr`는 `scripts/admin_feature_live_fixture.py`
  `_prepare_fixture_connection`의 `fixture target Alembic revision confirmation mismatch`.
- 원인: 기대값 `E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_ALEMBIC_REVISION`은 `/root/.d2-live.env`의 **손으로 적은** 값
  (`404_transport_provider_identity`)이었다. repin은 이 키를 쓰지 않았고(2026-10-05 인계 문서가 "head가 바뀌면 손으로
  고친다"고 적었다), 405·406이 들어오는 동안 아무도 고치지 않았다. 백업 사본 기록상 이 키는 303→309→400→403→404로
  다섯 번 손으로 바뀌었다. DB(`alembic_version`)는 정상적으로 406이다 — fixture는 mutation 전에 멈췄다(잔여물 없음).
- 수정: `scripts/n150/repin.sh` 5단계가 4단계의 같은 Map API 컨테이너에서 `ktm-application-schema head`(이미지가 설치된
  migration graph만 읽는 attest 명령, API entrypoint head 게이트와 같은 정본)를 읽어 그 줄을 다시 쓴다. schema·revision
  문법·줄 개수 확인, 0600 임시 파일 + source 값 대조 + rename.
- 게이트: `tests/unit/test_n150_repin_derives_fixture_alembic_head.py` — 생산자(`docker/application-schema-head.py`)를 이
  저장소 graph 위에서 실제로 돌린 출력을 repin 프로그램에 넣어 옛 `404_…` 줄이 현재 head로 바뀌는지 본다(리터럴 head
  없음). 거부 경로 11가지, 호출 경로가 `api.Dockerfile`의 설치 자리·schema 상수와 같은지도 본다.
- 재실행: 호스트 `/root/repin.sh` 재설치 → chain16 재실행(D 단계가 새 키를 쓰고, G 단계 `adjudicate.sh`가 이번 BLOCKED를
  잔여물 0 실측 뒤 정리).

## 2026-10-14 — chain16 D1 판정이 ANSI 커서 제어 때문에 11/11 통과를 실패로 읽음: 브랜치 `fix/chain16-d1-ansi`

- 증상: 배포(Map 4931f9c0 + PinVi 2fa1c166) 뒤 chain16 F(D1)가 `11 passed (32.2s)`를 냈는데 `!! D1: 목록 11건이 전부 passed가 아니다`로 중단.
- 원인: Playwright line reporter가 진행 줄을 `ESC[1A ESC[2K`로 덮어써 마지막 줄이 `^[[1A^[[2K  11 passed`가 되고, #1318의 판정 `grep -qE "^ *$D1EXPECT passed"`가 줄머리 앵커에서 실패.
- 수정: `scripts/n150/chain16.sh` D1 출력에서 ANSI CSI 시퀀스를 `sed`로 걷어낸 뒤 판정. 판정 규칙(목록 수 == passed, skipped/did not run도 실패)은 그대로.

## 2026-10-14 — chain16 C단계(C7 executor 이미지) 실패 원인 규명 + `file:` 의존성 COPY 게이트: 브랜치 `fix/c7-executor-vendor-tgz` (PR #1320)

prod pair(Map 4931f9c0 · PinVi 2fa1c166) 배포 뒤 `/root/chain16.sh` C단계(unit `eb-adr111-10132219`)가
`scripts/build-c7-playwright-image.sh`에서 "executor image build failed (values redacted)"로 멈췄다.

- **원인은 소스가 아니라 일시적 네트워크다.** `docker buildx history logs`(BuildKit 이력, 스크립트의 `--quiet`·가림과
  무관하게 남는다)로 본 실패 빌드의 실제 출력은 `npm ci` 49.9초 시점 `npm error code ECONNRESET` / `network aborted`.
  같은 n150에서 같은 커밋 archive를 그대로(기본 umask, 스크립트와 같은 umask 077 둘 다) 다시 빌드하니 `npm ci` ·
  `verify:npm-tree` · `verify:next-sharp` 모두 통과했다. 같은 입력의 빌드 다섯 번 중 둘(둘 다 스크립트 경유, 49.9초·177초)이
  같은 `ECONNRESET`으로 죽고 셋(`--quiet` 포함)은 통과 — 플래그가 아니라 확률이다. 실패 시점 n150은 iowait 64~70%·swap
  in/out 진행(load 15~21)이었다. 재실행 한 번이면 지나가지만 같은 부하에서는 다시 날 수 있다.
- **보이지 않던 이유 둘.** ① 스크립트가 `--quiet`로 빌드하고 실패를 가린다 — 원문은 `docker buildx history logs <id>`에
  남는다(`docker buildx history ls`의 최신 Error 행). ② chain16 C단계가 `Result=success`를 찍었다 — `systemd-run
  --collect`가 실패한 unit을 즉시 회수해 `systemctl show -p Result`가 기본값을 돌려준다. 실제 판정은 뒤의 라벨 대조
  (옛 이미지 c4d17343 ≠ MAP)가 했다.
- **가설(vendor tgz 누락)은 기각.** `c7-playwright.Dockerfile`은 1a3c46737(10-06)부터 `frontend/vendor`를 `npm ci` 전에
  복사하고 `.dockerignore`도 그것을 빼지 않는다. 다만 그 수정에는 게이트가 없었다 — `frontend.Dockerfile`은 72242b1a0에서
  vendor를 복사했는데 C7 쪽은 따라오지 않은 틈이 실제로 있었다.
- **게이트.** `tests/unit/test_dockerfile_workspace_manifest_coverage.py`: 정본은 `npm ci`가 읽는 `package-lock.json`의
  `packages[*].resolved` 중 `file:`(워크스페이스 `link: true` 제외). `npm ci --workspaces`를 도는 모든 Dockerfile이 그
  stage에서 그 RUN **이전** build-context COPY로 각 경로를 WORKDIR/<path>(루트 `package.json`과 같은 자리)에 두고,
  `.dockerignore`가 그것을 빼지 않는지 본다. 하한(file: 의존성 ≥1·실재), `.dockerignore`/COPY 배치 matcher는 인라인
  규칙으로 자기검사. 1a3c46737^의 Dockerfile, vendor를 빼는 `.dockerignore`, 틀린 COPY 목적지 각각에서 빨갛게 된다.
- **재실행.** 소스 수정이 필요 없으므로 chain16을 배포된 같은 MAP/PINVI로 C단계부터 다시 돌리면 된다(핀 변경 없음).

## 2026-10-13 — 공용 PG lock table 고갈(53200) 근본 수정 — Feature advisory fence 전역 gate(ADR-111): 브랜치 `fix/bulk-curation-locks` (PR #1319)

2026-10-12 09:25Z부터 root `97ac4e01-…`의 `feature.finalize_provider_curation_root`가 dataset 99(`transport_fuel_stations`,
11,820 Feature)의 링크 Feature마다 `pg_advisory_xact_lock('feature-write:<id>')`를 잡다가 공용 PG(`max_locks_per_transaction=64`)
lock table을 고갈시켜 SQLSTATE 53200으로 롤백됐고, reconcile sensor가 30초마다 무한 재시도하며 같은 cluster 전 tenant를
깨뜨렸다(12:59:54Z prod sensor 정지 — 운영자 조치, 이 PR 범위 밖). 같은 패턴이 프로시저 여덟 곳에 더 있었다.

- **설계(ADR-111).** 전역 gate `feature-write-all`: 대량 writer 9개(finalize root·receipts, materialize, curated
  source/rule/theme create·patch·archive)는 종전 Feature 잠금 루프 자리에서 gate **배타** 1회, 단건 writer 6개(approve
  request, curation item create/patch/archive, manual item, promote candidate)는 `feature-write:<id>` 바로 앞에 gate **공유**.
  순서 `curation-import → feature-curation-write → feature-write-all → feature-write:<id> → curation-catalog-write`.
  "Feature 잠금을 그냥 지운다"는 기각 — curated theme/source/rule 명령·promote·approve는 `feature-curation-write`를 잡지
  않아 증명이 성립하지 않는다(ADR §3). Python은 `feature-write`를 잡지 않는다.
- **migration `406_feature_write_gate`.** 사이드카 15개(`_406_<루틴>.sql`) = head 원문에서 잠금 몇 줄만 바꾼 사본
  (생성 후 head 원문과 diff해 잠금 줄 외 차이 0 확인). 소유자 창 `ktm_curation_command_owner` →
  `ktm_feature_request_procedure_owner` → `ktm_feature_schema_owner`로 끝남(RESET ROLE 없음). receipt head CHECK에 406.
  head-schema.sql은 n150에서 `KTM_WRITE_HEAD_SCHEMA=1`로 재생성(+25/−121, 잠금 줄과 CHECK만).
- **sensor 하드닝.** 결정적 SQLSTATE(08·40·57 class와 53300·55P03·55006 제외) 실패는 tick을 종전대로 실패시키되
  cursor `last_failure{run_id, SQLSTATE, count}`만 갱신(watermark 불변). 같은 run·같은 SQLSTATE 5연속 + terminal run이면
  `abandon_dagster_feature_run`이 기존 terminal 전이(`failed`/stage `failed`)로 root를 닫고 `feature_operation.reconcile_abandoned`
  error 로그. 새 상태·컬럼 없음(`quarantined_at`은 migration 소유라 쓰지 않음). ledger가 비면 cursor 모양은 종전 그대로.
- **테스트(효과 결박).** `tests/integration/test_feature_write_gate_lock_budget.py` — lock table 칸 수(설정에서 유도)의
  2배 Feature를 한 dataset에 링크하고 root 완결, 그 트랜잭션의 advisory lock 수 < 16. n150 실측: 405 스키마(406 제거)에서
  `asyncpg OutOfMemoryError: out of shared memory`로 **red**, 406에서 green. `tests/lint/test_feature_write_lock_order.py` —
  head 전 루틴(203)을 중첩 CALL까지 펼쳐 Feature 잠금 스칼라·gate 선행·전역 순서·공유→배타 승격 금지; 406 전 head에서
  위반 24건으로 red, 심은 위반 셋으로 탐지기 red 확인. sensor unit 6건(상한 도달·일시 SQLSTATE 미계수·다른 실패 리셋·
  진행 중 run 미닫힘·닫기 실패 재시도·cursor 하위호환).
- **열린 것.** `finalize_provider_curation_receipts`는 호출자 없음(지우지 않고 같이 고침). 서로 다른 dataset 대량 writer는
  이제 직렬화된다. 배포·sensor 재시작은 운영자 몫.
- **적대 리뷰 2건 반영(같은 브랜치, #1318 위로 리베이스).** 둘 다 잠금 순서·교착 결함은 찾지 못했고 CI가
  빨갰다. (1) BLOCKER — 통합 검사가 세션 공유 DB에 1.5만 Feature·active dataset·done job을 남겨 뒤의
  `test_mois_loader.py` 2건(glibc lane)을 깼다 → 그 모듈만의 DB를 같은 컨테이너에 만들어 head까지 올리고 지운다;
  active rule 하나를 걸어 중첩 materialize도 같은 규모로 돌린다(`observed_candidate_count == Feature 수`).
  (2) HIGH — 53200은 cluster의 다른 tenant가 일으킬 수 있으니 세면 안 된다(406 전에 sensor가 켜지면 2분 반 만에
  97ac4e01을 닫는다) → root를 닫는 SQLSTATE는 22/23/P0 허용 목록뿐, 그 밖은 cursor `retry_after`로 30s→15분 backoff.
  (3) MED — root 완결은 `feature-curation-write`를 든 채 gate를 기다리지 않는다(`pg_try_advisory_xact_lock`, 바쁘면 55P03);
  단건 writer 여섯은 `SET lock_timeout TO '5s'`, API는 55P03 → 503 `LOCK_TIMEOUT`(OpenAPI 바이트 불변, openapi-drift 초록).
  abandon 통합 검사(root failed/failed, done member 그대로, 로그 1행에 `provider_dataset_ids`·`action`, 두 번째 호출
  blocked/terminal). rollback 시 cursor 처리 ADR에 기록. (4) LOW — 대량 명령 여섯의 죽은 범위 재검사(두 scan + 40001)
  제거, 호출자 없고 gate 앞에서 행을 갱신하던 `finalize_provider_curation_receipts` DROP, lint가 `ops`·`provider_sync`
  호출과 행 쓰기의 trigger까지 펼친다(심은 trigger 위반으로 red 확인). ADR-111에 새 Feature에도 gate를 잡는 이유.
- **함정.** 시드의 `created_at`·`started_at`을 `clock_timestamp()` 두 번으로 넣어 μs 차이로
  `ck_import_jobs_ck_import_jobs_feature_engine_timeline`에 걸렸다 — 한 문장의 `now()`로.
- **델타 리뷰 반영(00630d19 위).** 마이그레이션·테스트는 GO, 재시도 논리에 HIGH 하나. (H1) 실패한 run 하나가
  tick 전체를 실패시켜 두 cursor가 멈추고 DB page에 닿지 못했다 — 42xxx·54000·SQLSTATE 없는 예외 같은 영구 실패면
  15분 backoff 아래 reconcile 전체가 무기한 선다. → run별 `deferred` 표로 실패한 run만 미뤄 두고 watermark·같은 page·
  DB page를 계속 돌며, 미뤄 둔 run은 시각이 되면 run_id로 다시 집는다(표 최대 200). 변이 확인: 앞 run이 계속 실패해도
  뒤 run과 DB page run이 같은 tick에 반영된다(`test_a_parked_run_does_not_block_the_others`). (M1) 같은 실패 5연속에
  `feature_operation.reconcile_stalled`를 한 번. (M2) 닫기는 `applied`일 때만 표에서 지우고, `blocked`면 표에 남겨 다시
  닫지 않고 멈춘 run으로 올린다(잘못된 "failed로 닫음(outcome=blocked)" 로그 제거). (M3) rollback은 `deferred` 키만 뺀
  cursor `--set`(prod는 null cursor 초기화 거부라 `--delete` 금지), 405 재배포 약속 대신 fix forward. (M4) 55P03은
  30초 고정 backoff, ADR에 "공유 보유자도 try를 막는다". (L) `_sqlstate`/`sqlstate_of`는 `orig`·`__cause__`만;
  API는 typed `DBAPIError` 처리기(55P03만, 나머지는 다시 던져 종전 500); lint는 lock 문장의 어떤 FROM도 scan으로 —
  그래서 `patch_curation_item_command`의 두 Feature 잠금을 `LEAST`/`GREATEST` 두 스칼라 문장으로 바꿨다. CHANGELOG·
  journal·resume에 남아 있던 diff3 base 표지(`|||||||`) 세 줄 제거.
- **3차 리뷰 — 미뤄 두는 표를 걷어내고 단순하게.** run별 `deferred` 표가 새 손실 경로(넘침으로 버린 Dagster 쪽 run은
  watermark가 이미 지나 DB page에도 없으면 영영 사라진다)와 재시도 폭주(tick당 실패하는 무거운 완결 최대 ~600건, 평가
  timeout 60초를 넘겨 cursor가 안 써지는 tick)를 만들었다. 소유자 원칙(단순하게)대로 걷어냈다: Dagster page는 **실패한
  머리 run에서 멈추고** watermark를 마지막으로 반영한 run에 둔다(건너뛰는 것이 없으니 잃는 것도 없다). cursor에는
  `head_failure` 하나, 물러선 동안 Dagster page를 통째로 쉰다. DB page는 매 tick 실패 3회·20초 예산 안에서 돌고 실패는
  기록하지 않는다(keyset이 다시 집는다). 닫기 규칙은 그대로(22/23/P0·머리·terminal·5회), `blocked/terminal`은 지나가고
  `blocked/cancellation`은 다시 한다. 55P03은 멈춤 보고 제외. `reconcile_stalled` 메시지에 이벤트 이름(`q` 검색)과
  running/terminal에 맞는 조치 문구. 실행 manifest 해석은 카탈로그 부재(`FeatureOperationInvariantConflict`)만 guard 거부로
  — 일시 실패가 관측 오류로 둔갑해 watermark를 지나가던 구멍(테스트 대역이 `LookupError`를 던져 가리고 있었다). 변이 확인
  둘: watermark를 지나가게 바꾸면, DB 예산을 없애면 해당 테스트가 빨개진다. journal 2026-09-16~19 7건을 아카이브로(§8,
  분리 전후 본문 sha256 `97fd54c2…` 동일). runbook은 pair 명시·preflight·systemd-run·원장/cursor 확인으로.
- **분할 결정 — sensor 재시도 설계를 되돌리고 후속으로.** 최종 리뷰(6d0ebfc98)가 backpressure 판에서도 HIGH 셋을 더 찾았다
  (DB root 없는 닫을 수 있는 머리의 영구 고착, 모든 lock_timeout 55P03을 gate 바쁨으로 봄, 서명이 번갈아 바뀌면 횟수
  초기화) — 설계가 매 판 새 구멍을 냈다. 406이 고착의 원인을 없애므로 sensor·`abandon_dagster_feature_run`·
  `reconcile_stalled`/`reconcile_abandoned` 로그와 그 테스트·대역을 origin/main으로 되돌렸다. main sensor에서 55P03은
  그냥 tick 실패 → 30초 뒤 재시도이고 닫는 경로가 없다. manifest 해석의 guard 축소는 남겼다 — main sensor에서 일시
  실패가 이제 다른 DB 실패처럼 tick을 실패시킬 뿐 관측 오류로 watermark를 지나가지 않는다. 리뷰 결과는 ADR-111 결정 4와
  `T-RECONCILE-RETRY`(해제 조건: 잃지 않음·tick 시간 유계·경과 시간 알림·gate 전용 SQLSTATE·명시 목록만 닫기)로.
- **migration 번호.** #1319가 406(`406_feature_write_gate`)을 쓰므로 Track 1(ADR-109)의 계획 번호를 하나씩 민다 — `feature_geocode_stamps` 406 → 407, `kor_travel_geo_releases` 407 → 408(tasks·acceptance·ADR-109·address-geocoding).

## 2026-10-13 — admin e2e 전체가 로드 단계에서 죽던 결함(ESM 전용 `@kor-travel/ui`): 브랜치 `fix/e2e-esm-kor-travel-ui`

n150 chain16 D1(Map `c4d17343`)이 테스트를 하나도 돌리기 전에 `Error: Package subpath './navigation' is not defined by
"exports" in …/@kor-travel/ui/package.json`으로 끝났다(require stack `src/lib/auth.ts:1` ← `e2e/auth-session.ts:5` ←
`e2e/live/auth.setup.ts:4`). acde3726(2026-10-06)이 `auth.ts`에 `@kor-travel/ui/navigation` import를 넣었는데, vendored
`kor-travel-ui-0.1.0-dev.6.tgz`는 `"type":"module"`이고 `exports`에 `types`+`import` 조건만 있다. admin frontend는
`"type":"module"`이 아니라 Playwright가 e2e TS를 CJS로 변환해 `require()`하므로 그 subpath를 해석하지 못한다. Next·tsc·
eslint·vitest는 모두 ESM/번들러 해석이라 통과했다.

- **영향 범위(n150 실측, `playwright test --list`).** `c4d17343`에서 mocked(`playwright.config.ts`)·live·cache-target-streams
  세 config 모두 rc=1 — mocked `e2e/auth.setup.ts`도 같은 `auth-session.ts`를 쓴다. 즉 10-06 이후 D1·M05 등 live와 mocked
  checkpoint 모두 로드 불가였다. CI가 못 잡은 이유: GitHub 워크플로 어디서도 Playwright spec을 로드하지 않는다
  (`frontend.yml`은 "e2e는 서비스가 필요해 n150에서 돈다"며 제외).
- **수정.** `SESSION_COOKIE_NAME`을 import 없는 `src/lib/session-cookie.ts`로 옮기고 `auth.ts`는 재export, e2e 두 곳
  (`e2e/auth-session.ts`, `e2e/live/cache-target-streams-isolated.live.spec.ts`)은 새 모듈에서 가져간다. 대안이던 frontend
  `"type":"module"`(Playwright ESM 로드)은 next/eslint/postcss config와 스크립트 전체의 모듈 해석을 바꿔 범위가 크다.
- **재발 방지(효과 결박).** frontend 패키지 `e2e:list` = 세 config의 `playwright test --list`, `frontend.yml`이 vitest 뒤에
  실행한다. 서비스·브라우저 없이 spec import 그래프를 실제로 require한다. n150에서 `c4d17343` 사본은 세 config 모두 rc=1
  (같은 오류), 이 브랜치는 rc=0(mocked 271 tests/28 files, live 1142/28, cache-target-streams 1/1) — 검사가 이 결함에서
  빨갛게 되는 것을 확인했다.
- **첫 live 실행(`bb602ea7`).** n150 prod 대상 읽기 전용 D1 4 spec(`--workers=1`): 11건 중 9 passed, 2 failed — live
  `auth.setup.ts`를 포함해 전부 로드·실행됐다(이전엔 0건). 처음엔 두 실패를 "무관·범위 밖"으로 적었으나 적대 리뷰
  (HIGH-2)가 chain16 D1은 spec 하나만 실패해도 죽으므로 둘을 남기면 D1이 계속 빨갛다고 짚어 **이 PR에서 고쳤다**(아래).
- **리뷰 반영 1 — `home-dashboard-roundtrip`(spec 결함).** 첫 실행 행을 `getByRole("row", {name: kind})`로 찾아 첫 페이지에
  같은 kind가 여럿이면(prod `import_job` 8행) strict mode 위반이었다. id(`shortId`)+kind 필터로 찾고 `toHaveCount(1)`.
- **리뷰 반영 2 — `admin-scenario-catalog` "pipeline live UI calls datasets catalog…"(실제 prod 결함).** 화면에 "Dagster
  연결 불가 — 응답 전체 대기 상한 초과"와 큐 sensor 차단 alert가 떠 `queueOperational=false`, 갱신 요청 dialog(=
  `/v1/ops/datasets` 호출)가 렌더되지 않았다. 원인은 PinVi #581과 같다: overview·schedules·summary 세 GraphQL 문서의
  `ticks(limit: 3)`가 `afterTimestamp` 없이 instigator의 전체 tick 이력을 읽는다(공유 `dagster_shared.job_ticks` 약 40만
  행). 수정: `dagster_graphql`에 `SCHEDULE_TICK_WINDOW_SECONDS`(2일)·`SENSOR_TICK_WINDOW_SECONDS`(1시간)·
  `MAX_TICKS_IN_WINDOW`(300)와 `tick_window_variables()`를 두고 세 문서가 `afterTimestamp: $scheduleTicksAfter|$sensorTicksAfter`를
  싣는다. OpenAPI 변경 없음(PinVi 재vendor 불필요). spec은 전제(overview HTTP 성공, 큐 sensor 차단 alert 부재)를 먼저 단언해
  원인을 메시지로 낸다.
- **실측(n150, 127.0.0.1:11002, 읽기 전용, 문서별).** overview(sensor tick만): 창 없음은 이 시점 4회 모두 **HTTP 500 at
  15.1~15.4초**(webserver statement timeout; 앞서 cold 10.0초·warm 1.3초도 봤다) → 창 있음 **0.08~0.12초**(같은 시각 교차
  측정 4회). 단 디스크 대기가 큰 순간(load 12~14, iowait 44~52%) 창 있음 첫 호출 1회가 27.4초였다 — 창은 읽는 행 수를 줄일 뿐
  n150의 I/O 정체까지 없애지는 못한다. schedules: 창 있음 0.18~0.24초. summary: 창 있음 0.20~0.22초(2일 창 기준; 62일
  창일 때 0.27~0.54초·0.50~0.53초). 오늘은 Map schedule이 전부 STOPPED라 schedule 쪽 행은 거의 없다.
- **schedule 창 2일(리뷰 4라운드 MED).** 처음엔 월간 cron(`10 3 1 * *`)을 덮으려 62일(최장 주기 2배)로 두었으나, Dagster
  `get_ticks`는 `selector_id = X OR (selector_id IS NULL AND origin = Y)`라 인덱스 순서 scan을 못 하고 창 안 전 행을 읽어
  정렬한다 — 비용은 창 안 tick 수에 비례한다. 같은 sensor 하나의 EXPLAIN ANALYZE(`BEGIN READ ONLY`): 창 안 211행 0.45초,
  9,690행 cold **7.4초**, 33,971행 warm 0.14~0.22초. 62일은 schedule이 전부 STOPPED인 오늘만 쌌고, `*/10` schedule
  (`feature_notice_transport_highway_incidents_ten_minute_schedule`) 하나가 켜지면 8,900행 → 7초대로 돌아간다. 검토한
  대안: schedule마다 자기 cron으로 창을 잡는 것(두 번째 요청·별칭 문서·cron 파서가 세 호출 지점에 필요)보다, **창 하나 +
  비용 상한 테스트**가 단순하다 — `test_schedule_window_cost_is_bounded_by_the_densest_cron`이 배포 Definitions의 최단 cron
  간격으로 창 안 tick 수(`*/10` × 2일 = 288)를 `MAX_TICKS_IN_WINDOW` 이하로 강제해, 더 조밀한 schedule을 더하면 창을 줄일지
  상한을 올릴지 고르게 한다(sensor도 같은 상한, 15초 × 1시간 = 240). 대가: 주간·월간 schedule은 마지막 tick이 2일보다
  오래면 `recent_ticks`가 비고, 1시간 넘게 멈춘 sensor도 그렇다. 관리자 UI는 RUNNING인데 비면 "최근 2일/1시간 tick 없음"으로
  표시한다(`src/lib/dagster-tick-window.ts`; 값은 같은 테스트가 API 창과 대조). sensor `typeSpecificData.lastTickTimestamp`로
  멈춤을 드러내는 안은 응답 DTO에 필드를 더해야 해(OpenAPI 변경 → PinVi 재vendor) 이번엔 표지로 그쳤다. 운영자 cron
  override(`load_schedule_cron_overrides`)는 정의에 없어 테스트가 못 본다 — override 간격이 2일보다 길면 같은 빈 목록, `*/10`보다
  조밀하면 비용이 그만큼 커진다.
- **효과 결박 테스트.** `tests/unit/test_dagster_tick_window.py`가 세 문서를 Map code location을 in-process로 실은 Dagster
  (1.13.24)에 실행해 storage `get_ticks`가 받는 `after`를 기록한다. main의 문서로 되돌리면 세 건 모두 빨갛다(n150 실측:
  summary는 `after=None`, overview·schedules는 batch 경로로 빠져 `get_ticks` 0건). 시계를 고정하고 instigator 종류별
  `after` 다중집합을 대조해 두 변수를 바꿔치기해도 빨갛다. 창 비용 상한(위), sensor 창 ≥ 10×최장 최소 간격, tick 선택 문서
  목록(`Assign`·`AnnAssign` 모두), UI 표지 값도 본다. 기존 router·service 테스트는 시계를 고정해 호출 지점 변수까지 대조한다.
- **리뷰 반영 3 — 게이트·config.** `scripts/verify-all-gates.sh`에 `e2e:list` 게이트(빠져서 CI pytest의
  `test_gate_script_covers_every_ci_blocking_command`가 빨갰다, HIGH-1). `e2e:list`의 live 실행은
  `e2e/reporter-load-check.ts`로 커스텀 reporter 둘(C7 redacted, mocked failure)을 **로드만** 한다(인스턴스·훅 없음 — n150에서
  파일 0개 확인, reporter에 ESM 전용 import를 넣으면 rc=1). `playwright.live.config.ts`의 top-level `testIgnore`가 chromium
  project의 `testIgnore`에 대체돼 격리 전용 `cache-target-streams-isolated` spec이 live suite에 들어가 있었다 — project-level로
  옮겨 live 목록이 1142/28 → 1141/27. CI 단계는 `forbidOnly`로 `test.only`도 잡는다(n150에서 `CI=1` 변이로 확인);
  `verify-all-gates.sh`도 `CI=1`로 같은 조건에서 돈다. `scripts/n150/chain16.sh` D1은 `--list` 개수만큼 passed여야 초록이고
  skipped·did not run·interrupted도 실패로 본다(전에는 failed/flaky 줄이 없으면 초록).
- **D1 재실행(브랜치 사본, prod 읽기 전용).** 11건 중 **10 passed, 1 failed**. `home-dashboard-roundtrip`은 이제 통과한다. 남은 1건은 `admin-scenario-catalog`의 새 전제 단언이 "큐 sensor 차단 alert — Dagster 상태 스냅샷을 신뢰할 수 없습니다"로 정확히 원인을 내며 실패한 것이다 — prod Map API가 아직 창 없는 문서를 쓰기 때문이고, 이 PR의 API 수정은 배포 뒤에야 live에 보인다. 배포 전 증명으로 이 브랜치의 세 문서를 그대로 prod Dagster에 보냈다(위 실측). **D1 11/11은 Map API 배포 뒤 재실행으로 확인할 일이다.**

## 2026-10-13 — chain17 B 단계가 같은 Map·새 PinVi 회전을 건너뛰던 결함: 브랜치 `fix/chain17-rotate-when-pinvi-changes`

n150 chain t1013e(2026-10-13 09:11Z)에서 `/root/chain17-pv.sh`(운영자 변형, `PINVI_OVERRIDE` 추가본)가 B 단계에서
`원장 map == MAP`만 보고 "이미 회전됨 — 건너뛴다"를 택했다. 인자로 준 새 PinVi `2fa1c166`은 회전되지 않았고, 원장의
옛 PinVi `97f2baf2`로 재구축·C6c 스모크가 돌아 1분 만에 같은 실패가 재현됐다. 수동 `rotate-pinned-pair c4d17343 2fa1c166
"<reason>"`은 성공했다 — registry는 같은 Map·다른 PinVi 회전을 허용하고 pair 전체가 같을 때만 거부한다. 즉 건너뛰어도
되는 조건은 "원장 map·pinvi 둘 다 인자와 같다" 하나뿐인데 스크립트는 절반만 보고 있었다.

- **수정(`scripts/n150/chain17.sh`, 정본 — ADR-102 결정 6).** (1) B 단계 skip 조건을 `map == MAP && pinvi == PINVI`로,
  하나라도 다르면 `rotate-pinned-pair`를 부른다. 회전 뒤 검증도 map·pinvi 둘 다 원장과 대조한다(map만 보면 같은 구멍이
  거기서 다시 열린다). 원장 읽기는 기존 `ktdctl pin show | awk` 패턴을 `pin <key>` 한 helper로 묶어 0·B 단계가 같이 쓴다.
  (2) 운영자가 `/root/chain17-pv.sh`로 손수 들고 있던 `PINVI_OVERRIDE`를 정본에 흡수했다 — README가 "호스트 사본을 손으로
  고치지 않는다"고 못박는데 변형이 호스트에만 있었고, 이 결함은 그 변형에서만 드러난다(정본은 PinVi를 늘 원장에서 읽어
  map만 봐도 pair가 같았다). 생략하면 원장의 **현재** pinvi를 그대로 다시 핀하므로, 원장과 다른 PinVi를 올릴 때는
  같은 Map이든 새 Map이든 `PINVI_OVERRIDE`가 필요하다 — 헤더·README가 "같은 Map일 때만"으로 좁게 읽히던 것을 적대
  리뷰(MED)가 잡아 그렇게 고쳤다. (3) launcher 경로를 `ROTATE` 변수로 올렸다(`KTDCTL`·`DRIVER`와 같은 꼴) — 테스트가
  stub으로 바꿔 끼우는 자리이고, 리터럴은 상단 한 곳에만 있다. (4) 리뷰 LOW 둘도 반영: 0단계 pinvi 출처 라벨이
  `${X:+..}${X:-..}` 결합으로 override 때 `PINVI_OVERRIDE<sha>`로 붙어 찍히던 것(`-pv` 변형에서 그대로 옮겨온 표시
  결함)을 `PINVI_SOURCE` 한 변수로; B 단계는 원장을 못 읽은 빈 값을 "다른 pair"로 보지 않고 비교 전에 그 사유로 멈춘다
  (전에는 회전을 시도해 '회전 실패'로 원인이 가려졌다).
- **테스트(효과 결박).** 새 `tests/lint/test_chain17_rotates_when_only_pinvi_changes.py`: 스크립트의 B 단계 본문과
  `die`·`say`·`pin` 정의를 잘라 가짜 `ktdctl`(원장 파일)·가짜 `rotate-pinned-pair`(호출 기록 + 원장 갱신) 위에서 bash로
  실행한다. 같은 pair → rotate 호출 0·skip, (같은 map·새 pinvi / 새 map·같은 pinvi / 새 pair) → `rotate MAP PINVI REASON`
  정확히 1회, launcher가 0으로 끝났는데 원장 pinvi가 그대로 → exit 1·C로 가지 않음, 원장이 비어 있거나 pinvi가 없음
  → rotate 호출 0·exit 1. 추출이 빈 본문을 집지 않았는지도 먼저 본다. 기존 `test_n150_host_scripts_drop_attestation_chain.py`의 hard-gate 순서 단언은 launcher **호출** 자리
  (`"$ROTATE" "$MAP" "$PINVI" "$REASON"`)로 옮기고 `ROTATE` 대입값을 대조한다. `bash -n`은 기존 파라미터 테스트가 덮는다.
- **문서.** `scripts/n150/README.md` 표·"무엇이 Manager 쪽인가"에 같은 Map·새 PinVi 사례 한 줄, CHANGELOG `[Unreleased]`.
  ADR-102는 B 단계를 서술하지 않아 손대지 않았다.
- **journal 분리(§8).** 이 엔트리로 `docs/journal.md`가 227,144 B가 되어 상한 225,280 B를 넘었고
  `tests/unit/test_docs_archive_links.py::test_every_docs_markdown_stays_within_readable_limit`이 빨갰다(적대 리뷰 HIGH).
  하단 2026-09-14 6건·2026-09-15 2건(8건, 본문 21,744 B)을 `docs/archive/journal-2026-09c.md`로 옮겼다 — 옮긴 절 본문의
  sha256이 분리 전후 같음(`36527129…`), 상대 링크 없음, 현행 창은 2026-09-16~. 분리 뒤 journal 205 KB.
- **운영 후속(외부).** 머지 뒤 운영자가 `sudo install … scripts/n150/chain17.sh /root/`로 재복사하면 `/root/chain17-pv.sh`는
  필요 없다. 이 PR은 n150을 바꾸지 않았다(`/root/chain17-pv.sh` 읽기만).

## 2026-10-13 — geo·transport 호스트 odroid 이전(Track 2) Map 쪽 문서: 브랜치 `docs/adr-110-geo-transport-on-odroid`

문서만 바뀐 PR(doc-only, origin/main `f7affea8` 위). Track 2 설계(geo·weather·transport 세 스택과 그 PG를 odroid로,
포트·이름 동일·host만 n150 → odroid; 3차 적대 리뷰·2026-10-13 odroid 실측 반영본)에서 **Map 저장소가
책임지는 것**만 ADR-110(proposed, 미구현)으로 옮기고 `T-MAP-01`·`T-MAP-02`를 열었다. 코드·`.env.example`·compose·
CHANGELOG·OpenAPI·테스트는 건드리지 않았다. 호스트 플립 자체는 Manager ADR-58·geo ADR-070·transport ADR-014의 일이다.

- **결정 요약(ADR-110).** (1) Map 저장소는 값을 바꾸지 않는다 — geo·transport origin의 정본은 오늘 Manager compose
  기본값 + root `.env`(geo 기본값은 Map 서비스 **4곳** `:1582,1723,1813,1920`·transport는 code-server `:1732-1733`,
  @08a515e; registry `hosts:` 파생은 Manager ADR-58 R2 — 오늘 registry에 host 필드 없음, 그 뒤 `.env` URL 재정의는
  validate 거부); 플립 뒤 `ensure map`은 Map target 전 서비스 재생성(옛 값 든 컨테이너 0개 게이트);
  `.env.example:198,234`는 standalone 값(주석은 T-MAP-02 코드 PR). (2) UI 재빌드
  없음 — BFF `/api/geo`는 런타임 `KOR_TRAVEL_GEO_INTERNAL_URL` 우선(`route.ts:3-6`), 빌드 인자는 공개 host라 변경 0
  (설계 §14-10은 열린 결정 1 — 설계는 추천 없이 두 선택지). (3) 장애 의미가 RST → timeout으로 바뀐다 — geo 10 s·
  transport 30 s 단일 timeout(`settings.py:159-164,537-542`)을 `httpx.Timeout(<기존>, connect=<connect 필드>)`(기본값이
  read·write·pool을 덮는다 — `Timeout(connect=, read=)` 둘만은 httpx 0.28.1에서 ValueError)으로 팩토리
  하나씩(geo `geocoding.py`·transport `_transport_connection` 옆)으로 분리(T-MAP-02, 코드 후속; **geo 8곳·transport
  3곳** — geo 8곳 중 `admin_issues.py:276,306`은 timeout 인자 없음(httpx 기본 5 s), `dagster/offline_uploads.py:50-53`·
  `cli/main.py:447`은 10.0 하드코딩이라 settings를 읽지 않는다; 적용 범위는 lint로 효과 결박), 회로차단은 Map에
  두지 않음(배치 호출이라 run 실패가 곧 신호; PinVi만), transport ±30 min 시계 검사는 fail-closed 유지. (4) geo
  공개 키는 **오늘도 대조된다** — 이전으로 바뀌는 것 없음(geo 면제는 admin 프록시 컨텍스트만, `security.py:154-170`;
  Map은 `X-KTG-API-Key`만 보냄 `geocoding.py:1289`; 08-13 401 사고가 저장소 안 증거). 위험은 geo 재적재로
  `public_api_keys`가 비는 것뿐 → 키 재발급·root `.env` 재적용·컨테이너 전부 재생성·키 경로 200이 플립 9단계 필수
  (외부 추적). VWorld 폴백은 Map #979 가드와 충돌해 채택 불가(열린 결정 3은 '추천 없음·(나)만 가능'). `9-전` curl은
  선택적 smoke로 격하. (5) transport export allow-list에 n150 LAN 주소 `/32`(transport 쪽 변경; XFF 불가). (6) ADR-109 amend(109 상단에 역포인터 한 줄) — `GEO_HEAVY_POOL`
  유지·근거만 'n150 디스크 대기' → 'odroid geo CPU 보호'; 센서·재지오코딩은 LAN 키 경로(RTT 9.7 ms, 전량 ≈2.5 h+
  추정); odroid 풀로드 뒤 플립 시 전량 재계획 **수용을 추천**(소유자 결정 대기 — 열린 결정 2, 대안은 운영자 UI skip;
  수용이면 mv_refresh 다음 날·야간 창 밖; dump 복원이면 0). (7) 전환 절차에서 Map이 하는 일은 단계 1·5·9-전·9·drill·11
  (설계 §11.2 발췌; 2~4b·8a/8b는 외부 단계로 Map이 확인할 선행 효과만 — odroid plane healthy·`targets validate`
  host·시계 동기) — 게이트는 효과(n150 피호출자 stop 상태에서 export 1회·키 경로 200·peer = n150 LAN 주소 로그·MOIS run
  예산 10 % 안 FAILURE — 유도: 첫 chunk 500행 ÷ 동시성 2 × connect 2 s ≈ ≤502 s, 10 s면 ≈2,502 s로 10 % 초과).
- **odroid 상태(FB §A3, 03:4xZ).** WSL 직접 ssh·NOPASSWD sudo·docker 그룹·NTP 수동 동기 **완료**; timesyncd 부팅
  사이클 drop-in·compose v2/buildx·방화벽·fstab bind·swapfile **미완** — ADR 컨텍스트 7에 완료/미완을 그대로 적었다.
- **설계와 달리 쓴 것(head `f7affea8` 재확인).** `docker/frontend.Dockerfile` 빌드 인자는 `:56`이 아니라 `:57`(ARG)·
  `:62`(ENV); `kor_travel_geo_preflight_required`는 `:164-176`이 아니라 `:165-176`, transport base URL은 `:509-519`
  (초고의 `:165-177`·`:509-520`은 한 줄 초과 — 1차 리뷰 정정); MOIS 동시성 `:364-374`, 예산 `:388-`; transport 시계
  검사는 `kor_travel_transport.py:104`(`INCIDENT_SET_MAX_AGE` 30 min)·`:435-452`(설계 `:441-453`). geo client 생성
  지점은 설계에 없던 file:line을 더한 것인데 초고의 "4곳"이 틀렸다 — 1차 리뷰(HIGH)가 `admin_issues.py:276,306`(timeout
  없음)·`dagster/offline_uploads.py:50-53`·`cli/main.py:447`(10.0 하드코딩)을 찾아 **8곳**으로 고쳤고, 팩토리 자리
  (`geocoding.py` 지역 import / `_transport_connection` 옆)와 lint 결박을 적었다. 설계 §9.1의 Map 행은 connect 분리만
  요구하므로 회로차단은 Map 결정에서 명시적으로 뺐다(ADR-110 결정 3·열린 결정 4). weather는 Map이 호출하지 않아
  (ADR-105) 범위 밖임을 한 줄로 못박았다. 설계 T-MAP-01의 `.env.example` 주석은 이 PR이 `.env.example`을 금지하므로
  T-MAP-02 코드 PR로 옮겼다. 설계 정본 파일은 세션 scratchpad라 ADR 본문을 정본으로 선언하고 §는 출처 표기로 낮췄다.
  **설계 §9.1 키 행·§5.6 ⑥의 "geo 키는 loopback 면제라 검증된 적 없다"는 틀렸다** — geo 면제는 admin 프록시
  컨텍스트(CIDR+proxy secret+actor/roles)만이고 Map 호출은 오늘도 대조된다(ADR 컨텍스트 4에서 정정, geo ADR-070
  작성자에게 전달). **T-MAP-02 착수 순서**를 설계 §13의 MGR → MAP 사슬에서 분리해 병렬을 제안했다(코드 의존 없음 —
  열린 결정 6, 소유자 확인; 선행 T-GR-00-LEDGER·`geocoding.py` T-GR-01 공유). **LAN 주소 리터럴은 쓰지 않았다** —
  `scripts/check_prod_redaction.py`(#508, `lint.yml`·pre-commit)가 docs의 사설 IP를 거부해 호스트 이름(`n150`·`odroid`)
  으로 썼다(설계·지시문은 호스트를 LAN 주소 끝자리로 적지만 여기서는 조각도 쓰지 않는다).
- **1차 리뷰 반영(2건, 19 finding).** 전부 반영: timesyncd 상태를 §A3(수동 동기 완료·drop-in 미완)로, §14-19를
  '수용 추천 + 열린 결정 2'로, CLAUDE.md의 'Manager registry 정본'을 '오늘은 compose 기본값 + root `.env`(registry
  파생은 ADR-58 계획)'·'값 없음'을 'standalone 값'으로, ADR-109에 amend 역포인터를, 제목 3곳 통일(connect 분리 포함),
  열린 결정 1의 추천 출처 표기, 'Map만 끊긴다' → 'n150 consumer', T-MAP-02 동반 문구에 `settings.py:509-519` 설명,
  T-MAP-01 종결 소유자(T-GR-00-LEDGER/T-MAP-02 PR), 'CI 대기 없이' → 'lint.yml 초록 뒤(소유자 지시)', T-GR-00-LEDGER
  수치 갱신.
- **2차 리뷰 반영(2건, 17 finding — 전부 반영).** HIGH 2: geo 키 전제 정정(위; 결정 4를 '재적재 시 키 소실'로 축소,
  `9-전` curl을 선택 smoke로, integration-map·resume·acceptance 동일), `#508` redaction guard 실측 11 hit EXIT=1 →
  IP 리터럴 전부 호스트 이름/placeholder로(EXIT=0 재확인). MED: (가) VWorld 폴백 '추천' 철회(Map #979 가드
  `test_geo_key_provenance:493,506`·`test_compose_geo_key_resolution:143`·`test_deploy_automation:382`와 충돌 → 열린
  결정 3 '추천 없음·(나)만'); `12501:12501` publish 인용 삭제(host network에서 `ports:` 무효 — 실제는
  `KTG_API_HOST: 0.0.0.0` Manager compose `:1089`@08a515e); T-MAP-02 의존을 '선행 없음'에서 'T-GR-00-LEDGER 선행 +
  T-GR-01과 `geocoding.py` 공유(늦은 PR 리베이스)'로 + 열린 결정 6; MockTransport 픽스처 삭제(항진명제 — backlog
  포화 서버만); T-MAP-02 해제를 '(1)(2)(3) 초록 + 머지 + 4a 전 배포'로 한정하고 curl·drill을 종결 조건에서 뺌. LOW:
  lint를 '`timeout=`이 팩토리 호출'로(settings float 직접 전달도 빨강), '설계 파일 보존은 T-MGR-07 몫' 삭제, 교차
  ADR 번호에 '(계획, 미작성)', CLAUDE.md를 한 문장으로, Manager sha 드리프트(origin/main `094d3976`, transport 줄
  `:1736` 부근) 주석, integration-map §2의 file:line·'8곳 중 4곳' 복제 삭제(ADR 포인터만), ADR-110 `## 후속` 절 추가.
  범위 목록 밖 수정 1건: `docs/adr/109-geo-release-regeocode.md` amended-by 3줄(역포인터).
- **3차 리뷰 반영(2건, 17 finding — 전부 반영, 기각 0).** HIGH 1: T-MAP-02의 유일한 코드 사양
  `httpx.Timeout(connect=2.0, read=…)`이 httpx 0.28.1에서 `ValueError`(worktree에서 실행 재확인) → ADR 결정 3·tasks·
  acceptance를 `httpx.Timeout(<기존>, connect=<connect 필드>)`(기본값이 read·write·pool을 덮는다)로, acceptance (1)에
  `write == pool == read` 단언 추가. MED 5: geo base URL이 Manager compose의 Map 서비스 **4곳**(api·code-server·dagster·
  daemon `:1582,1723,1813,1920`@08a515e — 로컬 Manager 체크아웃 `git show`로 두 ref 모두 확인)에 주입되는데 `:1582` 하나만
  적고 단계 9를 'cs·API 재생성'이라 쓴 것을 '전 서비스 재생성 + 옛 값 든 컨테이너 0개 게이트'로 통일(결정 1·4(a)·7);
  결정 7 표에 '2~4b(외부)'·'8a/8b(외부)' 행을 넣어 단계 5·9의 선행 조건(odroid plane healthy·`targets validate`
  host·`timedatectl` synchronized·풀로드/mv_refresh/키 정책 완료)을 결박; 단계 9의 '센서 계획 1건' 게이트를 열린 결정
  2(풀로드+수용 / dump 복원이면 0건 / T-GR-05 미배포면 해당 없음)로 분기; 교차 ADR 셋을 '미작성'에서 '**proposed·병렬
  PR 미머지**'로(로컬 체크아웃 `ktdm-t2docs`·`geo-t2docs`·`transport-t2docs`에 본문 존재, origin/main에는 없음 — 6곳);
  transport env 파일을 계획 이름 `.env.prod`가 아니라 오늘 이름 `.env.server14`(transport `README.md:123-124`)로 적고
  `.env.prod`는 ADR-014 개명 계획으로. LOW 11: backlog 포화 레시피를 '사전 connect ≥3건으로 큐를 채운 뒤 측정, Linux
  전제, non-routable 주소 금지'로; 잔존 `.13`/`.14` 조각(journal (7)·acceptance T-MAP-01)을 호스트 이름으로; T-MAP-01
  종결 소유자를 T-GR-00-LEDGER 단일로(tasks·acceptance·resume); 'T-GR-01과 같은 client 생성 지점' → '같은 모듈, 충돌
  범위는 import·새 함수 자리뿐'; drill 10 % 유도식(prefetch는 예외를 삼키고 `geocoding.py:430-432`, 실시간 조회가
  `GeoRequestError`를 전파해 첫 chunk에서 FAILURE — ≤502 s vs 10 s면 2,502 s); ADR-58 R2 뒤 `.env` URL 재정의가
  validate에서 **거부**됨을 컨텍스트 1·결정 1·integration-map·CLAUDE.md에 명시하고 "후속"에 표식 교체 세 시점을 둠;
  결정 6 셋째 bullet의 'skip 쓰지 않는다/대안은 skip' 모순을 조건부 문장으로; `up{host="odroid"}`에 'ADR-58 파생물
  계획, 오늘 Prometheus에 host 라벨 없음' 표식; 저장소 밖 메모리 파일 인용을 `integration-map.md` §4 포인터로.
- **원장.** `tasks.md`에 `T-MAP-01`·`02`(접두사 임시, ADR-110 열린 결정 5), `tasks-acceptance.md`에 두 절
  (`tests/lint/test_task_ledger_conventions.py`가 열린 task마다 절을 요구한다). `journal.md`는 이 항목 포함 약 224 KB로
  상한 225,280 B 아래라 아카이브 분리는 하지 않았다 — 여유 ≈1.3 KB라 다음 경계 분리(`T-GR-00-LEDGER`)는 어느 PR보다
  먼저다.
- **미결 소유자 결정**: ADR-110 열린 결정 6건(BFF 경로 §14-10·geo 적재 방식 §14-8 + 재계획 수용/skip §14-19·키 정책
  §14-21(재적재 시점의 일)·회로차단·task 접두사·T-MAP-02 착수 순서) + 외부: geo가 실제로 odroid로 가는지(설계 §3.2
  조건 3·§14-12 — 미달이면 ADR-110 geo 절은 발효하지 않는다).

## 2026-10-13 — geo 릴리스 재지오코딩 설계: 브랜치 `docs/adr-109-geo-release-regeocode`

문서만 바뀐 PR(doc-only). geo 주소 데이터셋 릴리스 → Map 반영 설계(Track 1, 2차 적대 리뷰 2명 반영)를 ADR-109
(proposed, 미구현)와 `docs/etl/address-geocoding.md`(코딩용 상세)로 옮기고 구현 task `T-GR-00`~`08`을 열었다.
코드·마이그레이션·OpenAPI·CHANGELOG는 건드리지 않았다.

- **결정 요약(ADR-109).** 스탬프는 별도 표 `feature.feature_geocode_stamps`(outcome `called|geocoded|not_called`
  셋 — 좌표 유무가 아니라 호출자의 `geo_applied` run 신호로 정한다; price/notice asset은 스탬프 없음). 현재 토큰은
  run 단위(`kor_travel_geo_dataset` resource; 실패 시 None = 오늘과 동일, fail-to-current). 재지오코딩은 새 엔진이
  아니라 적재 경로의 unchanged-skip 보강: stale 분기 + 값 동일 무쓰기(**override 열은 비교에서 제외**) + 빈 답
  가드(행: 저장 값 non-NULL인데 새 값 전부 None → 무쓰기·무스탬프·finding; run: MOIS의 비율 가드 공통화) +
  geo-release run 한정 timeout 1회 재시도(ADR-108 예외). 기동은 센서 → 전용 job RunRequest(큐 아님; 큐 worker run이
  있으면 Skip). 계획 identity `plan_id` + `(data_token, plan_seq)`(A→B→A도 다시 돈다), 항목은
  `provider_dataset_operations` DB 정본 + KNPS dataset별 run_config, run_key에 `plan_seq/dataset/attempt_seq`, MOIS
  `budget_exhausted`는 done이 아니라 이어 달리기(`mois_load_continuation_decision` 재사용), 완료 분모에서 skipped
  dataset 제외, 완료 시 `same_sigungu` 링크 재동기화. 쿼터 민감 dataset(MOIS·datagokr·standard_data)은
  `source_records.raw_data` replay 모드. concierge payload 토큰은 run 토큰과 같을 때만 신뢰하고 Map
  `raw_payload_hash`에서는 제외. admin API는 admin 프로필만(PinVi admin 스냅샷 재vendor 선행), 슬래시 동사.
- **설계와 달리 쓴 것(head `c4d17343` 재확인).** `client/__init__.py` 인용을 `load_feature_bundles` :1058·
  `find_unchanged_active_source_entities` :1081·`load_feature_bundles_reobserving` :1104·`find_fresh_open_findings`
  :2654로 정정(설계는 1008/1031/1054/2604); `apply_kor_travel_geo_address`는 `admin_issues.py:576`(설계 :546-662);
  `sync_poi_cache_target_feature_links`는 `poi_cache_target_repo.py:862`(설계 :48); `AdminEvidence`는
  `dto/admin_evidence.py:72`(`reverse_attempted` :102). 나머지 file:line은 일치했다. ADR-108에는 "건별 재시도 없음"
  문장이 없어 재시도 예외 각주를 §2(선조회 실패 뒤 실시간 1회) 아래에 달았다. runbook
  `docs/runbooks/geo-release-regeocode.md`·admin 화면 체크리스트 행은 구현 PR(T-GR-07/06) 몫으로 미뤘다.
- **T-GR-00 원장 분리.** `tasks-acceptance.md` 216,950 B(상한 225,280)에서 `scripts/archive_task_ledger_section.py`로
  닫힌 절 7개(`T-VN-41F1D-D1`·`-E`·`T-VN-M01`·`T-VN-M04`·`T-VN-39`·`T-VN-DAGSTER-STORAGE`·`T-VN-QUOTA-ARITHMETIC`)를
  `docs/archive/tasks-acceptance-*.md`로 옮겼다(166,931 B; 매 이동 다중집합 검산 통과, 상대 링크가 있는 절 셋은
  도구가 거절해 두었다). T-GR 절 9개와 1차 리뷰 반영을 더해 **1차 리뷰 반영 뒤 실측** 185,189 B(§T-GR-00
  실측 줄과 같은 값). 설계 §11 T-GR-00이 요구한 잔여 바이트: `journal.md` 208,660 B(이 항목 포함, HEAD 202,686)·
  `tasks-done.md` 200,699 B — 둘 다 규약 §8 분리 기준(200 KB 근접)을 이미 넘어 PR-1 전 doc-only 분리를 선행
  조건으로 적었다(이 PR 범위 밖).
- **1차 적대 리뷰(2명) 반영.** (HIGH) `address-geocoding.md` §1 "현재 사실" 표를 변환 **함수** 단위로 다시 썼다 —
  `address_resolver=`를 받는 모듈은 7개(mois·standard_data·datagokr_file_data·krforest·krheritage·opinet·krex(미사용))이고
  khoa·krairport·mcst·krforest·datagokr·standard_data·opinet은 geo에서 코드+일부 필드만 취해 자기 `Address`를
  조립하며(knps·krforest route·krheritage만 geo `Address` 그대로), Dagster asset·큐 runner는 어느 것도 `address_resolver=`를
  넘기지 않는다(`assets.py` 0건 → asset 경로 `geo_applied.geocode`는 전부 False) — 호출자 표를 추가했다. (MED)
  outcome 판정에 평가 순서를 박았다(①스탬프 없음 ②MOIS evidence ③reverse 시도 → `called` ④geocode → `geocoded`
  ⑤`not_called`); concierge 좌표 행은 payload 코드를 썼어도 `called`(geo가 채운 빈칸이 비교 대상 — 설계 §6.3의
  `not_called` 정정). geo 의존 유도의 런타임 정본은 `core/feature_operation.py` `GEO_DEPENDENT_OPERATION_KEYS`
  상수 + pool lint AST 유도와의 집합 동등(`/detect`는 API 프로세스라 `kortravelmap.dagster`를 import할 수 없다).
  빈 답 비율 가드는 상수·계산만 공유하고 MOIS는 ADR-108 §3a-2 degraded(실패 아님) 유지. ADR-109 열린 결정에
  11(전용 job vs 큐)·12(`raw_payload_hash` 토큰 제외)·13(범위 밖 drift 백로그)을 더하고 8에 backfill 전 배포 Skip
  승인을 합쳤다; 결정별 영향 조문 표를 §T-GR-00에 두고 timeout 재시도 옵션을 T-GR-01 → T-GR-05로 옮겼다(T-GR-01은
  결정 비의존). 포인터 메모(ADR-108·mois etl·integration-map)에서 복제된 상수(상한 12·5 min·21,600 s)와 Skip 규칙
  본문을 빼 ADR-109 결정 5만 가리키게 했고, `address-geocoding.md` §5도 코딩용 이름만 남겼다. (LOW) README 표에
  ADR-107 행 추가, T-GR-07의 `rg` 조건을 append-only 원장 제외로 한정, runbook 배포 순서에 Manager concierge lane
  추가, `address.py:63-119`·`geocoding.py:935`·`definitions.py:113-120` 정정, 머리말의 head sha를 날짜 기준으로.
- **2차 리뷰(2명) 반영 — HIGH 2·MED 8·LOW 11, 기각 0.** (HIGH) 빈 답 가드(행)의 판정 집합에서 provider 원문
  `address.road/legal/admin`을 빼고 geo에서만 오는 집합 G(`sido_name/sigungu_name/admin_dong_code/road_name_code/zipcode`
  + payload 코드 없을 때의 두 코드 열)로 고정했다 — `legal`을 넣으면 krheritage(`:483`)·standard_data(`:296-297`)·
  concierge(`:548`)에서 가드가 영구히 열리지 않는다(T-GR-03 의도적 빨강 (1)에 세 픽스처 명시). MOIS replay 제외
  술어를 **스탬프** `reverse_outcome='not_called'`(unchanged CTE와 같은 술어, 별도 코드 없음)로 박았다 — `raw_data`
  기준이면 스탬프 없는 payload-bjd 행이 `coverage.unstamped`에 남아 완료 판정이 불가능해진다(열린 결정 8의
  선채움은 시간 단축용 "선택"으로 근거 정정). (MED) concierge 토큰 전달 경로(`kor_travel_concierge_items_to_bundles(…,
  current_data_token=)` additive kwarg, 호출처 `assets.py:1508`)를 T-GR-03에; 비-MOIS 비율 가드 분자·분모를
  `GeoCallStats.empty['reverse']`/`calls['reverse']`로 고정(T-GR-01, 현재는 전송 실패만 센다 `:1140-1146`);
  `data_token=None`인 `DatasetRef`도 fail-to-current(스탬프 쓰지도 덮지도 않음 — 두 토큰 열 NOT NULL, NULL 스탬프
  없음); journal·tasks-done 분리를 `T-GR-00-LEDGER`로 독립(T-GR-01 의존); ADR-108 각주·§4 행에 "열린 결정 6 승인 전 미적용"
  표기; timeout 재시도 판별자를 `trigger_kind=sensor`(MOIS 이어 달리기 run에도 붙는다, `mois_chunked_load.py:1071-1075`)
  에서 run 태그 `kor_travel_map.geo_release_plan_id`로 교체(RunRequest 태그에 추가); 값 동일 비교 "7개"→6개,
  `FeatureAddressSnapshot`(`:104-117`)에 `road_name_code`·`admin_dong_code` 추가를 T-GR-03에; pool lint AST 유도의
  현재 동작(키워드 존재만·asset 이름·같은 모듈만)을 사실대로 적고 T-GR-04가 별도 술어 `_passes_geo_callable`+job 매핑을
  더하도록(pool 술어 불변, 과결박 회피). (LOW) 판정 ②를 결과 기준(`geocode_attempted and bjd_code`)으로 ④와 통일하고
  geocode 실패 행은 `not_called`(열린 결정 1 부류); "chunk 단위 판정"→"행별 evidence, chunk commit bulk";
  `_reverse_geocoder(context)` 22→20곳; `has_active_feature_override` 정의 `:5147`/masking 호출 `:829-883`;
  `apply_provider_feature_field_patch`는 프로시저(`:677`); rest_areas `:533-`; `mois.py:685`/`:827`; API validation job
  (`offline_uploads.py:1503`, 적재 없음) 호출자 표 행; Manager lane 단계는 concierge ADR-49 소속 명시; T-GR-02의
  T-GR-03 결박 항목에 "(T-GR-03 뒤)" 표시; concierge payload 코드 행 `not_called`→`called` 변경을 ADR 결정 6(a)에
  "설계와 다른 점"으로 드러냄. 2차 반영 뒤 최종 실측: `tasks-acceptance.md` 189,627 B · `journal.md` ≈ 211.5 KB ·
  ADR-109 31,807 B · `address-geocoding.md` 31,218 B(전부 225,280 B 아래).
- **미결 소유자 결정**: ADR-109 "열린 결정" 13건(task 접두사 `T-GR-` 임시 포함).

## 2026-10-13 — 고속도로 돌발 job pool 고갈(prod run `bfd18ef5`): 브랜치 `fix/highway-incidents-pool`

- 증상: 2026-10-12 12:09Z 수동 첫 적재가 807초 뒤 실패. 4회 시도 모두 step 시작 30초 만에 `get_notice_snapshot_watermark`
  (lock 안 첫 DB 호출)에서 `QueuePool limit of size 1 overflow 0 reached, timeout 30`. 같은 캠페인의 주유소·휴게소 job은 성공.
- 원인: `provider_run_lock`이 advisory lock용 session으로 pool의 유일한 연결을 끝까지 쥔 채, 본문 client 호출이 각자 새
  session(두 번째 연결)을 열었다. 2026-10-05 ADR-107(acde37264)이 Dagster `kor_travel_map_client`를 `pool_size=1,
  max_overflow=0`으로 줄이면서 드러났다(그 전 기본 5+10에서는 조용했다). 2026-10-03 ADR-106이 주유소 asset의 lock을
  걷어내 lock을 쓰는 asset은 고속도로 돌발 하나만 남았다 — 그래서 그것만 죽었다. 공용 Dagster에서 이 job은 이 run 한 번뿐이고
  성공한 적이 없다. 10분 schedule(STOPPED)의 coalescing은 RunRequest 발행 여부만 정하므로 켜도 매 tick 같은 자리에서 죽는다.
  큐 경로는 client를 executor 연결에 결합하므로 영향 없다.
- 못 잡은 이유: asset 단위 테스트의 fake client lock은 연결을 쥐지 않았고, 통합 테스트는 기본 pool(5+10) engine을 썼다.
- 수정: lock을 잡은 연결에 client의 session factory를 lock 구간 동안 묶는다(객체 identity 유지 — guard identity 대조와
  `context.resources` 재조회 때문에 복사본은 안 된다). 전역 pool 상향은 하지 않았다 — ADR-107 runbook의 "DB 연결 1개" 계약을
  지키고, 본문은 원래 순차다. 같은 결함의 `cache_target_snapshot_gc` drain(prod 미실행, 잠복)도 같은 방식으로 고쳤다.
- 리뷰(PR #1314 @ffa0986e) 반영: H1 — GC drain 수정이 `tests/unit/test_cache_target_snapshot_gc_client.py` 3건을
  깼다(fake connection에 실제 `make_connection_session_factory`가 불림, 내 전체 unit run이 그 commit보다 먼저 시작됐다).
  테스트가 그 함수를 lock 연결일 때만 fake factory를 주도록 바꾸고 engine-bound factory는 호출되면 실패시켜 "lock 연결
  위에서만 session을 연다"를 단언한다. L3 — `connection_advisory_lock`/`discard_connection_on_failure`(infra): 획득·본문
  실패·해제 실패 때 lock 연결을 invalidate해(server가 lock을 푼다) lock을 쥔 채 pool로 돌아가지 않게 한다. 본문 실패 때는
  unlock을 시도하지 않아 원래 예외를 가리지 않는다. L4 — asset 통합 테스트를 Dagster runtime login으로. mutation 5종 RED.
- 남은 것(미수정): 큐 경로 strict 실패 증거(`feature_update_evidence_client`)는 executor 연결 밖에서 별도 commit하려고
  두 번째 연결을 요구한다 — 실패 경로에서만, 설계 결정이 필요하다.
- 검증(로컬 WSL + testcontainers PostGIS): 회귀 테스트 4종(단위 SQLite pool 1/0 2건, 통합 lock·asset 전체·GC drain) 모두
  수정 전 client에서 prod와 같은 TimeoutError로 RED 확인. dagster 패키지 679 passed, 관련 통합 executor·notice·advisory·GC
  통과, ruff·mypy --strict·lint-imports 통과.

## 2026-10-13 — weather 잔재 정리(ADR-104/105 후속): 브랜치 `chore/weather-remnant-cleanup`

소유자 승인 정리. 세 갈래 스캔이 live weather 경로는 없고 죽은 코드와 낡은 문서만 남았다고 봤다. PR·머지·배포는 하지 않았다.

- **지운 코드.** `core.ids.make_weather_value_key`·`WEATHER_VALUE_KEY_HASH_LENGTH`와 `core` 재수출,
  `tests/unit/test_ids_weather.py`(호출자 0, grep 전수). `core.scoring.SOURCE_PRIORITY`의 `python-kma-api`·
  `python-airkorea-api` 항목(읽는 곳은 `source_priority()` 하나, master 선정 후보에 그 provider feature가 402/403 뒤
  남지 않는다). `test_export_openapi.py`의 `_CURATED_*` 상수 다섯 개 — `"weather"` variant만 죽은 게 아니라 #1023이
  소비 테스트를 지운 뒤 블록 전체가 아무도 읽지 않았다. admin frontend `vworld-map-view`·`poi-cache-targets`의
  weather 라벨·색(`Record<string,string>` + `??` fallback이라 kind union과 무관; dedup-review 표는 이미 깨끗했다).
- **남긴 것(결정).** `FeatureKind.WEATHER`·kind CHECK, `WeatherValue` DTO·weather enum(API 재도입 방지 검사가 기댄다),
  provider alias, baseline/seed/legacy migration, frozen H35 SQL(`feature_repo`의 KMA 분기 포함), maki weather 아이콘,
  `SourceRole.WEATHER_CONTEXT`(migration 필요 → 백로그).
- **문서.** ADR-062·072 superseded by ADR-104/105(본문 유지, 머리 노트), README 색인. ADR-105의 소유 참조를 ADR-068
  (Feature UUID)에서 ADR-104로 정정. integration-map(service resource는 `/v1/features/batch`뿐), live 인수 runbook
  (owned ID 7개 = place 6 + price 1, `_owned_ids` 대조), ETL 배너 다섯, architecture·data-model(§8.2 제거 노트,
  `current_summary_runs` CHECK는 402 이후 `'price'`)·feature-model·public-views(`latest_weather` 행)·poi-cache·test-strategy.
  stale 주석: maki.ts·mois.py·client docstring·dto/bundle.py.
- **백로그.** `T-WX-VNEXT-FREEZE`(계약↔계약 대조라 지워진 weather 표를 못 잡는다 — 확인함), `T-WX-SOURCEROLE`,
  `T-WX-DTO`, 그리고 스캔 중 찾은 `T-WX-NOTICE-CLOSE`(`close_notice_features`의 production 호출자 0). Manager compose
  `KOR_TRAVEL_MAP_KMA_*` env 제거는 외부 추적(Manager 저장소에서 진행 중).
- 검증(로컬 WSL ext4 사본 + uv venv, n150은 IO 포화라 쓰지 않았다): ruff check(CI 경로) 통과, mypy --strict
  main 153·api 67·dagster 30 통과, lint-imports 4 kept, `check_prod_redaction` 통과. pytest: core import 단위 704 passed,
  `tests/lint` 303 passed(+ `test_sealed_runtime_tree_ship` 2건은 git이 필요해 실제 worktree에서 2 passed),
  `test_export_openapi.py` 11 passed. frontend: admin type-check·touched ESLint 0 경고·vitest 46파일 391 passed,
  map-marker-react vitest 4 passed·typecheck 통과. 최종 게이트는 GitHub CI다.
- 기존 결함(이번 변경과 무관, 기록만): `make_feature_id` doctest 기대값이 origin/main에서도 틀린다(CI는 doctest를
  돌리지 않는다). 로컬 ruff의 `format --check`는 손대지 않은 줄 다수에 diff를 낸다(CI format step은 `if: false`).
- **journal 분리(규약 §8).** 이 항목으로 `journal.md`가 225,613 bytes가 돼 CI의
  `test_every_docs_markdown_stays_within_readable_limit`(225,280)이 붉었다. 가장 오래된 2026-09-11~09-13 5개 절을
  `archive/journal-2026-09b.md`로 옮겼다(하단 인덱스 표 갱신, 현행 창 2026-09-14~). 옮긴 절에 상대 링크는 없다.
  바이트 보존 검산: 새 live 문서에서 인덱스 행·창 문구를 되돌리고 옮긴 블록을 제자리에 넣으면 원본과 byte 단위로 같다.

## 2026-10-12 — MOIS ADR-108 통합 테스트 resource 누락·직접 호출 tag 실패

- PR CI 통합 두 lane이 `test_dagster_assets_validate_coordinates_and_load_to_postgis` 하나로 붉었다 —
  `Dagster resource 없음: mois_load_plan`. 테스트가 asset을 `build_asset_context`로 직접 부르며 resource dict를
  손으로 만든다. 운영 경로는 빠질 수 없다: `definitions.py`가 resource를 등록하고 asset이
  `required_resource_keys`로 선언하며(누락이면 Dagster가 정의 load에서 거부) 큐 runner도 plan을 넣는다. 그래서
  기본값을 두지 않고 fixture에 운영 기본 plan(전 업종 = 월간 schedule 경로)을 넣었다. 다른 직접 호출은
  `test_mois_assets.py`(이미 plan 제공)뿐이고 scripts에는 없다.
- 그 뒤에 숨은 두 번째 실패: `build_asset_context`의 run id `EPHEMERAL`은 instance에 없어 결과 tag 쓰기가
  `DagsterRunNotFoundError`로 터진다(로컬 probe로 확인). `_tag_run_outcome`이 그 예외만 삼킨다 — 실제 run에서는
  나지 않는다. 진짜 `build_asset_context`로 부르는 단위 테스트를 더했다(mutation RED 확인).
- 검증(로컬): dagster MOIS·assets·definitions·resources·runner 138 passed, ruff·mypy strict. 통합은 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 OpenAPI admin 계약 재핀(description만)

- PR CI의 vnext 계약 테스트 2건이 붉었다 — `openapi.json`(full-admin)이 diff freeze baseline·T-VN-40 receipt와 달랐다.
  merge-base 대비 바뀐 것은 `POST /v1/ops/pipeline/requests`의 409·502·503 응답 description 세 줄뿐이다(schema·
  operation·status code 불변). user/service spec bytes는 그대로라 그 두 핀은 손대지 않았다.
- 생성 스크립트는 없다 — 2026-10-05 ADR-107 선례(acde37264)대로 `openapi-diff-v1.json` admin baseline sha256 +
  revisions 항목, `consumer-rollout-v1.json` T-VN-40 pending receipt의 `map_full_openapi_sha256` + blocking_reason
  문장, 테스트의 `ARTIFACT_SHA256` 두 상수를 갱신했다. 검증(로컬): vnext·contract 단위 135 passed.
- PinVi 측: `apps/api/tests/contract/kor-travel-map-openapi-admin.json`이 full-admin bytes를 vendor한다 — receipt가
  이미 pending(exact re-vendor 대기)이라 이번 bytes도 그 re-vendor에 포함된다. PinVi는 이 operation을 호출하지
  않는다(`/v1/ops/pipeline/*` 읽기만). PinVi 변경은 이 작업 범위 밖이다.

## 2026-10-12 — MOIS ADR-108 narrow 리뷰 MED 1·LOW 3 반영

- **MED-1.** run 전체 비율을 업종 degraded가 있어도 언제나 잰다. 무엇이든 degraded면 조회 50행 미만 업종의 빈 답에도
  표식을 쓰지 않는다 — 큰 업종 하나를 degraded로 만든 지역 장애가 작은 업종들에 남긴 빈 답이 30일 가려지지 않게.
- **L-1.** 다시 풀린 표식 닫기 실패는 `IntegrityFindingPersistenceError`로 정규화해 경고만 남긴다(`transaction_destroyed`면 올린다).
- **L-3.** 연속 degraded 사슬은 최근 500 run까지 보고, 그 안에서 완료 run에 닿지 못하면 degraded로 본다(닫힌 쪽).
- **L-4.** ADR-108 남는 위험에 "문턱 아래·5% 아래 지역 장애는 여전히 표식이 되어 최대 30일 조회되지 않는다"를 되살렸다.
- 검증(로컬): MOIS 적재기 72 passed. mutation 4종(표본 미달 업종 표식·run 전체 판정 생략·사슬 상한 열린 쪽·닫기 실패
  전파) 전부 RED. 통합 테스트는 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 리뷰 MED 1·LOW 3 반영

- **MED-1.** 표식이 문턱 초과(probe 통과) chunk와 degraded 업종에도 쓰여, 실제 지역 장애가 다음 run에서 표식으로 가려져
  봉인·sync 성공이 남고 overdue도 울리지 않았다. 표식은 run 끝에 한 번, degraded가 아닌 업종에서 문턱 초과가 없던 chunk의
  행에만 쓴다(run 전체 degraded면 쓰지 않는다). 그런 행은 표식 없이 매 run 다시 조회돼 geo가 회복될 때까지 degraded가
  지속된다. 연속 degraded 판정은 직전 완료 전체 run까지의 사슬 전체(`budget_exhausted` 포함)를 본다. ADR-108 정정.
- **LOW.** 로그 문구(degraded 업종은 표식 없이 다음 run이 다시 조회; off 모드 주석은 표식 30일 반영). 다시 풀린 행의 열린
  표식을 닫는다(SELECT 뒤 있을 때만 UPDATE — statement trigger hot row 보호). 표식 기록 실패가 `transaction_destroyed`면
  올린다.
- 검증(로컬): ruff·mypy strict·lint-imports·OpenAPI drift. MOIS 적재기 67 + 관련 498(전체 `tests/lint` 포함) + API 240 passed.
  mutation 5종(문턱 초과 chunk 표식·degraded 업종 표식·사슬을 완료 run만·표식 닫기 제거·destroyed 삼킴) 전부 RED — 앞의 둘은
  지역 장애 테스트에서 서로를 가려 각자 전용 테스트를 더했다. 통합 테스트(표식 닫기 SQL 포함)는 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 설계: 역지오코딩 불가 표식·조회 행 분모·연속 degraded·SLA

- **원인.** 해상·매립지·잘못된 TM 좌표는 정상 geo에서도 늘 빈 답이라 적재되지 않고 매 run 다시 조회돼, 정상 상태에서
  조회 창·비율을 지배하고 건강한 업종을 매달 degraded로 만든다(MED-1). degraded는 tag·로그로만 보였다(MED-2). 비율이
  미변경 행으로 희석됐다(LOW-1).
- **표식.** geo가 건강할 때(chunk가 장애 판정 없이 commit) 빈 답을 받은 행을 finding `mois_reverse_geocode_unresolvable`
  (info, dedupe key = slug::mng_no, payload.source_record_key = 현재 payload)로 남기고, 다음 run은 같은 payload의 열린 표식이
  30일 안이면 조회·적재하지 않는다(`mois_known_unresolvable`). 새 표 대신 finding 표를 재사용한 이유는 ADR-108 §3a-3.
- **분모.** degraded 비율은 조회한 행 기준(최소 50) — 업종·run 둘 다.
- **드러내기.** 직전 봉인 자격 전체 run도 degraded면 FAILURE(재시도 없음). migration 405가 MOIS bulk policy에 40일 SLA를
  심어 `/v1/ops/datasets` overdue로 보인다(운영자 값 보존). graph artifact는 생성기로, head-schema는 receipt CHECK만.
- **LOW.** 생성 route 주석 정정(seed의 MOIS refresh operation 넷 중 셋은 handler 없음), 죽은 `ensure_mois_source_sync_*`·
  `MOIS_SOURCE_PRECHECK_ERROR_RESPONSES`·`MoisSourceSyncRequired`·테스트(통합 1파일 포함) 제거 — 운영 화면 precheck는 유지.
  비율 설정 `> 0`. 기준점 서울시청 문서화. run 전체 판정 테스트.
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·graph `--check`·migration lint. 관련
  테스트 249 + 578(전체 `tests/lint` 포함) passed. mutation 5종(표식 무시·분모 원복·연속 실패 제거·run 판정 제거·표식 미기록)
  전부 RED. 표식 SQL 통합 테스트(`test_fresh_open_marker_matches_only_the_same_payload_and_ages_out`)와 migration 405는 로컬에서
  돌리지 않았다 — GitHub CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 델타 리뷰 MED 1·LOW 2 반영

- **MED-1 지역 geo 장애.** probe가 다른 지역 좌표로 통과해 한 시·도가 통째로 빠진 채 봉인될 수 있었다. 빈 답 행은 어느 모드에서도
  적재하지 않고(off 포함 — 빈 bjd commit은 같은 payload에서 영원히 건너뛰어진다), 업종(관측 200행+)·run 빈 답 비율이
  `KOR_TRAVEL_MAP_MOIS_GEOCODE_DEGRADED_RATIO`(기본 5%)를 넘거나 같은 업종에서 "문턱 초과 + probe 통과"가 3회면 degraded로
  표시한다 — 실패시키지 않고(영구 정지 재발 방지) 봉인·sync 성공을 남기지 않는다. tag `kor_travel_map.mois_load.geocode_degraded`,
  metadata `mois_geocode_degraded*`·`mois_reverse_geocode_empty`·`mois_geo_probes`·`mois_geo_probe_passes`, 경고 로그.
  probe는 고정 기준점과 마지막 좋은 좌표 둘 다 묻는다.
- **LOW.** 생성 route는 MOIS source sync precheck를 부르지 않는다(유일한 MOIS operation이 전용 job 전용이라 도달 불가) —
  409 설명·테스트에서 `MOIS_SOURCE_SYNC_REQUIRED` 제거, 우연히 MOIS dict로 문서화되던 502/503은 실제 원인(geo resolver)으로.
  실행된 scope 없이 `dedicated_job_only`가 섞인 빈 계획은 실패(PinVi target을 갱신됐다고 보고하지 않는다).
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·TS 타입(lock 7.13.0) 일치. 지역 장애(drop/off)·off 모드
  재시도·K회 판정·건강한 run 봉인 유지 테스트 포함 296 + 177 passed. mutation 5종(봉인 조건에서 degraded 무시·off 모드 commit·
  K회 판정 제거·probe 좌표 하나·빈 계획 any→all) 전부 RED.

## 2026-10-12 — MOIS ADR-108 델타 리뷰(PR #1312) HIGH 1·MED 1·LOW 4 반영

- **HIGH-1 geo 장애 오판.** drop 모드에서 바다·경계 좌표 행은 적재되지 않아 매 run 다시 변환되고, 재개 run의 조회를 지배해
  비율 판정이 영구 실패를 냈다. 비율이 문턱을 넘으면 `PrefetchingReverseGeocoder.probe_healthy`가 이 run에서 법정동코드를
  받은 마지막 좌표(없으면 서울시청 기준점)를 캐시 없이 다시 묻고, 그것도 빈 답일 때만 장애로 실패한다. 표식 표 대신 probe를
  고른 이유와 대가는 ADR-108 §3a.
- **MED-1 재시도 정체.** run tag에 실제 상한(`…budget_seconds`)과 loop 시작 때 남은 시간(`…budget_available_seconds`)을 남기고,
  0행 정지는 상한 절반 이상을 받은 run에만 적용한다. tag가 없거나 깨지면 이어 달린다.
- **LOW.** (a) 생성 route 409 설명을 실제 409 전부로(dict 병합이 MOIS precheck 설명으로 덮던 것; run-now 설명은 원복),
  OpenAPI·admin 타입은 `openapi-typescript@7.13.0`(lock 버전)로 재생성. (b) plan 선행조건은 큐가 실행할 membership만.
  (c) `policy_disabled`가 먼저, 실패는 건너뛴 것이 전부 `dedicated_job_only`일 때만. (d) `_run_clock_start`가 비숫자·NaN·
  무한·0 이하·미래 start_time을 무시.
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·TS 타입 재생성 일치. 테스트 84(새·수정)
  + 377(API 관련) + 163(dagster·lint 관련) passed. mutation 5종(probe 제거·budget tag 무시·any/all·guard 필터 제거·
  start_time 검사 제거) 전부 RED.

## 2026-10-12 — MOIS ADR-108 적대 리뷰 MED 4건·LOW 반영: 브랜치 `feat/mois-chunked-resumable-load`

- **MED-1 소실 하한.** chunk마다 재던 drop 비율 하한을 끄고(`enforce_loss_guard=False`) 업종 누적·최소 표본 200행에서
  데이터 무효(`missing_address`)만 판정한다. 지오코더 원인(`reverse_geocode_failed`)은 따로 세고(다음 run이 다시 변환),
  geo가 최근 20건+ 중 80%+를 빈 답으로 내면 chunk 적재 전 upstream 장애로 실패한다(`PrefetchingReverseGeocoder`의
  최근 창 50건).
- **MED-2 재관측 충돌.** `ProviderEntityReobservationConflict`를 잡아 그 chunk만 run 안에서 최대 2회 다시 확인·적재.
- **MED-3 시간 기준.** run record `start_time`부터 재고, `min(설정, dagster/max_runtime tag - 30분)`. settings 최대값과
  job run 상한의 관계를 테스트로 고정.
- **MED-4 큐.** 정본 `core.feature_operation.DEDICATED_JOB_ONLY_OPERATION_KEYS`. MOIS뿐인 enqueue는 409
  `PROVIDER_DEDICATED_JOB_ONLY`, 섞인 요청은 실행 계획에서 빼고 `done` + error_message, 실행할 것이 MOIS뿐이면
  `failed` + cache target event `error_code=PROVIDER_DEDICATED_JOB_ONLY`(기존 실패 어휘). OpenAPI 409 설명·admin 타입 갱신.
  router 테스트의 큐 sample operation을 MOIS에서 khoa로 바꿨다(MOIS는 이제 큐로 받지 않는다).
- **LOW.** 이어 달리기: 미종료 run 재확인, 0행 전진이면 정지. sync 성공 = 봉인 조건(`authoritative`).
- 검증(로컬 py3.13 venv, n150 미사용): ruff·mypy strict(core/api/dagster)·lint-imports 통과. 관련 unit/api/dagster/lint
  테스트 MOIS 34·executor+provider+prefetch 52·dagster 관련 109·API router 163·API 관련 249·lint 175 passed.
  mutation 8건(chunk 하한 재활성·충돌 재시도 제거·step 시계·장애 판정 제거·0행 정지 제거·활성 run 재확인 제거 등) 전부 RED.
  통합 테스트는 돌리지 않았다(GitHub CI가 게이트).

## 2026-10-12 — MOIS 재개형 chunk commit 적재(ADR-108): 브랜치 `feat/mois-chunked-resumable-load`

소유자가 2026-10-12에 MOIS 적재 재구성을 승인했다(prod `1a3c4673` 읽기 전용 조사: 42업종 약 98만 행, 순차 역지오코딩
약 35시간 vs run 상한 6시간, 단일 transaction, `/tmp` 원천 SQLite). PR·머지·배포·prod 데이터 실행은 하지 않았다.

- **재개 키 = 원천 내용.** chunk(업종 안 최대 500행)마다 `(slug::mng_no, raw_payload_hash)`를 지오코딩 **전에** 계산해
  "head가 같은 payload이고 primary feature가 active인가"를 묻는다(`find_unchanged_active_source_entities`). 그 행은
  `load_bundle`이 관측 시각 말고 아무것도 바꾸지 않는 행이므로 재관측만 하고(`reobserve_unchanged_source_entities`,
  Phase A marker `synced_at` 기준 — 같은 snapshot 재실행은 다시 쓰지 않는다), 나머지만 변환·적재한다. 둘은 chunk
  transaction 하나(`load_feature_bundles_reobserving`). 새 표·cursor·마이그레이션 없음 — `load_bundle`이 읽는 표·열만 읽는다.
- **지오코딩.** kor-travel-geo에 batch endpoint가 없다(geo origin/main `02a3c2e`: `/v2/reverse`·`/v2/geocode` 단건).
  `PrefetchingReverseGeocoder`가 chunk 좌표를 중복 없이 bounded 동시성(`KOR_TRAVEL_MAP_MOIS_GEOCODE_CONCURRENCY`, 기본 2)으로
  선조회하고 run 수명 LRU(5만)에 둔다. 원천 `legal_dong_code`가 있는 행·이미 적재된 행은 조회하지 않는다. 선조회 실패는
  캐시하지 않는다(변환이 한 번 더 시도, 그래도 실패면 예외).
- **run 크기.** `KOR_TRAVEL_MAP_MOIS_LOAD_RUN_BUDGET_SECONDS`(기본 4시간)에서 새 chunk 시작을 멈추고 tag
  `kor_travel_map.mois_load.outcome=budget_exhausted`. `feature_place_mois_licenses_continuation_sensor`(STOPPED)가 같은
  run_config로 잇는다. retry 1회·5분. 월간 schedule은 활성 run과 합친다. 봉인·sync 성공은 전 업종을 한 run에서 끝까지 본
  run만. 큐 runner는 MOIS를 `dedicated_job_only`로 건너뛴다(큐는 쓰기를 한 transaction에 묶는다).
- **원천 영속.** 이미지가 `/opt/dagster/state/mois`(appuser)를 만들고 기본 경로로 둔다. standalone compose volume도 그리로.
  운영은 Manager 브랜치 `feat/map-mois-source-volume`(internal named volume, 경로·target 같은 변수).
- **검증 경로.** run_config `resources.mois_load_plan.config.{service_slugs, run_budget_seconds}`. 절차는
  `docs/etl/mois-license-feature-etl.md` §13.2.
- 테스트(n150, python:3.13, `-c docker/constraints-dagster.txt`, CI 세션 경계 그대로):
  - 정적: `ruff check`(CI 범위) 통과, `mypy --strict` core 153·api 67·dagster 30 파일 이슈 0, `lint-imports` 4 kept.
  - A unit+lint: 3056 passed / 26 failed — 같은 컨테이너의 main(`bcbd14c2`) 기준선과 실패 집합 동일(docker CLI·node·git 소유권
    환경 25건) + `test_orchestrator_guardian_lock_is_not_inherited_by_external_child` 1건(flock/SIGKILL 타이밍 — 부하 중 같은
    컨테이너에서 2/3 실패, 별도 컨테이너에서 4/4 통과, main도 통과; MOIS 무관).
  - B api: 1236 passed, coverage 78.1%(≥70). C dagster: 626 passed·4 skipped, coverage 82.9%(≥80), `mois_chunked_load.py` 95%.
  - 새 통합 `test_mois_resumable_load_repo.py`: 실 PostGIS 4 passed. 전체 D는 n150 IO 포화(`/proc/pressure/io` full avg300 ≈44%,
    `map-load-phase14` 적재 중)로 PostGIS testcontainer가 120초 안에 뜨지 못해 setup error — 두 번. 부하를 더하지 않으려 중단하고
    IO가 가라앉으면 도는 user unit `mois-gate-d-ready`로 넘겼다(로그 `~/mois-gate-logs/d3-*`). GitHub CI가 정본 게이트다.
  - 실제 python-mois-api(3cdee09)를 깐 상태에서 fetcher 업종 선택 테스트 포함 4 passed(CI는 `providers` extra를 깔지 않아 skip).
  - mutation(일부러 깨기): 재개 건너뛰기 제거 → 4건 RED, 선조회 동시성 1로 → 1건 RED, 시간 상한 제거 → 3건 RED. 모두 원복.

## 2026-10-08 — map-marker-react `roadblock`·`warning` 글리프: 브랜치 `feat/marker-roadblock-symbol`

- **변경.** `packages/map-marker-react/src/maki.ts`의 `MAKI_GLYPH`에 `roadblock`(🚧 U+1F6A7, `construction`과 같은
  글리프 — Unicode 바리케이드는 그것 하나다)과 `warning`(⚠, `alert`와 같음)을 더했다. krex 교통 공지와 krforest_safety
  산사태 예보가 첫 글자 배지("R"·"W")로 떨어지고 있었다. 이 패키지의 "심볼"은 SVG가 아니라 Unicode 글리프 표다.
- **누락 조사.** category catalog 58종은 T-017 gate가 이미 막고 있어 누락 0. catalog 밖 provider 상수 중 표에 없던 것은
  위 둘뿐이었다. 그 경로를 지키는 검사가 없어 `test_provider_direct_marker_icons_are_renderable_by_ts`를 더했다(상수
  값 자체를 import해 대조).
- **CI 사각.** 패키지 자체 vitest(`src/maki.test.ts`)는 admin vitest 범위 밖이라 어떤 워크플로도 돌리지 않았다.
  `frontend.yml`에 `map-marker-react unit tests + typecheck` 단계를 넣고 `scripts/verify-all-gates.sh`에도 미러링했다.
- **테스트(n150, node:22.23.1).** marker vitest 4 passed·typecheck 0; admin vitest 46 files/391 passed(첫 실행 1회 exit 1 —
  출력이 잘려 원인 미확인, 재실행 2회 green), admin type-check·lint 0, next build(CI env) 성공. Python: drift 2파일 6 passed,
  새 provider-direct 검사는 `maki.ts`에서 두 키를 지우면 `['roadblock', 'warning']`으로 RED; workflow·mirror 포함 38 passed;
  ruff 통과. npm 게시 없음(ADR-043). kor-travel-transport의 vendored 사본도 같은 내용으로 다시 복사했다.

## 2026-10-07 — entrypoint 봉인에서 `api grpc` 제거: 브랜치 `chore/entrypoint-drop-api-grpc`

- **변경.** `docker/dagster-entrypoint.sh`의 production `/usr/local/bin/dagster` 봉인이 하위 명령 `code-server start`
  하나만 받는다(9-argv, loopback `-h`, 숫자 `-p`, 고정 `-m` 그대로). 최상위 `api grpc`는 location reload를 무시해서
  전환용으로만 남아 있었고, Manager compose(#1295)·standalone compose(#1304)가 모두 옮겨 쓰는 곳이 없다. 거부 문구는
  다른 모양과 같다. local-dev의 preflight 분기에서도 `api grpc`를 뺐다.
- **테스트.** `test_dagster_production_code_server_rejects_other_shapes`에 `api grpc`를 넣어 n150에서 먼저 RED(1 failed)를
  보고 고쳤다. accepts는 `code-server start` 정확한 argv 하나, runtime-preflight 목록에서 `api grpc` 행을 뺐다.
  n150: `ruff check`(CI 범위) 통과, `test_docker_dagster_runtime.py`+code-location+constraints 332 passed / 14 failed —
  실패 14건은 main(8f9dd1cb) 기준선과 같은 집합(frontend dotenv validator·local admin stack 등 환경 의존).
- **실측(throwaway, 운영 Map code-server 이미지 `197597501a0b`, rev 1a3c467).** 새 entrypoint를 읽기전용 마운트:
  `api grpc` → rc=1 + 봉인 문구, `code-server start` → 35초 안에 `ListRepositories` 610 bytes(정상 응답, 오류 없음).
  proxy의 자식 `python -m dagster api grpc --socket …`은 entrypoint를 지나지 않아 영향이 없음을 프로세스 목록으로 확인.
  이미지 자체 entrypoint는 `api grpc`를 여전히 받는다(대조). 컨테이너·임시 파일 정리 완료.
- **배포.** 하지 않았다. 다음 Map pinned-pair 회전 때 반영되며, 운영은 이미 `code-server start`라 안전하다.

## 2026-10-06 — Map·PinVi 공통 Dagster 구현·재구축·live·머지 완료

[Common #28](https://github.com/digitie/kor-travel-common/pull/28) → [Map #1303](https://github.com/digitie/kor-travel-map/pull/1303) → [PinVi #576](https://github.com/digitie/pinvi/pull/576) 순서로 병합했다. Common·Map은 merge commit, PinVi는 main ruleset의 squash-only·linear history 정책에 따라 squash로 병합했다. PinVi 재구축 원본0058369와 검증 HEAD92d0f40는 remote tags codex/pinvi-map-runtime-20261006·codex/pinvi-map-reviewed-20261006 및 유지한 feature branch에 원본 이력을 보존했다. 저장소 설정은 변경하지 않았다. 최종 문서 포함 HEAD의 필수 CI, Common·Map main ancestry와 PinVi 보존 참조, 병합 tree 일치를 확인했다. 실제 paired 재구축, 두 독립 FULL 제품 리뷰·가이드 리뷰·최종 문서 리뷰, Chromium/Firefox×Map/PinVi live UI4건·8캡처, ACL40·D1 11건·D2 normal/attempt0·소유 fixture 정리·잔존0 검증을 완료했다.

머지 후 운영 API/UI/Dagster 여섯 이미지의 healthy 상태·설치 코드·배포 source·committed transaction이 기존 성공 증거와 같음을 실제 read-only 재확인했다. 최종 제품 Common a960bdb/Map1a3c467/PinVi0058369에 문서만 추가됐으며 재구축·장애 주입을 머지 HEAD에서 새로 실행한 것으로 집계하지 않는다. 격리 Map native raise/crash/stall·동시 정상 run·수동 복구는 관련 설치 코드/버전 불변 범위에 한정한다. 공유 운영 worker 장애 주입·운영 RSS 감소율은 미실측이다.

이 요청의 T-COMMON-DAGSTER는 완료 원장으로 이동한다. 기존 외부 transport/HAProxy 및 다른 미완료 task는 유지한다. 다음 작업은 기존 열린 backlog의 우선순위를 따른다.

[머지 후 실제 상태 증거](reviews/common-dagster-2026-10-05/evidence/final-postmerge-runtime-attestation.json), [가이드·실패·리뷰·수용 이력](reviews/common-dagster-2026-10-05/README.md). 아래 문단은 각 작성 시점의 이력이며 이 절이 최신 상태다.

## 2026-10-06 — Map·PinVi 공통 Dagster 실제 재구축·live 수용 완료

Common a960bdb, Map 1a3c467, PinVi 0058369의 제품113파일 두 독립 FULL 리뷰와 가이드 리뷰를 통과했다. 공용 Python은 bounded HTTP·경량 child health·실행 복구 정책을 제공하며 앱의 operation/lease/claim·비멱등 쓰기 계약을 유지한다. 요청별 응답4MiB/10초와 정리50ms, DB pool/step 제한·100개 batch를 적용했다. Map tick 조회의 오래된 batch history 정렬 지연은 상태 조건을 명시하여 native indexed LIMIT 경로로 줄였고 실제 summary/UI 복구를 확인했다.

운영 paired 재구축과 설치 source·관련 Common bytes·실제 이미지 identity·여섯 서비스 healthy를 검증했다. Chromium/Firefox×Map/PinVi 실제 UI4건과 캡처8개를 직접 확인했다. ACL40·D1 11건·D2 정상 수용/validator·소유 fixture purge1/7·잔존0/ACTIVE없음/BLOCKED없음까지 통과했다. Common의 ESM export를 읽기 위한 type=module은 별도 테스트 이미지 package.json에만 추가하고 실제 마지막 layer/semantic delta를 증명했다. 앞선 모든 실패·초기 BLOCK와 수정 후 PASS 원문은 보존한다.

격리 native Dagster에서 실제 raise·worker crash·stall/timeout 뒤 수동 재시도와 동시 정상 job을 확인했다. 최종 Map 운영 Dagster 이미지의 관련 설치 코드와 버전이 이전 격리 이미지와 같은지, 실제 최종 이미지 ID가 배포 기록과 맞는지 독립 검증했다. 이 결과는 해당 불변 코드 범위에 한정해 이어받는다. 공유 운영 DB의 worker 장애 주입이나 운영 RSS 감소율 실측으로 설명하지 않는다. 유한 응답·batch·동시성 구조와 합성 메모리 측정은 운영 RSS와 구분한다. 기존 인간 dirty checkout·외부 transport/HAProxy 후속은 보존한다.

도구 제한: Map own CodeGraph의 최종 sync/status는 NTFS disk I/O error로 완료하지 못했다. 기존 격리 인덱스와 SQLite immutable quick_check 정상은 보존했으며 원본 인덱스/프로세스의 강제 정리는 하지 않았다. 마지막 제품 변경은 tick 조회 조건과 C7 테스트 Docker COPY 순서이며 공개 Python/DTO 계약은 유지한다.

다음 한 작업은 문서 포함 exact HEAD CI 통과 후 Common #28 → Map #1303 → PinVi #576 순서로 merge commit 병합하는 것이다. 제품 Git pin의 ancestry를 보존한다. 이 절이 현재 상태이며 아래의 진행 중/NOT_RUN 문단은 이전 시점의 이력이다.

[실제 검증·리뷰 원문과 실패 이력](reviews/common-dagster-2026-10-05/README.md), [공통 적용 가이드](runbooks/common-dagster.md).

# journal.md — 작업 일지 (역시간순)

## 2026-10-05 — child health의 reserved metadata marker 차단 채택

Common 경량 probe의 독립 리뷰 반례(pointer/library map의 reserved serdes marker)를 차단하고 정상 default repository __repository__를 허용하는 profile을 API·Dagster 동일 Git revision으로 채택한다. unsupported stateful/custom metadata는 fail-closed하며 가이드에 지원 경계를 명시했다. 두 독립 재리뷰·현재 CI·실제 PinVi/Map paired 재구축/live는 아직 진행 중이다.

## 2026-10-05 — child health의 nested metadata 검증 채택

Common 경량 probe의 독립 리뷰 반례(null/미등록 pointer, 잘못된 executable/entry point 타입)를 반영한 표준 module/file/package profile을 API·Dagster 동일 Git revision으로 채택한다. unsupported stateful/custom metadata는 fail-closed하며 가이드에 지원 경계를 명시했다. 두 독립 재리뷰·현재 CI·실제 PinVi/Map paired 재구축/live는 아직 진행 중이다.

## 2026-10-05 — standalone 자식 저장소 응답 fail-closed 보강

최신 main #1304를 반영한 두 독립 리뷰에서 한 리뷰어가 빈 protobuf/잘못된 JSON이 substring 건강 점검을 통과하는 P2를 실제 reply fixture로 재현했다. 기존 PASS와 BLOCK 원문을 모두 보존한다. Common의 경량 `dagster_health`를 사용하여 proxy 뒤 자식의 정상 class·symbol schema와 wire/JSON을 검증한다. Dagster 전체 import를 피하며 각 RPC 4초·수신 4MiB·channel 정리를 유지한다. standalone은 건강 판정만 하므로 unhealthy 자체를 자동 재시작으로 설명하지 않는다. 새 source pin·두 리뷰·CI·운영 재구축/live는 아직 미완료다.

## 2026-10-05 — 요청 단위 Dagster client의 PostGIS fixture 정렬

Map CI의 glibc·alpine 통합 lane에서 동일한 projection 테스트 한 건이 실패했다. 앱 전역 client 주입을 제거한 뒤 기존 fixture가 실제 연결로 빠진 것이 원인이다. 두 schedule fixture에 요청마다 새 MockTransport client를 주입하고 실제 middleware의 정리를 유지했다. catalog 회귀도 schedule source가 `ok`인지 단언하여 묵시적 degrade를 막는다. 운영 Python·UI 코드는 이전 고정 후보와 동일하다. 실제 PostGIS 관련 22개 검사를 통과했으며 전체 CI를 다시 확인한다.

## 2026-10-05 — Map·PinVi 공통 Dagster 보강 (진행 중)

ADR-107과 [적용·복구 가이드](runbooks/common-dagster.md)에 따라 공통 Python HTTP/Dagster·로그인·메뉴·대시보드를 채택했다. 요청별 연결·응답/시간 상한·활성 run 별도 조회·step/DB 연결/100개 batch를 적용한다. 쓰기 run 자동 복제 없이 기존 operation/lease/claim 복구 계약을 유지한다. [검증 기록](reviews/common-dagster-2026-10-05/README.md)의 고정 후보 2인 리뷰·운영 재구축·live·CI·merge를 완료해야 한다. 원래 인간 dirty checkout은 보존했다.

적대적 원본 리뷰의 실패 상세·event cursor 회귀와 손상 Repository의 정상 빈 snapshot 오인을 보강했다. 선택한 run만 상세 조회하며 Docker deps에 고정 Common vendor를 복사한다. UI 390/API shape 24/strict mypy 96 및 production Next build PASS. React Doctor의 불필요한 mapper export를 제거했다. 후속 리뷰의 repository 소속 불일치도 selector identity와 비교하여 fail-closed하고 다른 location의 행을 제거했다. 정상 empty와 외부 name/location을 실제 HTTP 응답 fixture로 구분한다. 검색으로 선택한 run의 행이 숨겨져도 상세에 job/run identity·상태·시간 상한을 명시하여 다른 작업의 실패로 오인하지 않도록 보강했다. 후속 immutable 2인 FULL 리뷰·exact CI·실제 paired 재구축·live gate는 아직 미완료다.

## 2026-10-05 — standalone compose code-server를 `code-server start`로: 브랜치 `chore/standalone-compose-code-server-start`

- **변경.** `docker-compose.yml`의 `dagster-code-server` command가 `dagster api grpc`에서 운영(Manager)과 같은
  `dagster code-server start -h 127.0.0.1 -p ${PORT} -m kortravelmap.dagster.definitions`가 됐다(#1295 봉인이 받는 모양).
  `api grpc`는 location reload를 무시해서 import 때 읽는 schedule override가 반영되지 않는다. host·external-infra
  overlay는 command를 건드리지 않는다.
- **healthcheck.** 옛 probe(`DagsterApi` health → SERVING)는 `code-server start`에서는 proxy만 본다 — proxy health는 자식이
  load error여도 SERVING이다. proxy health 뒤 자식에 전달되는 `ListRepositories`를 raw bytes로 불러
  `SerializableErrorInfo`면 실패한다(dagster import 없음, 4초 deadline 둘). Manager probe의 PID 1 종료·orphan run 정리는
  standalone에 옮기지 않았다(판정만).
- **테스트.** `test_standalone_compose_code_server_is_reloadable_and_sealed`: compose argv 정확 일치 + 그 argv(포트 기본값
  풀어)를 실제 entrypoint 봉인에 넣어 통과 + probe가 `ListRepositories`/`SerializableErrorInfo`를 본다. dagster 프로세스
  서비스 유도 marker를 `dagster api grpc` → `dagster code-server start`로 바꿨다. 먼저 RED(2 failed: argv 불일치,
  유도 서비스 2개) 확인 후 GREEN.
- **n150 증거.** 영향 파일 3개(`test_docker_dagster_runtime.py`·`test_c7_prod_runtime.py`·
  `test_n150_repin_derives_dagster_services.py`) 368 통과/13 실패 — 13건은 main과 같은 집합(n150 checkout에 frontend
  node_modules 없음). CI 범위 ruff 통과. `docker compose config` base·host·external-infra 셋 다 `code-server start`로 렌더.
  live Map dagster 이미지로 일회용 컨테이너(host network, 빈 loopback 포트): 정상 모듈은 compose probe rc=0(~40초),
  `dagster api grpc-health-check` rc=0, `ListRepositories` 응답이 `ListRepositoriesResponse`. 없는 모듈은 compose probe
  rc=1인데 proxy health는 SERVING, `grpc-health-check`는 rc=0 — CLI probe로는 load error를 못 잡는다는 실측. 컨테이너는 치웠다.
- **남은 것.** entrypoint 봉인에서 `api grpc` 제거(이제 어느 compose도 쓰지 않는다).

## 2026-10-05 — 인계 문서와 n150 보조 스크립트를 저장소에 남김

- 세션 교대(다음 에이전트: Codex)를 위해 `docs/handoff/2026-10-05-shared-dagster-handoff.md`에 상태·진행 중 작업·
  TODO 7개·n150 운영 절차·실제로 밟은 함정을 정리했다. 운영 값은 넣지 않았다(#508).
- `docs/handoff/n150-scripts/`: `preflight.sh`(변경 전 사전 점검), `guarded-rb.sh`(실패 시 즉시 docker start하는
  pinned rebuild), `transport-deploy-unit.sh`, `weather-deploy.sh`, `dagster-job-status.py`. n150 `~/`에 실제 호스트가
  든 사본이 있다.
- 2026-10-03~04 사고 요약: 옛 메타DB 차단 뒤 rebuild가 옛 storage migrate에서 실패(→ Manager #459), 부하 cold start가
  healthcheck 창 초과(→ #460), C6c smoke 첫 요청 timeout(→ #461), D2 fixture가 실패 경로 정리를 거부(→ #1297).

## 2026-10-04 — D2 실패 run이 `cleanup-failed`로 굳던 결함: 브랜치 `fix/d2-fixture-restored-audit`

- **무엇이 일어났나.** D2(run `live-20261004102457-782ce6e6b79b`, a68c2b7d)의 main spec이 create 응답을 받지 못해
  실패했다. create 트랜잭션은 10:36:31.7Z에 시작해 약 10:37:01.4Z에 커밋됐다(약 30초). API access log에는 그 POST가
  없다 — 응답 전에 클라이언트가 떠났다. spec `finally`가 Feature를 `:cleanup`으로 은퇴시켰고, helper api-audit은
  완주 사슬과 `:retire` lifecycle override만 받아 `API-owned field override 소유권이 다릅니다`로 죽었다 → BLOCKED
  `cleanup-failed`(원래 `test-failed-restored`). 같은 감사를 부르는 `recover`와 helper `purge`도 구조적으로 통과 불가였다.
  #1296(transport consumer)은 무관하다 — field override·admin create 경로를 건드리지 않는다. 동시 Map Dagster run도 없었다.
- **고침.** lifecycle override의 reason을 **실제로 은퇴시킨 전이의 reason**(`:retire`|`:cleanup`)에 결박했다.
  `api-audit --expect complete|restored`: 러너가 spec 실패 시와 `recover`에서 `restored`를 넘긴다(생략=complete라
  clone lane은 그대로). 복구 증거 검증기는 restored 모양을 받고 purge `purged`를 감사한 개수와 대조한다.
  `feature_uuids` 길이를 `counts.features`에 결박했다(적대 리뷰 LOW1).
- **테스트.** `tests/unit/test_d2_api_owned_restored_audit.py`는 prod에 남은 행을 그대로 옮겼다. 고치기 전 a68c2b7d 코드가
  같은 행에 prod와 똑같은 오류를 낸다는 것을 n150에서 재현했고, 새 테스트는 먼저 빨갛게 확인했다.
- **~30초 절단은 저장소 밖이다.** Playwright(`page.evaluate` fetch 무제한, test 5분), Next proxy route(timeout 없음,
  abort signal만 전달), API(요청 timeout 없음) 어디에도 30초가 없다. D2는 `https://<map-ui-host>`로 가고
  n150에는 443 listener가 없다 → OPNsense HAProxy edge. H27은 `timeout tunnel 1h`만 바꿨으므로 기본 `timeout server`
  30초가 남아 있을 가능성이 가장 높다(라우터 설정은 직접 읽지 못했다 — 추정).
- **현재 BLOCKED 정리.** a68c2b7d로는 lane 복구가 불가능하므로 n150 `~/d2-adjudicate-782ce6e6.sh`(0600, 미실행)에
  판정 스크립트를 두었다: 잔여물 정확 대조 → `feature.purge_manual_feature`(감사되는 purge 명령) → 정본
  `scripts/n150/adjudicate.sh` → 운영자 메모·run dir 사본 보관. `--dry-run`이 먼저다.

## 2026-10-04 — delta 리뷰 반영: 같은 브랜치 `fix/transport-consumer-lows`

- **MED 회귀.** `_TransportTransientStatus`(HTTP 층 재시도를 다 쓴 502/504)가 부모의 `retryable=False`를 물려받아
  새 경계가 짧은 transport 재기동을 terminal로 만들었다(하루치 유가 손실). `retryable=True`·`failure_kind=
  transport_transient_status`. 다른 하위 클래스(NotCurrent True, Malformed·Empty·Hidden·ContractError False)는 의도대로다.
  경계 테스트에 503·502를 "재시도가 남아야 하는" 경우로 넣었다.
- **LOW** 경계의 원인 추적은 `__cause__`만 따른다(`__context__`는 처리 중 난 다른 실패).
- **LOW** locator 경고 logger(`kortravelmap.infra.feature_repo`)를 `docker/dagster.yaml` `managed_python_loggers`에
  더했다(lint로 결박). 공용 Dagster plane에서는 instance 설정이 Manager 쪽이므로 그쪽 목록에도 있어야 run 로그에 보인다.

## 2026-10-04 — transport 소비 후속 적대 리뷰 반영: 같은 브랜치 `fix/transport-consumer-lows`

- **MED locator 한 행이 전체를 죽였다.** `list_primary_place_locator`가 검증 없는 코드 칼럼으로 엄격한 `Address`를
  만들어, `manual_override` 하나(시군구만·오타)가 목록 전체를 `ValidationError`로 실패시켰다 — 모든 가격 run이
  실패하고 override가 provider 보정을 가리므로 저절로 낫지 않는다. 행마다 만들고 걸리면 빈 주소 + feature id 경고.
- **LOW 2·3 `retryable`이 행동을 바꾸지 않았다.** `FEATURE_LOAD_RETRY_POLICY`는 쿼터 말고 모든 예외를 다시 돈다.
  asset 경계가 `retryable=False` transport 실패(hidden·empty·contract·malformed)를 쿼터 소진과 같은 방식으로
  `Failure(allow_retries=False)`로 바꾼다(`raise_terminal_if_transport_unrecoverable`). 503만 재시도로 남는다.
  테스트는 `run_tracked_feature_asset`를 실제로 돌린다(두 갈래 × 네 종류).
- **LOW 6** 바깥 run 예산이 열린 채 다른 예산을 넘기면 `ValueError`(종전은 조용히 무시).
- **LOW 7** 감사 기록 실패·timeout·비-2xx는 `console.warn`(이벤트 종류·결과·오류 이름/HTTP 상태만, 비밀값 없음).
  테스트는 `vi.restoreAllMocks()`로 spy를 되돌린다.
- **LOW 5(수용, 기록).** 가격 feature가 place의 시군구 코드를 갖게 되어 시군구 범위 refresh가 이제 가격
  dataset도 포함한다. 첫 적재는 기존 가격 feature 주소를 한 번 고쳐 쓴다.
- **큐 경로 503(결정: 유지).** 큐 run의 실패한 update request는 원인과 무관하게 그 request로 끝나고 다시 큐에
  넣지 않는다. 다음 schedule/request가 다시 돈다. dagster README·ADR-106에 적었다.

## 2026-10-04 — transport 소비 후속(적대 리뷰 잔여 Low 다섯): 브랜치 `fix/transport-consumer-lows`

- **재시도 예산은 run 하나에 하나.** ADR-106 리뷰 M8은 "run 예산 공유"라고 적었지만 실제로는 fetcher 호출마다
  `RetryBudget()`을 새로 만들었다. 큐 run 하나는 scope 여러 개(주유소·휴게소·돌발·공항)를 돌므로 transport가
  내려가 있으면 scope 수 × 예산만큼 재시도했다. `upstream_retry.sharing_run_retry_budget()`(ContextVar)를
  asset step(`run_tracked_feature_asset`)·큐 op(`execute_feature_update_request`)·scope runner가 열고, 안쪽은 바깥
  예산을 그대로 쓴다. 테스트: 예산 1에서 세 fetcher가 연결 오류면 요청 4건(종전 6건).
- **failure_kind 분류.** 503·`collection` 어긋남(`transport_not_current`)은 `retryable=True`인 step 실패다 — HTTP
  층에서 바로 다시 부르지 않고 `RetryPolicy`가 step을 다시 돈다(경계는 원 예외를 그대로 낸다). 공항 0건은
  계약 위반이 아니라 `transport_empty`, JSON이 아닌 본문은 미분류 `JSONDecodeError`가 아니라
  `transport_malformed_upstream`(`TransportExportMalformed`)이다. 나머지는 `retryable=False`.
- **가격 feature 지역 코드.** transport 이관 뒤 주유소·휴게소 가격 feature는 `Address(road=...)`만 가져 bjd·시도·
  시군구가 비었다(옛 OpiNet 경로는 주유소 place 주소를 그대로 썼다). transport export에는 지역 코드가 없고 가격 job은
  역지오코딩하지 않으므로(M5) `list_primary_place_locator`가 place의 `legal_dong_code`·`admin_dong_code`·`sido_code`·
  `sigungu_code`·행정동 주소를 함께 싣고 가격 feature가 이어받는다. locator 행은 5-tuple이 됐다.
- **관리 UI 로그인 감사.** `recordAuthAuditEvent`의 fetch에 `AbortSignal.timeout(3000)` — 감사 API가 멈춰도 로그인
  응답이 붙잡히지 않는다(vitest).
- **문서.** transport 설정 표(BASE_URL·SERVICE_TOKEN·PAGE_SIZE·TIMEOUT_SECONDS)와 failure_kind 표를 dagster README에,
  integration-map은 peer 주소 게이트(`Host` 아님)·export별 응답 모양으로, settings 설명의 "Host로 닫는다"를 고쳤다.
  dagster README의 옛 `opinet_*`·`krex_*`·`krairport_*` resource/env/schedule 행과 external-apis의 OpiNet·KREX 키 행을
  정리했다. main의 `docs/resume.md`·`docs/journal.md`에 남아 있던 merge 표식 줄(`||||||| parent of 866d318c6`)도 지웠다.
- **RED → GREEN(n150 `~/ci-scratch/ktm-lows`, Python 3.14).** 테스트 커밋 `1bea708d8`: unit 5 실패, dagster 경계 3
  실패 + fetcher 테스트 collection 오류. 수정 head: 같은 표적 191건 통과. 전량: ruff check·lint-imports(4 kept)·
  mypy --strict 세 패키지 통과, unit+lint 3035 통과/16 실패(`test_docker_dagster_runtime.py` 13건은 main과 같은 집합 —
  n150 checkout 환경, 나머지 3건은 부하 아래 signal/lock 타이밍이라 재실행 통과), api 1217·dagster 582 통과,
  vitest RED(1 실패) → GREEN, tsc·eslint 통과.

## 2026-10-02 — Dagster entrypoint가 `code-server start`를 받는다: 브랜치 `fix/dagster-entrypoint-code-server`

- **원인(n150 prod 2026-10-01 21:52Z).** C7 schedule-write spec은 cron override를 `ops.dagster_schedule_overrides`에
  저장하고 location을 reload한다. Map은 override를 definitions import 때 읽는다. 그런데 code-server가 `dagster api
  grpc`라 reload는 "not currently supported" 경고만 남기고 무시됐다 — override가 반영되지 않아 C7이 빨갛다.
- **변경.** production 봉인의 code-server 분기가 하위 명령 `code-server start`도 받는다. 모양(9 argv, loopback `-h`,
  숫자 `-p`, 고정 `-m kortravelmap.dagster.definitions`)은 그대로 정확 일치다. `api grpc`는 Manager compose가 바뀔
  때까지의 전환용으로 남긴다. local-dev 분기도 같은 두 모양에서 runtime preflight를 돈다.
- **`-I`는 자식에 이어지지 않는다.** `code-server start`의 proxy는 자식을 `sys.executable -m dagster api grpc`로
  띄운다(run worker는 `api grpc` 때부터 같았다). user site는 요구된 `PYTHONNOUSERSITE=1`이, `PYTHONPATH`·`PYTHONHOME`·
  `PYTHONUSERBASE`는 기존 거부가 env로 자식까지 막는다. 남는 cwd-on-`sys.path`(`-P`)는 production exec 직전
  `PYTHONSAFEPATH=1`로 막는다(cwd `/app`은 root 0555라 지금도 쓸 수 없지만 기대지 않는다).
- **n150 실측(Manager 브랜치 `fix/dagster-code-server-reloadable`과 함께).** live Map dagster 이미지(1.13.24)로 일회용
  컨테이너를 빈 loopback 포트에 띄웠다: `api grpc`는 reload를 무시(import 1회), `code-server start`는 새 자식 pid로 다시
  import했다. proxy health는 고정 SERVING이라 Manager probe가 자식에 전달되는 `ListRepositories`를 보고 확정된 실패면
  PID 1을 끝낸다(load error·자식 kill 둘 다 재시작 확인).
- **테스트.** 두 모양 수용(자식 env에 `PYTHONSAFEPATH=1`), 섞인 하위 명령·`-h 0.0.0.0`·다른 `-m`·`-f`·추가 인자 거부,
  runtime preflight 매트릭스에 `code-server start`(production·local-dev) 추가.
- **남은 것.** 저장소 자신의 `docker-compose.yml`(standalone)은 `api grpc` 그대로다 — 바꾸면 Manager처럼 probe를
  자식에 묶어야 한다(후속).

## 2026-10-02 — 주유소·휴게소·돌발·공항 원천을 kor-travel-transport export로 이관(ADR-106): 브랜치 `feat/transport-api-sources`

- 소유자 결정: Map에서 transport로 얻을 수 있는 것은 transport API로 바꾸고, 필요하면 transport API를 고친다. OpiNet은
  transport 브라우저 수집본을 쓴다. 공항도 옮긴다. 새 provider 정체성 `kor-travel-transport`(internal) + identity 재지정
  보험. prod Map DB는 비어 있어(예상) shadow 없이 바로 전환한다.
- transport 쪽(`kor-travel-transport` 브랜치 `fix/fuel-latest-prices-incremental` → `feat/map-service-exports`): 최신 유가
  MV가 60초 timeout으로 영구 stale이던 것을 증분 테이블로 고쳤고(0022), 휴게소 기준정보·휴게소 유가 수집기와
  `GET /v1/service/exports/*`(토큰 + loopback Host, 404 은닉), 돌발 활성 집합(수집 실패·30분 정체면 503), 공항 15곳(KPO
  포함)을 더했다(transport ADR-013).
- Map: `providers/kor_travel_transport.py`(계약·엄격 파서), fetcher 5개(`fetch_transport_*`), asset/job/operation 6개를
  `*_transport_*`로 바꿨다. 정규화는 `opinet.py`·`krex.py`·`krairport.py`에 남고 provider 정체성만 바뀐다. migration
  `404_transport_provider_identity`가 새 dataset·operation·scope를 넣고 옛 identity를 옮기고(옛 돌발 entity가 있으면
  중단) 옛 적재를 끄고 계보 함수의 돌발 분기를 옮긴다.
- 지운 것: OpiNet 호출 예산·scope 모드·KST 일일 coalescing·POI target scope, krex 이중 snapshot 안정성 검사, krex rate
  gate 선언, krex/opinet 쿼터 예외 선언, 세 provider 핀, `KOR_TRAVEL_MAP_OPINET_*`·`KOR_TRAVEL_MAP_KREX_*` env.
- 적대 리뷰 반영(같은 날): 신선도를 두 겹으로 — transport는 이력 없음·실패·stale이면 모든 export에서 503,
  Map은 `collection` 플래그·완전 snapshot 0건·돌발 `collected_at` 30분을 다시 재고 `failure_kind`
  (`transport_not_current`·`transport_empty`·`transport_hidden`)로 실패한다(아무것도 지우거나 닫지 않는다).
  404는 자격증명 부재와 갈랐다. 유가 `observed_at`은 transport `collected_at`(마지막 확인)이다 — 오피넷
  `*_DT`(가격을 바꾼 때)를 쓰면 가격을 유지하는 주유소가 4일 지평선 밖으로 사라진다. 유가 job은 주유소를
  역지오코딩하지 않는다(locator로 부모만). UI "과거 날짜" 표식은 가격 도메인으로 고른다. 404 migration은
  옛 preview operation도 끈다. 페이지 상한·cursor 순환 검출·전송 오류 재시도를 더했다.
- C7: 공항 operation은 이제 transport 내부 export를 한 번 부른다. 계약 테스트를 "외부 provider 호출 0"으로 고쳐 적었다
  (`_transport_get`은 공항 export 상수로만 허용, 다른 경로는 빨강).
- 계약 관계(2026-10-03 소유자 결정): Map은 transport export의 소비자다 — pin·vendoring·repin 절차 없음. Map에
  필요한 필드·모양은 transport API를 직접 바꾼다(같은 PR 쌍, 호환 층 없음). 어긋남은 엄격한 런타임 검증이
  `failure_kind`로 실패시킨다. 대표 응답 5종(`tests/unit/golden/kor-travel-transport/`)이 실 파서를 지난다. 처음
  만들었던 vendored OpenAPI·`PIN.json`·repin 스크립트는 같은 날 지웠다.

## 2026-10-02 — ADR-105 적대 리뷰 반영: 같은 브랜치 `feat/remove-map-kma-dagster`

- **MED-1 PinVi가 다음 짝을 막는다.** Manager M05 harness가 OpenAPI hash 불일치를 거부하고 PinVi 계약 테스트가
  `BeachPublicView.latest_weather`를 단언한다. PinVi 브랜치 `chore/map-drop-weather`에서 재vendor한다. 순서: PinVi PR →
  Map PR → pair 회전.
- **MED-2 probe.** `cache_target_snapshot_gc`는 prod에서 돈 적이 없어(schedule STOPPED) 첫 gate가 GC 적체(최대 2,000
  batch)를 health check 안에서 지울 수 있었다. 전용 no-op job `map_run_heartbeat`를 두고 lint를 성질(resource ⊆
  {io_manager}, kortravelmap import 없음, run config 불필요, operation key 없음, in-process 성공)에 결박했다. 옛 기본값으로
  되돌리면 4개가 빨갛다.
- **MED-3 C7 왕복 복원.** KMA write spec이 덮던 "요청 → queue sensor → worker → 종결"을 krairport(번들 정적 데이터,
  upstream 0)로 되살렸다. 실제 prod write(공항 place 15건 멱등)다. 공유 plane Basic Auth 파일을 다시 읽는다.
- **LOW.** 401에 in-flight preflight(같은 upgrade에서 402의 `is_enabled` 필터를 빠져나가던 구멍; 막지 않으면 통과하는
  통합 케이스 추가), 403으로 lineage 함수의 KMA 분기 제거(앱 식과 DB 함수의 분기 집합 일치 unit 테스트 추가), 핀 제거,
  `.env.example` 키·stale docstring·삭제된 schedule mock 정리. frozen H35 replay의 KMA 텍스트는 해시 고정이라 남겼다.
  매분 schedule의 RUNNING 상태 행은 회전 전 stop(runbook)으로 처리한다 — Map에 RUNNING schedule이 0이어도 gate는
  SCHEDULER daemon heartbeat만 보므로 바닥이 빨갛게 고정되지 않는다.
- **n150 게이트(`9de7630`).** unit+lint 3,047 passed / 14 failed(main도 같은 환경 실패 15건 이하), API 1,217, Dagster 624,
  ruff·mypy 3패키지·lint-imports·graph check 통과. 통합 전량 1,106 passed / 2 failed(main에서도 실패하는 docker effect) /
  25 errors(bootstrap 19 환경, glibc collation 6은 단독 재실행 6/6 통과). `test_weather_removal_migration` 3/3(신규 400→402
  in-flight 중단 포함), `test_notice_lineage_key` 전부 통과, `head-schema.sql`은 재생성과 동일. probe lint는 기본값을
  `cache_target_snapshot_gc`로 되돌리면 4/20 빨강. 첫 실행에서 루트 설정의 경고→오류 때문에 setup ERROR 6건이 났다 —
  ERROR는 빨강이 아니므로 필터를 달고 다시 쟀다.

## 2026-10-01 — Map에서 날씨 feature·기상특보 notice 기능 삭제(ADR-105): 같은 브랜치 `feat/remove-map-kma-dagster`

ADR-104(KMA Dagster 경로 제거) 작업 중 소유자 결정이 넓어졌다: weather kind 기능 전부와 날씨 출처 notice(KMA 특보)만
지우고, UI에서도 지우고, 데이터와 관련 스키마도 지운다. 정의(kind·DTO·enum·`make_feature_id`·DB kind 값)는 남긴다.
산림청 산사태 예보와 KREX 교통공지는 날씨 출처가 아니라 남긴다. **배포 전 백업은 소유자가 명시적으로 면제했고, 삭제는
되돌릴 수 없다.** 정기 백업은 이 결정과 무관하다.

- **prod 읽기 전용 실측(12:00Z 전후).** `feature.features` 0행(모든 kind), weather fact·summary·notice 0,
  `source_entities`·`source_records` 0, `ops.current_summary_runs` weather 2,875(매분 schedule의 receipt)·price 5,
  weather·KMA 카탈로그 dataset 12·operation 18·scope 13. notice provider별 행도 0이라 지워지는 notice도 남는 notice도
  현재는 행이 없다. 그래서 402가 prod에서 실제로 지우는 것은 summary run 2,875행과 카탈로그 상태뿐이다.
- **나눈 작업.** Dagster(W1), 라이브러리·API·OpenAPI(W2), migration 402·스키마 산출물(W4), C7/D1/D2(W5), UI(W3), 교차
  정리(W6)를 파일 소유를 갈라 병렬로 했다. 정본 결정은 `WEATHER-REMOVAL-SPEC`(작업 메모)에 두고 모두 같은 정체성 규칙을
  썼다: weather = 카탈로그 `capabilities.produces ∋ "weather"`, 날씨 notice = notice이면서 provider `python-kma-api`.
- **402가 하는 일과 근거**는 migration docstring과 ADR-105에 있다. 지운 스키마 넷은 `head-schema.sql` 전수 검색으로
  weather 전용임을 확인했다. 공유 표 `ops.current_summary_runs`는 남기고 CHECK만 `price`로 좁혔다.
- **게이트에서 잡은 것.** (1) API guard가 `app.routes`로 경로를 셌는데 n150에서는 sub-app mount 때문에 `/metrics`
  하나만 보여 **빈 집합에서 빨갰다** — main에서의 빨강도 그 이유였을 수 있어, OpenAPI `paths`로 바꾸고 main에서 다시
  잰다. (2) squash 경계 검사가 root(`400`)만 허용해 401·402를 겨누는 통합 테스트를 retired 대상으로 봤다 — active
  graph의 revision을 허용하게 고쳤다. (3) PinVi rollout pending receipt의 OpenAPI sha를 재핀했다(`latest_weather` 소멸 —
  PinVi vendor는 다음 짝에서).
- **C7.** KMA 위에 서 있던 러너를 KMA 없이 돌게 했다: read-auth, schedule-write(allowlist
  `feature_place_krairport_airports_monthly_schedule` — fetcher가 번들 정적 데이터만 읽어 upstream 호출 0), POI
  `@c7-causal`. n150 `.d2-live.env`의 `E2E_C7_SCHEDULE`을 그 값으로 바꿔야 러너가 시작한다. D2는 price feature 하나만
  심는다. 둘 다 prod에서만 돌 수 있어 이번에 실행하지 못했다.
- **n150 게이트(브랜치 소스를 PYTHONPATH로, main과 대조).** unit+lint 3,026 passed / 14 failed — 14건은 main에서도
  같은 환경 실패(`test_docker_dagster_runtime` 13: node 의존, `test_c7_prod_live_runner_process` INT-130 1). API 1,217
  passed, Dagster 624 passed, ruff·mypy --strict 3패키지·lint-imports·migration graph `--check` 통과. frontend
  type-check 통과, vitest 380/381(실패 1은 main과 같은 maplibre worker 파일 부재), lint·build는 n150 node_modules가
  main에서도 깨져 판정 불가(W3가 로컬 eslint 통과를 확인). 통합 테스트는 n150 디스크 대기로 testcontainers PostGIS가
  `pg_ctl` shutdown checkpoint에서 죽어(교체된 이유) 하네스에서만 PGDATA를 tmpfs로 두고 돌렸다: 영향 파일 30개
  307 passed, `head-schema.sql`은 `KTM_WRITE_HEAD_SCHEMA=1` 재생성 결과와 바이트 동일. 통합 전량(glibc 이미지)은
  1,110 passed / 3 failed / 19 errors — 19 errors는 bootstrap 묶음의 알려진 n150 환경 실패, docker effect 2건은 main에서도
  같이 실패, `test_tvn34_public_projection_spine`의 EXPLAIN 1건은 단독 재실행에서 통과(공유 DB 통계 순서 의존).
- **빨강 실측.** 브랜치의 guard를 main 소스에 대고 돌렸다: Dagster 5/7 빨강(나머지 둘은 카탈로그 하한·남는 notice
  양성 검사), API 3/5 빨강(나머지 둘은 축 유도 하한·남는 notice preview 양성 검사), UI 4/6 빨강(W3, HEAD 파일 복원),
  DB는 `test_weather_removal_migration.py`가 401에서 19개 제거 검사가 0이 아님을 먼저 단언한다.
- **배포 영향.** 공유 plane Map location의 instigator 11개 중 `current_weather_summary_refresh_minutely_schedule`
  (RUNNING) 하나가 사라지고 sensor 10은 남는다. 옛 Map 전용 instance(`kor_travel_map_dagster`)의 같은 schedule 상태 행도
  쓰이지 않게 된다. 402의 `DROP INDEX`가 `feature.features`에 ACCESS EXCLUSIVE를 잡으므로 매분 schedule과 겹치지 않게
  배포한다(새 코드에는 그 schedule이 없으니 code server 교체 뒤 migration이면 겹칠 일이 없다).

## 2026-10-01 — Map Dagster의 KMA 적재 경로 제거(ADR-104): 브랜치 `feat/remove-map-kma-dagster`

소유자 결정: KMA는 kor-travel-weather가 소유하고, Map은 KMA data.go.kr 오퍼레이션을 다시는 부르지 않는다
(data.go.kr 키를 weather와 함께 쓰고 오퍼레이션당 일일 한도가 빠듯하다).

- **끄던 것이 능력을 남기고 있었다.** `DISABLED_FEATURE_LOAD_SCHEDULES`는 schedule을 만들지 않고 큐의 targeted
  요청만 건너뛰었다. Dagster UI launch·백필, `provider_dataset` 큐 요청, C7의 `external_system:c7-e2e` 요청은
  그대로 KMA를 불렀고, 카탈로그는 KMA refresh operation 5개를 enabled로 들고 있었다.
- **지운 것.** `dagster/kma_weather.py`(asset 5), KMA job·schedule, resource 셋, `fetch_kma_weather_alerts`, 큐
  runner spec·handler binding 5, KMA settings 넷, KMA 대상 좌표 조회(client 4·repo 4), asset 라벨·API cron 힌트,
  `providers.kma`의 Dagster 설정 파서 둘. `DISABLED_FEATURE_LOAD_SCHEDULES`에서 KMA 이름이 빠졌다(AirKorea 등 때문에
  목록은 남는다).
- **남긴 것.** `providers.kma` 변환·정체성 계약(이미 적재된 KMA feature 읽기, `/ops/datasets` fixture preview),
  카탈로그 행·scope·dataset(`is_active`), preview operation, 공개/운영 KMA 특보 이력 API.
- **DB.** `401_retire_map_kma_refresh` — provider `python-kma-api`의 `refresh`·`feature_load`를 `is_enabled=false`.
  이 저장소 관례(`_UPGRADE_STATEMENTS`)를 따르고 receipt head CHECK에 `400`·`401`을 더했다(graph 전체를 받아야 한다는
  lint 계약; `head-schema.sql` 동기화). 400 스쿼시 뒤 첫 child migration이라, 300~313 체인에 맞춰 박힌 migration lint
  하한 다섯(롤 전환 ≥5, 문장 ≥100 등)이 대상이 없는데 빨갰다 — 하한을 "소스 텍스트에 보이는 것을 추출도 전부 본다"로
  옮겼다.
- **재도입 방지.** `test_map_dagster_has_no_weather.py`가 시드 카탈로그에서 KMA operation key를 provider로 유도해
  Definitions(job·schedule·sensor·asset)·handler registry·큐 runner를 보고, 효과 축으로 Map 런타임 소스의 KMA client
  import와 KMA data.go.kr 경로(`1360000`)를 본다. DB 축은 `test_head_enables_no_kma_load_operation`.
  **각 검사를 한 번씩 빨갛게 만들었다**: main 소스에 대고 돌리면 job·asset·launch·소스 넷이 각각 KMA job 5개 /
  `kma_weather_alert_records` / registry의 KMA key 5개 / `import kma` 위치로 빨갛다. 하한 검사는 KMA 행을 뺀 시드로
  빨갛다. 처음 판의 sensor 축은 `RunStatusSensorDefinition`에 `job_names`가 없어 **효과가 아니라 AttributeError로**
  빨갰다 — 그 빨강은 아무것도 증명하지 않으므로 target의 `job_name`을 읽게 고치고 main에서 다시 KMA job 이름으로
  빨개지는 것을 확인했다.
- **prod 읽기 전용 실측(09:00Z 전후).** 공유 plane `dagster_shared`의 Map instigator는 sensor 10 + schedule 1
  (`current_weather_summary_refresh_minutely_schedule`), 옛 `kor_travel_map_dagster`도 같은 11개 — KMA instigator·
  KMA run 0. `dagster_shared`의 KMA schedule 5·run 63(전부 FAILURE)은 weather location 것이다. Map DB(rev `400`)는 KMA
  refresh 5·preview 4가 enabled, KMA feature·sync state·멤버십 가진 import job·요청 0. 그래서 배포가 바꾸는 것은
  Dagster 정의 목록(KMA job 5 소멸, instigator 변화 없음)과 카탈로그의 enabled 5행뿐이다.
- **남긴 일.** C7 러너 가족(`run-c7-prod-live-e2e.sh`, `ops-c7-*` spec)은 KMA 위에 서 있다 — KMA write spec은 이제
  요청 단계에서 거부되고, 러너는 schedule allowlist의 KMA schedule이 2026-09-09부터 없어 이미 돌 수 없었다. 배포 게이트
  (chain16 D1·D2)는 이 러너를 쓰지 않는다. `python-kma-api` 의존 핀, Manager compose의 `KOR_TRAVEL_MAP_KMA_WEATHER_*`
  env도 후속.

## 2026-10-01 — flip 전 drain 절차 정정(공유 Dagster plane cutover 완료): 브랜치 `docs/shared-plane-drain`

Map은 2026-10-01 05:54Z cutover로 05:58Z부터 공유 plane에서 돈다. C7은 06:02Z GREEN이었다.

- **runbook이 틀린 drain을 권했다.** #1290이 `docs/runbooks/docker-app.md`에 "writer drain으로 새 run을 막고 run이
  terminal이 될 때까지 기다린다"고 적었다. 코드(`writer_drain_service.py`)는 그렇게 하지 않는다. Map의 RUNNING
  instigator를 **전부** 멈추므로 operation을 종결 반영할 reconcile sensor와 run-status sensor도 멈추고,
  `min(15초, dagster_termination_timeout_seconds/2)` grace 뒤 남은 run을 `SAFE_TERMINATE`로 끊는다. 그래서 "active
  operation 0건"을 만들 수 없다.
- **실제로 쓴 절차를 적었다.** 창 전 in-flight load가 스스로 끝나게 두고 330초(reconcile lag 300 + 주기 30) 기다리며
  새 load·요청을 시작하지 않는다 → `ops.import_jobs`의 `queued`/`running`·`dagster_run_id` 있음·비격리·
  `provider_feature_load_run`/`feature_update_request` 건수 0을 게이트로 본다 → queue는 닫지 않는다
  (`DISABLED_FEATURE_LOAD_SCHEDULES` 불필요, run 없는 요청은 새 queue sensor가 집는다). Manager cutover script는 게이트를
  precheck와 fence·run-cancel 뒤 switch 전에 두 번 보는데, 두 번째는 snapshot이고 cancel된 `feature_update_request`
  run은 어느 sensor도 종결시키지 않아 손으로 정리한다. 정본은 Manager topology §7과 `scripts/dagster-shared-cutover.sh`.
- **writer drain의 자리.** 원래 용도(Manager cache-target diagnostic/cutover의 writer fence 직전 producer 비우기,
  ADR-082)로는 유효하다고 적었다. pool 이름 변경 배포 전제의 drain 설명("run이 끝나기를 기다린다")도 "grace 뒤 끊는다"로
  고쳤다. 다른 Map 문서에 flip용으로 writer drain을 권한 곳은 없었다(CHANGELOG·journal의 기존 언급은 pool 이름 변경용).

## 2026-10-01 — Map이 공유 Dagster plane에 오르기 전의 차단 항목: 브랜치 `feat/dagster-shared-map-prep`

리뷰가 Map flip 전에 고칠 것 셋을 짚었다. 셋 다 오늘의 Map 전용 instance에서도 같은 결과여야 먼저 머지·배포할 수 있다.

- **reconcile sensor가 모든 tenant의 run을 읽었다.** `_latest_dagster_watermark`·`_dagster_run_page`가 filter 없이
  `get_run_records()`를 불렀다. 공유 instance에서는 weather·PinVi·geo run을 watermark로 삼고, cursor가 없는 첫 tick은
  남의 run 때문에 "non-empty storage" 오류로 멈춘다. 새 `kortravelmap.dagster.run_scope.map_runs_filter()`가
  `dagster/code_location=<Map location>` tag를 붙이고(location 이름은 #1289와 같은 `docker/workspace.yaml` 정본에 결박),
  reconcile 두 조회와 coalescing schedule 둘(feature-load, 매분 weather summary)이 그것만 쓴다. 남의 run만 있는
  공유 instance의 첫 tick은 Map 범위가 비어 null cursor로 시작한다(fake와 실제 ephemeral run storage 두 테스트).
  Dagster는 remote origin이 있는 run에만 이 tag를 단다 — n150 읽기 전용 실측으로 Map instance의 run 1,825건 전부가
  `kortravelmap.dagster.definitions`를 달고 있었다. 배포된 location 이름이 다르면 reconcile은 0건을 조용히 보지 않고
  오류로 멈춘다(`context.code_location_origin` 대조).
- **run-status sensor 일곱이 `monitor_all_code_locations=True`였다.** 기본값으로 되돌렸다 — Dagster가 run의 remote
  origin을 sensor의 location·repository와 대조한다. Map job은 전부 한 location이라 오늘은 평가 대상이 같다.
- **검사.** 설치된 `DagsterInstance`에서 `RunsFilter`를 받는 조회(`get_runs`·`get_run_records`·`get_run_ids`·
  `get_runs_count`·`get_run_partition_data`)를 유도해, 호출이 `filters=map_runs_filter(…)`인지 AST로 본다.
  location으로 좁힐 수 없는 event·asset·backfill·run tag 조회는 금지 목록이다. `monitor_all_*`도 막는다. 옛 모양
  여섯이 각각 빨갛게 나오는지 detector를 테스트한다. sensor 테스트의 fake run storage는 이제 tag filter를 적용한다 —
  무시하던 fake에서는 좁히지 않은 조회도 초록이었다.
- **API가 공개 Dagster URL을 호출했다.** `KOR_TRAVEL_MAP_API_DAGSTER_GRAPHQL_URL`은 prod에서
  `https://map-dagster…/graphql`이고 API가 그것을 호출·보고했다(C7이 그 sha256을 대조). flip 뒤 공개 URL은 Basic Auth
  gateway다. 새 `KOR_TRAVEL_MAP_API_DAGSTER_INTERNAL_GRAPHQL_URL`이 호출 URL이고(없거나 빈 값이면 공개 URL — 오늘과
  같다), 공개 URL은 보고·링크에만 쓴다. allowlist는 호출 URL에만 걸고 공개 URL은 모양만 본다. 응답 DTO는
  `DagsterUrls.public_graphql_url`, 호출은 `graphql_url`이다. overview·dagster-runs·schedules에서 실제 POST된 URL과
  응답의 URL을 대조하는 효과 테스트가 있다.
- **D2가 없는 service를 가리켰다.** `.d2-live.env`의 `E2E_C7_PINVI_DAGSTER_SERVICE=pinvi-dagster`는 손으로 적은
  값이라 PinVi cutover 뒤 preflight가 cardinality에서 멈췄다. `repin.sh` 3단계가 이제 `ktdctl targets list --json`의
  `dagster.control_plane`과 `runtime_services`에서 유도한다 — 공유면 그 프로젝트의 Dagster runtime service 하나
  (code-server), 전용이면 적힌 값을 확인만 한다. Map flip 때 web·daemon 두 키는 Map code-server를 함께 가리키고,
  preflight는 이 두 role에만 service 공유를 허용한다. 공개 URL·hash는 caller attestation이라 유도하지 않고
  `scripts/n150/README.md`에 flip 값을 적었다.
- **C7 client의 Basic Auth.** 선택 키 `E2E_DAGSTER_BASIC_AUTH_FILE`(소유자 전용, `user:password` 한 줄)을 러너가
  검증하고 executor에 read-only bind로만 건넨다. Dagster에 직접 POST하는 세 자리(queue sensor controller, admin
  helper, 최종 복원 검증)가 그 파일이 있을 때만 `Authorization: Basic`을 붙인다.
- **적대 리뷰 후속(같은 브랜치).**
  - MED-1 첫 부팅 경주: 공유 instance 첫 부팅에서 매분 weather summary schedule이나 queue sensor가 reconcile 첫
    tick보다 먼저 Map run을 만들면 "non-empty storage" 규칙이 영구히 발화했다. 이제 cursor가 없고 Map run이
    `FEATURE_OPERATION_RECONCILE_PAGE_SIZE`(200) 이하면 null cursor로 처음부터 훑는다(반영은 멱등). 그보다 많으면
    (n150 전용 instance 1,825건) 여전히 명시 cursor를 요구한다. flip 전 drain 요구(옛 instance에만 run이 있는 active
    operation을 먼저 끝낸다)는 `docs/runbooks/docker-app.md`에 적었다.
  - L2: location 불일치는 `MapRunScopeMismatch`를 던져 tick이 FAILURE로 보인다(다른 예외처럼 SKIP으로 삼키지 않는다).
  - L3: schedule context에는 code location이 없다. coalescing schedule 둘은 location 상수 대신 Map job이 스스로 다는
    tag(`kor_travel_map.operation_key`·`kor_travel_map.job_kind`)로 좁힌다(`map_owned_runs_filter`, n150 weather
    summary run 1,000/1,000이 tag를 단다). lint는 두 helper만 받는다.
  - L4·L5·L7: `repin.sh`는 토폴로지를 stdin으로 받고, 유도한 service 이름을 `^[a-z0-9][a-z0-9._-]*$`로 확인하고,
    source 대조 전에 물려받은 키를 지운다. Map plane을 `E2E_C7_MAP_DAGSTER_CONTROL_PLANE`(own|shared)로 적고,
    preflight는 `shared`일 때만 web·daemon 공유를 허용한다(없으면 own — 엄격).
- 통합 테스트(`test_canonical_provider_operations`의 fake context 한 줄)는 n150에서 돌리지 않았다(PostGIS 컨테이너를
  prod host에 띄우지 않는다) — CI가 본다.

## 2026-09-30 — 공유 Dagster plane 준비의 적대 리뷰 반영: 브랜치 `feat/dagster-shared-stage0`

- **run 상세 범위 판정이 한 번도 발화하지 않았다(HIGH).** 소속을 `Run.tags`의 `.dagster/repository`로 읽었는데,
  GraphQL은 hidden `.dagster/*` tag를 걸러 낸다(`GrapheneRun.resolve_tags`의 `TagType.HIDDEN`). 그래서 "다른
  location → not_found" 갈래는 죽은 코드였고, 테스트는 오지 않는 tag를 가짜로 넣어 초록이었다. n150 12702에서 run
  하나를 조회해 보니 `tags`에 `.dagster/*`가 없었고, `repositoryOrigin`은 `__repository__` /
  `kortravelmap.dagster.definitions`로 왔다. 이제 run 상세는 `repositoryOrigin`을 묻고 selector와 비교한다. origin이
  없으면 not_found다. fixture도 실제 모양으로 고쳤다(hidden tag 없음, origin 있음). 응답 tag를 읽는 다른 자리도
  감사했다. MOIS precheck(coverage tag), dataset schedule(operation key), C7 live helper(request tag)는 모두 보이는
  tag만 읽는다. run 완주 게이트는 SQL `run_tags`를 직접 읽으므로 hidden tag가 있다. `RunsFilter.tags`도 storage를 보므로
  tag filter 자체는 옳다(같은 실측에서 Map 값은 run을 돌려주고 틀린 값은 0건).
- **CI가 constraints 없이 설치했다(MED).** 네 workflow의 저장소 설치 17곳이 모두 `-c docker/constraints-dagster.txt`를
  읽는다. `test_image_python_constraints.py`가 workflow를 훑어 이를 결박한다. 헤더의 "정확한 버전"도 고쳤다. 이
  파일은 나열한 패키지만 고정하고, 전체 freeze가 아니다.
- **범위 검사가 옛 drain 쿼리를 통과시켰다(MED).** 종전 검사는 `filter:` 글자만 봤다. 그래서
  `filter: {statuses: [...]}`처럼 repository tag 없는 리터럴 filter도 통과했다. 이제 `runsOrError` 선택은
  `filter: $runsFilter`여야 하고, 같은 operation이 `$runsFilter: RunsFilter!`와 `repositoryOrError(repositorySelector:
  $repositorySelector)`를 싣고 있어야 한다. bare `runsOrError {`도 잡는다. 훑는 범위를 API·Dagster·core·scripts
  (`lib`·`n150`, `.sh`)·admin UI `.ts`로 넓혔다. 옛 모양 다섯 개가 각각 빨갛게 나오는지 detector 자체를 테스트한다.
- **run 조회의 location 오타가 조용했다(LOW).** runs 패널, MOIS precheck, writer drain의 run 조회가 같은 요청에
  `repositoryOrError`를 싣는다. `Repository`가 아니면 각각 오류 응답, `DAGSTER_QUERY_FAILED`,
  `DAGSTER_PROTOCOL`로 멈춘다. 이전에는 빈 목록이 "run 없음"과 구분되지 않았다. drain이면 아무것도 기다리지 않고
  통과할 수 있었다. drain의 끝나지 않은 상태 집합에는 `STARTING`을 더했다.
- **pool 이름 변경 배포(MED).** 옛 이름으로 도는 run이 있으면 새 이름 run이 한 번 겹친다. OpiNet과 KREX notice에는
  advisory lock이 있지만 `kor_travel_geo` pool의 23개 job에는 없다. 그래서 배포 전제를 두었다. pool job의
  QUEUED·STARTING·STARTED run이 0건이거나, writer drain 아래에서 배포해야 한다. 이 전제를 runbook·CHANGELOG·resume
  체크리스트에 적었다. 검사 명령은 pool job 목록을 live `assetNodes { pools jobNames }`에서 유도한다. n150 실측은
  pool job 27개(`__ASSET_JOB` 포함), 끝나지 않은 run 0건이었다. 이번 한 번만 필요한 전제라 `scripts/n150`에 스크립트로
  두지는 않았다.

## 2026-09-29 — 공유 Dagster plane의 Map 쪽 준비(stage 0 + 3.1): 브랜치 `feat/dagster-shared-stage0`

계획은 `F:\dev\handoff\dagster-shared-plan.md`(Manager 쪽 정본은 `docs/platform-topology.md` §7). 배포 변경은 없다 —
Map은 나중에 Manager pinned pair와 chain17로 나간다.

- **stage 0 — 이미지 버전 고정.** Map은 lockfile 없이 `pip install ".[providers]"`로 설치해 왔고, `dagster>=1.9,<2`는
  하한일 뿐이라 실제 버전은 빌드한 날 PyPI가 준 것이었다. 공유 host(webserver/daemon)보다 높은 dagster가 code-server에
  끼어드는 것은 Dagster 호환 정책 밖이다. `docker/constraints-dagster.txt`에 목표 집합을 `==`로 적고(dagster family
  1.13.24, dagster-postgres 0.29.24, grpcio 1.84.0, grpcio-health-checking 1.81.1, protobuf 6.33.6, pydantic 2.13.5 /
  core 2.46.5 / settings 2.15.0, SQLAlchemy 2.0.54, psycopg 3.3.6(+binary, pool 3.3.3), psycopg2-binary 2.9.13, asyncpg
  0.31.0) API·Dagster Dockerfile이 둘 다 `-c`로 읽는다. 값은 n150 live 이미지(`3d0411dd`)와 같다. n150에서
  `uv pip compile`(Python 3.12, 두 이미지의 설치 인자 그대로)로 해소 가능함을 확인했다. Python은 기존 digest 핀
  3.12.13 그대로다(3.12.14로의 digest bump는 계획상 선택이라 하지 않았다). `test_image_python_constraints.py`가 핀
  형식·누락·family 일치·pyproject 범위 포함·두 Dockerfile의 `-c`와 COPY 순서를 본다.
- **3.1 — code location 범위 조회.** API의 Dagster GraphQL이 전부 `repositoriesOrError`(전 repository)와 filter 없는
  `runsOrError`였다. 공유 webserver에서는 다른 프로젝트 것이 섞이고, **writer drain은 다른 프로젝트의 schedule/sensor를
  멈추고 run을 끊는다.** 이제 `DagsterUrls`가 settings의 repository selector를 들고 다니고, 조회는
  `repositoryOrError(repositorySelector)`와 `runsOrError(filter: {tags: [.dagster/repository=__repository__@<loc>]})`다
  (요약·pipeline overview/runs/schedules·schedule 명령·dataset schedule index·MOIS precheck·writer drain). run 상세는
  다른 code location의 run을 `not_found`로 답한다. 프로젝트별 webserver에서도 selector가 유일한 repository를 가리키므로
  오늘 배포와 호환된다. admin UI 운영 홈의 Dagster 링크는 `/locations/kortravelmap.dagster.definitions`(Dagster UI는
  `__repository__`면 경로에 location만 쓴다 — live 번들에서 확인), C7 live helper 둘과 run 완주 게이트도 같은 selector로
  좁혔다. `test_dagster_code_location_is_one_name.py`가 이름을 쓰는 자리(settings 기본값·`.env.example`·UI 상수·C7
  helper·게이트)를 `docker/workspace.yaml`과 대조하고, API src·scripts에 `repositoriesOrError`와 filter 없는
  `runsOrError`가 돌아오지 못하게 한다.
- **pool 접두사.** pool 이름공간과 `default_limit`은 instance 전역이다. `opinet_api`·`krex_notice_snapshot`·
  `kor_travel_geo`(geo 프로젝트와 겹칠 이름)를 `kor_travel_map.` 접두사로 바꿨다. 배포 직후 옛 이름 슬롯을 잡은 run과 새
  이름 run이 한 번 겹칠 수 있다.
- **D4 확인(읽기 전용, n150 12:40Z 무렵).** live GraphQL의 schedule 34·sensor 10 전부 live 상태 = 코드 `default_status`,
  metadata DB `jobs` 11행 전부 `DECLARED_IN_CODE`. DB에만 켜진 instigator가 없어 코드 변경은 없다.
- 남긴 것: 7개 run-status sensor가 `monitor_all_code_locations=True`라 공유 daemon에서는 다른 프로젝트 run 이벤트도
  평가한다. `kor_travel_map.operation_key` tag가 없으면 `panel_only`로 끝나 정확성 문제는 없고 비용만 든다 — 끌지는
  C3e 설계 결정이라 별도로 판단한다. 공유 plane의 env 이름(`KOR_TRAVEL_DAGSTER_SHARED_PG_URL`)·URL 재지정은 cutover
  때 Manager rendering 몫이다.

## 2026-09-29 — Map DB를 공용 PostgreSQL로 옮겼다

소유자가 위험을 받아들이고(결정 C) Map 전용 인스턴스(12700)를 공용 인스턴스(11000)로 합치기로 했다. superuser는 새로
만들지 않았다(S1): Map 부트스트랩이 superuser를 요구하는 것은 새 DB를 만들 때 한 번뿐이라, Manager가 그 one-shot에만
공용 admin 자격증명을 secret 파일로 넣는다(n150 Compose v5.2.0에서 env·inspect·argv에 드러나지 않음을 먼저 실험으로 확인).
Map 전용 튜닝(1GB 버퍼, 모든 DB prewarm 등)은 소유자 지시로 공용 인스턴스 전체에 적용했다.

순서가 곧 안전장치였다. 먼저 Manager M1(펜스: 인스턴스 admin 소유 DB는 절대 drop하지 않는다, rebuild는 PostgreSQL 서비스를
재생성하지 않는다, Map DB는 PUBLIC CONNECT를 닫고 연결 상한을 건다)을 넣고 12700에서 새 pair로 검증했다. 공용 튜닝(MT)과
이전(M2)은 창 안에서만 머지·설치했다 — main에 미설치로 두면 누군가의 설치가 공용 재생성을 무장시키기 때문이다.

창은 스크립트로 돌았다. 공용 재생성은 CHECKPOINT·`stop --time 300`·설정 read-back·20분 tenant 게이트로 감쌌고, 이전은
writer fence → 12700에서 감사 dump → 12700 clean stop(보존) → M2 설치·`.env` 편집(G 잠금) → `--adopt-live-databases`
rebuild → V1~V9로 갔다. 공용 인스턴스의 반복 재시작 원인(고아가 된 헬스체크 프로세스를 PID 1 postmaster가 입양)은
전날 다른 세션의 Manager #433이 이미 막아 두었다.

## 2026-09-29 — MP 적대 리뷰 2차: compose 경고로 새던 비밀 조각, 탐지기 다듬기, fixture 대상 대조

- **MED(둘, 같은 결함)**: `repin.sh` 3단계와 `chain16.sh` E 단계가 Map API를 `docker compose … ps`로
  찾으면서 stderr를 흘렸다. compose는 `ps`에서도 project `.env`를 해석한다. `/opt/.env`의 따옴표 없는 값에
  든 `$`의 꼬리를 변수 이름으로 읽어 `The "<꼬리>" variable is not set` 경고를 찍는데, n150에서 그 꼬리는
  UI 관리자 비밀번호 hash의 조각이었다. chain16은 repin 출력을 `2>&1 | tail -12`로 옮기므로 한 사이클에
  여덟 줄이 운영 로그(`/root/chain17-<tag>.log`)에 남는다. 옛 `docker ps --filter label=…`은 compose를
  읽지 않았으니 MP가 새로 연 경로다. 두 조회에 D2 러너와 같은 `2>/dev/null`을 붙였다(실패는 `|| die`·64-hex
  검사가 잡는다). 새 검사 `test_compose_calls_keep_compose_warnings_out_of_the_output`은 `scripts/n150`의
  모든 compose 호출이 stderr를 버리거나(`2>/dev/null`) 잡는지(`capture_output=True`) 본다 — 세 스크립트의
  redirect·capture를 하나씩 지우면 각각 빨갛다.
  - Map 밖(소유자 몫): `/opt/.env`의 `*_UI_ADMIN_PASSWORD_HASH` 넷을 작은따옴표로 감싸거나 `$$`로 바꾼다
    (CLI compose 모델이 값을 망가뜨린다). 조각이 리뷰 transcript에 한 번 찍혔으므로 Map UI 관리자 비밀번호
    교체도 권한다.
- **탐지기(LOW 둘)**: 넓던 규칙 둘(`host:port/`, `-p`/`--port`)이 `curl …:12701/healthz`·`ssh -p 22`를
  잡고, 공용 instance로 가는 모양 다섯(`docker compose … exec`, `docker container exec`, 키워드
  `host=`/`port=`, `PGHOST`/`PGPORT`, `postgres:` 서버 이미지)은 놓쳤다. 규칙을 좁혀 바꿨다: DSN 문자열
  (`postgres(ql)(+drv)://`), libpq 연결 키워드·env, PostgreSQL 서버 이미지. exec는 compose·container 형태도
  보고, 값 있는 flag(`-e X=1`)를 target으로 읽지 않는다. exec 허용은 이름 목록이 아니라 **유도**다 — 같은
  스크립트가 API 조회 결과로만 대입한 변수(`API="$(docker compose … ps …)"`, `api = apis[0]`)에만 허용하고,
  다른 대입이 하나라도 있으면 빠진다. 리뷰가 실측한 모양을 두 자기 검사 목록에 넣었다.
- **판정 도구 읽기 전용(LOW)**: `adjudicate.sh` COUNT_PROGRAM의 "아무것도 쓰지 못한다"를 검사로 바꿨다. 같은
  wrapper에 INSERT를 넣어 돌리면 `read-only transaction`으로 거부되고 행이 남지 않는다. `readonly=True`를
  빼거나 ROLLBACK까지 COMMIT으로 바꾸면 빨갛다.
- **다섯째 잔여물 줄(LOW, 원래부터)**: fixture의 provider dataset(`admin-live-{run_id}-{kind}`)을 센다. source
  계보와 refresh policy가 모두 그 아래 달리므로, dataset 쪽만 남은 BLOCKED lane이 네 줄 0으로 `clear-blocked`
  되지 않는다. 양성 대조는 fixture의 `_dataset_key`로 심고 다른 run·운영 dataset을 이웃으로 둔다.
- **fixture 대상 대조(LOW)**: D2 러너 `validate_runtime`이 lock·state 전에 fixture DSN의 host·port·DB·query를
  API 컨테이너의 `KOR_TRAVEL_MAP_PG_DSN`과 대조한다(사용자·비밀번호는 다를 수 있다). 확인 키 셋(DB 이름·login·
  head)은 다른 instance의 같은 이름 사본에서도 맞으므로, 이동·롤백 직후 repin 없이 러너만 돌 때 API가 읽지
  않는 사본을 고치는 것을 막는다. 값은 출력하지 않는다.
- 작은 것: bootstrap 모듈의 `create_labels` import를 skip guard 밖으로(없으면 19건이 조용히 skip이 아니라
  실패), `_postgis_image.py` 주석은 MT 설치 전의 정본이 실행 중인 공용 컨테이너의 `.Image`임을 적었다.
- n150 대상 실행(`cfb1eb45` + 이 변경): 대상 unit 141 passed, ruff 초록. count 모듈 alpine·glibc 각 **4 passed**,
  bootstrap 모듈 alpine·glibc 각 **19 passed**(client 잔여 0). 변이는 모두 빨갛다 — compose redirect·capture
  제거 셋, adjudicate에 넣은 공용 instance 모양 여덟(compose exec 둘, container exec, 이름만 맞춘 `api=` 셸·
  python 재대입, 키워드 connect, `PGPORT`, `postgres:` 이미지), 러너 대조 무력화·호출 제거·사용자까지 비교,
  count의 readonly 제거·COMMIT·dataset 0·run 무시, labels import 이름 변경(19 errors, skip 아님).
- 전량: lint 검사 하나(`test_adjudicate_only_clears_a_lane_that_is_really_stopped`)가 줄 수 확인을 `4`로 박아
  빨개졌다. 리터럴 대신 COUNT_PROGRAM이 실제로 세는 줄 수와 확인이 같은지 보게 했다(확인을 4로 낮추거나 여섯째 줄을
  더하면 빨갛다). n150 `b91a41a6`: ruff 초록, `mypy --strict` 일곱 대상 초록, lint-imports 4 kept, unit+lint
  **3079 passed / 15 skipped / 14 failed** — 14건 모두 main(`90b1e5e0`)에서 같은 node로 실패한다(node_modules
  없는 체크아웃의 frontend 검증 13, `test_lifecycle_preserves_signal_exit_status[INT-130]`). GitHub
  `postgis-only.yml`(run 36456439859, `66a1cb3a`): glibc **1163 passed / 12 skipped**, alpine 첫 시도는
  `test_public_partial_indexes_have_exact_state_predicate_and_explain_proof` 1건(planner 선택, 알려진 flake — n150
  단독 3회씩 이 브랜치·main 모두 passed), 실패 job 재실행 **1157 passed / 18 skipped**.

## 2026-09-28 — Map DB를 공용 instance로 옮기기 전에 Map 쪽에서 할 일(MP): glibc 정렬, 두 번째 CI lane, 유도된 DB 접근

소유자가 Map의 두 DB를 공용 instance `kor-travel-shared-postgres`로 옮기기로 결정했다(결정 C, ADR-103 ·
Manager ADR-53). 이동 자체는 Manager의 창에서 하고, 이 PR은 Map 쪽 준비다. 창 전에 새 pair로 핀해야 한다.

- **collation**: 공용 instance는 glibc 이미지(PG 16.9·PostGIS 3.5.2, `en_US.utf8`)다. alpine(musl)에서는 default
  collation이 byte 순서와 같아서 순서가 digest·잠금·Python `sorted()` 비교에 들어가는 text 키가 지금까지 무방비였다.
  evidence export와 backup twin(`principal_id`), evidence restore(lease 재구축·`FOR UPDATE`), curation collection
  advisory lock, cache target source head `FOR KEY SHARE` capture와 member 조회에 `COLLATE "C"`를 걸었다.
  - feature update scope 잠금은 일부러 두었다. DB 함수 `lock_feature_update_request_member_scopes`가 같은 default
    collation 순서로 잠그므로, 한쪽에만 `COLLATE "C"`를 걸면 오히려 잠금 순서가 갈린다.
  - 탐지기 `test_collation_sensitive_orderings_glibc.py`는 lane 이미지 위 최소 표면에서 `'a-b'`·`'ab'`·`'B'`·`'a'`를
    흘린다. advisory lock 순서는 `search_path` 앞 schema에 같은 이름의 함수를 두어 기록하고, row lock 순서는
    `INSERT … SELECT … FOR KEY SHARE`의 삽입 순서로 잰다. alpine lane에서는 skip, 공용 glibc digest에서는 판별력이
    없으면 실패한다.
- **CI**: `integration` job을 `lane: alpine`·`lane: glibc` 두 leg으로 나눴다. 이미지 정본은
  `tests/integration/_postgis_image.py`(`KTM_TEST_POSTGIS_IMAGE`)다. 값이 있는데 digest 모양이 아니면 조용히
  alpine으로 떨어지지 않고 실패한다. main에 required check가 없으므로 두 leg 초록은 리뷰가 확인한다.
- **n150 스크립트**: `adjudicate.sh`는 Map API 컨테이너 안에서 그 컨테이너의 DSN으로 읽기 전용으로 세고,
  `repin.sh` 3단계는 D2 fixture DSN을 그 DSN에서 유도한다. instance 이름·port·superuser 문자열은 없다.
- glibc lane을 n150에서 처음 전량으로 돌리자 두 가지가 나왔다(1139 passed / 20 failed).
  - bootstrap-on-existing-db 19건이 `/usr/bin/sleep: not found`로 죽었다. 테스트가 스크립트를 **서버 컨테이너
    안에서** 돌렸는데, Debian 기반 공용 이미지에는 `/usr/local/bin/psql`도 `/usr/bin/sleep`도 없다. 운영은
    Manager one-shot(`postgres:16-alpine`)이 TCP로 붙으므로 문제는 테스트 모양이었다. 서버 network를 나눠 쓰는
    alpine client 컨테이너에서 돌리게 바꿨다 — 두 lane 모두 19 passed.
  - head 오라클(`alembic/head-schema.sql`)이 헤더 빈 줄 하나로 어긋났다. pg_dump 16.10+는 `\restrict` fence
    뒤에 빈 줄을 하나 더 쓰고, 공용 instance의 16.9는 fence를 쓰지 않는다. 정규화가 fence 뒤 빈 줄도 걷게 했고,
    alpine lane 재생성이 커밋본과 바이트까지 같다.
- n150 부하(load 16~20)에서 docker API가 60초를 넘겨 testcontainers가 `ReadTimeout`으로 죽는 일이 잦았다.
  테스트 하네스에만 docker-py timeout을 늘리는 플러그인을 얹어 돌렸다(코드 변경 아님). alpine lane 첫 전량에서는
  bootstrap 모듈 19건이 알려진 부팅 경합(`not yet accepting connections`)으로 죽었고, 단독 실행은 19 passed다.
- 두 수정 뒤 n150 전량(`0fd7de1c`): glibc **1161 passed / 12 skipped / 0 failed**, alpine 1154 passed / 18 skipped /
  1 failed(`test_public_partial_indexes_have_exact_state_predicate_and_explain_proof` — 단독 재실행은 이 브랜치와
  main 모두 passed). unit·lint 세션의 실패 16건은 main과 같은 집합이다(node_modules 없는 체크아웃·git 아닌 트리).
- 적대 리뷰 반영:
  - **adjudicate 잔여물 측정의 양성 대조.** 종전 테스트는 빈 스키마에서 키 넷과 0만 봐서, 늘 0을 내는 프로그램도
    초록이었다(n150 실측: 변이 `always_zero`·`no_wildcards`·`count_nothing`·`WHERE true` 넷이 살아남았다). 0은 이
    판정에서 위험한 방향이다 — `clear-blocked`가 잔여물이 남은 lane을 지운다. 세어야 할 행은 migrated DB에 둘 수
    없다: session이 나눠 쓰고, `ops.feature_requests`는 삭제가 막혔고, alias CHECK가 `e2e_live_acceptance::`를
    거부한다. 그래서 같은 cluster에 버리는 DB를 만들고, 프로그램이 읽는 열만 실제 타입(catalog에서 읽는다)으로
    만들어 `ktm_feature_schema_owner`로 커밋해 둔다. 소유 이름은 D2 fixture의 `_admin_fixture_name`에서 온다.
    그 run_id의 네 줄이 모두 1, 다른 run_id는 소유분 0이다. 위 넷과 `SET LOCAL ROLE` 제거까지 다섯 변이가 모두 빨갛다.
  - n150 스크립트 셋(`repin.sh`·`chain16.sh` M01·`adjudicate.sh`)이 Map API 컨테이너를 D2 러너와 같은 compose
    project(`/opt/kor-travel-docker-manager`)에서 정확히 하나로 찾는다. service 라벨만으로는 같은 라벨을 단 다른
    stack을 집고, chain16은 `head -1`이었다.
  - `repin.sh` 3단계는 임시 파일을 소비자처럼 `set -a; .`로 읽은 값이 API DSN과 같을 때만 rename한다. 문자 검사는
    `~`를 받는데 대입의 `:` 뒤 `~`는 tilde 확장된다(`:~:pw@` → `:/root:pw@`). 옛 read-back은 바이트를 비교해 통과했다.
  - 인스턴스 탐지기를 이름에서 효과로 옮겼다: PostgreSQL client, DSN `host:port/`, port flag, 유도한 API가 아닌
    곳으로의 `docker exec`. 공용 instance의 이름으로 적은 줄도 이제 빨갛다.
  - 수동 `postgis-only.yml`과 로컬 `verify-all-gates.sh`도 glibc lane을 돈다. 게이트가 둘이 되자 geo live probe
    검사가 두 줄을 합쳐 보던 탓에 변이 R11·R11b가 살아남았다(n150 전량에서 드러남). 이제 게이트마다, 그 게이트가
    쓴 로그로 사후 단언을 요구한다. `test_ci_workflows`는 통합 suite를 도는 모든 workflow job에 두 lane이 있는지
    본다. bootstrap client 컨테이너는 testcontainers label(Ryuk)·`--rm`·`sleep 7200`을 갖는다.
  - 결과: GitHub `postgis-only.yml` dispatch(`3234b3d1`, run 36421797357) glibc **1162 passed / 12 skipped**, alpine
    **1156 passed / 18 skipped**. `ci.yml`의 두 leg는 PR이 열려야 돈다. n150 대상 실행은 두 lane 모두 count 모듈
    3 passed, bootstrap 모듈 19 passed(client 잔여 0).
- Manager ADR 번호 정정: #433이 ADR-52(공용 instance의 `init`·exec probe·grace)가 되어, 이 이동의 Manager ADR은
  **ADR-53**이다. ADR-103 `관련`, `CLAUDE.md`, `integration-map.md`, `deploy.md`, `rest-api.md`와 이 절·resume을
  고쳤다. main의 docs 커밋 #1286 위로 리베이스했다(journal·resume 충돌은 양쪽을 모두 남겼다).
  - 리베이스 뒤(`8b0941a8`): GitHub `postgis-only.yml` dispatch(run 36450175854) glibc **1162 passed / 12 skipped**,
    alpine **1156 passed / 18 skipped**. n150: ruff 초록, `mypy --strict` 일곱 대상 초록(공유 venv에 dev extra
    `types-PyYAML`이 없어 scratch target으로 보탰다), lint-imports 4 kept. unit+lint 3044 passed / 15 skipped /
    15 failed — 14건은 main(`90b1e5e0`)에서도 같은 node로 실패한다(node_modules 없는 체크아웃의 frontend 검증 13,
    `test_lifecycle_preserves_signal_exit_status[INT-130]`), 1건(`test_orchestrator_guardian_lock_…`)은 단독
    재실행에서 passed. gate mirror·mutation battery 17 passed.

## 2026-09-28 (저녁) — 공용 PostgreSQL은 크래시한 것이 아니라 고아를 입양했다

Map DB를 공용 인스턴스로 옮기는 계획을 검토하다가, 공용 인스턴스가 오늘 새벽 한 번이 아니라 67시간 동안 다섯 번
재시작했다는 것이 드러났다. 매번 로그는 "server process (PID N) exited with exit code 2"였고, 그 PID는 로그에 한
줄도 남기지 않았다.

원인을 네 갈래(PG 로그, 호스트·Docker 이벤트, 클라이언트, PG 16.9·moby 소스)로 조사하고 반박 검증을 붙였다. 결론은
"백엔드가 죽은 것이 아니다"였다.
- 컨테이너에 `init`이 없어 postmaster가 PID 1이다.
- 헬스체크 `CMD-SHELL pg_isready`는 sh → Perl 래퍼 → 실제 pg_isready로 자식을 만든다.
- 호스트가 멈칫하면(다섯 번 모두 Manager 재구축·chain17 중) 5초 timeout이 나고, Docker는 exec의 main PID인 `sh`만
  죽인다. 남은 pg_isready는 postmaster에 입양되고, 서버가 응답하지 못하면 exit 2로 끝난다.
- PG16 `CleanupBackend`는 BackendList를 찾기 전에 종료코드부터 보고 전체를 리셋한다.

어제 Dagster에서 본 CMD-SHELL 고아와 같은 계열이다. Dagster에서는 좀비가 쌓였을 뿐인데, Postgres에서는 고아 하나가
전 테넌트 재시작으로 증폭된다. `pg_postmaster_start_time()`은 크래시-재시작에서 바뀌지 않아 이 사건들을 가렸다.

고침(`init: true`와 exec 형식 `pg_isready -t 2`)은 소유자가 지시한 공용 튜닝과 같은 재시작에 넣는다. Map을 옮기기 전에
이것이 먼저 들어가야 Map이 이 위험을 물려받지 않는다.

## 2026-09-28 — M05가 끝까지 갔다: 마지막 벽은 부하가 아니라 PinVi의 빈 Dagster 저장소였다

healthcheck 폭주를 잡은 뒤에도 M05의 PinVi `app-dagster`는 unhealthy였다. 부하 탓으로 보기 쉬웠지만 원인은
PinVi #558의 회귀였다. app compose의 dagster가 `PINVI_DAGSTER_PG_URL`을 받지 못했고 `pinvi_dagster` DB도 없어서,
한가한 호스트에서도 뜰 수 없었다. PinVi #570이 bootstrap 스크립트와 one-shot `app-dagster-db-init`을 넣었다.

새 pair(Map `a18d9274` + PinVi `c5be9eb4`, pinset `8c9f9ad1`)로 회전해 chain17을 돌렸다. t63a는 D1 한 건이
15초 poll에 걸렸고(같은 Map이 직전과 직후 사이클에서 통과), t63b는 ACL 40/40, D1 11, D2 passed였다.
Manager `88599eb9` 설치 뒤 실행 identity가 바뀌었으므로 리허설(p9r `rehearsed`)부터 했다. 실제 실행 p9는
약 11분 만에 `passed`/`completed`로 끝났다. Manager #428로 포트를 고정한 덕에 이미지 빌드가 캐시를 탔다.

같은 날 정리한 것:
- **안 쓰는 전용 PostgreSQL 퇴역**(Manager #429). 목록에서 지운 것은 geo·concierge·pinvi 전용 인스턴스와
  airport-db다. n150에서 실제로 내린 것은 접속 0이던 `pinvi-postgres` 하나이고, 데이터 디렉터리는 남겼다.
  그 과정에서 Manager 백업 cron이 9/20 무렵부터 매일 실패하고 있었음을 찾았다. cron은 git이 아닌 배포 사본을 돌리는데,
  그 사본이 compose 모델보다 뒤처져 있었다.
- **공용 PostgreSQL의 원인 미상 재시작**(03:28:57Z). 백엔드 하나가 exit code 2로 끝났다(보통 SIGQUIT 처리 경로다).
  postmaster가 모든 연결을 끊고 재초기화했다. 디스크 대기 속에서 pre-fsync에 82초가 걸렸다. OOM 흔적은 없다.
  그 시각 이 세션의 에이전트는 n150 임시 사본에서 가짜 대역 단위 테스트만 돌리고 있었다.
  Map을 공용으로 옮기는 계획은 이 영향 범위를 따져야 한다.
- `CLAUDE.md`와 `docs/integration-map.md`는 여전히 "프로젝트별 전용 인스턴스 넷"이라고 적고 있었다.
  실측(공용 11000 + map 12700)으로 고쳤다.

## 과거 기록 아카이브

> 현행 작업 창(2026-09-28~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [`journal-2026-09f.md`](archive/journal-2026-09f.md) | 2026-09-26 ~ 2026-09-27 | 14건 | 31 KB |
| [`journal-2026-09e.md`](archive/journal-2026-09e.md) | 2026-09-20 ~ 2026-09-25 | 8건 | 27 KB |
| [`journal-2026-09d.md`](archive/journal-2026-09d.md) | 2026-09-16 ~ 2026-09-19 | 7건 | 22 KB |
| [`journal-2026-09c.md`](archive/journal-2026-09c.md) | 2026-09-14 ~ 2026-09-15 | 8건 | 22 KB |
| [`journal-2026-09b.md`](archive/journal-2026-09b.md) | 2026-09-11 ~ 2026-09-13 | 5건 | 26 KB |
| [`journal-2026-09a.md`](archive/journal-2026-09a.md) | 2026-09-01 ~ 2026-09-10 | 23건 | 84 KB |
| [`journal-2026-08d.md`](archive/journal-2026-08d.md) | 2026-08-29 ~ 2026-08-31 | 14건 | 25 KB |
| [`journal-2026-08c.md`](archive/journal-2026-08c.md) | 2026-08-28 ~ 2026-08-28 | 21건 | 20 KB |
| [`journal-2026-08a.md`](archive/journal-2026-08a.md) | 2026-08-14 ~ 2026-08-27 | 124건 | 200 KB |
| [`journal-2026-08b.md`](archive/journal-2026-08b.md) | 2026-08-01 ~ 2026-08-14 | 89건 | 166 KB |
| [`journal-2026-07c.md`](archive/journal-2026-07c.md) | 2026-07-26 ~ 2026-07-31 | 60건 | 167 KB |
| [`journal-2026-07a.md`](archive/journal-2026-07a.md) | 2026-07-13 ~ 2026-07-24 | 115건  | 219 KB |
| [`journal-2026-07b.md`](archive/journal-2026-07b.md) | 2026-07-01 ~ 2026-07-12 | 28건   | 45 KB  |
| [`journal-2026-06a.md`](archive/journal-2026-06a.md) | 2026-06-10 ~ 2026-06-30 | 172건  | 219 KB |
| [`journal-2026-06b.md`](archive/journal-2026-06b.md) | 2026-06-02 ~ 2026-06-10 | 179건  | 220 KB |
| [`journal-2026-06c.md`](archive/journal-2026-06c.md) | 2026-06-01 ~ 2026-06-02 | 36건   | 53 KB  |
| [`journal-2026-05a.md`](archive/journal-2026-05a.md) | 2026-05-24 ~ 2026-05-31 | 90건   | 218 KB |
| [`journal-2026-05b.md`](archive/journal-2026-05b.md) | 2026-05-24 ~ 2026-05-24 | 3건    | 7 KB   |
