# journal 아카이브 — 2026-10

[현행 기록](../journal.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다.

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

## 2026-10-19 — production MapLibre worker asset 누락 복구 (PR #1340)

- **실측 원인.** 인증된 live UI가 `/maplibre/maplibre-gl-worker.mjs`를 404 HTML로 받았다. Map 화면 코드는 worker가 없으면 GeoJSON source가 로드되지 않아 고배율 marker를 표시하지 못한다. Docker runtime stage가 `.next/standalone`과 `.next/static`만 복사하고 `public`은 누락했다.
- **수정.** frontend image에 builder의 `public`을 같은 standalone package 경로로 복사하고, live UI가 worker/shared 두 파일의 HTTP 200·JavaScript content type·비어 있지 않은 본문을 검사한다. marker 시나리오는 데이터가 있는 좌표-bearing `place`에서 실행하고, viewport 안정화는 외부 타일의 무한 `idle` 대기를 피하도록 bounded로 바꿨다.
- **검증.** `docker build -f docker/frontend.Dockerfile` 성공, 결과 이미지에서 worker 19 KB와 shared 502 KB 확인, E2E `tsc` 성공. 운영 UI 반영과 live 브라우저 검증은 PR CI 후 진행한다. Dagster를 import하는 Python unit test는 로컬 개발 환경에 Dagster가 없어 수집 단계에서 실행하지 못했으며, PR CI가 해당 게이트를 담당한다.

## 2026-10-17 — 통합 planner flake 결정화(T-TEST-PLANNER-INDEX): 브랜치 `fix/t-test-planner-index`

- **원인(실측).** keyset 쿼리에 같은 열의 인덱스가 둘이다 — partial `idx_features_updated_keyset`과 술어 없는 admin
  `idx_features_admin_updated_keyset`. 공개 행만 있는 seed에서 partial의 이점은 Filter 비용 하나(약 0.19)라, 인덱스 크기가
  갈리면 뒤집힌다. 크기를 가르는 것은 **LP_DEAD 비대칭**이었다 — admin 목록처럼 admin 인덱스만 훑은 쿼리가 죽은 항목에
  표시를 남기면 다음 insert가 admin 쪽에서만 자리를 다시 쓴다(n150 재현 partial 622~744 page vs admin 127 page, plan은
  CI 실패와 같은 `Index Scan using idx_features_admin_updated_keyset … Filter`).
- **고정.** 테스트 transaction 안 `REINDEX`(keyset 쌍 두 벌, 롤백) + 같은 수의 비공개 행(더 새 `updated_at`, 일부 같은
  이름) + 실패 시 plan 전문. 재시도·skip 없음. 고정을 되돌리면 같은 순서에서 2/2 빨강, 고정 판은 20회 연속 초록.

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

[현행 기록으로](../journal.md)
