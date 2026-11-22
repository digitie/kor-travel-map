# journal 아카이브 — 2026-10 (j)

[현행 기록](../journal.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다. 상대 링크만 `docs/archive/` 기준으로 다시 맞췄다.

## 2026-10-28 — run-status sensor tick 실패로 cursor 엿새 정지(#1434)

prod code server가 30초마다 `operation_has_no_enabled_memberships`(419로 끈 transport run 3건)를 찍었다. 원인은
tick 실패다: 앞 이벤트가 `None`(reaction), 뒤 이벤트가 `SkipReason`이면 `evaluate_tick`이 `CheckError`로 tick을
죽이고 cursor를 commit하지 않는다(#1345 뒤). 추적 행은 이미 terminal이었다. 수정: operation 이벤트는 `DagsterRunReaction`(tick당 하나),
`RunRequest`는 success만; 실제 `evaluate_tick` 테스트 4건. 운영: 네 sensor cursor를 최신 이벤트로 옮김(백업 n150 `~/mapnoise-cursor-backup-*`).

## 2026-10-28 — ADR-117: SH 스냅샷·스칼라 정책 경로 퇴역(alembic 435)

소유자 승인(DC-2). prod 읽기 전용 측정에서 SH 경로는 한 번도 돌지 않았다(flag OFF, 정책 0, attempt·artifact 0,
schedule run 0, 427 index 100 MB `idx_scan`=0 — ADR-117 §1).

- **435**: 434 head 보존 루틴 15개를 hash 고정으로 다시 쓰고 SH 전용 루틴 74·표 10·index 3을 CASCADE 없이 지운다.
  사전 조건(정책·attempt·스냅샷·lease·활성화 trigger) 하나라도 있으면 아무것도 지우지 않는다. head는 pg_dump 18.
- **P는 배타 전용**으로 남긴다(ADR-111 완전 복귀는 재증명이 필요해 기각). 단건 writer 10개는 P를 잡지 않아 seal이
  관리자 동시 편집에 23514로 닫히고 적재가 재시도된다 — §2.2 잔여(#1426의 교환).
- Python·Dagster 스냅샷·scoped·opt-in·reader·harness와 env 3종(무시)을 지웠다. T-CWRITE-01~09는 대체로 이관했다.
- head-schema 재생성 중 identity 문자열의 search_path 의존과 trigger 함수 drop 순서 결함을 잡아 고쳤다.

## 2026-10-28 — T-PG18-CI: prod coord_5179 PROJ 7→9 drift 검사 clean

공용 PG 16→18(pg_upgrade)로 PROJ 7.2.1 → 9.8.1이 된 뒤 runbook `coord-5179-proj-pin.md` §3을 n150 prod Map DB에서
읽기 전용으로 전수 실행했다(API 컨테이너 DSN, `feature_id` keyset 5,000행 51배치, 배치마다 READ ONLY transaction·
`statement_timeout` 30s·0.4초 휴지, load·`/health` 지연 감시). checked 252,447(= 종료 시 `coord IS NOT NULL` 수),
`drifted`(> 1mm) 0, max 1.63e-9 m, p50/p90/p99 0, p99.9 7.0e-10 — 0 초과 2,306행은 모두 1e-6 m 미만 부동소수 잡음.
§4 재계산·REINDEX 불필요. 25초, load 최대 2.46, `/health` 최대 15ms. 아무것도 쓰지 않았다.

## 2026-10-28 — T-PG18-CI: CI·compose를 PG18 공용 digest 한 lane으로(ADR-118, #1431)

공용 PG 16→18 뒤 CI 통합 suite를 `postgis/postgis:18-3.6@sha256:4a43e3c3…` 한 lane으로 바꿨다(옛 PG16 alpine·glibc 삭제).
PG18이 드러낸 가정 — `400` fresh guard(`attstattarget` NULL·소유자 MAINTAIN·contype `'n'`), catalog 해시의 `'n'` 행,
RESTRICT 23001, parent420 ACL digest — 을 major 무관하게 고쳤고 head 오라클을 pg_dump 18로 재생성했다. migration은 없다.
n150 CI-parity 4세션 초록(통합 1988 PASS/23 skip). 남은 것: GitHub CI·머지, prod PROJ 7→9 drift 검사(acceptance).

## 2026-10-28 — #1426의 main 병합 뒤 resume 크기 경계 복구

ebb92ca9의 새 Python CI는 문서 크기 한 항목에서 실패했다(resume 227100B > 225280B).
§8에 따라 9월8일 M05 완료 이력 한 절 5075B를 원문 그대로 기존 9월 archive로 옮겼다.
기존 archive 세 절과 나머지 live 본문은 보존하고 원래 위치의 원문 링크·상단 탐색표를 남긴다.
제품·시험·상한·현재 미완 판정과 snapshot profiles OFF는 그대로다. 새 exact-head CI와 UI는 별도다.

## 2026-10-28 — #1426의 main 충돌·기존 통합 회귀 호환 교정

기준 head `28a97e6d`의 양 PostGIS CI는 각각 6개가 실패했다. main `fddc1659`의
배포·공개 UI 수용 기록과 PR의 WI-5~11 기록을 모두 보존해 두 문서 충돌을 해결했다.
434의 장부 L-only·epoch=0 단건 진입을 따르도록 기존 시험 네 파일을 교정했다.
승인 요청 행의 실제 잠금 timeout·rollback·동일 key 복구, K→L 대기 task 취소와
pool1 재사용, 현재 schema head의 ACL, 같은 TX의 확정 prefix 선점을 검증한다.
장부 뒤 확정으로 승격하는 역순은 계속 23514이며 실패 TX의 변경은 rollback된다.
제품 코드·SQL·마이그레이션·운영 flag는 바꾸지 않았다.

로컬 alpine 고정 digest에서 기존 실패 6개가 77.93초에 통과했다. CI 범위 Ruff,
main mypy 198파일, import-linter 4계약도 통과했다. 넓은 `ruff check .`의 기존
비제품 문서 스크립트·journal 검사 스크립트 7건은 별도 실패로 보존했다.
새 후보 전체 CI·독립 최종 리뷰·UI·434 운영 배포는 아직 미완이며 전체
T-CWRITE-01~09 미완·snapshot profiles OFF와 ADR-117 선행 조건을 유지한다.

## 2026-10-28 — 현재 배포·원51복구·공개 UI13 수용

Map001487에 검증6611이 포함돼 별도 구버전 재배포는 하지 않았다.
PG18 유지보수 뒤 원 RUNNING51을 복구했고 원 STOP13·외부3을 포함한67상태가 같다.
공개 UI13·정리는45.225초에 통과했다.
[운영 정산](../reports/2026-10-27-bound-snapshot-stale-replan.md#현재-배포-포함원51복구공개-ui13-수용)에
실패 이력을 보존했다. 전체 writer9개 미완/OFF·CPU/RSS 미측정을 유지한다.

## 2026-10-27 — typed stale 복구 코드의 최종 CI·후보UI·정상 머지

정확6611 CI10과 양 PostGIS(glibc1953PASS/23skip·alpine1947PASS/29skip), 원 writer
pair2·후보 실제UI14 및 두 독립 검토 뒤 #1424를 mainc3adc0c로 정상 머지했다.
새17개는 전체 suite/skip 전집으로 포함을 확인했으며 개별 PASS event 계측은 아니다.
[최종 정산](../reports/2026-10-27-bound-snapshot-stale-replan.md#정확6611의-최종-ci실제-ui정상-머지-수용)에
원 실패·source6611/API와 f29 UI build 구분·쿠키 삭제/401/정리를 남겼다. archive 원문
9819B 뒤 footer로 EOF P3를 닫는다. 운영433/공개UI는 후속이며 전체9미완/OFF를 유지한다.

## 2026-10-27 — Codex PR 통합 리뷰의 비잠금 항목(WI-5~11)

최근 1주 Codex PR 46건(#1358~#1419) 통합 리뷰를 하나의 PR로 정리하는 작업 중 잠금 순서와
무관한 항목이다. 브랜치 `feat/map-codex-review-misc`에서 만들어 통합 PR 브랜치에 합친다.

- **WI-5** shadow hook이 순서가 뒤바뀐 bundle의 record key를 recorder에 넘겨 23514로 적재
  transaction 전체를 rollback시켰다. 저장 head가 그 record일 때만 capture한다. 운영은 shadow
  scope 미설정이라 휴면이었다(n150 Dagster env 읽기 확인).
- **WI-6** 관리 파일의 오프라인 업로드 링크가 없는 상세 경로(404)를 가리켰다.
  `/admin/offline-uploads`로 고치고 `_build_links`의 모든 href가 `page.tsx`에 대응하는지 본다.
- **WI-7** inbound 자격 증명 목록 하나로 기동 distinctness와 `/v1/service/*`의 403 판정을 묶었다.
  수동 생성 digest가 feature-request·reconciliation digest와 같아도 통과했고, 그 토큰은 403이
  아니라 401로 떨어졌다. 운영 API env(읽기만)는 설정된 8종 사이 충돌 0건이다.
- **WI-8** K 없는 정상 반환에서 정리만 실패하면 503 대신 연결을 폐기하고 commit된 결과를
  돌려준다. ownership reload는 일반 session을 쓴다.
- **WI-9** 기준선 측정 harness를 필수 CI에서 뺐다. 공용 container 안의 전용 DB에서 DML 비중첩·cold/warm
  hash·개수만 본다. reader snapshot pool 경합 시험의 대기를 5초로 올렸다.
- **WI-10** 지도 cluster·geometry label·clickable marker를 Tab·Enter/Space로 고를 수 있다.
  `audit:dev`의 `|| true`를 뺐다(redocly 1.34.22로 dev 전체 audit 0건).
- **WI-11** SH 설계 문서 3건 superseded, 418·424 정오표, integration-map §3 admin-features 행,
  runtime_privileges docstring(ADR-100). T-CWRITE-04 링크는 main이 먼저 고쳤다.

검증은 n150의 CI와 같은 네 pytest 세션·lint·frontend·Playwright에서 했다(결과는 PR 본문).

## 2026-10-27 — alpine 관찰자 cold-array codec 경계 최소 교정

원alpine2FAIL/1945PASS/29skip을 보존했다. 기존관찰자300ms timeout stack은
SELECT 본문전 asyncpg int4[] introspection이어서 SQL exact-holder membership을 bool로
반환하도록2줄만 바꾼다. PID/start/login/Lock/ungranted·300ms/0.8초/1초를 유지한다.
[원실패·실측대기](../reports/2026-10-27-bound-snapshot-stale-replan.md#alpine-관찰자-cold-codec-실패의-최소-교정)를
명시하고 source두리뷰뒤 원pair2만실측한다. runtime·운영0/전체9미완/OFF를 유지한다.

## 2026-10-27 — 실제 제품16·후보UI14 뒤 head oracle 빈줄1개 교정

f29 local16과 후보UI14는 통과했으나 전체glibc CI는1952PASS/23skip 뒤 head-schema
정본 비교1개에서 실패했다. complete live dump diff의 초과빈줄1개만 교정하며 함수/
runtime/API/UI/migration은 바꾸지 않는다.
[원 실패·승계 한계](../reports/2026-10-27-bound-snapshot-stale-replan.md#f29-전체-glibc-ci의-oracle-형식-실패)를
보존하고 새exacthead CI와 두리뷰가 끝나기 전 머지하지 않는다. 전체9미완/OFF/운영0이다.

## 2026-10-27 — typed reset 실제 제품16 통과, CI 계약 교정 중

source6cce26ef의 단일 owned16은16PASS18.90초/정확 CID·volume1·label0 정리PASS다.
양 caller 저장원본 재계획·후처리/seal·원 replay 불변과 새권한·경합 경계를 확인했다.
source2591/SDK53전후/import63/Common19네지점도 검산했다.
[실제 수용·CI 구분](../reports/2026-10-27-bound-snapshot-stale-replan.md#교정-source6c의-실제-제품16-수용과-ci-경계)을
남겼으며 CI 문서크기/ACL선언 두 실패를 보존하고 교정 중이다. 전체9미완/OFF/운영0이다.

## 2026-10-27 — 첫 제품 PG14PASS/2FAIL 보존과 canonical head 교정

owned16 첫 실행은14PASS/2FAIL22.46초였고 정확 CID·volume1·전체 label0 정리는
통과했다. prokind 자료형과 application graph432 누락을 좁게 교정한다. startup 엄격검사는
유지하며 head 불일치 후 inventory skip을 별도 손상으로 확대하지 않는다.
[원 실패와 미실행 post gate](../reports/2026-10-27-bound-snapshot-stale-replan.md#첫-제품-owned16-실패와-canonical-head-교정)를
보존하고 기존 source/head 계약을 확장했다. 순수 계약145개25.70초·graph check·Ruff는 통과했고 제품 전체 수용·CI는 미완/운영 변경0이다.

## 2026-10-27 — typed reset scope 권한을3열로 제한하고 통합17개 수집

제품 PG 전 발견한 CommandOwner scope 읽기 누락을 SELECT(key/epoch/owner)
세 열만 추가해 고쳤다. lease/UPDATE/runtime 직접 권한과 frozen430은 그대로다.
replay는 실제 apply 진입 추가0과 row/receipt 불변으로 표현하고 SQL문장 계측으로
과장하지 않는다. [범위](../reports/2026-10-27-bound-snapshot-stale-replan.md#실행-전-발견한-scope-열-권한과-관측-범위-정정)를
반영해 순수142개14.45초·통합수집17개10.38초가 통과했다. source 두리뷰/소유PG/
최종CI·최신main합성은 남아 있고 운영·profile 활성화0/전체9개미완을 유지한다.

## 2026-10-27 — typed bound reset 통합 source16개와 순수142개

양 provider atomic stale MAX3·migration 더 긴 timeout cap 순수142개가14.08초에
통과했고, [통합 source](../reports/2026-10-27-bound-snapshot-stale-replan.md#제품-통합-실행-전-checkpoint)16개를
10.54초에 수집했다. 실제 canonical 두asset/원bytes·seal·replay, holder/foreign
epoch·취소·lease, 별도 작성 ACL/startup을 포함한다. 새 제품 PG0이며 최종 두리뷰·
single-owned 실행·CI는 남아 있다. 실제caller 이전 freshquota를 보존하고 운영/
profile 활성화는 하지 않는다. 기존 실패·상한·전체9개 미완은 유지한다.

## 2026-10-27 — 새 typed reset의 순수 경계138개 통과

현재executor READY reset의 migration owner/ACL·client 원 plan/CAS·ACK 불명과
Airport/Rest의 계획오류/atomic rollback 분리 회귀138개가16.80초에 통과했다.
잘못된 ledger 경로의 초기 수집0 로그도 보존했다. [통합 후속](../reports/2026-10-27-bound-snapshot-stale-replan.md#첫-제품-순수-회귀)의
actual PG/현재·옛 owner/cancel/live apply·실제 수집/replay 수용은 아직 남았다.
새 제품 PG/운영 변경0, 전체 CWRITE9개 미완·profile OFF를 유지한다.

## 2026-10-27 — 실제 stale→rollback→live READY reset 거부 재현과 첫 제품 경계

정확ea2fbcc5 owned PG1개가25.52초에 통과했다. 정확40001→aborted TX→
유효READY/원 artifact 보존→기존 typed55P03을 관찰했고 두 선행실패·정리를 보존한다.
[제품 후속](../reports/2026-10-27-bound-snapshot-stale-replan.md#실제-재현-수용과-첫-제품-구현)은
433의 현재executor typed reset과 원 apply plan을 받는 client/두 실제catch 결선이다.
계획오류/ACK불명/외부binding은 기존안전경계를 유지하며 새 제품 PG·두리뷰·CI는
아직 미완이다. profilesOFF/MAX3·상한·전체9개미완/운영변경0을 유지한다.

## 2026-10-27 — bound 재현의 strict Geo 입력 연결만 정정

두 번째 owned 시도는 setup432 뒤 observation 준비에서1FAIL/45.29초였다.
reader의 frozenset과 Stats set 연결을 놓친 시험 오류로, 아직 실제 stale/reset 미관찰이다.
원 log/XML/result·정확 정리를 보존하고 기존 donor의 실제 builtinset 연결만 복원했다.
실제 준비 source의 strict encode/decode 왕복은 순수0.0182초에 통과했다.
[기록](../reports/2026-10-27-bound-snapshot-stale-replan.md#두-번째-시도의-strict-입력-실패와-순수-준비-확인)처럼
두 리뷰 뒤 격리 재현1회가 남았다. 제품·validator·상한·운영 변경0, 전체9개 미완이다.

## 2026-10-27 — bound snapshot 첫 재현은 baseline setup timeout으로 미도달

정확 d13312a9의 최초 owned 시험은 baseline400 적용 중40초 marker가 만료되어
1ERROR/41.53초였고, 제품 지점은 아직 미관찰이다. 원 log/XML/result와
정확 CID·volume1·label0 cleanup PASS를 보존했다. [기록](../reports/2026-10-27-bound-snapshot-stale-replan.md#최초-owned-재현-시도의-setup-실패)처럼
기존 donor module50초만 맞추고 나머지 실행/SQL/자원 상한은 유지한다.
제품 변경·운영 호출0, 두 리뷰 후 격리 재시도1회가 남아 있다.

## 2026-10-27 — bound snapshot stale 뒤 live lease 재계획 경계 조사

Airport 실제 atomic apply의 정확 stale→전체 rollback→기존 typed reset55P03을
관찰할 [재현 source와 작은 설계](../reports/2026-10-27-bound-snapshot-stale-replan.md)를
작성했다. 아직 실제 PG/운영 호출0이며 제품 수정 전이다. source 두 리뷰 뒤 격리 PG로
재현하고, 동일 executor의 exact binding만 정리하는 typed 경계를 검토한다.
MAX3·저장 artifact·취소/fence·후처리/seal·상한/OFF와 T-CWRITE9개 미완을 유지한다.

## 2026-10-27 — Common 최신 제품 공식 pair 배포·공개 UI13 수용

검증 Map `0d60cd0b`/PinVi `9ebb588a`를 공식 Manager pair로1회 배포했다.
새 committed transaction·실제6image·보호5·DBidentity/schema·기존 c6c45행을 검산했고,
정확한 이번 smoke 이력1개만 추가됐음을 확인했다. 원 RUNNING51개 복구 뒤 전체67상태가
baseline과 같으며 자기 supervisor/process 정리를 끝냈다. Weather·Transport 이미지 변경은0이다.

공개 HTTPS UI는 최초56.39초 전체FAIL(Map7PASS/PinVi3뒤adminTimeout)을 보존한다.
제품/예산 변경 없이 관측 필드만 추가한 두 번째 실행은49.27초에 Map7+PinVi6을 통과했다.
최초 원인은 불명이며 제품 수정·재발 방지·성능 개선으로 확대하지 않는다.
상위 T-CWRITE-01–09/일반 coordinator·전 writer 전환·운영 CPU/RSS 저감은 여전히 미완이다.
[실제 배포·복원·두 UI 결과](../reports/2026-10-27-common-aa232-pair-deploy-public-ui.md).

## 2026-10-27 — 동시 쓰기 제한 시험 두 PR의 최종 CI·정상 병합

부모 #1421의 정확 head `e23c277d`와 후속 #1422의 `a32674a1`은 각각 CI10개를
통과했고, 검증 tree 그대로 main `0d60cd0b`·`c62a9868`로 순서대로 정상 병합됐다.
후속의 양 PostGIS 전체 integration은 glibc1936 PASS/23 skip·alpine1930 PASS/29 skip이며,
전체 skip 사유에 새 shared Feature/부모 worker pair 시험은 없다. quiet 로그의 개별
성공 node 출력을 가정하지 않고 정확 수집·전체 실행·skip 사유를 함께 확인했다.

원 owned PG의 부모2PASS27.88초·후속2PASS24.80초와 정확 정리·모든 선행 실패는 보존한다.
이번 정산은 문서뿐이다. 일반 coordinator·전 writer 전환·운영 활성화와 CPU/RSS 개선,
상위 T-CWRITE-01–09는 미완이며 공식 배포·공개 UI 수용은 아직 별도다.
[부모 근거](../reports/2026-10-27-provider-snapshot-os-worker-pair.md#최종-합성본의-ci정상-병합-수용),
[후속 근거](../reports/2026-10-27-shared-feature-artifact-replan.md#최종-ci와-정상-main-병합).

## 2026-10-27 — snapshot OS worker pair 최종 CI·정상 병합 수용

PR #1421의 Common 합성 head `e23c277d`는 두 독립 리뷰와 CI10개를 통과했고,
동일 tree의 main `0d60cd0b`로 정상 병합됐다. 양 PostGIS 전체 integration은 glibc1934개·
alpine1928개 PASS이며 기존 skip 사유에 신규 worker pair는 없다. CommonAA 설치와
실제 import/fixture closure를 확인했고 중복 local PG는 실행하지 않았다.

원6307의 제한 owned PG2 PASS·정확 정리와 선행 fixture/SDK/marker/ledger 실패는 보존한다.
이번 정산은 문서뿐이며 상위 T-CWRITE-01–09·운영 CPU/RSS 실측·상위 Common 제품의
공식 배포/공개 UI 수용은 별도다. 후속 #1422의 머지 완료로 확대하지 않는다.
[최종 근거](../reports/2026-10-27-provider-snapshot-os-worker-pair.md#최종-합성본의-ci정상-병합-수용).

## 2026-10-27 — 공유 Feature의 동일 artifact 재계획 실제 PG 수용

정확 source `e35f5dc3`은 두 독립 리뷰 뒤 같은 상한의 owned PG2case를24.80초에 통과했다.
양 capture/leader의 실제 participant-scope 대기·정확40001·전체TX aborted·unbound READY
public cancel·동일 bytes 새 attempt/key/manifest·winner/base/lineage·완료 replay source DML0을
확인했다. source2582/import59/SDK53·격리 CommonAA19의 전후 검산, 정확CID/volume1/label0
회수도 PASS다. 첫 관찰bind2FAIL와 순수실패2회는 아래/원장에 보존한다.

생산/운영 변경0이며 최종 CI·병합은 대기한다. 일반 coordinator·전 writer 전환과 운영
CPU/RSS 개선, 상위 T-CWRITE-01–09는 미완이다.
[제한 수용과 원본 증거](../reports/2026-10-27-shared-feature-artifact-replan.md#실제-pg-수용).

## 2026-10-27 — 공유 Feature 첫 실제 PG의 xid8 관찰 bind 정정

CommonAA 정상 합성 `f691a8e1`의 첫 owned PG2case는 정확 scope 대기·선택된40001·READY
불변 뒤 관찰용 xid8 bind에 문자열을 넘겨2FAIL(28.02초)이었다. 정수 xid를 그대로
전달하는 시험1줄만 수정한다. 원결과와 정확CID/volume1/전체label0 정리PASS를 보존하며,
aborted 상태 확인·동일 artifact 재계획/완료 replay의 실제PASS는 아직0이다.
두 좁은 리뷰 뒤 같은 상한으로 재시험한다. 생산/운영 변경0·상위 T-CWRITE-01–09 미완이다.
[실패와 정정 원장](../reports/2026-10-27-shared-feature-artifact-replan.md#첫-실제-pg-실패와-관찰용-bind-정정).

## 2026-10-27 — 공유 Feature의 동일 artifact 재계획 시험 착수

PR #1421 문서 head `3e962183` 위에 시험 전용 후속을 쌓는다. 정렬 participant-scope
대기→선택된 stale40001→전체 TX rollback→unbound READY public cancel→동일 bundle의
새 attempt/key·현재 manifest 재계획과 양방향 winner/lineage·완료 replay DML0을 검사한다.
순수 회귀21PASS(같은 bytes의 hashseed1/2 복원 포함)·통합2case fixture 미정의0을 확인했다.
초안 순수실패2회의 원인·정정은 원장에 보존한다. 두 독립 리뷰와 부모 최신 main 합성,
owned PG·최종 CI는 아직 대기다.
생산 코드/SQL/API·OFF 설정과 운영은 변경하지 않는다. T-CWRITE-01–09 및 일반
coordinator/운영 CPU·RSS 개선은 미완이다.
[범위와 검증 원장](../reports/2026-10-27-shared-feature-artifact-replan.md).

## 2026-10-27 — snapshot OS worker pair의 제한 실제 PG 수용

정확 시험 source `6307ec63`은 두 독립 리뷰와 Airport/Rest 양방향 owned PG2개를
27.88초에 통과했다. spawn2·각 pool1·실 source overlap·정확 topic blocker·두 commit ACK,
후처리의 원 connection/PID/XID·marker NULL 회수·원 receipt·별도seal을 확인했다.
source2580·선택 import56·SDK53 전후 동일과 정확 CID/volume 회수·cleanup도 통과했다.

원 fixture 누락 P1, SDK import 실패(PG0), marker 기대값 오류의 실제2실패는 원장에 보존한다.
CI가 발견한 ledger300자 위반은 task 본문을 원장 link로 단축해 고친다. 시험 source와 생산
코드/SQL/schema·운영 OFF 설정 및 기존 예산은 바꾸지 않으며 최종 CI·머지는 아직 대기다.
T-CWRITE-01–09와 운영 CPU/RSS 개선 수용은 미완료 상태를 유지한다.
[범위와 원장](../reports/2026-10-27-provider-snapshot-os-worker-pair.md).

## 2026-10-27 — Codex PR 통합 리뷰의 비잠금 항목(WI-5~11)

최근 1주 Codex PR 46건(#1358~#1419) 통합 리뷰를 하나의 PR로 정리하는 작업 중 잠금 순서와
무관한 항목이다. 브랜치 `feat/map-codex-review-misc`에서 만들어 통합 PR 브랜치에 합친다.

- **WI-5** shadow hook이 순서가 뒤바뀐 bundle의 record key를 recorder에 넘겨 23514로 적재
  transaction 전체를 rollback시켰다. 저장 head가 그 record일 때만 capture한다. 운영은 shadow
  scope 미설정이라 휴면이었다(n150 Dagster env 읽기 확인).
- **WI-6** 관리 파일의 오프라인 업로드 링크가 없는 상세 경로(404)를 가리켰다.
  `/admin/offline-uploads`로 고치고 `_build_links`의 모든 href가 `page.tsx`에 대응하는지 본다.
- **WI-7** inbound 자격 증명 목록 하나로 기동 distinctness와 `/v1/service/*`의 403 판정을 묶었다.
  수동 생성 digest가 feature-request·reconciliation digest와 같아도 통과했고, 그 토큰은 403이
  아니라 401로 떨어졌다. 운영 API env(읽기만)는 설정된 8종 사이 충돌 0건이다.
- **WI-8** K 없는 정상 반환에서 정리만 실패하면 503 대신 연결을 폐기하고 commit된 결과를
  돌려준다. ownership reload는 일반 session을 쓴다.
- **WI-9** 기준선 측정 harness를 필수 CI에서 뺐다. 공용 pg_container에서 DML 비중첩·cold/warm
  hash·개수만 본다. reader snapshot pool 경합 시험의 대기를 5초로 올렸다.
- **WI-10** 지도 cluster·geometry label·clickable marker를 Tab·Enter/Space로 고를 수 있다.
  `audit:dev`의 `|| true`를 뺐다(redocly 1.34.22로 dev 전체 audit 0건).
- **WI-11** SH 설계 문서 3건 superseded, 418·424 정오표, integration-map §3 admin-features 행,
  runtime_privileges docstring(ADR-100), T-CWRITE-04 링크.

검증은 n150의 CI와 같은 네 pytest 세션·lint·frontend·Playwright에서 했다(결과는 PR 본문).

## 2026-10-27 — Codex PR 리뷰 정리: tracking 장부는 L만, 단건 writer는 regime 진입(434)

Codex PR #1358~#1419 리뷰를 정리한 잠금 핵심을 `feat/map-codex-review-core`에 구현했다(PR은
gate 뒤에 연다, 미머지). 434는 432 정본 루틴 20개의 본문 SHA·소유자·시그니처를 고정하고
검토한 바늘만 바꾼다. 하나라도 다르면 아무것도 바꾸지 않고 실패한다.

- WI-1: tracking 장부 쓰기는 L만, 큐레이션 확정(seal·root 완결·권위 finish·SUCCESS 완결 취소
  전이)만 P EX→L. 430 write-prefix guard도 같은 분류로 좁혔다.
- DC-1: 단건·관리 writer(SQL 10개+Python 관리 경로)는 regime 진입 — epoch=0이면 P 없음,
  epoch>0이면 P EX. 계획의 "epoch>0 공유"는 strict guard가 manifest 없는 SH를 거부해 배타로
  바꿨다. 전화 override·curation import와 provider 증거를 먼저 잡는 M05·재활성화는 P EX를
  유지한다(적대 리뷰가 다중 bundle 적재·병합과의 순환을 찾았다).
- WI-2 무장 대기 0→1초 결함, WI-3 418 GRANT 재부여+ACL 오라클, WI-4 lock-order lint의 P·L·leaf
  규칙과 Python helper 분석.

운영 읽기 전용 확인: flag 3종 OFF, shadow scope 미설정, epoch 0, active policy·write attempt 0,
남은 로그 창과 DB 원장에서 LOCK_TIMEOUT 503·55P03 0건 — 결함은 잠재 상태였다.
[ADR-115 §11](../adr/115-scoped-concurrent-feature-writes.md#11-구현-상태2026-10-27-alembic-434-기준).
문서 한도: 병합 뒤 journal이 220 KiB를 넘어 가장 오래된 2026-10-13 두 절을 [아카이브](journal-2026-10d.md)로 원문 이동했다(tasks-rule §8).

## 2026-10-27 — kor-travel-common 최신(`aa232ad5`) 반영: 브랜치 `chore/common-latest-map`

- Python API `[http]`·Dagster `[dagster]` 핀 `e746e4b8` → `aa232ad5f255233184de80eceaab2e9b6ccb00c9`(#44~#47 병합).
  그 뒤 main `c289b462`(#48)은 문서만 바꿨다. 그 사이 Python 변경은 #44 하나다 — `kor-travel-dagster-daemon run`
  (`kortravelcommon.daemon_pool`)에서만 `KOR_TRAVEL_DAGSTER_WORKSPACE_RELOAD_SECONDS`(`60`|`180`, 미설정이면 SDK 원
  동작)로 workspace 갱신 주기를 늦춘다. Map code location·API는 이 모듈을 쓰지 않고 standalone compose daemon은 일반
  `dagster-daemon run`이라 대상이 아니다. 공용 daemon env는 Manager 소유라 켜지 않았다(`runbooks/common-dagster.md`).
- 관리자 UI `@kor-travel/ui` dev.7 → dev.9. Common CI `packages` lane 조건(Node 22.23.1·npm 11.19.1·루트 `npm ci`·
  `npm pack -w packages/ui`)으로 재현한 tgz가 Common T-217 정규 산출물 SHA256 `b738d882…`와 같다. tokens 0.1.0은 그대로,
  쓰지 않는 dev.6·dev.7 tgz는 지웠다. 낡은 출처 기록(`third-party-common.md`의 dev.6·`1f8e339c`)도 고쳤다.
- dev.8 지도 작업면(`MapWorkspace`·`MapFilterPanel`·`MapStage`, 상세 header/접기)은 opt-in이고 dev.7 props·CSS·치수가
  그대로라 Feature 지도는 바뀌지 않는다. 남은 높이 작업면 채택은 고정 70dvh stage와 698px e2e 기준을 바꾸는 화면
  설계라 이번 범위가 아니다(후속 후보). dev.9 로그인 폼은 hydration 전 입력·제출을 비활성으로 두고 준비 전 제출을
  막는다. Map e2e 로그인은 모두 `/api/auth/login` 직접 호출이라 고칠 시험이 없었고, SSR 비활성·mount 뒤 활성 단위
  회귀를 더했다.
- main CI(`0324cab3a`)가 이미 빨갰다 — CI를 건너뛴 문서 커밋 `7d64c96e8`이 `tasks.md` T-CWRITE-04 본문을 341자로 늘려
  `test_task_ledger_conventions`(상한 300자)가 세 Python에서 실패한다. 사실(432 수용·새 profile OFF·근거 링크 셋·미완 범위)은
  그대로 두고 300자로 줄였다. ADR-115·acceptance 포인터는 같은 절 머리말에 있다.

## 2026-10-26 — Rest432 제한 단위의 최종 CI·배포·공개 UI 수용

PR #1418의 최종 제품 `65202158`은 CI 10개 모두 성공했고, 같은 tree의 main
`d7fd7d18`로 병합됐다. 같은 상한의 coverage owned PG는 합성215 전체 반영·후처리·별도seal과
byte quota 11건 뒤 12번째53000·전체TX rollback을 통과했다. 같은 source의 새 빌드/실제
API·Next 후보 UI14개도 통과했다. 기존 CI/fixture/UI 실패와 당시 미도달 기록은 아래에 보존한다.

공식 배포는 committed, 실제 schema432/PinVi0102·7healthy다. 배포 후 공개 UI는 Map7개와
PinVi6개 모두 PASS(55.972초)이며 실제 로그인·쿠키·지도/목록/상세·재조회·로그아웃 뒤
보호401·세션잔류없음과 정확 browser/profile 정리를 확인했다. 이는 격리 후보 cancellation14와
별도 시험이다. 기존 RUNNING 37개만 복원하고 STOPPED 14개와 새 profile OFF를 유지했으며
설치 env의 bytes·mode도 보존했다. 새 수집 활성화나 운영 business DML 시험은 하지 않았다.

이번 수용은 Rest 제한 profile의 구현·정확성/복구 시험·최종 CI·공식 설치와 공개 UI 범위다.
상위 **T-CWRITE-01–09는 모두 미완료**이며 운영 부하 CPU/RSS·215 backend CPU/RSS,
실 upstream215 수집·공유 Feature의 양성 동시 쓰기·전 writer 전환/확대·실 OS worker 사망과
물리 wire 단절은 별도다. 작은 두 profile의 backend ticks/RSS 표본은 운영 효과가 아니다.
[최종 증거와 한계](../reports/2026-10-26-rest-snapshot-atomic-implementation.md#최종-제품652의-ci병합공식-배포-수용).

## 2026-10-26 — byte quota 최종 CI 실패와 문자열 선검사 비용 보강

`5d6f982b`의 최종 CI는9개 성공·glibc PostGIS1개 실패다. 후자는 byte quota 반복 등록이
전체30초에 걸렸으며 reader3초 실패가 아니다. Alpine과 실제215는 통과했지만 머지하지 않는다.

공통 codec 선검사는 exact 문자열/None/bool의 불필요한 모델 탐색과 ASCII escape·인용문
문자별 Python 순회를 줄인다. UTF8·depth·node·문자열 비용 및 canonical 검증을 유지하며
한도·SQL·quota fixture는 바꾸지 않는다. 새 경계28개를 포함한 관련207개 순수시험은 통과했다.
초안의 escape 메모리 회귀는 두 독립 리뷰로 수정했고, 같은 상한 실제PG·새 최종CI는 아직 대기한다.
운영 CPU/RSS 개선을 주장하지 않는다.
[근거](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest 중복 검증 제거의 PG·후보 UI 수용

두 독립 리뷰를 거친 `8fa17bf4`가 같은 상한의 coverage 실제 PG 두 건을 통과했다.
합성215개는 원자적 구간19.733초·후처리·별도seal을 확인했고, byte quota는11건 등록 뒤
12번째53000·정확 constraint·전체rollback을 확인했다. reader3초·lock1초·전체30초와
8MiB/16행은 유지했다. 각 pytest case100.369/119.625초는 전체 runner·원자적 구간과 다르다.

동일 source의 새 UI 빌드와 실제 API/Next UI14개도50.038초에 통과했다. 로그인·취소·
재조회·실제WS·로그아웃200 뒤보호401·재연결없음 및 세션 미해제 가능성false를 확인했다.
선택module을 fixture 전에 검증했고 source2576/SDK53/UI351·정확 자원 정리를 확인했다.
서버CPU/RSS·CI와 환경동등·운영432 완료로 확대하지 않으며 최종 CI·머지/배포는 남는다.
원6ceb CI 실패와 COMMIT 결과 불명 경계는 앞선 원장에 보존한다.
[원장](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest 최종 두 PostGIS 시간초과 보강 중

6ceb의 최종CI는8성공·PostGIS2실패다. 실제215와 byte quota 반복 등록이 전체30초에
걸렸고 원 실패·COMMIT 불명 경계를 보존한다. 전체/SQL/lock 상한을 유지하면서 같은
호출 안의 중복 codec/의미 대조 준비만 줄이는 후속 수정이 관련 순수160개를 통과했다.
두 독립 리뷰·실제PG·최종CI·머지/운영배포는 아직 남는다.
[원장](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest reader 제품 PG 통과와 로그아웃 이동 경합 보강

개입 코드 없는 `81164788`의 coverage 실제215 시험이 통과했다. reader2.333초·
atomic24.251초, 전체 항목·후처리·seal 및 정확 정리를 확인했다. 두 독립 리뷰와
원장 검산을 마쳤으며 운영 CPU/RSS 개선 실측을 뜻하지 않는다.
[근거](../reports/2026-10-26-rest-reader-local-jit.md).

관리자 로그아웃 POST와 늦게 도착한401의 중복 이동은15초 monotonic lease로 조정한다.
실패·만료·비정상 시계에서는 재시도할 수 있고 기존401/키 폐기/다른 탭 알림은 유지한다.
두 독립 리뷰, 관련75개 및 전체 frontend49파일410개가 통과했다. 원 실제 UI의
로그아웃 이동 실패와 세션 해제 미확정 표시는 보존하며 원인이 단독 확정된 것은 아니다.
선행 `d8a08b9e` CI10개는 성공했고 최종 source CI·새 빌드/실제UI·머지/배포는 남는다.

## 2026-10-26 — Rest reader 조회에 한정한 JIT 비활성화 초안

coverage를 켠 실제215 owned 시험에서 기존 reader가3초에 취소됐다. 같은 한도에서
JIT OFF 개입 시험은 reader2.274초·atomic23.841초/전체215·후처리·seal을 통과했다.
단일 개입 결과이며 서버CPU/RSS·JIT 컴파일 시간이나 원인의 확정은 아니다.

제품 초안은 잠금 뒤 reader 조회에만 transaction-local JIT OFF를 적용하고 성공 뒤
원 jit/statement/lock 설정을 복원한다. 오류·취소는 원 예외를 전파하고 caller 전체
rollback으로 설정을 회수한다. 더 짧은 제한과 기존3초/1초·전체30초는 유지한다.
관련18개 단위/Ruff/mypy1은 통과했으며 두 독립 제품 리뷰·제품 실제PG·최종CI는 남는다.
[근거와 범위](../reports/2026-10-26-rest-reader-local-jit.md).

## 2026-10-26 — Rest432 최종 CI 실패와 최소 수정

`7fc5bff1`의 최종 CI는 10개 검사 중 8개 성공·2개 실패다. 세 Python 검사는 모두
통과했지만 두 PostGIS 검사에서 같은 세 문제가 발생했다. 실제 asset의 deprecated
`context.run_id` 경고 1개, 실제215 원자적 처리와 byte quota 반복 등록의 전체 30초
시간초과 2개다. 원 실패를 보존하고 CI green·머지·운영432 배포로 처리하지 않는다.

Rest는 기존 정본 helper로 native run ID를 고정해 후속 관측에 전달하도록 수정했다.
직접 호출의 기존 fallback과 OFF 상태의 영속 복구 순서를 유지한다. 두 독립 리뷰와
관련 순수76개는 통과했으며 실제 asset의 수정 후 PG 시험은 별도로 남는다.
중복 codec 검증 제거와 coverage를 켠 실제215·quota 시험을 이어서 검증한다.
CI는 coverage7.17.0·Python3.13.16이며 이전 로컬 시험은 환경이 달라 비용을 동일하게
비교할 수 없다. [원 실패·후속 검증](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest432 추가 물리 경합·후보 UI 수용과 CI 잔여 정정

`511da0a0`에서 새 물리 경합 3개와 양 profile 계측 2개, fresh build 기반 후보 UI
14개 판정이 통과했다. 원 실패·cleanup 및 계측 범위는 보존하며 운영432 배포 완료를
뜻하지 않는다. 운영431과 별개로 최종 CI·머지/배포 수용은 계속 대기한다.

세 Python CI lane은 같은 static lint 1FAIL(각 4425PASS/7SKIP)을 보였다. 새 seal-race의
비실행 listener marker를 실제 procedure 호출로 오인한 경계여서 marker의 `CALL `만
제거했다. 실제 SQL의 9인자·핵심 단언·검사기·allowlist는 그대로이며 수정 후 최종 CI는
아직 대기한다. [수용 범위](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest432 설계 누락 경합·계측 시험 보강

실제215·quota/GC5·복구3·두writer2 PASS와 별도로 설계 S5를 대조해 동일member등록,
이전read/다른worker seal, 적용중GC의 새물리node3개와 양profile 자원계측을 추가했다.
두독립리뷰의 JSON부분공개·정리회수 오류를 수정했고 기존검증/제품가드/한도는 보존했다.
아직 이추가시험의 실제PG/계측 수용전이며 최종CI/UI·머지/배포도 미완이다.
[범위와 실측](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest432 quota/GC·복구 재검증 통과

`b18470d5`의 새 quota/GC5개와 별도 복구3개가 모두PASS다. 정확 constraint·초과TXrollback·
실행중보존/종결후quota반환, ownbackend종료/18표rollback/pool1재사용·lateGeo거부·같은
Dagsterrun SDK0재개를 확인했다. 원FAIL은 보존하며 실제 OSworker종료/물리wire유실이나
S5전체pair 수용으로 확대하지 않는다. source/SDK·정확자원정리 확인, 최종CI/UI·머지/배포는
미완이며 OFF는 유지한다. [원장](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest432 실제215·두 writer 검증

`7651cc39`의 owned215 전체 후검사·후처리·별도seal이1PASS(70.59초), 별도 Airport/Rest
물리 두writer의 실제 blocker/양쪽commit·receipt 검증이2PASS다. source/SDK 및 정확 자원
정리도 확인했다. SQL CPU 동시 실행·운영 처리량/서버RSS 측정으로 확대하지 않는다.
quota/GC4FAIL1PASS와 recovery1PASS2FAIL의 fixture 오류는 원 실패를 보존하고 최소 수정 후
재검증한다. 최종 CI·후보UI·머지/배포는 미완이며 runtime 기본OFF를 유지한다.
[실측과 범위](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — 431 reader 배포·공개 UI·원 일정 복원 완료

1415의 CI/후보 UI를 거친 main과 문서까지 고정해 Map `df877690`·PinVi `9ebb588a`를
공식 Manager `0889d3b4`로 배포했다. 1872.74초/committed, 실제 head431/Pin0102·7healthy다.
공개 UI 한 번50.277초의 Map7/PinVi6 모두PASS·각login/logout1·보호401·정확browser/profile
정리와 새session잔류없음을 확인했다. 기존37 RUNNING만복원하고 새활성화0·PinViWeatherOFF,
복원 뒤 fresh431/7healthy도 확인했다. 예전3FAIL/미확인session 경계는 지우지 않았다.
Map 백업복원은 verified이나 catalog권한차이 비차단경고를 별도보존한다.
다음 #1418의432실제원자성/215전체/물리2writer·CI/live는 아직미완이다.
[진행 원장](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 — Rest432 선택 A 구현 첫 checkpoint

431 main `df877690` 위에서 저장·원 결과·필수 후처리를 한 RC connection/TX로 묶는
내부 coordinator와 Airport 연결을 구현했다. 기존 공개 own-TX 서명은 유지하고 seal은
별도 정본 경로다. 기존 단위34PASS/Ruff/strict mypy5source 통과이며 실제 PG 수용은 아니다.
Rest SQL·HTTP·관측/runner와 실제 두 writer 시험을 담당별 병행 중이다. runtime 기본OFF,
전체통합·적대2리뷰·실제PG/CI/live·운영은 미완이다.
[구현 원장](../reports/2026-10-26-rest-snapshot-atomic-implementation.md).

## 2026-10-26 · Rest431 최종 CI와 main 반영 정산

- PR #1415의 정확 source e1b203bb는 5 workflow/10 check를 모두 통과했다. CI의 실제
  merge checkout과 source의 tree가 같았고, 일반 merge adc0a8d7의 tree도 같았다.
  최종 CI 원장 4bf0fcc1와 merge 원장 e8a5d2d0으로 확인하며 원65 CI6FAIL은 아래에 보존한다.
- 최종 후보 원14PASS47.526초와 제품의 두 독립 리뷰·215 reader·공식 golden·직접 SQL 음성의
  각 source 범위를 유지한다. 첫 후보 a1f39 FAIL/철회 미확정 True는 원인 미확정 그대로이며,
  운영 공개 원3FAIL과도 별개다. 새 성공으로 어느 과거 실패도 철회하지 않는다.
- Rest431은 main에 반영됐지만 운영은 기존 Map430/PinVi0102다. 이 문서 결합은 제품·배포·
  수집 활성화를 바꾸지 않는다. 후속432의 단일 current-export window·unchanged SH/retire0,
  선택A 한TX와 공유 topic의 물리 두writer/직렬화 실측은 열린 과제로 유지한다.
- 아래 이전 체크포인트와 실제 main의 journal/resume 전체 원문을 함께 보존한다.

## 2026-10-26 · Rest431 최종 제품과 격리 후보 추가 인수

- e1b203bb의 supplied_fields 집합 순서만 정규화하는 제품4줄을 W/T가 독립 검토했다.
  T의 seed41 회귀1PASS2.25초에서 동일 입력 수용·실제 name 변조 거부를 확인했다.
  원65 CI6FAIL·seed41 수정 전 실패와 기존3fa reader/golden 실측은 그대로 보존한다.
- 별도 e1b r5 reader는 XML1PASS52.627초/215 whole EOF·적격/257 whole 거부다.
  215 client wall6.309399초·CPU2.168916초·JSON4,133,119B는 codec/두 reader/평가를 포함하며
  backend CPU/RSS·실제 upstream EOF 수용으로 확대하지 않는다.
- 운영 공개 원3FAIL과 **다른 격리 후보 첫 실행 a1f39의 1FAIL**을 구분한다. 첫 후보는
  logout200 뒤 Error/보호401 미관측·possible_unrevoked=True를 영구 보존한다.
  새 진단 r4의 원14PASS47.526초·보호401/5초 WS·DBattempt1·정확 정리(fb2c115c/e5562b78)는
  그 원 Error 원인 확정이나 과거 미확정 철회가 아니다.
- 정확 e1b 전체 CI 최종 수용·1415 main 반영은 작성 시점 미완이다. 1417은 그 뒤 문서만
  재결합한다. 새 제품/PG/운영/활성화 변경 없이 [원문·범위](../reports/2026-10-25-rest-area-evidence-reader.md)를 정산한다.

## 2026-10-26 · Map/PinVi 배포·공개 읽기·일정 복원 정산

- Map #1414·#1411의5f3506a와 PinVi #602의8f1b998f를 공식2단계로 배포했다. 첫418 commit 뒤
  정식1키 CAS·최종 rotate/rebuild를 마쳤고 Map430·PinVi0102·7 healthy를 새 readback했다.
- 새 Map·PinVi 백업과 공식 격리 복원 리허설은 verified였다. Map의 비차단
  REHEARSAL_CATALOG_DRIFT 경고는 보존하며 catalog 소유권·ACL 전체 일치를 주장하지 않는다.
- Map29f1 CI5 workflow/10 check·격리 Map14·별도 PinVi 후보6 인수와 구분하여,
  최종 공개 TLS 읽기 R7의 Map7+PinVi6을 통과했다. 성공 실행의 양쪽 로그인·로그아웃은 각1회,
  보호401·실제 목록/상세·지도·같은 source lineage와 정확 브라우저 정리를 확인했다.
- 원 공개3 FAIL과 R4의 테스트 세션 철회 미확정은 영구 보존한다. R7의 새 두 세션 정리 성공은
  그 원 실패를 덮지 않는다. Map의 live immutable 정적 응답 RAM 재사용 예외와 실제 네트워크
  계수는 [읽기 인수 보고서](../reports/2026-10-25-pinvi-admin-feature-read-scope.md)에 구분했다.
- 원 instigator47/RUNNING38에서 최종51/RUNNING37·STOPPED14를 확인했다. 새 항목은 모두OFF,
  퇴역한 highway incidents ten-minute schedule은 재생성하지 않았다. 읽기 자격 분리·WeatherOFF도 유지했다.
- 현재 pair의 배포·공개 읽기/auth·원 일정 복원만 종결한다. 물리 두writer·전체수집 최적화·
  Rest 후속 영속 연결·전체1commit·W/T 운영 활성화는 별도 미완이다.
  [후보·CI 범위](../reports/2026-10-25-snapshot-recovery-final-candidate-ui.md).

## 2026-10-26 — Rest432 단일 export 영속 재관측 설계 초안

431최종65e source를 보존하고 별도WT에서 spec/task 두 문서만 준비했다. 단일current-export-window
strictEOF≤256·DBmembership/Geo/policy/non-scalar 동일의 unchanged SH/retire0로 한정하며
latestbatch·absence-retire·EXbootstrap 권위는 없다. 430재사용 여섯경계와 apply/result TX 대
후처리TX gap·quota미정·SDK0복구·물리두writer 과제를 명시했다. 제품/PG/HTTP/Chrome/운영0,
1415머지 전 문서만 선행머지하지 않는다.
[설계·열린 결정](../reports/2026-10-26-rest-snapshot-registration-spec.md) ·
[작업·실제시험](../reports/2026-10-26-rest-snapshot-registration-tasks.md).

## 2026-10-26 — Rest431 CI의 unordered presence 비교 결함 수정

65e Python3.13CI6FAIL/4355PASS/7SKIP 원본을 보존했다. hashseed41에서 typedfrozenset은같지만
JSON배열순서만deepcopy로뒤집히는같은6FAIL을재현했다. 공유native 의미비교의 supplied_fields만
정렬하고 다른list/raw/hash/codec/SQL/권한0변경을유지한다. 새seed41동일입력양성+실name변조음성
회귀 수정전1FAIL→기존Rest/native81PASS·Airport/Rest/codec307PASS11.46초/Ruff/mypy통과다.
제품delta2리뷰·정확새CI/최종APIcandidateUI미완, 기존215/직접SQL/golden은별도carry범위다.
추가PG/Chrome/운영0. [원인·범위](../reports/2026-10-25-rest-area-evidence-reader.md).

## 2026-10-26 — Rest431 관리 직접SQL 음성 실제 수용

source07867의 새 owned1개가15.448초 PASS/skip0이다. 정본EX guard 아래 RW savepoint에서
policy subset·후보 중복·검증hash·Geo/base·큰datum5분기의 전체empty/EOFFalse와 정확reason,
매rollback 원JSON 전체동일을 확인했다. 별도PK23505/정확constraint·PythonRR전후양성도 통과했다.
이 경로를 PythonRR 음성이나51모든datum/4MiB합계 부정 전수검증으로 표현하지 않는다.
raw8/Git2543SDK53/import17·head431 및 새읽기 exactCID/UUID/global0/volume1부재로 PG0이다.
제품/골든3fa/59ada 불변·기존215별도PASS, 독립사실검산/최종CI/431candidateUI와 운영EOF·
durable/collector·활성화는 별도 남는다. 운영/Chrome0.
[실제 경계·원장](../reports/2026-10-25-rest-area-evidence-reader.md).

## 2026-10-26 — Rest431 실제215 fit와 최종 공식 golden

A1/A2 원timeout을 보존하고 A3 source3fa59cc의 owned lab1개가 통과했다. 실제215는
complete/EOF/item215/assessment 적격, 실제257은 empty/EOFFalse 전체거부다.215합산client
wall6.480초/CPU2.209초는codec+두read+decode/assessment이며 원각3초/lock1초를 유지했다.
같은64 진단은public.515초/CPU.51초, 최종fresh300→431공식oracle1은38.387초PASS였다.
실제dump59ada12d를golden으로복사하고 함수3+ACL3/receiptCHECK1외0변경whole역대조했다.
각phase정확정리PG0·Git2542SDK53/import15·15·9확인. sourceW/T delta수용과원FAIL을분리하며
전체lint373PASS/기존6SKIP35.12초로 원golden2FAIL을 닫았다. 최종golden/docs리뷰·정확CI·
운영EOF/collector/등록활성화는미완이다. 운영/Chrome0.
[실측·한계](../reports/2026-10-25-rest-area-evidence-reader.md).

## 2026-10-26 — Rest431 원64 비용 계량과 A1 source

원 lab은1/15 complete 뒤64 원3초 timeout으로 실패해215/257 미도달이며 별도 보존했다.
catalog/startup/ORM2와 공식 oracle1은 통과했다.64 진단은 private inventory2.537초/CPU2.53초,
public57014 3.007초/CPU3.00초, 두 bulk EXPLAIN2.594/18.579ms로 관측했다. RSS는 지점값이다.
A1은 inventory의 refs/seen만 typed3배열+최종 firstordinal JSON으로 바꾸고 원13블록의
검사·과금·NULL·첫 참조 순서를 whole 역대조했다. 관련242PASS10.07초, 변경 후 PG/개선율은
미검증이다. WSL CPU2/1536MiB·전체150/parent160/cleanup15 유지, 독립 적대2인 머지 전
검토와 동일64/215 재계량·최종 실제 golden이 남았다. 등록/collector/운영0.
[실측·한계](../reports/2026-10-25-rest-area-evidence-reader.md).

## 2026-10-26 — Rest431 통합 source와 실제 lab 준비

merged main5f3506a 위 설계1412·codec1413·명시 reader/preparation 및 direct assessment P2를
합성했다. 기존 더티4파일 원본은 별도 WT에 보존했고 관련 순수242PASS9.94초를 확인했다.
T FULL의 P2 HOLD는 Root/T closure와 구분해 기록하며 최신 합성의 두 source 리뷰·
실제215 fit/권한/공식431 golden·시간/메모리 측정은 미완이다. PG/등록/collector/운영0.
[현재 범위와 계량 계획](../reports/2026-10-25-rest-area-evidence-reader.md).

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

## 2026-10-25 — Rest431 reader 미호출 source

새 migration/SD3·decoder 및 최소 typed ACL/startup signature를 준비했다.
정적144/52 PASS, 기존427/430·golden 불변. SQL 두 리뷰/실제 lab·215 fit·준비/평가/수집 연결은 미완이다.


명시 Rest Geo domain/정확 입력형과 순수106PASS를 확인했다. SQL·reader·215 fit·운영은 미완이다. [source 범위](../reports/2026-10-25-rest-area-evidence-reader.md).

## 2026-10-25 — 휴게소431 명시 profile 설계·계량 경계

synthetic215의 기존 codec36행/typed47행 거부와 후보 wire733,671B를 구분했다.
PG reader 비용·운영 fit는 미측정이며 Airport 상한/제품/SQL/운영 변경0이다.
Rest 전용 유한 profile과 RR chunk 비교·주간 GC/quota·작은 구현 단위는
[후속안](../reports/2026-10-25-rest-area-snapshot-profile.md)에 기록했다.
다음은 설계 두 리뷰 뒤 owned PG 비용 lab 구현이며 동시 worker 수용은 미완이다.

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

정본215 tuple의 Geo 유무 lossless roundtrip과 전행 byte/node/token 거부를 구현했다.
Airport 기존 wrapper/상한을 보존하며 codec·관측·후처리 순수231 PASS/skip0,
Ruff/mypy/import 검사를 확인했다. SQL/등록/collector/운영 변경0이고 두 리뷰·CI/PG는 미완이다.
[범위·실측](../reports/2026-10-25-rest-area-snapshot-artifact.md). 다음은 독립 source 검토와 J reader lab 결합이다.

## 2026-10-25 — 휴게소431 명시 profile 설계·계량 경계

synthetic215의 기존 codec36행/typed47행 거부와 후보 wire733,671B를 구분했다.
PG reader 비용·운영 fit는 미측정이며 Airport 상한/제품/SQL/운영 변경0이다.
Rest 전용 유한 profile과 RR chunk 비교·주간 GC/quota·작은 구현 단위는
[후속안](../reports/2026-10-25-rest-area-snapshot-profile.md)에 기록했다.
다음은 설계 두 리뷰 뒤 owned PG 비용 lab 구현이며 동시 worker 수용은 미완이다.

## 2026-10-26 · expired reset applying holder의 정본 fixture 회귀

- CI 두 lane의 guard 미설치 원1 FAIL을 보존하고 해당 한 case만 기존 strict_engines로
  준비했다. 고정 c265f90c의 owned PG430 한 case가15.044초에 통과했으며 원 단언·상한·
  제품은 유지했다. source2523/SDK53·실제 import37과 정확 정리를 확인했다.
  실행기 donor 요약3/34는 원보존 후 XML1/import37 별도 원장으로 정산했다.
  전체 최종 CI·배포는 별도다. [범위](../reports/2026-10-26-expired-plan-reset-guard-fixture.md).

## 2026-10-25 · 전용 읽기 동결 소비 계약 정렬

- 원3Python CI 각3FAIL/3826PASS를 보존하고 새 GET2의 baseline/동결 pending 대상 hash를
  정렬했다. 원 receipt pending·과거 후보 증거·제품/스펙은 유지하며 계약18 PASS다.
  [범위](../reports/2026-10-25-pinvi-admin-feature-read-scope.md).

## 2026-10-25 · Feature read/create 중복 자격 정정

- 8555 독립 리뷰의 digest 중복 P2와 수정 전6 FAIL/1 PASS를 보존하고 정본 수동 생성
  자격 검사에 read digest 비교1개를 추가했다. 기존 런타임 검사도 공유하며 관련227 PASS다.
  OpenAPI·기존 admin body는 유지한다. 새 두 리뷰·CI·운영은 미완이다.
  [원 실패와 범위](../reports/2026-10-25-pinvi-admin-feature-read-scope.md).

## 2026-10-25 · PinVi admin Feature 전용 읽기

- 별도 digest/scope로 두 service GET에 기존 admin 목록·단건 함수와 DTO를 공유한다.
  기존 BFF/write 권한은 유지하며 운영 provision·배포는 미완이다.
  [계약·검증 범위](../reports/2026-10-25-pinvi-admin-feature-read-scope.md).




## 2026-10-25 snapshot 잔여 fixture 실제 확인

- 정식 prefix/RC와 typed begin 반환으로 잔여 fixture를 정렬했다. event 소유권 불변과 typed 원문 변조 거부를 실제 별도 경로로 확인한다.
- 고정13866의 실제10개26.99초와 대량2개150.23초를 분리 검증했다. 원 cap/감사 fixture 실패와 각 정확 정리를 보존했다.
- [기록](../reports/2026-10-25-snapshot-pg-tracking-fixtures.md). 전체 합성 CI·새 실제 UI·운영 배포는 미완이다.

## 2026-10-25 — PostGIS 추적 fixture 정리

전체 CI 실패를 보존하고 배치·취소 cleanup 및 projection seed가 기존 P EX→L 규약을 따르게 수정했다. 제품·guard·기대값 변경 없이 실제 PostgreSQL100개/33.18초/skip0과 소유 자원 정리를 확인했다. 별도 scalar 제품 수정·전체 CI·운영 배포는 아직 미완이다. [범위와 증거](../reports/2026-10-25-snapshot-pg-tracking-fixtures.md).

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

## 2026-10-25 — 430 전체 PG gate 첫 원인 수정 준비

7f40 glibc118FAIL/30ERROR 원문 보존. unchanged foreign winner의 불필요 INSERT와
정확 관리자 cleanup/RC·bounded/reset fixture를 수정 준비했다.25unit PASS/63collect,
새SQL 두 리뷰·실제 paired/전체 PG 재수용은 미완이며 운영 배포는 보류다.


최종1093 API/schema430·동등351입력의7839 production UI로 실제 로그인/취소·replay/DB1attempt/WS17frame/logout 14판정 PASS와 소유 자원 정리를 확인했다. 1093 CI의 과거429 역비교1FAIL을 고정 fixture로 바로잡고 전체 unit4180 PASS/6SKIP을 확인했다. 제품·SQL·권한 변경0, 원 실패 보존이다. 최종 CI·운영 배포·실제 두 dataset 동시 쓰기와 Common 후속은 미완이다. [실제 증거와 범위](../reports/2026-10-25-snapshot-recovery-final-candidate-ui.md).

## 2026-10-25 — 공항 snapshot 원자적 후처리 구현 중

원 발견사항·sync cursor·stale 정리를 한 fenced RC transaction과 receipt로 연결하고, 종결된 임시 입력의 7일/최대16개 정리를 추가했다. 합성430의 실제 설치/startup/ORM/후처리 rollback·replay/null 경계15 PASS와 정리를 확인했다. 분리 시험의 GC16·세대/커서3·물리 DB 연결 사망/pool1 복구1·scheduled caller2와 공식oracle 생성을 확인했다. 최종덤프·두 리뷰·CI·복구 live UI·운영은 미완이다. [범위와 검증](../reports/2026-10-25-airport-snapshot-durable-postprocess.md).

## 2026-10-25 · cancellation 원 backend cleanup 후보

- 원 backend 종료 요청1회/advisory0과 SQLAlchemy54/55 순수49·dc70 actual5 PASS를 확인했다. 7839 실제 후보 API·Next·브라우저는 화면취소/replay/DB/WS/logout14판정 PASS·정확 정리했다. 원 CI·build/live FAIL은 보존하며 exact CI/운영은 별도다. [근거](../reports/2026-10-25-pipeline-cancellation-disconnect-cleanup.md).

## 2026-10-25 API task 취소·pool 경계 시험 소스

실제 K 보유→P 대기 중 task 취소와 pool1 새 요청/replay를 독립 시험으로 준비한다.
제품/SQL 변경·실제 PG0이며 [범위](../reports/2026-10-25-pipeline-cancellation-task-pool.md)의
소스 두 리뷰와 고정 실행기 승인 전 실행하지 않는다.

## 2026-10-25 비활성 strict SH guard429 owned 검증

- 46666 CI 원결과를 보존하고 검토된428 cac89의 ORM metadata/반사식 수정과 원 fresh300 검사1 PASS를 상속한다. 429 SQL·공식dump·role trace는 유지하며 새 합성 CI는 별도다.
- ac441 CI의 마지막 role 추출 실패를 보존하고 실제 receipt/마지막 SET ROLE tuple 배선을 정렬했다. 양28/26 execute trace는 같고 lint 전체+전용 unit381 PASS/기존6 SKIP이다. 새 CI는 미완이다.
- 별도 source의 실제30/새11과 공식oracle1 PASS·정리를 확인했다. 원25 PASS/5 FAIL은 보존하며 단일41 실행으로 세지 않는다.
- 검토된 root428c98·최신 main/공항427 부모와 실제429 dump를 상속한다. 제품 SQL·공유 fixture는 유지한다. 최종 두 검토/정확 CI·성능·취소/pool·전체 closure·RC/복구/SH 운영은 미완이다. [범위·근거](../reports/2026-10-25-strict-sh-data-guard-foundation.md).

## 2026-10-25 — 인덱스 metadata 반사 표현식과 실제 검사 정산

427의 누락 인덱스 선언과 PG 반사 CASE 차이를 보완한 16ac를 상속했다. 원 실패를 보존하고, 변경하지 않은 fresh300 metadata 검사 실제 1 PASS/17.172초·정확 정리를 확인했다. 428 SQL/oracle은 유지한다. 합성 source의 새 CI·SH/복구·운영은 미완이다. [근거](../reports/2026-10-25-transport-airport-evidence-reader.md).

### 2026-10-25 공항 인덱스 PG 반사 표현식 보완

- 4bd 실제 autogen 1 FAIL/정확 정리를 보존하고 metadata CASE를 PG canonical 반사와 맞췄다. 기존 comparator 순수 회귀3 FAIL→equal·migration 포함8 PASS, 새 실제 검사는 미실행이다. [보고서](../reports/2026-10-25-transport-airport-evidence-reader.md).

### 2026-10-25 공항 reader ORM 인덱스 metadata 보완

- 70cb 양 PG CI의 autogen 단일 실패/원 로그를 보존하고 canonical metadata에 기존 인덱스3만 등록했다. 생성 SQL 전체 대조와 migration 회귀8 PASS, 실제 autogen/새 exact CI는 미실행이다. [보고서](../reports/2026-10-25-transport-airport-evidence-reader.md).

## 2026-10-25 — capture 권한 인벤토리 CI 정정

c98 CI의 signature literal 검사 실패1개를 보존하고, 존재 검사를 pg_catalog 이름 조회·GRANT를 카탈로그 서명 치환으로 정렬한다. 역할/SQL/oracle은 유지하며 새 정확 CI는 미완이다. [근거](../reports/2026-10-25-bounded-curation-capture.md).

## 2026-10-25 — 제한된 현재집합 capture(428, 구현 중)

실제 PG16.14에서 통합37 PASS/15.798초, fresh bootstrap 공식 oracle1 PASS/22.897초를 확인했다. 덤프를 갱신했으며 기존 실패와 시험 수정 기록을 보존한다. 검토된 최신 공항427·main을 상속했으며 최종 CI, SH/RC/복구 연결과 운영 배포는 미완이다. [범위·예산·검증](../reports/2026-10-25-bounded-curation-capture.md).

### 2026-10-25 공항427 준비 경계 소스

정본 converter/loader 기반 공항1→15·R1/R2/Geo 시험1개와 비활성 준비 함수를 추가했다.
순수12 PASS 뒤 첫 실제1FAIL을 보존했다. N1 단언 후 EX plan을 SH entry로 호출한
시험1곳을 EX entry로 정정하고 b3b synthetic15 실제1 PASS·공식oracle1을 확인했다.
R2/R3 비이름 의미 P2 반례2FAIL→순수157 PASS로 보강하고 두 source/binding 리뷰 뒤
c63 재검증1 PASS15.246s·complete15와 정리를 확인했다. 운영15fit·collector·SH·EXPLAIN/
peak·최종CI는 미완이며 현재PG0다.

## 2026-10-25 공항427 key/index 보강

- 논리CASE index3·caller 서버상한·area EXISTS, provenance P2 정정. 순수143 PASS.
- 실제 설치/oracle/EXPLAIN·Geo/native 준비·수집/SH는 미완, 두 source gate 전 PG0.

## 2026-10-25 공항427 SQL/decoder source

- 426 부모 보존, STABLE3함수·51가변열·RR decoder 배선. 순수108 PASS/mypy4.
- 실제 PG/oracle·provider 준비/native 연결·15 fit·collector/SH/운영은 미완.

## 2026-10-25 — 공항 reader Geo 계약(427, 부분)

- 원천 hash32/Geo digest64 혼동을 정정하고 원실패를 보존했다. 순수 Geo28개 경계이며 SD/DB·수집은 미완이다. [범위](../reports/2026-10-25-transport-airport-evidence-reader.md).

## 2026-10-25 — 가격 추이 본문 읽기 Low 3건(#1365 리뷰 후속)

- gzip 끝 뒤 bytes는 `upstream_contract`, 쓰이지 않던 `DecodingError` catch 제거, 503 본문 읽기 중 끊김은 `upstream_unavailable`.

## 2026-10-25 — 현행 기록 크기 경계 재분리

journal의 10월1~12일28절을 [10c](journal-2026-10c.md)로 보존하고 상대 링크만 재기준화했다. 본문 누락 없이 220 KiB 경계를 확보했다.

## 2026-10-25 — 공개 provider patch P-first(426)

실제25·공식 oracle1 PASS와 정리를 확인했다. 원실패를 보존한다. [근거·미완](../reports/2026-10-25-provider-patch-protocol-entry.md). CI·운영·실제 SH는 미완이다.

## 2026-10-25 — Provider base UPDATE-first 후보(425, 미수용)

- 실제15·oracle1·EX18·제한 A/B를 정산했다. 원 실패를 보존하며 최종 CI·운영은 미완이다. [범위·한계](../reports/2026-10-25-provider-base-update-first.md).

## 2026-10-25 — tracking P→L prefix(424, 부분)

- 기존 SER/capture/kernel/SH OFF를 보존했다. 직접25·정본oracle1·기존 client4와 별도 ASGI1(503→새요청200→재요청200)·fresh triple7을 검증했다. 공유 cutover DB의 통합11 원실패(9 PASS/2 FAIL)는 보존·합산하지 않는다. 정확 CI 양 PostGIS lane의28 FAIL/1 ERROR를 보존·분석 중이며 운영·whole snapshot은 미완이다. [범위·근거](../reports/2026-10-25-tracking-protocol-prefix.md).

## 2026-10-25 — Place projection 예산 검사 추출

- Heritage 사전 검사를 core로 이동하고 기존 wrapper·9DTO·본문을 보존했다. 순수 회귀114 PASS이며 DB/수집 연결은 없다. [범위·미완](../reports/2026-10-25-place-projection-budget-extraction.md).

## 2026-10-25 — 첫 동시 수집 후보 설계(미구현)

- 공항15·휴게소215를 읽기 전용으로 확인하고 기존 fetch/Geo 차이를 반영한 [구현 순서](../reports/2026-10-25-transport-small-native-pair-design.md)를 정리했다. 전체 크기·적격성·실제 두 worker·복구·운영은 미완, T-CWRITE-04/06/07 체크는 유지한다.

## 2026-10-25 — EX context 단일 조회(423)

- 기존 검증·권한을 보존하고 실제9 PASS, 별도 공식 oracle1 PASS/ACL보존, schema423 API startup1 PASS/고정GET3을 확인했다. 초기 감사 실패는 보존한다. 함수A/B6회는 뚜렷한 전체 CPU 개선을 입증하지 못했다. 최종 정확CI·collector/운영은 미완이다. [근거·한계](../reports/2026-10-25-exclusive-context-single-select.md).

## 2026-10-25 — scalar batch 내부 실행 단계 분리

- 기존 begin/manifest 검증/항목 적용/finish를 구체 private 함수로 나누고 실행 AST·SQL·공개 계약·전체30초·완료 조기반환을 보존했다. 두 소스 리뷰와 기존 실제 PG20 PASS/23.57초·정확 정리를 확인했다.
- main1395/1397 문서를 통합했다. 초기 CI의 부모 tasks04 길이 실패를 보존하며 새 정확 CI는 별도다. collector/coordinator·운영 변경0. [범위와 증명](../reports/2026-10-25-scoped-provider-batch-phases.md).

## 2026-10-25 — 전체 snapshot 동시 쓰기·복구 설계(미구현)

전체 입력·capture·동일 run 복구의 남은 문턱을 [설계](../reports/2026-10-25-full-snapshot-coordination-design.md)에 정리했다. 작은 비용과 [schema422 API startup](../reports/2026-10-25-schema422-api-startup-observation.md)은 별도 관측했으며, 실제 SH collector·운영 동시 쓰기·후속 전파는 미완이다.

## 2026-10-25 — Heritage bounded evidence reader 입력 계약(부분)

- 422 source 두 리뷰 뒤 SDK/권한/입력/snapshot20 PASS(15.11초)와 별도 새raw부정3 PASS(14.29초), 공식 fresh oracle1 PASS(14.68초)를 확인했다. 초기 실패는 보존하며 단일최종23 실행으로 세지 않는다. 추가 의미부정·메모리/비용·schema API startup/SH 운영은 미완이다. [근거·범위](../reports/2026-10-25-heritage-bounded-evidence-reader.md).


## 2026-10-25 — SH 운영 후보 크기 실측

- 국가유산/세계음식점 current head와 active primary place가 각각4,279/9,494로 기존 SH 한도를 넘음을 읽기 전용으로 확인했다. 작은 조회·시험을 운영 전체 동시성으로 세지 않는다. [실측·후속 범위](../reports/2026-10-25-sh-operating-scope-measurement.md).
- 문서만 변경하며 정책·상한·운영 활성화0, T-CWRITE-04는 미완이다.

## 2026-10-25 — Geo stamp SQL writer 권한 경계(421)

- 일반 runtime raw stamp 쓰기를 회수하고 EX/SH 전용 SD와 SI 진입 검증·기존 active full-context/정렬 잠금을 유지했다. 실제 SH collector 배선/운영 활성화는0이다.
- 장수 backend 비용 회귀와 실패 원본을 보존하고 UPSERT 한 문장만 계획하는 후보를 검증 중이다. 집중115·lint373/기존6skip·문서4 통과, 최종 비용·정확 CI/UI는 별도 수용이며 [구현·제한](../reports/2026-10-25-stamp-writer-boundary.md)에 정산한다.

## 2026-10-25 — 실제 SH 수집 연결의 설계 초안(A4)

- Heritage 이름 변경과 MCST 동일 key 반복 입력의 최소 범위를 나누고 현재 normalizer/Geo stamp·dataset retire0·full capture/후속 receipt를 필수 조건으로 정리했다.
- 실제 두 dataset DML 중첩·worker 복구/Geo pool은 별도 수용이며 구현/정책/운영 변경0, 전체 T 체크는 미완이다. [설계와 필수 반례](../reports/2026-10-25-sh-collector-integration-design.md).

## 2026-10-25 — main 419 보존과 EX 적재 연결 420 재검증

- 머지 직전 main에 들어온 PG transport 퇴역419를 보존하고 미머지 EX 적재 연결만420으로 재배치했다. DDL sidecar 본문과 main 비중복33파일·journal/resume 원문 suffix를 보존했다.
- 새 합집합 집중199 PASS/155.27초·lint373 PASS/기존6skip·CI 대상 Ruff/mypy5/import4 통과. 원419 세대의 CI/UI를 새420 결과로 세지 않으며, 새 정확CI·두리뷰·fresh UI는 별도다. [근거와 경계](../reports/2026-10-24-exclusive-provider-full-refresh.md#main-419-병합-뒤-420-재검증).

## 2026-10-24 — 제한 primary place의 명시 EX 전체 적재(A3 checkpoint)

- 최종 converter 입력에서 bounded plan을 만드는 opt-in client/EX 경로를 추가했다. 기존 applying EX manifest·비활성 base/Geo와 활성 winner를 같은 TX로 닫고 기본 선택은 OFF다.
- 최종 집중190건(140+중복 없는 converter50)·oracle/metadata2·lint377/기존6skip·mypy5/import4 통과. 실제 SDK/asset tracking은 격리 시험이며 실제 worker/운영 수집은 아니다. 최종 두리뷰·정확CI·fresh UI는 별도다. [범위와 남은 gate](../reports/2026-10-24-exclusive-provider-full-refresh.md).
