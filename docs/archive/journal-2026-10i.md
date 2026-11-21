# journal 아카이브 — 2026-10 (i)

[현행 기록](../journal.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다. 상대 링크만 `docs/archive/` 기준으로 다시 맞췄다.

## 2026-10-24 — 생성 SQL의 protocol-first 진입과 승인 복구(418)

- core/provider/manual/요청승인4개를 첫EX로 보강하고 내부owner2개에 함수EXEC만 추가한다. 승인55P03은 기존503/RetryAfter5로 전달한다.
- 실제PG/ASGI·기존M01/M04·unit/graph/docs 집중51 PASS, 별도 이전mapper500→수정503/동일key복구를 확인했다. [범위·실패·검증](../reports/2026-10-24-creation-protocol-entry.md).
- 제품J/W·경계시험root/W 검토PASS. 정확CI·최신418 실UI·전체수집전환/후속전파는 미완이다. 기본OFF/seed0/운영0.

## 2026-10-24 — protocol EX 재진입 비용 개선(417)

- 이미 보유한 EX는 xact 소유를 재확보한 뒤 반복 설정 조회를 생략한다. session/xact·savepoint·NULL/SH 승격·timeout 계약은 유지한다.
- 실제PG7+unit4=11·oracle/metadata4·graph18·lint373 PASS(기존6skip). 합성1000회 wall 중앙값584.55→24.95ms이며 운영 CPU 개선율은 아니다.
- 선행 #1379·#1383은 각각 최신CI/실UI16·18 통과 뒤 main에 머지됐다. #1385는 실UI18+별도HTTP2 PASS/정확CI 대기, #1386은 두리뷰 PASS/CI·수집UI 대기다.
- 이번417의 독립2코드리뷰 PASS. 정확CI·실UI와 생성SQL·전체수집전환·후속전파는 미완이다. 기본OFF/seed0/운영0. [범위·실측](../reports/2026-10-24-protocol-ex-reentry.md).

## 2026-10-24 — 큐레이션 import의 protocol-first 진입

- 실제 whole M03 import와 direct manual의 역순40P01을 재현하고 normal-head 첫 advisory 전 protocol EX만 추가했다. h35/다른2caller·DDL·권한은 유지한다.
- 최종PG9+기존curation/merge48·관련unit76·lint377 PASS(기존6skip). 두 리뷰·정확CI는 대기이며 기본OFF/seed0/운영0이다. [범위·실패·증거](../reports/2026-10-24-curation-import-protocol-entry.md).
- tasks-rule §8에 따라 가장 오래된09-30 한 절3480B를09h로 원문 보존해 분리했다. 옛DB 전체 replay·전체 writer 활성화는 미완이다.

## 2026-10-24 — field override 진입 보강(416)

- SQL author/revoke·patch/create를 조기EX로 맞추고 manualcreate55P03을 기존503/RetryAfter5로 반환한다.
- 실제 PG/ASGI29+순수5=34·unit110·oracle/metadata2·lint373 PASS(기존6skip). native Python helper·수집배선은 제외다.
- 두 코드리뷰 PASS, 정확CI·실UI는 대기다. 기본OFF·seed0·운영0. [실패·범위·검증](../reports/2026-10-24-field-override-protocol-entry.md).

## 2026-10-24 — 파일 레지스트리의 백업 링크 복구

- 실제 통합 UI에서 파일 상세의 백업 링크가 없는 상세 route를 prefetch해404를 냈다. 백업 목록 페이지로 연결하고 중첩·공백 파일 경로의 회귀를 추가했다. DB·DTO·프론트·수집/잠금 변경0이다.
- 수정 전 회귀1 FAIL을 보존했고 수정 뒤 router9 PASS·Ruff·strict mypy1·문서 redaction PASS다. 독립2리뷰·정확 CI·최종 실제 UI는 후속 수용이며 기존16case별 PASS를 전체 성공으로 세지 않는다. [원인·범위](../reports/2026-10-24-backup-file-link.md).

## 2026-10-24 — state/lifecycle SQL first-entry 폐포(415)

- admin/reactivate/core/lifecycle author·revoke5개를 함께 protocol-first로 보강하며 원래 서명·본문·owner/ACL을 보존한다. Python 업무·field override·identity·정책 seed/운영 변경0이다.
- 실제 PG36+unit5 총41 PASS(16.63초), valid nested state·M05 non-kept·기존 provider retire·SH 거부/rollback·active-policy 거부·닫힌 ACL을 확인했다. 초기 seed 준비 실패는 별도 보존했다.
- 공식 oracle 기록1skip과 별도 비교/metadata2 PASS·전체 lint373 PASS/기존6skip을 구분했다. 독립2리뷰·정확 CI/UI는 미완이며 전체 동시 쓰기 완료가 아니다. [범위·실패·증거](../reports/2026-10-24-state-lifecycle-protocol-entry.md).

## 2026-10-24 — 통합 전체 CI의 시험 격리 보완(#1379)

- b460의 두 실제 PG lane는 같은5건 실패였다. 4건의 새 읽기 세션 fixture 누락과 metrics의 앞선 committed행 미고려를 제품 변경 없이 고쳤다. 0/2 sibling 제어군으로기존실패를 재현하고 old/new snapshot·writer commit 단언을 보존했다.
- test-only c5b635363의 실제 PG/ASGI48 PASS(120.45초), 제품/DDL0diff·Ruff/redaction PASS다. 원본 glibc1425/12skip/5FAIL·alpine1419/18skip/5FAIL 및 수정전 제어군 로그를 보존했다. 새 정확 전체 CI·실제 UI·머지는 미완, 기본OFF/seed0/운영0 유지. [원인·수정·제약](../reports/2026-10-24-scoped-concurrent-write-integration.md).

## 2026-10-24 — ADR115 구현 합집합 수용(#1379)

- 10개 검토된 구현 부모를 제품 고정점 `ebb62ccb8`로 합쳤다. 유일한 제품 합성은 승인 native 전체에 승인 phone 첫 gate2줄뿐이며 나머지 제품은 승인 부모 blob과 동일하다. 공통 문서의 양쪽 전체 항목도 보존했다.
- 최종 집중175 PASS·공식 oracle/metadata2 PASS·lint373 PASS/기존skip6·Ruff/strict mypy/import4계약 PASS, 독립 교차 리뷰2 PASS. 실제 SIGKILL 복구(#1378)와 M05 old40P01 재현·414 보강(#1381)을 예외 rollback과 구분했다. task 안내 길이 실패는 원인을 고쳐 재검증하고 원본을 보존했다.
- main 정확 CI·최신 실제 HTTP/UI·머지/운영 수용은 미완이다. 기본 OFF·seed0·운영0, 전체 T/collector·Geo/지역/identity·Weather/Transport 전파 및 취소된 export 운영 활성화 재개 없음. [통합 증거·제약](../reports/2026-10-24-scoped-concurrent-write-integration.md).

## 2026-10-24 — M05 중복 후보·판정의 protocol-first 보강(414)

- 실제 기존 M05 CALL과 scoped begin의 Feature/head 역순에서 40P01을 재현했다. 414는 후보 기록·판정 public v2/private inner의 첫 BEGIN에 EX만 추가하고 본문·서명·ACL은 보존한다. 기존 내부 owner EXEC만 정본에 더하며 새 공개 권한·정책 활성화는 없다.
- 수정 후 실제 PG8개·순수4개 총12 passed/14.23초, 전체 lint373 passed·기존 skip6, 공식 실제 oracle 재비교+metadata2 passed다. 초기 관측 PID/진단 시간 실패는 분리 보존했다. [재현·상한·범위](../reports/2026-10-24-manual-dedup-protocol-entry.md).
- 기본 OFF/정책 seed0/운영 활성화0이며 컨트롤러를 둔 소규모 정확성 시험이다. 전체 writer 전환·Geo·대량/운영 ARM 성능·Weather/Transport 전파·최종 두 리뷰/정확 CI/UI 수용은 미완이다.

## 2026-10-24 — ADR115 제한 native scalar 비용 실측(#1376)

- schema412의 로컬 amd64·2CPU/1536MiB 격리 환경에서 고정 2dataset·2record를 직렬/병렬2 각각 fresh clone 3회로 측정했다. 중앙값 elapsed는 **273.81→158.42ms**였지만 **PG CPU는 +4.2%**여서 CPU 감소를 입증하지 못했다. 전체 수집·운영 ARM·대량/공유 Feature 성능으로 일반화하지 않는다.
- 별도 정확성 probe에서 두 실제 source DML의 미커밋 중첩 79.23ms를 확인했다. 이 강제 barrier는 성능 6회에서 제외했고, 결과/lineage/완료 receipt hash는 모두 같았다. 자체 container의 정확 생성 ID 정리를 확인했으며 운영·provider 호출은 0건이다.
- 실측 source는 `4c9916d0b90406a0613ca8b41434260b6ec85696`의 `tracked_clean=true`이고, 현재 runner SHA256 `64cd3944e648a2be957aee01aec78a3bb845f8585b80770b740e44122d154fc9`와 같다. 원시 JSON SHA256 `f3f33144390854288657d47209dada2c5c5f6092dd4b7fc1b1dad61d2dbd236f`와 로그는 별도 로컬 감사 보관소에 동일 bytes로 보존했다.
- 두 독립 source 리뷰를 통과했으나 정확 CI·전체 T-CWRITE 수용은 별도다. 최신 부모 대비 제품 소스 변경 0, 기본 OFF·정책 seed0·운영0을 유지한다. 후속 413 수용·전체 SQL writer 전환·일반 수집 배선·API p95·Weather/Transport 전파는 이 측정의 완료 범위가 아니다. [수치·실패·제약](../reports/2026-10-24-scoped-native-scalar-measurement.md).

## 2026-10-24 — ADR115 구현과 전체 수용 범위 구분

- #1371~#1377의 커널·reader·제한 winner/native·비용·직접 SQL 보강과 증거를 [수용 현황](../reports/2026-10-24-scoped-concurrent-write-acceptance-status.md)에 정리했다. 정확 CI가 진행 중이거나 feature base에서 아직 발행되지 않은 PR은 green/머지 완료로 세지 않는다.
- 제한 병렬2의 elapsed 개선과 PG CPU 약4.2% 증가를 분리했다. 예외 rollback을 실제 worker 사망으로 세지 않으며 SIGKILL 검증은 별도다. 모든 T-CWRITE 전체 수용·운영 활성화·Weather/Transport 전파는 미완, 취소된 export 운영 활성화/Map 연동 검증도 재개하지 않는다.

## 2026-10-24 — ADR115 SQL 직접 진입 413 실제 검증

- 기존 SQL 7개의 첫 protocol EX 진입을 원문 signature·본문 SHA-256, 원래 owner/ACL과 함께 검증했다. 공유→배타 승격 거부·실제 두 세션 차단 PID·옛 전역 fence 선점 방지를 포함한 단위/PG/전체 lint **407 PASS/6 기존 skip**, 공식 head oracle·metadata **2 PASS**다.
- receipt 정적 검사에서 드러난 동적 문자열 문제를 명시 전체 head 목록으로 정리했다. 초기 실패도 기록했다. 두 독립 리뷰·정확 CI 수용 전이며 기본 OFF/seed0/운영0, 전체 writer·Geo·지역 전환과 Weather/Transport 전파는 미완이다. [증거와 범위](../reports/2026-10-24-legacy-sql-protocol-entry.md).

## 2026-10-24 — ADR115 기존 SQL 직접 호출의 잠금 순서 보강 착수

- Python fence만으로 커버되지 않는 기존 SQL 7개에 첫 protocol EX 진입을 추가한다. 기존 body/owner/search_path/ACL을 유지하고 scalar OFF·seed0·운영0을 지킨다. 전체 writer 전환이 아니다.
- 실제 전체 bootstrap+기존 fence5 PASS(13.85초), 정적 역할 검사7 PASS/1 기존skip. SQL 직접 CALL/경합·head oracle·독립2리뷰/CI 수용은 진행 중이다. [범위·초기 실패·남은 검증](../reports/2026-10-24-legacy-sql-protocol-entry.md).

## 2026-10-24 — ADR115 제한 native scalar 실제 DML 중첩

- 기존 primary 장소의 이름·전화만 다루는 명시 helper를 별도 추가했다. claim artifact 검증→protocol/epoch/manifest→source/head→후보/winner→finish를 같은 TX에 묶는다. 자동 수집·지역 분할·운영 활성화는 없다.
- 실제 PG에서 독립 dataset의 두 source DML 동시 미커밋 구간, 실패 rollback/같은 artifact 복구, 완료 receipt의 무 DML 재호출, 오래된 artifact 보존을 확인했다. first_seen 불변식 충돌을 수정한 뒤 native3+기존lineage1 모두 PASS(26.39초).
- 412 선행 수용·최종 두 리뷰/CI/HTTP/UI·대량/전체 writer 전환과 Weather/Transport 전파는 미완이다. [범위·실패·검증](../reports/2026-10-24-scoped-native-scalar-refresh.md).

## 2026-10-24 — ADR115 제한 scalar winner·정합성 검증(#1373)

- 412는 기존 Feature/primary source의 name·phones만 명시 정책으로 투영한다. R1 값/R2 검증 head, override/revoke, 실제 순서 반전·old RR·Geo 증거 보호를 확인했다. 기본 OFF/정책 seed0/운영 활성화0이며 mixed legacy writer preflight 전 production cutover는 금지한다.
- 실제16 PG/18 unit 통과, role tuple 정산 뒤 lint369 passed·기존 skip6, 공식 head oracle 재생성 후 비교+metadata2 passed. 초기 revision 길이·ACL inventory·generated 열·fieldset 축소 실패는 수정 후 재검증했다.
- OFF 10k×7표를 411/412 fresh clone 각3회 측정해 scalar trigger0/원래 validator 동일/deferred context 동일을 확인했다. 로컬 관리자 synthetic이며 운영 ARM/실제 collector 성능 개선율이 아니다. [원본 수치·제약·실패 기록](../reports/2026-10-24-provider-field-scalar-projection.md).
- 413 기존 SQL 직접 진입점의 protocol-first 보강, 전체 membership/Geo/일반 수집 전환, 두 독립 최종 리뷰·정확 CI·HTTP/UI 수용과 Weather/Transport 전파는 미완이다. 기존 API/UI 동작을 새 native 수집에 자동 연결하지 않았다.

## 2026-10-24 — ADR115 운영·관리 다중 reader 후속

- 초안 #1374는 관리·운영 GET 13개의 DB 읽기 phase를 RR로 고정한다. 외부 Dagster HTTP는 첫 DB 조회 전에 끝내며 외부 상태까지 같은 snapshot이라고 약속하지 않는다.
- reconciliation snapshot의 기존 FOR SHARE는 유지하고 이 1개 경로만 RR/read-write로 분리했다. 나머지 12개는 read-only다. 실제 readonly 제어군의 25006 오류를 재현하고, row lock 경합·응답 종료 뒤 writer 재개·pool의 기본 RC 복귀까지 검증했다.
- 최종 소스 708672f06 실제 PG/ASGI 10 passed, cache 단위 178 passed, 앞선 8 router 단위 510 passed다. 부모 #1372 기반이므로 main 재기준 뒤 CI가 필요하며 두 독립 리뷰·실제 HTTP/UI·운영 적용은 미완이다. [검증과 미완](../reports/2026-10-24-api-ops-reader-snapshot-followup.md).

## 2026-10-24 — ADR115 순수 다중 조회의 snapshot 고정

- 초안 #1372는 29개 순수 다중 SELECT를 최초 데이터 조회 전 read-only REPEATABLE READ로 고정한다. 쓰기·lease·외부 HTTP와 별도 요청 페이지의 원자성을 확대하지 않는다.
- cold API key 인증 세션을 hash 조회 직후 반환해 pool size=1 재진입 timeout을 없앴다. 실제 PG/ASGI 13 passed(기존 RC 혼합 반증·RR 일관성·pool 복원·cold 인증 포함), 관련 API 198 passed다. 전체 API 1,344 passed/1 failed는 새 dependency의 테스트 override 누락을 수정한 뒤 auth 93 passed로 재검증했다.
- 소스 b8f6e677a는 독립 리뷰 2인 PASS다. 정확한 최종 문서 포함 후보의 CI·별도 실제 HTTP/UI 검증은 남아 있다. 기존 writer 잠금·운영 정책·배포 변경은 없다. [전체 reader 분류와 경계](../reports/2026-10-24-api-reader-snapshot-inventory.md).

## 2026-10-24 — ADR115 범위 커널·기존 writer fence 통합

- #1371에 411 scope/epoch/owner/manifest·membership 재검증과 기존 protocol→전역 fence 순서를 연결했다. runtime 직접 테이블 쓰기는 닫고 기존 writer 배타 경로·기본 OFF를 유지한다.
- 실제 PG 커널·전체 bootstrap·metadata 56 passed/1 오라클 기록 skip, 후속 오라클 비교 포함 40 passed/1 기존 skip. 별도 legacy fence 15 passed. 초기 role/trigger 실패는 수정 후 재실행했다.
- 제한 scalar·reader는 별도 초안 #1373/#1372다. 전체 provider DML 병행·정책 seed·운영 활성화·Weather/Transport 전파는 아직 미완이다. [검증과 한계](../reports/2026-10-24-scoped-concurrent-writes-implementation.md).

## 2026-10-24 — ADR115 실제 동시 쓰기 구현 착수

- 기준선 #1370은 정확 `2a53dce7c`의 CI 5개·실제 glibc/alpine·독립 리뷰 2인을 통과해 머지했다. 두 lane의 원본과 checkout/runner/fixture/ACL/12phase를 대조했다. 직렬 synthetic 기준선이며 운영 절감이나 동시 쓰기 완료가 아니다.
- 다음은 후보 완전성/winner·scope/epoch/manifest·순수 reader snapshot을 분리 구현한 뒤 실제 독립 DML 중첩과 공유 Feature·복구를 검증한다. 기존 전역 fence·기본 OFF·정책 seed0·운영0을 유지한다.
- Weather·Transport 전파는 Map의 해당 개선 수용 이후다. [순서·검증·남은 범위](../reports/2026-10-24-scoped-concurrent-writes-implementation.md). T-CWRITE-01~09 전체 acceptance는 미완이다.

## 2026-10-24 — ADR-114 2단계 재리뷰 Low·main 재기반(#1365 뒤): 브랜치 `feat/adr114-valkey-weather`

- origin/main(#1365 transport T4·#1368·#1369) 위로 rebase. OpenAPI 3종·admin `types.ts`는 rebase한 트리에서 n150이 다시
  뽑았고, vnext 계약 두 파일은 main 쪽을 받은 뒤 weather 항목(revision·service added 5건)을 다시 얹고 sha를 다시 쟀다.
  문서만 손으로 합쳤다(새 항목 위, 줄머리 충돌·diff3 마커 없음).
- 재리뷰 Low: `/nearest` 예보는 후보 최대 50곳(관측·요약은 10곳 그대로 — 예보 없는 측정소 12곳이 KMA 격자보다 가까운 통합
  검사), 이미 지난 `to`/`forecast_to`는 422, 배치 id는 경로 `feature_id`·weather `location_id`와 같은 모양·길이 검사(docstring은
  "둘 다 가능"으로), `…_DAILY_SUMMARY_DAYS=1`이면 `vs_previous_day`는 언제나 null(ADR W7·설정 설명), 테스트 이름 정정.
- 검사(n150 일회용 python:3.13, origin/main `0b2dc53d0` 위): ruff·mypy --strict(279)·lint-imports·OpenAPI drift 초록, 통합
  (실제 Valkey) 34 passed, unit+lint+api 4,773 passed·24 failed(main 기준선 환경 실패 그대로 — docker runtime 23·
  `test_settings_default_values` 1), dagster 패키지 세션 905 passed.

## 2026-10-24 — ADR-114 2단계 리뷰 반영(#1367): 브랜치 `feat/adr114-valkey-weather`

- origin/main(#1358·#1359)로 rebase. 생성물(OpenAPI 3종·admin `types.ts`·vnext baseline·receipt 핀)은 rebase한 트리에서
  다시 뽑았고 문서만 손으로 합쳤다.
- 정확성 리뷰(차단 없음): 깨진 저장 값 → 부분 `unavailable`(위치 값 503과 같은 판정), `partial`을 읽는 시각으로 다시
  계산(KST 경계 `daily_slot_bounds`, 끝났어도 적재 때 partial이면 유지), partial 구간은 `vs_previous_day=null`(06:30 아침),
  429·5xx(500 포함, 503 제외) 재시도, `|`·제어 문자 location_id는 페이지 전체 계약 위반(재시도 없음 — 행만 빼면 위치가 조용히
  사라진다), 둘째 페이지 이후 422는 처음부터 한 번 재시작(두 번째는 계약 위반), roster `source_status`는 null.
- 운영·소비자 리뷰: `/nearest`는 근처 최대 10곳에서 부분마다 데이터가 있는 가장 가까운 위치(`source{feature_id, location_id,
  distance_m}`, HIGH — 가장 가까운 대기질 측정소가 KMA 예보를 가리던 문제), weather 반경 100 km(weather 전용 상수, transport
  모듈 import 제거 — #1365 충돌 회피, `bbox_search_box`만 남김), `POST /locations/batch`(50곳, weather `location_id` lookup),
  묶음 읽기는 `read_many`로 왕복 두 번, 예보 `from`·`to` 창, ETag `If-None-Match` + 304 시 `checked_at`만 기록, schedule을
  weather 공개 시각 뒤로(관측 :25·:40, 초단기 :48, 단기 하루 8회, 중기 06·07·18·19시, 외부 3시간), `/status` 오류는
  `failure_kind` 코드만, 인증 header 설정(`…_AUTH_HEADER`), ADR W6 벌 수 정정(최악 약 240 MB)·W8 토큰 위험·지속성·회전 순서·
  Manager env.
- weather ETag 확인(main `7aa7e70` `export_snapshots.py`): ETag는 `snapshot_id`를 포함하고 같은 manifest의 snapshot은 TTL
  15분 동안만 재사용된다 — 15분보다 긴 주기의 poll은 내용이 같아도 거의 매번 200이다(관측 :25→:40 같은 짧은 간격에서만
  304 기대). 비용은 주기 정렬로 줄인다.
- 검사(n150 일회용 python:3.13, origin/main `1d01ccbc2` 위 rebase): ruff·mypy --strict(279)·lint-imports·OpenAPI drift 초록,
  통합(실제 Valkey, root `filterwarnings=error` 세션) `test_valkey_{weather,transport}_state.py` 33 passed, unit+lint+api
  4,696 passed·24 failed(전부 main 기준선 환경 실패 — docker runtime 23·`test_settings_default_values` 1), dagster 패키지
  세션 905 passed. 첫 재검사에서 잡은 둘을 고쳤다: rebase가 남긴 diff3 기준 마커 줄(CHANGELOG·journal·resume),
  `POST /locations/batch`의 domain command registry 등록(`_query`, 쓰기 수 79 → 80).

## 2026-10-24 — ADR-114 2단계: weather 현재·예보·세 구간 요약 Valkey·service REST: 브랜치 `feat/adr114-valkey-weather`

- 원천 계약: weather main `7aa7e70`(W1~W5 producer 머지 완료 — #143~#164)의 OpenAPI·라우터·실제 HTTP 예시로 맞췄다.
  `GET /v1/service/exports/{locations,current,forecasts?style=,daily-summaries?days=,status}`, header `X-Admin-Token`
  (weather `KOR_TRAVEL_WEATHER_ADMIN_TOKEN`), `{items, meta}` + 서명 cursor(TTL 15분)·`snapshot_id`·`source_status`,
  503 = 완결 export 없음, 410 = snapshot 만료, 401 = 토큰. 로컬 `F:\dev\kor-travel-weather`는 `9aa0d33`(main보다 1
  커밋 뒤, 문서만 차이) — 읽기 전용 scratch clone으로 대조했다.
- live(읽기 전용): odroid weather API는 `3a0ae398`(weather128)이라 `kortravelweather_api.routers.service_exports`가 없고
  `/v1/service/exports/*`는 404다. n150 Map code-server에는 weather 주소·토큰 env가 없다(Valkey URL·transport env만 있다).
  n150 어떤 컨테이너에도 weather 관리자 토큰이 없다 — Manager가 넣어야 한다.
- 설계(ADR-114 "구현 설계 — 2단계" W0~W8): 데이터셋 7개(`weather.locations`·`current`·`forecast_{ultra_short,short,mid,
  external}`·`daily_summaries`), **값 하나 = 위치 하나**(`make_feature_id(kind="weather", category="99000000",
  bjd_code=None)`), GEO는 위치 데이터셋 하나·다른 데이터셋은 같은 id로 `HMGET`. 매 run 전량(증분 `since`·ETag 미사용),
  410은 처음부터 한 번 재시작, `source_status`(worst)·`source_collected_at`(min, 하나라도 null이면 null)을 세대 메타에
  싣는다. 지난 예보 시각은 읽을 때 뗀다. REST는 `/v1/service/weather/{locations,locations/{id},nearest,status}` — 묶음은
  데이터셋별 `status`로 부분 장애를 알리고 요약은 전날 같은 구간 대비 `vs_previous_day`를 싣는다. 메모리 추정 약 48 MB
  (교체 겹침 최대 약 100 MB, transport 포함 200 MB 미만 / 1 GB).
- ADR-105 재도입 방지 검사(`test_api_serves_no_weather.py`·admin vitest)는 `/v1/service/weather/` 접두사만 예외로 두고
  예외의 실재·폐쇄(전부 service 정책, 예외 스키마는 다른 경로에서 닿지 않음, 빼는 것이 실제로 있음)를 따로 잰다.
  Dagster 쪽 검사(카탈로그 operation·client 쓰기·KMA import)는 그대로 초록이다 — 이 job은 PG를 쓰지 않는다.
- OpenAPI: admin·service에 4 operation·스키마 18개 **추가**(기존 불변, user 불변) → PinVi `apps/api/tests/contract/
  kor-travel-map-openapi-{admin,service}.json` 재vendor 필요. admin TS 타입(`types.ts`)도 재생성했다 — main에서 1단계
  transport route가 빠진 채 drift였던 것도 함께 들어갔다(frontend CI는 main에서 이미 빨갛다 — npm audit).
- 검사(n150 일회용 python:3.13, `-c docker/constraints-dagster.txt`): ruff·mypy --strict(276 파일)·lint-imports·
  OpenAPI drift `--check` 초록. unit+lint+api+dagster 5,536 passed·24 failed — 실패는 전부 main 기준선의 환경 실패
  (`test_docker_dagster_runtime.py` 23·`test_smoke_import.py::test_settings_default_values` 1; safe.directory를 넣어
  sealed tree·tick window는 이번엔 초록). 통합(실제 Valkey 컨테이너) `test_valkey_weather_state.py`+
  `test_valkey_transport_state.py` 30 passed. 첫 통합 실행에서 테스트의 httpx 전역 patch가 API 미들웨어의
  `isinstance(…, httpx.AsyncClient)`를 깨뜨려 고쳤다(적재 op 동안만 patch). dagster 패키지 테스트를 다른 패키지
  테스트와 한 세션에 섞으면 dagster `BetaWarning`이 오류로 승격돼 정의 검사가 빨갛다 — CI처럼 패키지 세션으로 돌리면
  초록(1단계 transport 검사와 같다). admin vitest(`map-ui-has-no-weather.test.ts`)는 n150에 workspace node_modules가
  없어 돌리지 않았다 — 예외 조건만 바꿨다.

## 2026-10-24 — ADR115 T-CWRITE-01: 격리 쓰기 기준선 runner

- 고정 synthetic fixture와 전용 PostGIS container/template clone으로 native load_bundles→seal/commit의 cold/warm 3회 runner를 구현했다. CPU/RSS/WAL·실제 DML 구간/잠금 샘플·CI artifact를 남기며 전체 T01/동시 쓰기 완료로 세지 않는다.
- 첫 실제 PG에서 post-upgrade runtime ACL 조정 누락을 확인해 정본 routine/setup pool 폐기·fresh worker 최소권한 preflight/login 검증을 보완했다. GRANT 추가/owner 측정 우회 없이 두 lane을 재수용한다.
- 기존 global fence/FeatureRepo/winner/API는 변경하지 않는다. 외부 DSN·운영 접속·새 로컬 DB/container0. [범위·미완](../reports/2026-10-24-scoped-write-baseline.md).
