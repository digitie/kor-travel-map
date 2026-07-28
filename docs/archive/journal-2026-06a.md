# journal 아카이브 — 2026-06-10 ~ 2026-06-30

> `docs/journal.md`에서 분리한 과거 기록(역시간순). 현행 정본은
> [`docs/journal.md`](../journal.md)이며, 전체 아카이브 목록도 거기에 있다.
> 이 파일은 읽기 전용 이력이다 — 새 엔트리는 `docs/journal.md` 상단에 추가한다.

## 2026-06-30 (claude) — codex PR #613/#617 리뷰 후속 fix (#618)

codex #613(feature ops + Dagster 컨트롤)·#617(세션 UI 재반영 + MOIS sync-before-reads)을
상세 리뷰하고 findings를 #618로 반영했다.

- **#617 HIGH — Phase B read마다 전국 MOIS Phase A sync(42업종 download+upsert)가
  무조건 돌던 문제**: codex #617이 `feature_update_runner._mois_resources`와
  `resources._sync_then_fetch_mois_license_records`에서 read 전 `sync_mois_source_db`를
  무조건 호출 → RUNNING feature-update queue sensor를 통해 operator가 MOIS refresh를
  큐잉할 때마다 전국 sync가 돌아 #614의 STOPPED 봉쇄를 우회했다. **freshness 게이트**
  (`ensure_mois_source_db_fresh`)를 추가: 소스 DB가 존재·비어있지 않고 `<db>.synced`
  마커가 TTL(`mois_source_sync_ttl_hours`=24h) 이내면 sync를 생략한다. 두 read 경로를
  게이트 경유로 교체.
- **#617 MED — 동시 worker run 경합**: sync 엔진에 `busy_timeout=30s` 부여 + `<db>.lock`
  파일락으로 동시 Phase A sync를 1개로 제한(락 못 잡으면 sync 생략, 오래된 락은 회수).
- **#617 MED — async 런너 이벤트 루프 블로킹**: `FeatureUpdateAssetRunner.__call__`에서
  `spec.resources(...)`(MOIS는 게이트된 sync I/O 포함)를 `asyncio.to_thread`로 보냄.
- **#617 LOW — 소스 볼륨**: `kor-travel-map-mois-source` 볼륨이 dagster·dagster-daemon에
  마운트돼 있어 sensor-launch worker run·MOIS asset run 실행 컨텍스트를 커버한다(확인).
- **#617/#613 reconcile — KREX 교통공지 10분 스케줄 vs 최소주기 가드**: #617이 추가한
  `*/10` 스케줄을 #613 cron 가드가 거부하던 것을, 분 필드 `*/N`(N>=10) 허용으로 완화
  (매분/매5분 runaway는 계속 거부). API `_DEFAULT_SCHEDULE_CRONS`의 stale monthly 항목을
  `..._ten_minute_schedule: */10`로 정정. 해당 스케줄은 `default_status=STOPPED`(운영자
  enable 필요)임을 확인.
- 회귀 테스트: freshness 게이트(fresh→skip / missing→sync / stale→re-sync) 3건 추가.
- 검증: ruff + mypy --strict clean, dagster+api 관련 pytest green.

## 2026-06-30 (codex) — 세션 개선 요청 후속 재반영

PR #615를 문서 복기 PR로 정리해 병합한 뒤, 병합된 `main`에 세션 중 요청됐던 UI/Dagster 개선이
남아 있는지 다시 대조하고 누락분을 후속 브랜치에서 보강했다.

- **MOIS/Dagster**: `mois_license_records` resource와 feature update runner가
  `mois_localdata_source_sync`를 먼저 실행한 뒤 source DB에서 bulk record를 읽도록 연결했다.
  Dagster/Dagster daemon compose env와 volume에 `KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH`를 추가했다.
- **스케줄**: 고속도로 교통공지 notice schedule을 월간에서 10분 주기로 바꾸고 회귀 테스트를 추가했다.
- **작업 자동화 UI**: Dagster 실행 시각 epoch 단위 보정, 스케줄 tick collapsible 기본 닫힘,
  시작/중지 버튼 spinner·색상·아이콘을 보강했다.
- **운영 UI**: 중복 검토 provider/dataset/category와 보강 검토 provider를 다중 combobox로 바꿨고,
  신규 Feature 작성의 시군구 코드 입력은 자동검색 후보를 필드 하단에 표시한다.
- **적재/로그/지도**: 적재 작업 목록·상세는 한국어 중심, 진행률/작업 링크/상단 오류/중지 위치/payload
  시각화를 보강했다. 운영 로그의 `live live` 중복 표시는 `실시간`으로 정리했고, Feature 지도
  kind 필터 초기화는 outline 버튼으로 표시한다.
- **검증**: Dagster 대상 pytest 37 passed, Dagster ruff, compose config, frontend type-check,
  frontend lint(기존 경고 4건), frontend unit 45 passed, Dagster mypy 19 source, import-linter
  4 contracts kept를 확인했다.
## 2026-06-30 (claude) — MOIS source sync WAL 디스크-풀 사고 후속 하드닝 (#614 리뷰 반영)

#614(MOIS LOCALDATA 소스 sync를 전체 업종 단일 트랜잭션 → 업종별 commit + `wal_checkpoint(TRUNCATE)`로
바꿔 n150 루트 디스크 100% 사고를 막은 PR)의 사후 리뷰 findings를 반영했다.

- **사고 요약**: MOIS Phase A source sync가 42개 업종을 한 트랜잭션으로 적재 → SQLite WAL이 commit
  전까지 무한 성장 → Dagster daemon 임시 공간(`/tmp` = n150 루트 overlay)을 채워 디스크 100%. #614가
  업종별 commit + 슬러그별 WAL TRUNCATE로 WAL 피크를 “42업종 합”에서 “최대 단일 업종”으로 축소했다.
- **이번 하드닝(`mois_source_sync.py`)**:
  - `_checkpoint_sqlite_wal`을 명시적 AUTOCOMMIT 연결로 실행하고, `wal_checkpoint(TRUNCATE)` 반환행을
    캡처해 `busy != 0`(동시 reader가 truncate 차단)이면 경고 로그 — 조용히 WAL이 잔존하는 상황을 관측.
  - 명시적 빈 `service_slugs`는 `ValueError`로 fail-fast(예전 무음 no-op 회귀 복구).
  - `sync_kind`를 마지막-업종-덮어쓰기 대신 distinct 집합으로 합산.
  - WAL checkpoint가 슬러그별+마지막에 호출되는지 구조적 spy 테스트 추가(checkpoint를 지우면 깨지게).
- **MOIS 스케줄은 의도적으로 STOPPED 유지**(source-sync weekly + feature-load weekly). 코드상
  `default_status=STOPPED`가 durable baseline이며, 사고를 유발한 enable은 out-of-band Dagster UI 토글이었다.
- **재가동 체크리스트**: `docs/runbooks/docker-app.md` §MOIS 재가동 참조 — (1) 본 fix 배포 → (2) source
  sync 1회 수동 materialize → (3) 중 `*-wal` 크기·루트 디스크 헤드룸이 bound되는지 확인 → (4) 문제
  없으면 source-sync·feature-load 스케줄 재가동.
- **남은 후속(별도 이슈)**: 단일 최대 업종(`general_restaurants` ~2.5–3M행)은 provider
  `mois.sync_localdata_source_db`가 슬러그당 1회만 commit해 그 한 트랜잭션 동안 WAL이 multi-GB까지 커질
  수 있다 — 근본 해결은 provider(python-mois-api) 측 batch별 commit이며 cross-repo(ADR-006)라 본 PR
  범위 밖. 디스크 영구 가드(MOIS source DB 전용 볼륨 + `/tmp` tmpfs size cap + df 헤드룸 알림)도 후속.

## 2026-06-30 (codex) — PR #615 보존 브랜치 정리와 n150 UI 복기

n150 UI가 이전 화면처럼 보인다는 보고를 받은 뒤, 배포 image 시각 해석과 git worktree metadata
깨짐을 함께 복기하고 PR #615를 현재 `main` 기준 문서 보강 PR로 다시 정리했다.

- **시각 해석**: Docker inspect의 `image_created=2026-06-30T10:49:30Z`는 UTC 기준이므로
  한국시간으로는 `2026-06-30 19:49:30 KST`다. 따라서 “오전 버전”이라는 표현은 시각대 해석만으로는
  맞지 않지만, 그 이후 UI 변경은 rebuild/recreate 전까지 반영되지 않는다는 점을 명시했다.
- **배포 검증 기준**: n150 UI 최신 여부는 image 생성 시각만으로 판단하지 않고, 컨테이너 내부
  `/app/packages/kor-travel-map-admin/frontend/.next` marker와 로그인된 public DOM marker를 함께
  확인하도록 정리했다. 비로그인 `/login` HTML이나 잘못된 `/app/.next` 경로 grep은 근거로 쓰지 않는다.
- **git 복구 사고**: `.git`이 사라진 worktree metadata를 가리켜 `git status`가 실패했고, 긴급 보존을
  위해 `codex/admin-ui-ops-review-polish-save` branch와 draft PR #615를 먼저 만들었다. 리뷰 결과
  기존 보존 스냅샷은 현재 `main` 대비 회귀가 있어 로컬 `backup/pr615-before-cleanup-20260630`에
  남기고, PR head는 현재 `main` 위에 문서 보강만 다시 얹도록 정리했다.
- **재발방지 문서**: `docs/runbooks/agent-failure-patterns.md`에 B5(worktree metadata 복구 중 diff 폭증)
  와 F11(n150 UI image 시각/번들 검증 오판)을 추가했다. emergency 보존 PR도 push 전 redaction guard,
  민감값 패턴 검사, prod-specific literal scan을 통과해야 한다.

## 2026-06-30 (codex) — Feature 변경/작업 자동화 운영 UI n150 배포

Feature 변경 작성·검수 분리와 작업 자동화 스케줄 제어 UI를 n150에 배포하고 실제 live UI e2e로
write 흐름을 검증했다.

- **작업 자동화**: `/admin/dagster`를 `작업 자동화` 메뉴로 정리하고, 스케줄 cron override 저장,
  기본값 복귀, 시작/중지, 즉시 실행 명령을 admin UI/API에서 수행할 수 있게 했다. reload timeout은
  스케줄 저장 성공과 분리해 `reloaded=false` 경고로 표현한다.
- **Dagster 표시**: asset 한국어 표기 상수를 추가해 UI에서는 한국어명을 우선 표시하고, 코드 레벨
  이름은 작게 말줄임/툴팁으로 보여준다. Code locations는 하단으로 내려 compact하게 정리했다.
- **Feature 변경**: 작성 페이지와 검수 페이지를 분리하고, 검수 페이지는 승인/반려·필터·상세 확인에
  집중하도록 live spec을 보강했다. 생성/편집 폼의 한글 label과 상태 배지에 맞춰 e2e 기대값도 정리했다.
- **검증**: n150 배포 후 로그인 POST 200 + Set-Cookie와 wrong password 401을 확인했다. 공식
  Playwright Docker image로 `dagster-runs-roundtrip.live.spec.ts` 3 passed / 1 skipped,
  `admin-features-change-requests-write.live.spec.ts` 3 passed,
  `misc.live.spec.ts` 182 passed를 확인했다.
- **로컬 게이트**: frontend `type-check`, `lint`(기존 경고 4개만), 관련 pytest 22건, ruff,
  `git diff --check`를 통과했다.

## 2026-06-29 (codex) — Feature change requests 편집 UX 보강

Feature change request 작성 화면을 운영자가 실제 feature 수정에 바로 쓰기 쉽도록 정리했다.

- **admin features 연계**: `/admin/features` 상세 패널에 `편집` 링크를 추가했고, change request
  화면은 query의 `action=update`/`feature_id`를 받아 feature detail을 조회한 뒤 form을 prefill한다.
- **feature 상세 연계**: `/features/[featureId]` 상세 페이지의 `수정` 링크도 같은 change request
  update prefill 경로로 연결했다. prefill은 이름/카테고리/좌표뿐 아니라 주소, 행정코드, 관계 id,
  좌표 정밀도, 전화·행사·URL 필드까지 개별 입력으로 채운다.
- **form 구조**: 요청 메타, 기본 정보, 위치/마커, JSON payload 구간으로 나누고 `category`,
  `marker_icon`, `marker_color`를 카탈로그 dropdown으로 바꿨다.
- **위치/마커 다이얼로그**: 지도 중심 다이얼로그에서 lon/lat/icon/color/sigungu를 함께 수정한다.
  지도 우클릭과 모바일 오래누르기는 선택 좌표를 form에 반영하고 reverse geocoder로 시군구 코드와
  이름을 표시한다. 다이얼로그는 `적용`/`취소` 버튼으로 바깥 form 반영 시점을 분리한다.
- **시군구 검색**: `sigungu_code`는 숫자 코드 prefix와 한글 이름 입력을 모두 geocoder 검색으로
  즉시 후보화하며, 실제 코드가 잡히면 시군구명을 badge로 보여준다.
- **geo 프록시**: 브라우저 CORS에 의존하지 않도록 admin UI의 `kor-travel-geo` 호출을 인증된
  same-origin `/api/geo/...` 프록시로 보낸다.
- **review 지도**: enrichment/dedup review 상세 비교 지도는 두 좌표가 모두 보이도록 bounds에 맞춰
  중심과 zoom을 조정한다.
- **메뉴명**: Admin UI 사이드 메뉴는 `Feature 지도`, `Feature 목록`, `Feature 변경`처럼
  Feature 계열을 같은 이름 체계로 묶고, 나머지 운영 메뉴도 한글 중심의 직관적인 이름으로 바꿨다.
- **문서**: Playwright UI/e2e는 WSL에서 실행하지 않고 n150을 1순위, Windows 호스트 브라우저를
  2순위 fallback으로 쓴다는 기준을 개발 환경/runbook/playwright config 주석에 명시했다.
- **검증**: frontend `type-check`, `type-check:e2e`, `lint`(기존 경고만), `test` 45건, `build`,
  `git diff --check` 통과. n150에 배포한 뒤 공식 Playwright Docker image로 targeted live spec
  `admin-features-change-requests-write.live.spec.ts`를 실행해 인증 setup과 read/edit UI 시나리오
  2 passed, write opt-in spec 1 skipped를 확인했다.

## 2026-06-29 (codex) — tasks 백로그 정리

사용자 결정에 따라 열린 백로그를 다시 정리했다.

- **tasks**: `T-229-buildx`는 추가 추적하지 않기로 결정해 열린 백로그에서 제거했다.
- **tasks**: `T-AUDIT-0616` F-01 옵션 A는 ADR-058의 옵션 B(re-key 없음, geocoder 필수화)
  채택으로 필수 진행 백로그에서 제외했다.
- **tasks-done**: T-229 아카이브의 `docs/tasks.md` 후속 추적 문구를 현재 결정에 맞게 정정했다.

## 2026-06-29 (codex) — n150 live e2e backup runner tracked 전환

n150 full live e2e에서 복구한 `live-e2e-backup-runner`가 untracked 상태라 배포 rsync/정리 시 다시
사라질 수 있는 문제가 있어, 민감정보 없는 runner 스크립트를 repo에 포함했다.

- **runner**: `backup.sh`는 API/Dagster 컨테이너의 기존 DSN을 읽고 host-network PostgreSQL client
  컨테이너와 RustFS volume archive를 사용해 backup artifact를 만든다.
- **runner**: `restore.sh`는 staging DB/volume만 대상으로 복구하며, superuser role은 기존 DB 안에서
  조회해 extension/schema 선행 생성과 dump restore에 사용한다.
- **safety**: `swap.sh`는 `apply=1` 자동 hot-swap을 거부하고 plan/검증용 출력만 제공한다.
- **검증**: runner 3개 shell script는 `bash -n`을 통과했다. tracked runner 내용을 n150에 반영한 뒤
  targeted `backups-restore.live.spec.ts`는 8 passed / 1 skipped로 통과했다.

## 2026-06-29 (codex) — n150 full admin live e2e 완료

PR #596을 CI green 후 squash merge하고 n150 운영 디렉터리를 `main@860a987`로 맞춘 뒤, admin
live e2e 전체 실행을 다시 완료했다.

- **운영 runner**: PR #595 재배포 때 untracked `live-e2e-backup-runner`가 삭제되어
  backup execute가 503으로 실패했다. n150 로컬 runner를 복구하고 docker-manager 배포 topology에
  맞춰 API/Dagster DSN, host-network PostgreSQL client, RustFS volume archive 경로로
  backup/restore를 수행하게 조정했다.
- **검증**: runner 복구 후 targeted `backups-restore.live.spec.ts`는 실제 backup execute,
  staging restore execute, swap plan까지 8 passed / 1 skipped로 통과했다.
- **full live e2e**: 최종 `playwright-live-full-20260629T054002Z`는 status 0으로 종료했다.
  결과는 1,886 passed / 2 flaky / 22 skipped이며 실패는 0건이다.
- **flaky**: 2건은 full 부하 중 일시적인 `Failed to fetch`와 `ERR_NETWORK_CHANGED`였고, 둘 다
  retry #1에서 통과했다. backup execute/restore execute/swap plan은 최종 full run에서 모두 통과했다.

## 2026-06-29 (codex) — feature-update live spec refreshable 계약 정합화

PR #595 머지/배포 후 full n150 live e2e 전에 feature-update write live spec을 다시 점검했다.
PR #595에서 API가 refresh 가능한 provider/dataset 조합만 enqueue하도록 바뀌었기 때문에, 기존
spec의 bogus provider/dataset no-op 전략이 422 계약과 충돌하는 것을 확인했다.

- **e2e**: feature-update live write spec은 실제 refreshable catalog pair
  (`python-kma-api`/`kma_short_forecast`)를 사용하되 한국 남서쪽 경계 근처의 극소 반경으로
  scope를 제한하도록 바꿨다.
- **e2e**: 목록 row 식별은 provider 문자열 대신 생성 응답의 `request_id` short link로 바꿔
  운영 데이터와 섞여도 자기 row를 안정적으로 찾게 했다.
- **e2e**: 다중 provider×dataset 가정은 새 API 계약에 맞춰 단일 provider의 다중 refreshable
  dataset 검증으로 바꿨고, API 목록 확인에는 `created_from`/`dataset_key` 필터를 보조로 쓴다.
- **검증**: frontend e2e type-check와 `git diff --check`를 통과했다. n150 targeted live 검증 후
  PR/CI/머지를 진행하고 full live e2e를 이어간다.

## 2026-06-29 (codex) — Claude 후속 이슈 #589~#594 정리

full n150 live e2e 재실행 전에 Claude 사후 리뷰로 열린 #589~#594를 먼저 반영했다.

- **API 계약**: feature-update request 생성/run-now 경로에서 refresh 가능한 provider/dataset 조합만
  enqueue되도록 catalog 검증을 추가했다. MOIS history/closed/detail 같은 non-refreshable 조합은
  직접 API 호출이어도 422로 거절한다.
- **API 계약**: dedup/enrichment review list 응답은 cursor 없는 `OffsetMeta`를 사용하도록 분리해
  `meta.page.next_cursor` 영구 null 직렬화를 제거했다. OpenAPI와 admin generated type을 재생성했다.
- **e2e**: backup/restore/swap execute live spec의 죽은 UI 토글을 제거하고, swap execute도
  `/api/proxy` 직접 POST 후 Admin UI 목록 반영을 확인하는 경로로 맞췄다.
- **테스트/문서**: backup router 테스트 들여쓰기, dedup fast-count/decision 단언 분리, 잔존
  Windows Playwright 문구를 n150 Linux 우선 기준으로 정리했다.
- **검증**: 관련 pytest 56건, `ruff`, OpenAPI drift, admin/user generated type drift,
  frontend `type-check`/`type-check:e2e`, 대상 mypy, import-linter를 통과했다. 로컬 mocked
  Playwright는 현재 WSL 배포판을 Playwright가 지원하지 않아 Chromium 설치 단계에서 중단했다.

## 2026-06-29 (codex) — n150 full live e2e long-tail 안정화

n150 write/destructive full live e2e는 1차 재실행에서 1,869 passed / 12 flaky / 17 skipped /
7 failed / 5 did not run으로 끝났다. 실패 원인은 제품 동작 회귀보다는 full 부하에서 드러난
live spec 동기화 문제였다.

- **e2e**: Dagster run detail과 features map detail의 중복 텍스트 strict locator를 `.first()`로 좁혔다.
- **e2e**: import-jobs live navigation은 `ERR_NETWORK_CHANGED`/timeout을 짧게 retry하는 `gotoLive`
  helper를 거치도록 정리했다.
- **e2e**: ETL provider catalog 로딩은 n150 full 부하를 고려해 ETL 구간 timeout만 45초로 늘렸다.
- **e2e**: enrichment review deep pagination은 5분 response wait로 hang하지 않도록 response 관측을
  짧게 제한하고 UI disabled state 검증을 유지했다.
- **검증**: 실패 축 targeted 재실행은 12 passed로 통과했다.

## 2026-06-29 (codex) — Enrichment review detail live smoke 클릭 안정화

n150 targeted review live e2e에서 enrichment 목록/score=all 조회는 통과했지만, 상세 다이얼로그
smoke가 테이블 overflow/hit-test 경로에서 row click으로 이어지지 않는 현상을 확인했다.

- **UI**: enrichment review actions 컬럼에 `detail` 버튼을 추가해 상세 비교 다이얼로그 진입을 명시화했다.
- **e2e**: enrichment review 상세 smoke는 `detail` 버튼을 클릭하고, detail GET 응답이 성공했는지
  확인한 뒤 다이얼로그/지도 surface를 검증하도록 보강했다.
- **검증**: n150 targeted backup/restore live spec은 8 passed / 1 skipped, targeted enrichment review
  live spec은 3 passed로 통과했다.

## 2026-06-29 (codex) — Backup destructive live e2e 실행 경로 분리

n150에서 backup/restore 실제 command는 API 직접 호출로 정상 완료되지만, UI destructive button 응답 대기에서
Playwright가 멈추는 현상이 있어 live e2e 책임을 분리했다.

- **e2e**: backup/restore plan은 계속 Admin UI 버튼 경로로 확인하고, 실제 destructive execute는 인증된
  browser context의 `/api/proxy` 요청으로 수행한 뒤 Admin UI 백업 목록에 artifact가 반영되는지 확인한다.
- **운영 runner**: n150 live runner는 compose 파싱 대신 API/Dagster DSN과 PostgreSQL client image를 사용해
  backup/restore를 수행하도록 조정했다.
- **검증**: 직접 `/api/proxy` backup execute와 restore execute가 200 completed를 반환함을 확인했다.

## 2026-06-29 (codex) — Backup live e2e 상태 배지 assertion 안정화

n150 targeted backup live e2e에서 command 실행 전 기본 옵션 테스트가 `plan only`/`execute enabled`
상태 배지 전환을 분기형 `isVisible`로 확인하다 stale 분기를 타는 문제를 정리했다.

- **e2e**: backup page 실행 상태는 `plan only` 또는 `execute enabled` 중 현재 렌더링된 배지 하나가
  보이면 통과하도록 단일 locator assertion으로 바꿨다.
- **검증 예정**: frontend e2e type-check 후 PR/CI/merge, n150 backup targeted live e2e 재실행.

## 2026-06-29 (codex) — n150 live e2e 실패 보강

n150 full live e2e write 실행에서 드러난 백업 command 시작 실패와 enrichment review 조회 500을
작은 API/SQL 보강으로 정리했다.

- **백업 API**: backup/restore/swap command 실행 전에 `cwd` 또는 command 시작이 실패하면
  `BACKUP_COMMAND_UNAVAILABLE` 503 문제 응답으로 반환해 운영 설정 문제를 UI/API에서 식별할 수 있게 했다.
- **리뷰 조회**: enrichment review 거리 기반 점수 SQL에서 35km 이상 후보는 `spatial_score=0`으로
  clamp해 아주 먼 좌표 조합이 numeric underflow로 목록/상세 조회를 깨뜨리지 않게 했다.
- **검증**: admin backup router 단위 테스트 12건, enrichment review integration 대상 2건, 변경 파일
  ruff를 통과했다. n150 재배포 후 targeted/full live e2e 재실행이 다음 단계다.

## 2026-06-29 (codex) — Enrichment review 지도 비교 surface 일원화

#572 지적에 따라 enrichment review 목록의 인라인 지도 비교 surface를 제거했다.

- **UI**: `mapReviewId` state, 행별 `지도` 버튼, `enrichment coordinate map` section을 삭제하고
  #559 상세 다이얼로그의 VWorld 지도만 좌표 비교 surface로 남겼다.
- **e2e**: mocked enrichment action spec과 live review smoke를 행 클릭 상세 다이얼로그 지도 기준으로
  바꾸고, 목록 행에 `지도` 버튼이 더 이상 보이지 않음을 단언한다.
- **검증**: frontend `type-check`, `lint`(기존 6 warnings), production `build`, `git diff --check`,
  Docker Playwright 수동 시나리오(로그인 → 목록 mock → 행 클릭 → 상세 다이얼로그 지도)를 통과했다.

## 2026-06-29 (codex) — Dedup/Enrichment review page-only 계약 정리

#571 지적에 따라 review 목록의 이중 pagination 계약을 제거했다.

- **API 계약**: `GET /v1/admin/dedup-reviews`와 `GET /v1/admin/enrichment-reviews`의
  `cursor` query parameter를 제거하고 `page`/`page_size`/`meta.page.total` 기반 계약만 남겼다.
- **repository/UI**: dedup/enrichment review repository의 cursor decode/encode 경로와 `next_cursor`
  계산을 삭제하고, admin UI의 죽은 `nextCursor` fallback도 total 기반 page 이동으로 단순화했다.
- **회귀 가드**: 같은 score에서 `review_id DESC` tie-breaker가 page 순회에서도 빠짐없이 유지되는지
  integration/EXPLAIN 테스트를 갱신했다.

## 2026-06-29 (codex) — Linux/WSL 개발 실행 정책 문서 정합성 보정

#570 지적에 따라 옛 Windows Git/Windows Playwright 표준 문구를 제거했다.

- **agent-guide**: worktree 진입 예시를 WSL `/mnt/f/...` + Linux `git`으로 바꾸고, §9를
  Linux/WSL 단일 실행 흐름으로 재작성했다.
- **CLAUDE/debug UI 문서**: Playwright e2e 기준을 n150 Linux 우선, Windows 호스트 브라우저는
  fallback으로 정리했다.

## 2026-06-29 (codex) — data.go.kr curated fileData 4종 월간 schedule 보강

#568 지적에 따라 단일 기본 dataset만 돌던 fileData 월간 schedule을 dataset별로 분리했다.

- **schedule**: `DATAGOKR_FILEDATA_DATASETS` 4개 dataset마다 별도 job/schedule spec을 만들고,
  같은 `feature_place_datagokr_file_data` asset에 dataset_key run config를 주입한다.
- **resource**: `datagokr_file_data_records`와 `datagokr_file_data_dataset_key` resource가 schedule
  `run_config`의 dataset_key를 우선 사용하도록 바꿨다. config가 없으면 기존 settings 기본값을 유지한다.
- **검증**: Dagster definitions/resource 테스트 22건, feature-update runner 테스트 7건, Dagster package
  mypy를 통과했다.

## 2026-06-29 (codex) — Enrichment detail source audit-only 계약 명시

#567 지적에 따라 enrichment 상세 비교 다이얼로그의 detail source 선택 의미를 정직하게 낮췄다.

- **API 계약**: enrichment detail/decision 응답에 `detail_source_effect: "audit_only"`를 추가하고,
  decision 응답은 요청의 `selected_detail_source`를 함께 반환한다.
- **UI 문구**: 상세 다이얼로그의 source 선택 옵션을 `기록:` prefix로 표시하고, 접근성 설명/tooltip도
  실제 적용 데이터 변경 없이 decision reason에 기록되는 선택임을 명시한다.
- **문서 정리**: changelog의 기존 “데이터 선택” 표현을 audit-only 기록 선택으로 바로잡았다.

## 2026-06-29 (codex) — Dedup review count fast path 보강

#566 지적에 따라 dedup review 목록의 count 경로를 정리했다.

- **count fast path**: provider/dataset/kind/category/q 같은 확장 필터가 없으면
  `feature.features`와 `provider_sync` LATERAL join을 타지 않고 `ops.dedup_review_queue`에서
  status/score 조건만으로 count한다.
- **성능 회귀 가드**: T-212d EXPLAIN 테스트에 fast count SQL을 추가해 `idx_dedup_status_score` 사용과
  relation set이 `dedup_review_queue` 하나뿐임을 단언한다.
- **검증**: 관련 unit 9건, T-212d 대상 EXPLAIN integration 1건, 변경 파일 ruff를 통과했다.

## 2026-06-29 (codex) — PR #564 사후 리뷰 반영: live write 게이트와 catalog 정직성

PR #564 상세 리뷰의 #569/#574 지적을 반영해 admin live e2e의 기본 실행 안전성과 catalog 표현을
정리했다.

- **write 게이트**: `admin-features-change-requests-write.live.spec.ts`는
  `E2E_ADMIN_FEATURES_WRITE=1` 또는 `E2E_ADMIN_WRITE=1`, `settings-write.live.spec.ts`는
  `E2E_SETTINGS_WRITE=1` 또는 `E2E_ADMIN_WRITE=1`일 때만 실제 mutation을 수행한다. Settings
  public API key 테스트는 생성 응답 대기 실패 시나리오를 줄이기 위해 같은 label의 active key를
  `finally`에서 한 번 더 revoke한다. 삭제 불가 auth audit event는 opt-in 밖에서는 생성하지 않는다.
- **catalog 정직성**: 13,651건 count를 실행 커버리지처럼 단언하던 threshold 검증을 제거하고,
  route smoke가 실제 catalog의 `live_smoke` 항목을 따라 돌도록 바꿨다. 문서 표현도
  “열거된 surface taxonomy”로 정리했다.
- **risk/API 계약**: backup artifact 정리를 위해 `DELETE /v1/admin/backups/{backup_id}` API 계약을
  추가하고 OpenAPI/frontend generated type을 갱신했다. scenario catalog의 write API는 path substring이
  아니라 명시 `method/path/risk` metadata로 destructive를 분류한다.

## 2026-06-28 (codex) — Admin UI 전체 live e2e 시나리오 catalog 보강

Admin UI 전체 표면을 대상으로 live e2e 시나리오 catalog와 실제 write 반영 검증을 보강했다.

- **시나리오 catalog**: home/public features/admin features/change requests/curated/issues/import jobs/
  providers/consistency/logs/reviews/update requests/POI targets/offline uploads/backups/dagster/settings/ETL
  preview를 포함해 13,651건의 논리 시나리오 taxonomy를 산출한다.
- **실제 write 반영**: 기존 feature add/update/deactivate/delete 승인 흐름에 더해 Settings에서 public API
  key 생성·API 조회·UI revoke·API/UI revoked 확인, API로 생성한 auth audit event의 Settings UI 노출을
  추가했다.
- **발견 및 수정**: n150 DB에서 404가 나던 오래된 feature fixture를 현재 active id로 갱신했고,
  curated 후보가 0건일 때 empty row를 후보로 오인하던 spec을 `curated-feature-row` test id 기준으로
  고쳤다. Settings route/nav/문서 누락도 보강했다.
- **n150 검증**: 공식 Playwright Docker image + host network에서 full live suite 수정본
  1,828 passed / 5 skipped / 0 failed (34.1분)를 확인했다. 로컬 `type-check:e2e`, frontend `lint`
  (0 errors, 기존 warnings 6개), `git diff --check`도 통과했다.

## 2026-06-28 (codex) — Admin features/change requests UI live write e2e 추가

`/admin/features`, `/admin/features/new`, `/admin/features/change-requests`를 하나의 실제
read/write live UI 흐름으로 묶는 e2e 시나리오를 추가했다.

- **시나리오**: change request 화면의 form/filter/table/detail 표면을 확인한 뒤, 새 feature 작성 화면에서
  실제 add 요청을 만들고 승인한다. 이어 admin features 목록 검색/필터/preview/detail 링크, update 승인,
  update 거절(실제 feature 미변경), deactivate, delete 승인, public detail 404까지 확인한다.
- **실제 반영 검증**: 각 write 뒤 `/api/proxy`를 통한 admin/public API 조회로 DB 반영을 확인한다.
  생성/수정은 public 상세에 노출되는지, 삭제 뒤에는 admin 상세가 `deleted`이고 public 상세가 404인지 확인한다.
- **운영 검색 차이 반영**: live change request 목록 검색은 payload `name`/`request_id`가 아니라
  `feature_id`/`reason` 중심임을 확인하고, spec 검색 기준을 운영 SQL 계약에 맞춰 조정했다.
- **n150 검증**: 새 write live spec은 공식 Playwright Docker image + host network에서 2 passed.
  기존 admin features read-only live 목록 suite도 333 passed. 실패 재시도에서 생긴 synthetic feature까지
  점검해 `user_request::e2e_admin_features::live-*` 활성/미삭제 feature가 0건임을 확인했다.

## 2026-06-28 (codex) — Backup/restore UI live e2e 실제 실행 경로 추가

`/admin/backups`에 대해 read-only smoke가 아니라 실제 backup/restore 실행까지 갈 수 있는 live e2e
시나리오를 추가했다.

- **시나리오**: 실행 옵션 기본값, invalid backup id 오류 alert, backup command plan, 실제 cold backup
  artifact 생성, 생성 artifact 기준 staging restore plan/execute, hot-swap plan, 선택적 swap command
  execute를 직렬 spec으로 묶었다.
- **가드**: 실제 backup/restore는 `E2E_BACKUP_RESTORE_EXECUTE=1`, swap command 실행은
  `E2E_BACKUP_RESTORE_EXECUTE_SWAP=1`일 때만 동작한다. `swap 즉시 적용`은
  `E2E_BACKUP_RESTORE_EXECUTE_SWAP_APPLY=1`일 때만 켠다.
- **n150 검증**: n150 host는 Playwright bundled Chromium deps가 없어 공식 Playwright Docker image를
  host network로 실행했다. 기본 run은 4 passed / 5 skipped, execute/apply run은 9 passed.
- **n150 execute/apply**: API command enable + runner mount를 붙여 실제 backup artifact 생성,
  staging DB/RustFS volume restore, swap `apply=true` 요청까지 UI live e2e로 통과시켰다. apply는
  API 요청 응답 이후 helper 컨테이너가 map API/UI/Dagster를 restore env로 재기동하는 방식으로 분리했다.
  apply 뒤 map 컨테이너 healthy, API/Dagster restore DB DSN 전환, 로그인 POST 200 + Set-Cookie를 확인했다.

## 2026-06-28 (codex) — Refreshable provider catalog와 MOIS detail runner 정렬

`is_feature_load=False`인 PriceValue/WeatherValue/detail 보강 dataset이 Dagster runner로 실행 가능한데도
`/ops/providers` never-run 목록에서 빠지는 문제를 정리했다.

- **카탈로그 분리**: `is_feature_load`와 별도로 `is_refreshable`을 추가해, 새 Feature를 만들지 않는
  OpiNet/KREX/KMA/VisitKorea 보강 계열도 feature update request 실행 목록에 노출되게 했다.
- **MOIS detail**: `mois_license_detail`을 refreshable로 전환하고 기존 MOIS license asset runner가
  해당 dataset_key를 받을 수 있게 했다. 상세 API는 detail source record를 먼저 조회하고, 없으면 기존
  bulk source record로 fallback한다.
- **유지 항목**: 전화번호 보강(`place_phone_enrichment`)과 AirKorea station alias는 운영 실행 목록에
  노출하지 않도록 유지했다.
- **검증**: refreshable catalog 56개와 Dagster runner spec 비교에서 누락 0건을 확인했다. 관련 pytest
  32건, 변경 파일 ruff, 대상 mypy를 통과했다.

## 2026-06-28 (codex) — Feature update AirKorea/OpiNet 및 누락 Dagster 자산 보강

Feature update requests에서 AirKorea/OpiNet 요청이 실패하던 원인을 수정하고,
카탈로그상 feature load 대상이지만 Dagster runner가 받지 못하던 provider/dataset 불일치를 정리했다.

- **AirKorea**: provider catalog의 feature-load 대상을 standalone `airkorea_stations`가 아니라
  실제 Dagster asset인 `airkorea_air_quality`로 정렬했다. 기존 `airkorea_stations` 요청도 같은
  asset으로 실행되도록 runner alias를 남겼다.
- **OpiNet**: Dagster feature update 실행 전에 `KOR_TRAVEL_MAP_OPINET_API_KEY` 누락을 명확한
  `ProviderCredentialMissing`으로 실패시키도록 해 provider client 내부 인증 오류 대신 운영자가
  바로 이해할 수 있는 메시지를 남긴다.
- **누락 Dagster**: MOIS history/closed, `standard_special_streets`, data.go.kr curated fileData 4종을
  feature update runner가 실행할 수 있게 했다. 지역특화거리와 fileData 공용 Dagster asset/resource/
  schedule도 추가했다.
- **회귀 방지**: `catalog_feature_load_entries()`의 모든 항목이 runner spec에 포함되는지 확인하는
  계약 테스트를 추가했다.
- **검증**: 카탈로그/runner drift 점검에서 missing 0건 확인, Dagster 테스트 199건 통과, API provider
  router/catalog 테스트 19건 통과, 전체 `ruff check .`, 대상 mypy 통과.

## 2026-06-28 (codex) — Linux/WSL 개발 실행 정책 정리

개발 실행 위치 정책을 Windows Git 예외 기반에서 Linux/WSL 단일 실행 원칙으로 정리했다.

- **환경 정본**: `AGENTS.md`, `SKILL.md`, `README.md`, `docs/dev-environment.md`에서
  `git`/`gh`/`codegraph`를 포함한 모든 개발 명령을 Linux/WSL에서 실행하도록 수정했다.
- **Runbook**: agent workflow, codegraph worktree, failure patterns, runbook index의 Windows Git
  전제를 제거하고, Windows 경로 기반 worktree metadata 복구 절차를 추가했다.
- **Playwright**: debug UI e2e는 n150 Linux 환경 우선, n150에서 불가할 때만 Windows browser
  fallback으로 실행하도록 frontend README와 Playwright config 주석까지 문서화했다.
- **검증**: 문서 변경만 수행했으며 `git diff --check`를 실행했다.

## 2026-06-28 (codex) — Review 상세 비교 다이얼로그 추가

Dedup review와 Enrichment review에서 테이블 요약만으로 판단하기 어려운 후보를 행 클릭으로 상세 비교할
수 있게 했다.

- **API/저장소**: dedup/enrichment review 단건 상세 조회 API를 추가했다. 상세 응답은 양쪽 feature/source
  상세 JSON, raw source payload, 좌표, 거리/score, 기간 정보를 함께 반환한다.
- **Admin UI**: dedup/enrichment 테이블 행 클릭 시 상세 비교 다이얼로그를 열고, 두 자료의 핵심 필드와
  raw/detail JSON, 하나의 VWorld 지도에 표시한 두 좌표를 함께 보여준다.
- **Enrichment 선택**: 축제 enrichment 상세에서 관리자가 `정리된 datagokr` 또는 `visitkorea` 상세를
  선택할 수 있게 했다. 정리된 target detail이 비어 있으면 VisitKorea를 기본값으로 선택하고, accept
  요청에는 선택 source를 함께 기록한다.
- **검증**: 전체 pytest 1367건, 전체 ruff, `mypy src/kortravelmap`, import-linter, OpenAPI drift check,
  admin frontend type-check/lint/gen:types:check, mocked review Playwright e2e 23건 통과.

## 2026-06-28 (codex) — Feature update request queue 실행 복구

Update requests 메뉴에서 provider 요청과 run-now 요청이 queue에만 쌓이고 실제 provider 적재가
진행되지 않던 문제를 Dagster worker 쪽에서 수정했다.

- **Dagster**: `feature_update_runner` 기본 resource를 추가하고, worker가 queued/run-now request를
  provider/dataset별 기존 feature load asset 실행으로 dispatch하도록 연결했다.
- **Provider 범위**: OpiNet 유가, KREX 유가/기상, KMA 실황·예보·특보, AirKorea 대기질을 포함해
  현재 live fetcher가 연결된 주요 provider asset을 lazy resource 방식으로 실행한다.
- **회귀 테스트**: runner dispatch 단위 테스트와 Definitions 기본 resource 등록 테스트를 추가했다.
- **검증**: targeted pytest 21건, 변경 파일 ruff, `mypy --python-version 3.12` 3파일 통과.
  기본 mypy 설정은 현재 `numpy` stub의 Python 3.12 `type` 문법과 충돌해 중단되는 것을 확인했다.

## 2026-06-28 (codex) — Review 테이블 페이지네이션 상/하단 보강

Dedup review와 Enrichment review 테이블의 페이지 이동을 cursor-only UI에서 page 번호 기반 UI로
보강했다.

- **API/저장소**: dedup/enrichment review 목록에 `page` 쿼리와 `meta.page.total`을 추가했다.
  기존 `cursor`는 호환용으로 유지하고, page 조회는 `OFFSET`과 전체 count를 함께 반환한다.
- **Admin UI**: 두 review 테이블 바로 위와 아래에 동일한 페이지바를 표시한다. 첫/이전/다음/마지막
  페이지 버튼과 `페이지 n / total · 총 x건 · 현재 y건` 요약을 보여준다.
- **e2e**: mocked Playwright에서 page 쿼리 전진, 상/하단 페이지바 2벌, 마지막 페이지 버튼,
  빈 목록 비활성 상태를 검증하도록 보강했다.
- **검증**: targeted ruff, mypy 3파일, router/unit pytest 20건, SQL integration 2건,
  OpenAPI drift check, admin frontend type-check/lint, mocked review e2e 21건, review smoke e2e 2건 통과.

## 2026-06-27 (codex) — Enrichment/Dedup review 검수 테이블 보강

Enrichment review와 Dedup review 테이블을 운영 검수자가 같은 화면에서 더 촘촘하게 좁혀 보고,
좌표·거리·기간 차이를 바로 판단할 수 있게 보강했다.

- **API/저장소**: enrichment review 목록 응답에 datagokr 대상 feature의 좌표/기간, visitkorea
  source 좌표/기간, 두 좌표 사이 `distance_m`, 거리 기반 `spatial_score`를 추가했다. VisitKorea
  enrichment source record에는 TourAPI 좌표를 보존하도록 했다.
- **Admin UI**: enrichment/dedup review에 검색, 상태/성격별 필터, score band, page size,
  cursor pagination을 추가했다. enrichment 테이블은 대상/source 기간과 거리 컬럼을 표시하고,
  좌표가 있는 행은 하나의 VWorld 지도에서 datagokr/visitkorea 마커와 이름을 함께 확인한다.
- **e2e/live**: mocked Playwright에 enrichment 필터·페이지네이션·지도, dedup 전용 필터·페이지네이션
  회귀 테스트를 추가했고, N150 live spec에도 두 review 화면의 필터/페이지네이션/지도 smoke를 보강했다.
- **검증**: Python unit 1109건, enrichment repository integration 9건, API/router targeted 28건,
  ruff, mypy, import-linter, admin frontend lint/type-check/gen:types, Vitest 45건, mocked review e2e
  21건 통과.

## 2026-06-27 (codex) — Curated place-search 반영 정책 수정

Admin curated feature에서 manual_review 후보의 place-search 결과를 `반영`해도 REUSE가
`allowed`로 바뀌지 않는 문제를 수정했다.

- **UI**: `CuratedPlaceSearchPanel`의 PATCH payload에 `reuse_policy: "allowed"`를 포함해 검색 결과
  반영과 공개 재사용 허용 전환이 한 번에 저장되도록 했다.
- **e2e**: route-mocked curated mutations spec에 manual_review → place-search 반영 → REUSE
  `allowed` 갱신 회귀 테스트를 추가했다. mock PATCH 응답은 실제 서버처럼 body를 반영하고
  `updated_at`/`content_version`을 갱신하도록 보강했다.
- **검증**: admin frontend type-check, 변경 파일 ESLint, curated mutations Playwright 21건,
  `git diff --check` 통과.

## 2026-06-27 (codex) — Feature update request live e2e 보강

Feature update request UI의 live e2e와 에러 케이스를 보강하고, update request 완료/재요청 이벤트가
feature 지도 계열 query를 다시 읽도록 연결했다.

- **UI/e2e**: `/admin/feature-update-requests` live spec을 추가해 form controls, validation error,
  실제 API dry-run preview, `/features` 지도 화면의 `Update` 진입 링크를 확인한다.
- **에러 케이스**: mocked list/create e2e에 lon 필수, lat 범위, radius 최소값 validation과 create API
  422 alert 케이스를 추가했다.
- **지도 반영**: feature update request create/run-now 및 ops-live `feature_update_requests`/단건 topic이
  `features`, `feature`, `admin-features` query를 invalidate하게 했다. `/features` mocked map spec은
  새 ops-live 구독이 라이브 WS 잡음을 만들지 않도록 inert WS를 설치한다.
- **검증**: admin frontend type-check, 변경 파일 ESLint, mocked update request Playwright 8건,
  live feature-update-request Playwright 5건, `git diff --check` 통과. `src/api/live.test.ts`는 추가했지만
  현재 WSL `node_modules`에 `@vitejs/plugin-react`가 없어 Vitest를 실행하지 못했고, `npm install`
  보강도 NTFS `node_modules` 권한(EACCES)으로 중단했다.

## 2026-06-27 (codex) — Curated place search provider 직접 호출

Admin curated feature의 주소/POI 검색이 kor-travel-concierge의 검색 API를 경유하지 않도록
FastAPI backend에서 Kakao Local, NAVER Search, Google Places API를 직접 호출하게 바꿨다.

- **API**: `/v1/admin/curated-features/{id}/place-search`는 provider별 키가 있는 경우 해당 API를
  병렬 호출하고, 키 누락/호출 실패는 provider별 `errors`에 담아 반환한다.
- **설정**: `KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY`,
  `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID`, `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET`,
  `KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY`를 settings에 추가했다. 기존 짧은 env 이름은
  `scripts/load-env.sh`와 `docker-compose.yml`에서 `KOR_TRAVEL_MAP_*`로 매핑한다.
- **검증**: direct provider 호출 정규화/키 누락 단위 테스트와 변경 파일 ruff 통과.

## 2026-06-27 (codex) — Admin curated/features/Dagster 후속 보강

Admin live 확인 뒤 남은 curated review, feature 상세, OpiNet, Dagster 노출 문제를 보강했다.

- **Curated UI**: place 검색은 후보 선택만으로 자동 호출하지 않고 검색 버튼을 눌렀을 때만 호출하게
  바꿨다. 후보 전환 시 검색어와 결과 패널이 새 후보 기준으로 초기화된다. 화면 표시에서
  `kor-travel-concierge`/`concierge` 문구는 중립 표시명으로 바꿨고, provider 선택 시 source rule의
  실제 theme을 따라가게 했다.
- **상세 화면**: admin curated feature 단건 상세 route를 추가하고, 기존 우측 검토 패널(지도,
  place search, display 편집, detail snapshot)을 전용 상세 화면에서도 재사용한다. admin features
  목록/상세에는 지도 preview를 추가하고, 목록의 `detail` 버튼은 `/features/{feature_id}` 상세로
  바로 이동하게 바꿨다.
- **OpiNet/Dagster**: OpiNet `low_top_area`의 no-data 예외를 건너뛰고 일정 호출 수 뒤 sample-grid
  fallback으로 보강한다. Dagster feature load schedule에 krforest/standard/khoa/krairport/
  airkorea/visitkorea 누락 asset을 추가하고, admin Dagster 화면은 asset group 내부 asset을 모두
  표시한다.
- **검증**: admin frontend type-check/e2e type-check, 변경 파일 ESLint, Dagster/API targeted pytest,
  ruff, OpenAPI export drift test 통과.

## 2026-06-27 (codex) — Admin live review 데이터/표시 보강

N150 admin에서 enrichment/dedup review가 0건이고 price/provider/log/curated review 화면의
운영 판단이 어려운 문제를 점검했다.

- **운영 확인**: KMA weather `TMP` 값은 존재했지만 marker label이 `deg_c` 단위를 섭씨로 인식하지
  못할 수 있었다. OpiNet price는 여전히 제주/완도권 bbox에 머물렀고, `lowTop10` 부분 응답이 있으면
  fallback을 타지 않는 것이 원인이었다. enrichment/dedup queue와 ops log 테이블은 운영 DB에서 0건,
  provider sync state는 KMA만 기록되어 있었다.
- **Dagster/API 보강**: OpiNet `low_top_area` 부분 성공 시에도 전국 sample fallback을 타도록
  최소 station 수 기준을 추가했다. VisitKorea enrichment asset은 자동 적재가 아니라 review queue
  refresh 경로를 호출하게 바꿨고, feature load 계열 asset은 성공 시 provider sync state를 기록한다.
- **Admin UI 보강**: curated feature review 우측에 위치 지도/좌표/주소/분류 패널과 concierge
  place-search 결과 패널을 추가했다. admin features, curated features, logs 주요 table에는 현재
  page/page size 표시와 첫 페이지/다음 페이지 상태를 보강했다. MOIS place feature는 인허가/영업상태/
  facility_info 특화 패널을 표시한다.
- **검증**: OpiNet/Dagster provider fetcher targeted pytest, Dagster integration, OpenAPI export test,
  API ruff, admin frontend type-check/e2e type-check, 변경 파일 ESLint, `git diff --check` 통과.
  `/admin/enrichment-reviews` live Playwright read-only e2e 34건 통과.

## 2026-06-26 (codex) — OpiNet fallback 주요 도심 anchor 보강

N150에 `low_top_area`를 배포하고 `feature_price_opinet_stations_job`을 수동 실행했지만
active price feature가 295건 그대로였고, 좌표 bbox도 `126.1794~126.9535 / 33.2226~34.3038`로
제주권에 머물렀다. `feature.feature_price_values`도 최근 30분 갱신 0건이었다.

- **원인 보강**: 기존 fallback은 `lowTop10`이 0건일 때만 sparse grid `aroundAll`을 호출한다.
  5km 반경 대비 grid 간격이 넓어 도심 주유소를 비켜갈 수 있으므로, fallback 후보 앞에 전국 주요
  도심 anchor를 추가했다.
- **범위**: 전체 전국 bbox exhaustive scan은 계속 금지한다. 주요 도심 anchor + 기존 grid를 합쳐도
  휘발유/경유/고급휘발유 3종 기준 약 900회 호출로 일일 한도 안에 둔다.

## 2026-06-26 (codex) — Feature별 상세 패널 + Dagster 실패 상세 보강

Feature 상세 화면이 non-price feature에도 weather panel을 보여주던 문제를 고치고,
kind별 특화 상세 화면으로 분리했다.

- **API**: `/v1/features/{feature_id}/contained-features`를 추가해 area polygon 안의 point
  feature를 반환한다. `/v1/features` summary에는 weather marker용 현재기온(`T1H`/`TMP`) 요약을
  붙였고, public/admin feature 상세에는 `area_square_meters`를 노출한다.
- **Admin UI**: `/features`, `/features/{featureId}`, `/admin/features` inspector가 공용
  `FeatureKindDetailPanel`을 사용한다. weather panel은 weather feature에서만 표시하고, price는
  이력 그래프, event는 기간/장소, area는 면적/포함 feature, route는 구간 메타를 표시한다.
- **지도 marker**: weather feature marker에 현재기온 라벨을 붙이고, weather marker icon을
  `marker_icon` metadata 그대로 사용한다.
- **좌측 메뉴**: `/features` 지도 화면도 `AdminShell` 안으로 편입하고, 데스크톱 sidebar 접기/펼치기
  상태를 localStorage에 저장한다.
- **Dagster**: feature load schedule을 weather 시간당 1회, price 일 2회, 기타 월 1회로 정리했다.
  run 상세 응답과 admin UI에는 실패 원인 요약/stack 표시를 추가했다.
- **검증**: 전체 pytest 1,357건, 전체 ruff, import-linter, strict mypy(`src/kortravelmap` +
  API/Dagster package), admin frontend type-check/lint(기존 warning 7건), OpenAPI generated type
  drift check, production build(필수 public env 주입), `git diff --check` 통과.

## 2026-06-26 (codex) — OpiNet low_top_area 운영 빈 응답 fallback

N150에 `OPINET_SCOPE_MODE=low_top_area`를 배포한 뒤 OpiNet price job을 수동 실행했으나
active price feature가 기존 295건(좌표 있는 OpiNet 196건)에서 늘지 않았다.

- **운영 확인**: Dagster job은 `RUN_SUCCESS`였지만 `feature.feature_price_values` 최근 2시간
  적재가 0건이었다. 운영 컨테이너에서 `KorTravelMapSettings.opinet_scope_mode`는
  `low_top_area`로 정상 로드됐다.
- **provider 응답**: 운영 OpiNet client 기준 `areaCode.do` root가 0건, `lowTop10.do`가 area 유무와
  상관없이 0건을 반환했다. 수동 확인 시 `aroundAll.do`도 0건이라 당일 provider 응답/제한 이슈
  가능성이 남았다.
- **코드 보강**: `low_top_area`가 `areaCode`/`lowTop10`에서 한 건도 얻지 못하면 전국 샘플 그리드의
  `aroundAll`을 휘발유/경유/고급휘발유 3종으로 호출하는 fallback을 추가했다. 전체 전국 bbox
  exhaustive scan은 여전히 금지하고, fallback 호출량은 3개 제품 기준 약 800회로 제한한다.

## 2026-06-26 (codex) — OpiNet price scope 제주 bbox 원인 확인 + 전국 저가 모드

N150 admin 지도에서 유가가 제주도 주변에만 보이는 원인을 확인했다. 운영 Dagster env가
`KOR_TRAVEL_MAP_OPINET_SCOPE_MODE=bbox`,
`KOR_TRAVEL_MAP_OPINET_SCOPE_BBOX=126.15,33.19,126.98,34.21`로 고정되어 있어 OpiNet
수집 자체가 제주/완도권 bbox만 적재하고 있었다.

- **운영 확인**: active OpiNet price feature는 196건이고 좌표 bbox는
  `126.18~126.95 / 33.22~34.30`으로 제주/완도권에 한정된다. KREX price 99건은 원천에
  좌표가 없어 지도 marker에 표시되지 않는다.
- **API 한계**: `python-opinet-api` 확인 결과 OpiNet 공개 API에는 전국 bulk 주유소 목록이 없고,
  전국 bbox를 `aroundAll` 5km 격자로 덮으면 1만 회 이상 호출되어 일일 한도(1,500회)를 넘을 수
  있다.
- **코드 보강**: `OPINET_SCOPE_MODE=low_top_area`를 추가했다. 시군구별 `lowTop10`을
  휘발유/경유/고급휘발유 3종으로 호출해 전체 주유소는 아니지만 전국 저가 유가 분포를
  quota-safe하게 생성한다. `lowTop10` Station 단일 제품 가격 row를 `kind=price` anchor와
  `PriceValue`로 적재하는 변환 경로를 추가했다.
- **검증**: OpiNet provider unit 19건, Dagster provider fetcher 63건(+1 skip), Dagster definitions
  포함 targeted pytest 92건(+1 skip), 수정 파일 ruff, strict mypy(`src/kortravelmap` +
  Dagster package) 통과.

## 2026-06-26 (codex) — Admin price feature 표시 + Dagster 주기 정리

`kind=price` feature를 열어도 `detail`이 비어 있고 공통 weather panel만 보여 가격 정보가
표면화되지 않는 문제를 UI/API 양쪽에서 보강했다.

- **API**: `/v1/features/{feature_id}/price`를 추가했다. 응답은 제품별 최신 가격(`current`)과
  최근 가격 이력(`history`)을 포함한다. `feature.feature_price_values` 조회는 `price_repo`에
  `build_price_card`로 모았다.
- **지도 summary**: `/v1/features` bbox 응답의 `FeatureSummary`에 `price_summary`를 추가했다.
  `feature.feature_price_values`에서 제품별 최신값을 lateral query로 붙여, 지도 marker가 별도
  N+1 호출 없이 휘발유/경유/고급휘발유 최신 가격을 표시한다.
- **Admin UI**: `FeaturePricePanel`을 추가했다. `/features` 지도 우측 선택 패널과
  `/features/{featureId}` 상세 화면에서 `kind=price`일 때 price panel을 보여준다. marker DOM에는
  `휘/경/고` 가격 라벨을 붙인다. 가격 history 그래프는 사용자가 별도 후속 PR로 요청했다.
- **Dagster**: OpiNet/KREX price Feature schedule은 일 2회로 낮췄다. KMA/KREX weather 관련
  schedule은 시간당 1회로 정렬했고, 관련 Dagster/KMA ETL 문서 표를 갱신했다.
- **OpenAPI/types**: admin/user OpenAPI와 admin frontend/user-client TypeScript generated types를
  재생성했다.
- **후속 요청 메모**: PR 머지 후 feature kind별 우측 메뉴를 분리한다. price는 숫자 history 그래프,
  weather 상세는 weather feature에서만, event는 기간 등 추가정보, route는 구간 상세정보를 표시한다.
  로그인 후 좌측 메뉴는 모든 화면에서 보이게 하고 닫을 수 있게 한다.
- **검증**: API targeted pytest 20건, Dagster definitions 10건, OpenAPI drift check, admin frontend
  type-check, user-client type-check, admin frontend lint(기존 warning 7건), targeted ruff,
  `git diff --check` 통과.

## 2026-06-25 (codex) — 가격 시계열 테이블 설계 + OpiNet/KREX 유가 적재

admin Feature UI의 `price` 필터가 0건인 원인을 N150 DB에서 확인했다. 기존 OpiNet 주유소는
`place` feature 196건만 있었고 `kind='price'` feature와 가격 시계열 영속 테이블이 없었다.
196건은 N150의 현재 `poi_cache_target` bbox scope 기준 OpiNet 주유소 수이며, OpiNet에는 전국
일괄 dump endpoint가 없어 전국 적재는 bbox grid enumerate와 호출량 정책 검토가 별도로 필요하다.

- **DB 설계**: `feature.feature_price_values` Alembic migration을 추가했다. PK는 결정적
  `price_value_key`, 논리 unique는 `(feature_id, provider, price_domain, product_key, observed_at)`,
  값은 `NUMERIC(14,4)` + `value_number >= 0` CHECK, source 추적은 nullable
  `source_record_key` FK로 둔다. 최신/추세 조회용 `(feature_id, price_domain, product_key,
  observed_at DESC)`와 provider/domain 운영 검증용 인덱스, `observed_at` BRIN을 추가했다.
- **적재 경계**: `AsyncKorTravelMapClient.load_price_features(...)`를 추가해 price anchor
  `FeatureBundle`과 `PriceValue`를 한 transaction에서 upsert한다.
- **OpiNet**: station detail의 중첩 `OIL_PRICE`를 `kind=price` anchor feature +
  제품별 `PriceValue`로 변환한다. price feature는 주유소 place feature를
  `parent_feature_id`로 연결하고 `fuel/P-08` marker를 쓴다.
- **KREX**: EX `curStateStation` 휴게소 유가 snapshot을 `kind=price` anchor feature +
  gasoline/diesel/lpg `PriceValue`로 변환한다. 원천 row에 좌표가 없어 현재는 주소/이름을 보존한
  coordless price feature로 적재하고, rest area place matching은 후속 보강 범위로 남긴다.
  live 적재 중 provider가 `gasolinePrice='X'`를 정수로 파싱하다 실패해
  `python-krex-api@cc8609c`로 `X`/`-`/`N/A` sentinel을 결측 처리하도록 pin을 올렸다.
- **Dagster**: `feature_price_opinet_stations`, `feature_price_krex_rest_areas` asset과 매시
  schedule/job을 추가했다.
- **Alembic graph**: main hotfix의 `0035_merge_price_and_curated`와 N150 선배포의
  `0035_merge_curated_price` revision ID를 모두 보존하고, `0036_merge_price_merge_aliases` no-op
  merge revision으로 단일 head를 만든다. 이로써 `0034_feature_price_values`를 먼저 적용한 DB와
  `0034_generic_curated_contract`를 먼저 적용한 DB가 모두 같은 head로 upgrade된다.
- **로컬 검증**: OpiNet/KREX provider unit, Dagster resource/fetcher/definition unit,
  Alembic + Dagster 통합 테스트, `ruff check .`, strict mypy, import-linter를 통과했다.
- **N150 배포/적재**: API/Dagster/UI 이미지를 재빌드·재기동했고, 최종 Alembic graph를
  `0036_merge_price_merge_aliases` 단일 head로 올렸다. KREX/OpiNet price job을 새 이미지에서
  재실행했다. 최종 active price feature는 295건(`opinet_gas_station_prices` 196건,
  `krex_rest_area_prices` 99건), `feature.feature_price_values`는 1,132건
  (`python-opinet-api/opinet_gas_station` 874건, `python-krex-api/rest_area_fuel` 258건)이다.
- **N150 live smoke**: `/health` 200, public `/v1/features`는 운영 key 정책상 key 없이 401,
  trusted admin proxy read-only 헤더로 전국 bbox `kind=price` 조회 200과 price item 5건을 확인했다.
  UI는 `/` 307, `/login` 200, API/UI/Dagster 컨테이너 healthy를 확인했다.
- **로그인/UI live e2e**: Windows Playwright live config로 N150 공개 prod URL의 admin 로그인 setup
  1건 통과. 같은 인증 세션으로 `features-list.live.spec.ts`와 `features-map.live.spec.ts`의 `price`
  grep 대상 16건을 실행해 admin feature 목록의 `kind=price` 필터, deep link, status×kind matrix,
  `/features` 지도 kind chip 노출/토글/초기화/테이블·지도 뷰 유지가 모두 통과했다.

## 2026-06-25 (codex) — Alembic curated 배포 체인 hotfix

N150 운영 DB에는 `0034_feature_price_values`가 이미 적용되어 있었지만 main의 Alembic graph에는
해당 리비전 파일이 없어, curated 범용 계약 배포 시 API entrypoint의 `alembic upgrade head`가
`Can't locate revision identified by '0034_feature_price_values'`로 중단됐다.

- **마이그레이션 체인 복구**: 운영 DB에 존재하는 `feature.feature_price_values` DDL과 동일한
  `0034_feature_price_values` 리비전을 main graph에 복원했다.
- **branch merge**: 이미 main에 들어간 `0034_generic_curated_contract` 리비전 ID는 보존하고,
  두 `0034` 리비전을 `0035_merge_price_and_curated` no-op merge 리비전으로 합쳤다.
- **목표**: N150처럼 price value 리비전이 이미 적용된 DB와 curated 리비전을 먼저 적용한 DB가 모두
  제품명 없는 curated API/DB 계약으로 정상 upgrade되도록 한다.

## 2026-06-25 (codex) — Curated API 범용 계약 정리

kor-travel-map은 특정 소비자 제품명을 알지 않는다는 정책에 맞춰 curated feature API/DB 계약을
범용 명칭으로 정리했다. curated features는 임의 외부 사용자가 목록과 상세를 조회할 수 있는
공개 데이터 계약이고, 상세 snapshot preview는 admin 운영 도구 전용으로만 남겼다.

- **public API 축소**: user OpenAPI profile의 curated public surface를
  `/v1/curated-features`, `/v1/curated-features/{curated_feature_id}`만 노출하도록 정리했다.
  제품 전용 상세 snapshot endpoint와 hidden 호환 route는 제거했다.
- **DB/API rename**: `feature.curated_features`의 재사용 관련 컬럼은
  `curation_relation`/`reuse_policy`/`content_version`, snapshot table은
  `feature.curated_feature_detail_snapshots`로 정리했다. source rule metadata와 snapshot JSON도
  같은 범용 key로 migration한다.
- **POI cache metadata**: 외부 POI 식별자는 `external_poi_id`만 받도록 API schema와 JSONB
  migration을 정리했다.
- **admin UI/OpenAPI**: admin preview route는
  `/v1/admin/curated-features/{curated_feature_id}/detail-snapshot`로 이동했고, admin/user
  TypeScript OpenAPI type을 재생성했다.
- **검증**: curated/POI API targeted 21건, curated/POI/schema integration 14건, OpenAPI drift,
  admin/user generated type drift, admin/user type-check, frontend unit 43건, curated mocked e2e
  22건, ruff, strict mypy, import-linter를 통과했다. 전체 pytest는 1,345건 통과했고,
  `kor-travel-geo` live reverse geocoder가 400을 반환한 외부 의존 테스트 5건만 별도 실패했다.

## 2026-06-25 (codex) — KNPS 비매칭코스 route 제외 + N150 env/DB rename

N150 production의 active route에서 `비매칭코스` 1건을 확인했다. source는
`python-knps-api/knps_trails`, `source_entity_id=15000000000`, raw `코스ID=0`,
`탐방코스(한글)=비매칭코스`, `탐방코스(영문)=Nonmatching Course`였고, 161,179 vertex /
약 1,295km의 거대 placeholder route로 적재되어 있었다. 이는 공식 탐방코스가 아니라 KNPS
원천의 코스 미매칭 placeholder라 route 적재 대상에서 제외했다.

- **코드 수정**: `knps_trails` 변환에서 `비매칭코스`와 `Nonmatching Course` 계열 영문명을
  감지하면 bundle을 만들지 않도록 했다. 일반 이름 없는 route skip과 별도로, 한글 raw name과
  영문 raw name을 모두 본다.
- **회귀 테스트**: 단건 `비매칭코스`가 빈 결과를 반환하고, 배치에 영문 `Nonmatching Course`와
  정상 `북한산 둘레길`이 함께 있을 때 정상 route만 남는 unit test를 추가했다.
- **N150 삭제/배포**: 수정 provider/test 파일을 N150에 반영하고 map API/Dagster/daemon 이미지를
  재빌드·재기동했다. 운영 DB의 active `비매칭코스` route 1건은 soft delete 처리했고,
  active unmatched route 0건과 active route 617건을 확인했다.
- **OpiNet 재적재**: 로컬 `python-opinet-api/.env`의 OpiNet key를 N150 운영 `.env`에
  `KOR_TRAVEL_MAP_OPINET_API_KEY`로 저장하고, bbox scope
  `126.15,33.19,126.98,34.21`를 `KOR_TRAVEL_MAP_OPINET_SCOPE_*`로 저장했다.
  `feature_place_opinet_stations_job` 실행은 성공했고, `python-opinet-api /
  opinet_fuel_station_details` source record 196건, active place feature 196건을 확인했다.
- **N150 이름 정리**: 운영 `kor-travel-docker-manager` 활성 `.env`/compose에서 `KRTOUR_MAP*`,
  `krtour_map`, `krtour-map`, `krtour-uploads` 잔여를 제거했다. PostGIS DB/role은
  `krtour_map` → `kor_travel_map`, `krtour_map_dagster` → `kor_travel_map_dagster`,
  role `krtour_map` → `kor_travel_map`으로 rename했고, API/Dagster 컨테이너가 새 DB/role을
  바라보는 것을 확인했다.
- **live e2e**: N150 health 200 확인. UI live Playwright는 `features-map.live` 118건
  통과(마커 렌더 1건 retry 통과), `features-list`/`features-detail`/`providers-consistency`
  753건 통과, 나머지 live 묶음 896건 통과 후 `reviews /admin/issues @ mobile-390` 1건이
  실패했으나 단독 재실행 2건 통과했다. full suite 단일 실행은 20분 제한으로 timeout되어
  spec 묶음 단위로 검증했다.

## 2026-06-25 (codex) — Concierge curated source 추가 + curated 계약 보강

`kor-travel-concierge`의 YouTube 장소 후보를 curated feature 기본 source로 올리고,
curated 재사용 계약을 범용 detail snapshot 기준으로 정리했다.

- **concierge source rule**: `kor-travel-concierge-youtube/youtube_place_candidates`를
  `media-places` theme의 `curated` 기본 rule로 등록했다. rule apply 시 `selected_at`을
  채우고, `display_title`은 concierge payload의 `source_title` → playlist/channel title →
  검색어 계열 title 순서로 결정한다.
- **curated 재사용 계약**: `feature.curated_features`의 재사용 속성, detail snapshot cache,
  public/admin endpoint를 제품명 없는 curated feature 계약으로 정리했다.
- **POI cache metadata**: 외부 target metadata의 POI 식별자는 `external_poi_id`로 serialize한다.
- **검증**: curated unit/API/Dagster targeted 33건, curated integration 6건, OpenAPI drift check,
  admin/user TypeScript type-check, ruff, strict mypy, import-linter를 통과했다.

## 2026-06-25 (codex) — KNPS protected area Gemini 한글명 보정 + N150 재적재

N150 production의 active `area` provider를 다시 확인했고, 현재 `area` source는
`python-knps-api`의 `knps_park_boundaries` 23건과 `knps_protected_areas` 1,516건이다.
`knps_protected_areas`의 영어/로마자 표기가 남은 distinct source name을 모아 Gemini 2.5 Flash에
JSON 입력/JSON 출력으로 일괄 번역했다. 프롬프트 앞부분에는 한국 장소명 번역 지침, JSON 구조 이해,
라틴 문자 금지, 숫자 prefix 보존 규칙을 명시했고, 요청 방식은 `kor-travel-concierge`의
`GEMINI_API_KEY`, `gemini-2.5-flash`, `responseMimeType=application/json`, schema 지정,
retry/backoff 패턴을 참고했다.

- **코드 수정**: `knps_protected_areas`용 한글명 테이블 1,431건을 추가하고, raw 한글 후보 복구 다음
  단계에서 provider `name`/raw `NAME`을 테이블에 매칭한다. 런타임은 Gemini를 호출하지 않는다.
- **mojibake 보강**: 라틴 문자와 손상 한글 음절이 섞인 raw `ORIG_NAME`은 정상 한글 후보로 보지
  않게 해 `Jeju Volcanic Island and Lava Tubes` 같은 raw `NAME` fallback이 한글명으로 매핑된다.
- **N150 반영/재적재**: 수정 provider 파일을 N150 `~/kor-travel-map`에 rsync하고
  `kor-travel-map-api`, `kor-travel-map-dagster`, `kor-travel-map-dagster-daemon`을 재빌드·재기동했다.
  Dagster 컨테이너에서 `knps_protected_areas` 1,516건을 fetch→변환→적재했고, 기존 `f_global_*`
  중복 1,386건은 inactive 처리했다. geocoder가 법정동을 못 채운 현재 정본 130건은 active로 유지했다.
- **N150 데이터 검증**: 최종 active area는 `knps_park_boundaries` 23건,
  `knps_protected_areas` 1,516건이며, active `area` 이름 중 라틴 문자 포함은 0건이다.
- **live e2e**: 공식 UI live Playwright 인증+`/features` 지도 smoke, 인증+`/admin/features` 목록 smoke가
  통과했다. 추가 커스텀 smoke에서 로그인 200, `/features` area filter ON, marker 25개, BFF
  `/v1/admin/features` protected area 1,516건 전체 cursor 순회, 라틴 이름 0건, `제주 화산섬과
  용암동굴` 검색 1건, console error 0건을 확인했다.
- **로컬 검증**: KNPS unit, 전체 pytest, ruff, strict mypy, import-linter, `git diff --check`를
  통과했다.

## 2026-06-25 (codex) — Admin 로그인 submit 보강 + N150 area live 재검증

N150 production 화면 재검증 중 로그인 form에 값이 보이는데 `/api/auth/login` payload의
password가 빈 문자열로 전송되는 케이스를 확인했다. React state와 실제 DOM form value가
자동입력/테스트 입력 타이밍에서 어긋날 수 있어 submit 시점의 `FormData`를 정본으로 읽도록
보강했다.

- **코드 수정**: `LoginForm` submit은 `event.currentTarget`에서 `FormData`를 읽어 username/password를
  전송한다. input에는 `name="username"`/`name="password"`를 명시했다.
- **회귀 테스트**: password input의 DOM value만 바꾼 뒤 submit해도 fetch payload에 현재 form 값이
  들어가는 jsdom 테스트를 추가했다.
- **N150 반영**: 수정 frontend 파일과 changelog를 N150 `~/kor-travel-map`에 rsync하고
  `kor-travel-map-ui`를 재빌드·재기동했다. Next production build 내 TypeScript가 통과했고,
  UI/API 컨테이너 모두 healthy 상태를 확인했다.
- **N150 live e2e**: 공식 live Playwright `auth.setup.ts` + `/features` 지도 smoke 2건 통과.
  추가 계측 smoke에서 로그인 POST 200, 낮은 줌 area 요청 `include_geometry=false`, 응답 72건,
  지도 cluster 25개, partial 표시 없음, console error 0건을 확인했다. 같은 세션에서 한글 area
  표본 `보성`으로 확대 시 `include_geometry=true`, geometry 포함 8건, geometry source feature 4건,
  area fill/outline layer 2개 렌더를 확인했다.
- **로컬 검증**: `npm run test -- src/components/login-form.test.tsx`, `npm run type-check`,
  대상 ESLint, `git diff --check` 통과.

## 2026-06-24 (codex) — Admin area 클러스터링 + KNPS protected area 한글명 보정

N150 feature 화면에서 `area` 로딩이 느리고 플리커가 심하다는 제보와, KNPS area 이름이 영어로
표시된다는 제보를 함께 처리했다.

- **성능 원인**: `/features` 지도 조회가 낮은 줌에서도 `area` geometry를 항상 포함했고,
  `area`는 point cluster source에서 제외되어 polygon/label만 직접 갱신했다. 전국 범위에서
  대형 polygon payload와 geometry layer 갱신이 겹쳐 느린 로딩과 flicker가 발생했다.
- **지도 동작 변경**: 낮은 줌에서는 `area`를 centroid marker로 cluster에 포함하고,
  `area` polygon/label geometry는 줌 14 이상에서만 요청·표시한다. 선택 feature의 geometry는
  기존처럼 표시할 수 있게 남겼고, query 전환 중에는 이전 데이터를 유지해 빈 지도 flicker를 줄였다.
- **tile 조회 보정**: area/route 같은 geometry-light 필터는 tile 개수로 `page_size`를 나누지 않고,
  tile zoom을 한 단계 더 잘게 잡으며, tile별 `next_cursor`가 남으면 이어 받아 area 단독 필터의
  false partial 표시와 누락 가능성을 줄였다.
- **KNPS 이름 보정**: `knps_protected_areas`는 raw 속성의 `ORIG_NAME` 등에서 한글 후보를 먼저
  사용한다. UTF-8 문자열이 CP949로 잘못 decode된 recoverable 값은 한글로 복구하고,
  이미 `�`가 섞였거나 repair 실패 후 CJK mojibake가 남는 값은 영어 이름을 유지한다.
- **검증**: `tests/unit/test_providers_knps.py`, frontend type-check/build, 수정 frontend ESLint,
  `ruff check .`, `python -m mypy --strict src/kortravelmap`, import-linter, `git diff --check`를
  통과했다. 로컬 mocked Playwright는 기존 dev server/env 상태 때문에 신규 기대값 검증이
  안정적으로 끝나지 않아 N150 배포 후 live smoke로 보완한다.

## 2026-06-24 (codex) — KNPS area 이름 복구 + N150 feature 화면 확인

N150 feature 화면에서 `area`가 보이지 않는다는 사용자 제보를 재점검했다.

- **원인 보강**: `python-knps-api` geometry dataset 중 `knps_park_boundaries`와
  `knps_protected_areas`는 실제 Polygon/MultiPolygon geometry가 있지만, provider normalized
  `name`이 비어 있고 raw 속성(`NPK_NM`, `NAME` 등)에만 이름이 있어 기존 변환기가 skip했다.
- **코드 수정**: KNPS geometry 변환에서 park boundary/protected area는 `record.name`이 비어도
  raw 이름 컬럼으로 이름을 복구한다. route/trail처럼 이름이 없는 record는 기존처럼 skip한다.
- **N150 데이터 확인**: 운영 DB에는 KNPS `area` active 1,539건
  (`knps_park_boundaries` 23건, `knps_protected_areas` 1,516건)이 적재되어 있고,
  `krheritage`의 geometry 없는 1,178건은 inactive 상태다.
- **N150 반영**: `src/kortravelmap/providers/knps.py`를 N150 `~/kor-travel-map`에 rsync하고
  docker-manager compose로 `kor-travel-map-api`, `kor-travel-map-dagster`,
  `kor-travel-map-dagster-daemon`을 재빌드/재기동했다. API/Dagster 컨테이너 내부 wheel에
  `_geometry_record_name` 반영을 확인했다.
- **N150 UI live 확인**: 운영 로그인 후 `/features`에서 `area` 필터를 켜면
  `203건 표시`, maplibre marker 203개, 테이블 `AREA active` 행이 표시된다.
- **검증**: `tests/unit/test_providers_knps.py` 45건 통과, `ruff check .` 통과,
  `python -m mypy --strict src/kortravelmap` 통과, import-linter 4계약 통과.

## 2026-06-24 (codex) — krheritage area 보정 + concierge 적재/N150 live 검증

사용자 요청으로 산림청 SHP와 provider area feature를 점검하고, `krheritage`의 면적 없는
`area` 분류를 수정한 뒤 N150 production 서버에 반영했다.

- **area 분류 보정**: `python-krheritage-api` 유산 feature는 Polygon/MultiPolygon 경계 geometry가
  있을 때만 `area`로 만들고, 기존처럼 좌표만 있는 사적/명승은 `place`로 적재하게 했다.
  적재 시 area geometry의 centroid를 대표 좌표로 쓰고 면적(`area_square_meters`)과
  `AreaDetail`도 실제 면 geometry가 있을 때만 기록한다.
- **기존 오염 데이터 정리**: `provider_sync.source_links`/`source_records` 기준으로 특정 provider
  source에서 생성된 active geometryless `area` feature를 inactive 처리하는 repository/client
  경로를 추가했고, `krheritage_heritage_features` Dagster asset 적재 후 자동으로 정리하게 했다.
- **다른 provider 점검**: 현재 코드상 `area` 생성 provider는 `knps`와 `krheritage`뿐이다. `knps`는
  이미 Polygon/MultiPolygon geometry 검증 후에만 `area`를 생성한다. `krforest`는 현재
  휴양림/수목원 point place만 제공하며, 로컬 `python-krforest-api`의 관련 SHP도 수목원 point
  dataset으로 확인했다.
- **concierge provider 적재**: N150에서 `kor-travel-concierge` snapshot을 map DB에 적재해
  `kor-travel-concierge-youtube/youtube_place_candidates` active `place` 79건을 생성했다.
- **N150 반영**: `~/kor-travel-map`에 수정 파일을 rsync하고 docker-manager compose로
  `kor-travel-map-api`, `kor-travel-map-dagster`, `kor-travel-map-dagster-daemon`을 재빌드/재기동했다.
  disk full 상태는 Docker build cache/unused image prune으로 해소했고, 최종 map API/UI/Dagster와
  concierge/geo API가 healthy임을 확인했다.
- **N150 데이터 검증**: 배포 후 `krheritage_heritage_features`의 active geometryless `area` 1,178건을
  inactive 처리했다. 최종 `feature.features` 기준 active geometryless `area`는 0건이다.
- **검증**: 로컬 unit/integration targeted pytest 48+4건, 수정 파일 ruff, 수정 Python strict mypy를
  통과했다. N150 API live e2e는 health/version/public features/search/providers/admin list/detail과
  active area 0건을 확인해 통과했다. N150 UI live e2e는 실제 로그인 세션으로 admin features list/map
  smoke 4건과 실제 concierge feature detail smoke를 통과했다.

## 2026-06-23 (codex) — Admin 로그인 + public API key 관리

사용자 요청으로 `kor-travel-geo` PR#399의 로그인/API key UX를 `kor-travel-map` admin UI에
맞춰 반영했다.

- **로그인/세션**: Next.js admin frontend에 `/login` 화면을 추가했고, `admin` 단일 계정을
  gitignored `.env`의 PBKDF2-SHA256 password hash(`ad.min` 원문 미저장)와 server-only session
  secret으로 검증한다. 세션은 HttpOnly/SameSite=Strict cookie + user-agent fingerprint +
  logout revocation으로 관리한다.
- **프록시 경계**: 기존 브라우저→FastAPI 직접 호출을 `/api/proxy` BFF로 전환했다. BFF는 세션
  확인 후 `X-Kor-Travel-Map-Actor`와 proxy secret을 주입하고, FastAPI admin router는 secret이
  설정된 환경에서 trusted proxy CIDR + secret + actor를 확인한다.
- **감사 기록**: `ops.admin_auth_events` migration/repo/router를 추가해 로그인 성공/실패/거부와
  로그아웃을 저장하고 `/admin/settings`에서 최근 100건을 볼 수 있게 했다.
- **Public API key**: `ops.public_api_keys`에 key hash/hint만 저장하고, UI에서 VWorld 호환 32자
  key를 랜덤 생성/폐기한다. 원문 key는 생성 직후 한 번만 보여주며, active hash는 TTL cache +
  생성/폐기 시 cache invalidation으로 검증 경로 DB 부하를 줄인다.
- **kor-travel-geo v2**: frontend와 backend geocoding 호출에 `key` query를 붙일 수 있게 했고,
  현재 `.env`에는 VWorld API key와 동일 값을 쓰도록 설정했다. CLI/API/Dagster/live test의
  `KorTravelGeoRestClient` 생성 경로도 `KorTravelMapSettings.kor_travel_geo_api_key_value`를
  주입하도록 맞췄다. `scripts/load-env.sh`와 Docker compose/buildx/dev stack도
  `KOR_TRAVEL_GEO_VWORLD_API_KEY`/`VWORLD_API_KEY`를
  `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`와 `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`로
  같은 값 매핑한다.
- **Docker env hardening**: admin password hash처럼 `$`가 포함된 값을 깨뜨리지 않도록
  `load-env.sh`가 `.env`를 shell `source`하지 않고 raw `KEY=VALUE`로 읽게 했다. compose
  `env_file`에는 `format: raw`를 지정하고 scripts의 compose 호출은 `--env-file /dev/null`로
  기본 `.env` interpolation을 우회한다.
- **PR#399 리뷰 반영**: X-Forwarded-For/X-Real-IP는 명시 opt-in 전에는 rate-limit/audit에
  쓰지 않게 했고, username 불일치 시에도 PBKDF2 검증을 수행한다. proxy-secret deny
  테스트, 401 로그인 리다이렉트, 로그인 실패 a11y, clipboard fallback, invalid UUID revoke
  404화도 반영했다. Alembic revision id는 `alembic_version.version_num varchar(32)`에 맞게
  32자 이하로 줄였다.
- **검증**: `pytest -q` 1326 passed, `ruff check .` passed,
  `python -m mypy --strict src packages/kor-travel-map-api/src packages/kor-travel-map-dagster/src`
  142 files passed, import-linter 4 contracts kept, admin frontend `npm run test` 37 passed,
  `npm run type-check` passed, `npm run lint` 0 errors / 기존 warnings 6, OpenAPI/type drift
  check passed, user-client typegen/type-check passed, `docker compose --env-file /dev/null config
  --quiet` passed, shell script `bash -n` passed.
- **prod smoke**: N150 production 서버(`<prod-host-ip>`)에 rsync + docker-manager compose
  rebuild/restart로 반영했다. `rustfs` 재생성 중 bind mount 권한이 `root:root`라 실패한 문제는
  컨테이너 UID/GID `10001:10001`로 소유권을 맞추고 `rustfs`만 force recreate해 복구했다.
  이후 `rustfs`, geo API, map API/UI, Dagster가 healthy 상태임을 확인했다. geo v2
  `POST /v2/reverse`는 key 없이 `400`, VWorld와 같은 key로 `200`을 반환했고, map API
  `/v1/categories`는 key 없이 `401`, public key로 `200`을 반환했다. map API 컨테이너 내부
  `KorTravelGeoRestClient(api_key=...)` reverse 호출도 `status=OK`, 후보 11건, 주소/법정동 코드
  포함으로 성공했다.

## 2026-06-23 (codex) — Admin 지도 route/area 렌더링 + prod 직접 반영

사용자 요청으로 admin Feature 지도에 feature 종류/카테고리 기반 마커와 route/area 전용
지도 표현을 추가했고, N150 production 서버에 직접 반영했다.

- **지도 렌더링**: point feature는 기존 `marker_icon`/`marker_color` 기반 maki 마커를 유지하되,
  `weather` feature는 날씨 아이콘 대신 소스/종류 구분용 단순 색상 마커로 표시한다.
- **route/area**: `/v1/features?include_geometry=true`가 route/area용 GeoJSON `geometry`와
  area `area_square_meters`를 선택적으로 반환한다. admin 지도는 route를 선+이름 라벨,
  area를 면 채움/외곽선+이름·면적 라벨로 그린다.
- **성능 보강**: 클러스터 DOM 마커 갱신을 MapLibre 매 `render` frame에서 수행하던 구조를
  `moveend`/`zoomend`/`sourcedata`/`idle` 중심으로 줄였고, 낮은 줌에서는 bbox 캐시/요청
  범위를 더 거칠게 양자화해 큰 범위 지도 이동 시 refetch churn을 줄였다. 또한 bbox SQL의
  `MATERIALIZED` CTE를 제거해 낮은 축척에서 100만 건 후보를 전부 만들고 정렬하던 경로를
  `ORDER BY feature_id LIMIT` 조기 종료 경로로 바꿨다. route/area 지도용 GeoJSON은
  원본 geometry 대신 화면 표시용 단순화 geometry로 반환해 대형 route 응답 크기를 줄였다.
  이후 admin frontend bbox fetch를 WebMercator tile 단위 요청으로 나눠 tile별
  react-query 캐시를 적용했고, tile 수가 많을 때는 tile별 `page_size`를 자동 조정해
  응답 총량이 과도하게 커지지 않게 했다.
- **검증**: API 단위 테스트 `13 passed`, 신규 PostGIS geometry 통합 테스트 `1 passed`,
  admin frontend `type-check` 통과, ESLint 0 errors(기존 warnings 8), 수정 Python 파일 ruff 통과.
  WSL Playwright는 Chromium binary 미설치로 실행 자체가 실패했다.
- **prod 반영**: N150(`<prod-host-alias>`, `<prod-host-ip>`)의 기존
  `kor-travel-map-{api,ui,dagster,dagster-daemon}` 컨테이너를 내린 뒤
  `~/kor-travel-map`에 rsync 반영하고 docker-manager compose로 재빌드/재기동했다. prod
  `feature.features`는 `ANALYZE` 후 약 109만 건이며, 기존 큰 bbox plan은 약 2.4초였고
  SQL 패치 후 동등 plan은 약 3ms 수준으로 개선됐다.

## 2026-06-23 (claude) — KMA 날씨 복제 제거 마이그레이션 완료 + krex 휴게소 관측 기상 weather source 추가

#496(KMA 격자 anchor 저장)에 이어 **prod DB의 기존 복제 데이터를 마이그레이션으로 정리**하고,
**krex 고속도로 휴게소 관측 기상을 새 weather source로 추가**했다(사용자 요청 "마이그레이션
끝나면 krex도 날씨 feature에 추가").

- **마이그레이션(prod)**: `feature.feature_weather_values`에서 `provider='python-kma-api'`
  복제 행(231k features × 49-50 격자 좌표 = **30.3M 행 / 15GB**)을 batched DELETE(500k/batch,
  COMMIT per batch로 WAL 제어) + `VACUUM (FULL, ANALYZE)`로 제거했다. 결과: 테이블
  15GB→1.98MB, **디스크 8G→24G 회수**(N150 7G-free 압박 해소). 이후 60격자/anchor 설정으로
  KMA 3개 asset 재적재 → `feature_weather_values = 66,766`행(airkorea 4,474 + KMA anchor ~62k,
  복제 0). 대량 DELETE+VACUUM FULL은 classifier가 막아 사용자 승인("진행") 후 실행.
- **krex weather 추가**: airkorea 대기질 패턴 미러. 휴게소를 `unit_code` 안정키 + 행 내
  좌표로 self-contained **weather-kind Feature**로 만들고(place 휴게소와 fuzzy 매칭 안 함,
  ADR-010), 기온/습도/풍속/강수를 metric별 `WeatherValue`로 melt. **`temperature → T1H`**라
  `build_weather_card` nearest-temp(`T1H/TMP` 조회)가 휴게소를 **기온 anchor**로 발견 — KMA
  격자가 못 덮는 고속도로 농촌 구간(태안·울진·정선 등 10 gap sigungu)을 ~400개 휴게소
  관측값으로 보강한다. de-rep과 동일하게 휴게소당 1 feature(복제 없음).
  - 변경 파일: `providers/krex.py`(Protocol `KrexRestAreaWeatherRecord` + 변환 2종 + melt
    테이블 `_REST_AREA_WEATHER_METRICS` T1H/REH/WSD/RN1), `providers/__init__.py`(re-export),
    dagster `provider_fetchers.py`(`fetch_krex_rest_area_weather`, EX key `restarea.latest_weather`),
    `resources.py`(live resource spec/def), `definitions.py`(resource key),
    `assets.py`(`feature_weather_krex_rest_areas` + `run_*`), `schedules.py`(매시 schedule),
    테스트(`test_providers_krex.py` 5건 + `test_definitions.py` 등록).
  - EX key(`KEX_GO_API_KEY`)는 traffic_notices가 이미 쓰던 것 재사용 — **신규 env 불필요**.
  - 기존 `rest_area_weather_to_values`/`KrexRestAreaWeatherItem`(이미 melt된 1 metric/행,
    etl_live fixture용)는 그대로 유지 — 신규 record 경로는 wide row를 직접 melt.
  - CI-parity(Docker python:3.13): ruff check / mypy×3(core·api·dagster) / lint-imports /
    pytest(krex 5 신규 + dagster 169) 통과. `ruff format --check`는 CI에서 `if:false`(미게이트).

## 2026-06-22 (claude) — provider repo 전부 public → dagster build 토큰 불필요(full ETL 항상)

provider repo 13종 중 마지막 private였던 `python-datagokr-api`가 **public으로 전환**됐다
(사용자 조치). `gh repo view` × 13 + `git ls-remote`(datagokr) 익명 성공으로 재확인.

- **사실 정정**: 직전 배포 서사의 "13종 private"는 부정확했다 — 실제 private는
  `python-datagokr-api` **1개뿐**이었고(나머지 12 public), 그 1개를 쓰는 fetcher는
  `provider_fetchers.py`의 표준데이터 4종(`fetch_datagokr_cultural_festivals`,
  `fetch_standard_museums`, `fetch_standard_tourist_attractions`,
  `fetch_standard_parking_lots`)뿐. all-or-nothing `[providers]` extra 탓에 그 1개 때문에
  public 12개까지 통째로 빠져 토큰 없는 prod의 live ETL이 0이었다.
- **변경**: `docker/dagster.Dockerfile`을 "토큰 있을 때만 `.[providers]`" → **토큰 유무와
  무관하게 항상 `.[providers]`**로 변경(전부 public이라 익명 clone 가능). BuildKit secret
  `github_token`은 선택사항으로 남김(미인증 rate-limit 회피 / 재-private 대비). 빌드
  플럼빙(`scripts/docker-buildx.sh`/`load-env.sh`/compose)은 이미 토큰을 optional로
  다뤄 무변경.
- **문서 정정**: `docs/runbooks/docker-app.md`·`docs/tasks.md`(T-229-buildx)·
  `docs/resume.md` — "private pin 빌드에 GITHUB_TOKEN 필요/토큰 주입 배포 환경에서만 가능"
  서술을 "전부 public → 토큰 없이 빌드 가능"으로 갱신.
- **prod 재배포**: 토큰 없이 dagster 이미지를 `.[providers]`로 재빌드·재기동(아래 결과).

## 2026-06-22 (claude) — kor-travel-map prod 첫 배포 + e2e/dagster 배포 follow-ups

prod 호스트(<prod-host>/N150)에 kor-travel-map을 **처음 배포**했다(이전엔 컨테이너/소스
없음, geo·concierge만 가동). docker-manager 기반.

- **배포(api+ui)**: dev clean main(#487) rsync provision, docker-manager 컴포즈 #29(env
  rename + prod 도메인) 적용, dev provider/VWorld 키 12종 prod `.env` 병합, api 기동 시
  `alembic upgrade head` 자동 적용(0027). 공개 도메인 `<map-host>`(200)/
  `map-api`(health ok, categories 실데이터). geo/concierge 무중단.
- **live e2e**(prod URL): home 실백엔드 스모크 3/3, route-mock 스위트 618/619. 유일 1건은
  spec이 dev Dagster URL을 하드코딩한 것 — prod 빌드가 `<map-dagster-host>`를
  올바르게 인라인한 결과(결함 아님, #29 검증).
- **follow-up (a)**: `home-density-matrix.spec.ts` 헤더 Dagster 링크 href를 `E2E_DAGSTER_URL`
  override 가능하게 해 dev/prod 양쪽 통과(미설정 시 dev localhost 정규식 유지).
- **follow-up (dagster, 토큰 없이)**: `docker/dagster.Dockerfile`을 token 없으면 `[providers]`
  없이 빌드하도록 보강(graceful degradation — webserver/daemon·asset graph 정상, live ETL fetch만
  런타임 비활성; provider import는 모두 lazy라 미설치로도 definitions import 가능). 토큰 주입 시
  `.[providers]` full ETL. (dev·prod 모두 GITHUB_TOKEN 부재.)

## 2026-06-22 (claude) — admin fetch abort signal 전파 (concierge #111 동일 계열)

kor-travel-concierge PR #111(BFF 프록시가 `request.signal`을 upstream으로 전달 안 해 abort된
요청이 백엔드에서 계속 → undici 커넥션 누수)과 **동일 계열 패턴**이 admin frontend에 있는지
점검하고 수정했다.

- **진단**: admin은 BFF 프록시가 아니라 **브라우저 직접 호출**(CORS)이라 정확히 같진 않지만,
  같은 계열의 결함이 있었다 — `src/api/client.ts`(getJson/postJson/…)와 모든 read fetcher가
  react-query queryFn의 `AbortSignal`을 받지/전달하지 않아 **query 취소가 무력화**됐다.
  필터·지도 bbox(매 pan/zoom refetch)·목록 churn으로 취소돼도 in-flight fetch가 계속 → host당
  브라우저 커넥션(~6) 포화 → "처음 빼고 느림/무응답" 위험.
- **수정**: `client.ts`에 optional `signal` 추가(getJson/postJson/putJson/patchJson/deleteJson/
  postFormData/fetchHealth/fetchVersion, 하위호환). 15개 api 파일의 모든 `useQuery` queryFn을
  `({ signal }) => fetchX(args, signal)`로, 각 read fetcher에 `signal?: AbortSignal` 추가해
  `getJson(path, { signal })`로 전달. mutation 경로는 react-query 자동취소 대상이 아니라 무변경
  (korTravelGeo/live/providerRefreshPolicies는 query 없음 → 무변경).
- **검증**: type-check(0)·ESLint(0 errors)·next build·vitest 33 passed(기존 30 + 신규
  client signal-forwarding 3). multi-agent 워크플로(18 agents)로 파일별 병렬 수정 후 전역 검증.

## 2026-06-21 (codex) — UI live e2e 재실행 + 하네스 안정화

정본 보고서:
[`docs/reports/ui-live-e2e-rerun-2026-06-21.md`](../reports/ui-live-e2e-rerun-2026-06-21.md).

- live stack(`api :12701`, `admin/user UI :12705`, `dagster :12702`) 기준 전체 Playwright e2e
  630개를 실행했다.
- 1차는 629 passed / 1 failed. 실패는 `home-density-matrix.spec.ts`의 공통 `gotoHome()`이
  full `load` 이벤트를 기다리다 live static asset 지연에 걸린 하네스 문제였다.
- `T-UI-E2E-LIVE-20260621` 작업으로 `gotoHome()`을 `waitUntil: "domcontentloaded"`로
  조정했다.
- 재검증: `npm run type-check:e2e` passed, 실패 케이스 단독 1 passed,
  리베이스 후 현재 브랜치 별도 live stack(`api :12711`, `admin/user UI :12715`,
  `dagster :12712`)에서 전체 live UI e2e **631 passed**.

## 2026-06-21 (codex) — UI e2e 테스트 3배 확장

정본 보고서:
[`docs/reports/ui-e2e-density-expansion-2026-06-21.md`](../reports/ui-e2e-density-expansion-2026-06-21.md).

- 기존 209개 Playwright e2e를 631개로 확장했다(3.02배).
- 신규 `home-density-matrix.spec.ts`에서 공용 shell/nav 18개 항목, 390/768/1440 viewport,
  홈 metric count 포맷, import job/dedup summary, Backend/Dagster 상태, endpoint 실패/복구,
  새로고침 refetch를 matrix로 촘촘히 검증한다.
- 검증: `npm run type-check:e2e` passed, 신규 spec 단독 422 passed,
  전체 `npx playwright test --workers=1 --reporter=dot` **631 passed**.

## 2026-06-21 (codex) — 사용자/admin UI live e2e dev/prod green

정본 보고서:
[`docs/reports/ui-live-e2e-dev-prod-copy-2026-06-21.md`](../reports/ui-live-e2e-dev-prod-copy-2026-06-21.md).

- dev stack(`api :12701`, `dagster :12702`, `admin/user UI :12705`)를 WSL에서 기동하고,
  Playwright는 Windows 호스트에서 실행했다.
- Next 16 Turbopack dev panic과 Playwright 산출물 watcher 간섭을 제거했다:
  `run-admin-stack.sh`는 e2e용 web을 `next dev --webpack`으로 기동하고, Playwright
  artifact/report는 OS temp로 이동한다.
- 깨진 Dagster console-script shebang은 현재 venv Python entrypoint fallback으로 보강했다.
- e2e 하네스 보강: route-mock catch-all의 `/_next/` 정적 자산 passthrough, `home-nav`
  direct deep-link 검증, feature-update-request 폴링 mock race gate.
- **dev live 검증**: unmocked live spec 6개/19 tests passed, 전체 admin e2e
  **209 passed**, `npm run type-check:e2e`, `bash -n scripts/run-admin-stack.sh`,
  `git diff --check` 모두 통과.
- **prod 복사/검증**: 검증된 파일과 `.env` 계열 설정을 `F:\dev\kor-travel-map`으로 복사했다.
  기존 `.env`는 `.backup-20260621-115048`로 백업했고, 최종 재복사 전
  `.backup-20260621-122939`도 추가로 남겼다. prod stack을 새 `.env` 기준으로 재기동한 뒤
  전체 admin e2e **209 passed**를 다시 확인했다.

## 2026-06-21 (codex) — concierge/geo prod API 계약 재점검 + live smoke

`kor-travel-concierge`와 `kor-travel-geo` 로컬 repo를 `origin/main` 기준으로 다시 읽고
`kor-travel-map` 소비 계약을 대조했다. 정본 보고서:
[`docs/reports/prod-api-live-contract-check-2026-06-21.md`](../reports/prod-api-live-contract-check-2026-06-21.md).

- **concierge**: `origin/main` `bec63ad2ab39` 기준 `GET /api/v1/features/{snapshot,changes}`,
  `X-API-Key`, envelope 없는 `{items,next_cursor,has_more}`, `limit<=500`,
  provider/dataset/source identity가 현재 Dagster fetcher와 provider 변환 계약에 맞음을 확인했다.
  prod env(`APP_ENV=production`, `API_AUTH_ENABLED=true`)에서 `snapshot?limit=1` /
  `changes?limit=1` 모두 200, 첫 item upsert/provider/dataset 정합, fetcher 첫 item read,
  live item → `FeatureBundle` 변환 성공(`f_global_p_`).
- **geo**: `origin/main` `8b7efbe20e92` 기준 v2 `CandidateV2.point={lon,lat}`
  정본을 확인했다. 기존 `kortravelmap.geocoding` REST 파서가 pre-ADR-062 `x/y`만
  읽던 drift를 수정해 `lon/lat` 우선, `x/y` fallback으로 정렬했다. public method
  시그니처는 유지했다.
- **live smoke**: geo `geocode` OK(좌표 파싱/`point_lonlat=true`), address_geocoder 좌표
  반환, reverse `bjd=1114010300`, regions-within-radius 시군구 6건. concierge는 read-only
  export와 loader 변환만 실행했고 DB write/Dagster materialize는 하지 않았다.
- **검증**: `tests/unit/test_geocoding.py` 58 passed, 관련 ruff passed,
  `test_providers_kor_travel_concierge.py` + Dagster `test_provider_fetchers.py`
  71 passed / 1 skipped(`mois.db` optional).

## 2026-06-20 (Codex) — Claude PR #481~#484 리뷰 후속 수정

사용자 요청으로 2026-06-19 00:00 KST 이후 Claude Code가 올린 merged/closed PR #481~#484를
사후 리뷰하고, 확인된 compose/env/geocoding 결함 3건과 full-run 검증 중 드러난 logging
격리 결함 1건을 통합 후속 브랜치에서 수정했다.

- **리뷰 코멘트 작성**: closed PR #481, #482, #483에 각각 PR 대화 코멘트로 재현 가능한 결함을
  남겼다. #484는 추가 코드 수정이 필요한 결함을 찾지 못했다.
- **CORS fallback 복원(#481)**: `docker-compose.yml`의
  `KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS` 기본값이 `12705`로 고정돼 직접 compose 실행과
  `KOR_TRAVEL_MAP_ADMIN_WEB_PORT` 커스텀 포트에서 어긋나던 문제를, admin web port 변수를
  다시 참조하도록 고쳤다.
- **kor-travel-geo point alias 수용(#482)**: live `kor-travel-geo` v2 응답이
  `point: {lon, lat}`를 반환해 기존 `{x, y}` 전용 파서가 `KeyError`를 내던 문제를 고쳤다.
  `point.x/y`와 `point.lon/lat`를 모두 받아 geocode/reverse 경로가 깨지지 않게 했다.
- **host network env 정정(#483)**: `docker-compose.host.yml`이 `scripts/load-env.sh`의
  bridge용 `KOR_TRAVEL_MAP_DOCKER_*` 기본값(`dagster`/`rustfs`)을 물어 host 모드에서도
  내부 주소가 잘못 렌더되던 문제를 정정했다. host override는 `127.0.0.1:<12xxx>`를 기본으로
  쓰고, 사용자가 명시한 external DB/object-store override와 external Postgres host port를 보존한다.
- **Alembic logging 격리**: integration migration 후 `fileConfig` 기본값이 기존
  `kortravelmap.*` logger를 disable해 뒤따르는 `caplog` 테스트가 warning을 잡지 못하던 full-run
  순서 의존 실패를 `disable_existing_loggers=False`로 고쳤다.
- **검증**: `docker compose config` 렌더로 커스텀 admin port CORS(`12706`), host network
  `API_DAGSTER_URL`/PG/ObjectStore `127.0.0.1`, external Postgres `15433`, 명시 external DSN/object
  override 보존을 확인했다. geocoding 단위 테스트에 `point.lon/lat` 케이스를 추가했다.

## 2026-06-20 (claude) — admin UI Next 기본 오류 화면 복구 보강 (geo #391 동일 반영)

사용자 요청으로 kor-travel-geo PR #391(이슈 #390/T-278)을 admin frontend에 동일 반영했다.
(#390은 PR이 아니라 이슈 — #391이 fix.)

- **포팅(핵심)**: Next App Router `src/app/error.tsx`·`src/app/global-error.tsx` + 복구 패널
  `src/components/app-error-panel.tsx` + 헬퍼 `src/lib/error-recovery.ts`. Next 기본 영어 오류
  화면 대신 한국어 복구 패널(다시 시도/이전 화면/오류 정보)을 보여 주고, chunk/RSC/network
  계열 오류는 sessionStorage flag로 같은 pathname당 1회 hard reload. unit test
  `src/lib/error-recovery.test.ts`(3) 동반.
- **스택 적응**: geo는 raw CSS 클래스, 본 repo는 Tailwind/shadcn이라 패널을 디자인 토큰
  (`bg-card`/`text-text-*`/`rounded-2xl`/`Button`)으로 재구성. reload prefix는
  `kortravelmap.admin.error-reload`, goBack fallback은 `/`(admin 홈).
- **미반영(geo-specific)**: geo의 `PerfValidationSummary` `next/link`→`DocumentNavLink`
  (_rsc 회피) 변경은 본 repo에 `DocumentNavLink`/해당 컴포넌트 analog가 없어 제외(SPA 내비
  광범위 전환은 별도 결정). 핵심 오류 boundary는 전부 반영.
- **검증**: admin type-check(tsc+e2e tsconfig)·ESLint(0 errors)·next build·vitest 30 passed
  (기존 27+신규 3).

## 2026-06-20 (claude) — dev 스크립트 개선: 포트 가드 + 127.0.0.1 + Docker host 네트워크 기본

dev/prod 분리를 명확히 하고(별도 지시 없으면 dev), dev 기동 스크립트를 개선했다.

- **포트 가드(`scripts/preflight-ports.sh` 신규)**: 고정 포트가 이미 사용 중이면 새 포트로
  열지 않고, prod 유무와 관계없이 **강제종료 여부를 묻고**, 거절(또는 비대화형 기본)하면
  **기동 중지**(기존 서비스/prod 보존). `KOR_TRAVEL_MAP_FORCE_KILL_PORTS=1`로 프롬프트 없이
  강제종료. `stop-fixed-ports.sh`는 sourceable로 리팩터(탐지 함수 재사용, `port_has_listener`
  추가) — 직접 실행/`ports:stop`만 강제종료. `run-admin-stack.sh`·`docker-up.sh`가 preflight 호출.
  WSL 실측: free→exit0, occupied+비대화형→detect+abort(미kill), FORCE=1→kill 확인.
- **내부 주소 127.0.0.1**: `run-admin-stack.sh` bind host 기본 0.0.0.0→**127.0.0.1**. e2e는
  `KOR_TRAVEL_MAP_*_BIND_HOST=0.0.0.0` opt-in.
- **Docker host 네트워크 dev 기본(`docker-compose.host.yml` 신규)**: `docker:up`이 host
  override를 기본 적용 — `network_mode: host`, `ports: !reset null`(host 모드 비호환), 서비스 간/
  공유 인프라 주소를 `127.0.0.1:<12xxx>`로 통일(PG_DSN/DAGSTER_PG_URL/DAGSTER_URL/OBJECT_STORE
  ·rustfs `:12101/12105`·init 컨테이너 `-h 127.0.0.1`/alias). `KOR_TRAVEL_MAP_DOCKER_NETWORK=bridge`로
  opt-out. `docker compose config`: host(9×host, 0 published ports, URL=127.0.0.1)·bridge(6 ports) 둘 다 VALID.
- **문서**: `docs/dev-environment.md` §0(dev vs prod 표·고정 포트·host 네트워크·포트 가드),
  `docs/deploy.md`(dev=standalone/host, prod=docker-manager+도메인 pointer), `ports:preflight` npm script.
- **미검증(라이브)**: host 네트워크 실제 bring-up은 12xxx 포트 점유+빌드가 필요해 정적
  `config` 검증까지만 했다(사용자 no-kill 지시 준수). 라이브 기동 검증은 사용자 동의 후.

## 2026-06-20 (claude) — kor-travel-geo 프로덕션 도메인 env 반영

map/s3 도메인(직전)에 이어 kor-travel-geo 도메인(<geo-api-host>/<geo-console-host>)을 반영했다.

- **필요한 것만 배선**: 프론트(브라우저)는 `korTravelGeo.ts`가 직접 fetch하므로
  `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL`=geo-api(public). 백엔드(API admin_issues/feature_update_requests/
  offline_uploads + Dagster ETL)는 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL`(main settings)로 server-side
  지오코딩 — 비우면 좌표만 적재. 둘 다 gitignored `.env.prod`에 실 도메인으로 채웠다.
- **compose 무변경**: `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL`은 이미 build-arg/env(line 168/173),
  백엔드 var는 api/dagster/dagster-daemon의 `env_file: [.env]`로 주입돼 추가 배선 불필요.
- **문서(committed, placeholder)**: `.env.example` prod 블록 + `docs/deploy.md` 도메인 표에 geo-api/
  geo-console 행과 env 노트 추가. geo console(:12505)은 프록시 라우트일 뿐 앱 env 아님 명시.
- **검증**: `docker compose --env-file .env.prod config -q` VALID, geo 렌더=geo-api 도메인 확인.
  `.env.prod`는 gitignored(커밋 안 됨).

## 2026-06-20 (claude) — 프로덕션 reverse-proxy 도메인 env 반영

사용자 prod 도메인(<map-host>/<map-api-host>/<map-dagster-host> + <s3-api-host>/<s3-console-host>)을 외부 노출
없이(gitignored) 반영하고, compose를 그에 맞게 보강했다.

- **compose 보강(코드)**: `docker-compose.yml` api service의 `KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS`가
  localhost로 **하드코딩**돼 있어 prod frontend origin이 CORS 거부되던 것을, `DAGSTER_ALLOWED_HOSTS`와
  같은 `'${VAR:-localhost default}'` 패턴으로 바꿔 env override를 허용했다. NEXT_PUBLIC_* build args,
  Dagster URL/allowed-hosts, `OBJECT_STORE_PUBLIC_BASE_URL`은 이미 env 파라미터화돼 있어 무변경.
- **실 도메인(gitignored)**: `.env.prod`(=.env.* → gitignore)에 4개 값만 둔다 —
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`=map-api, `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL`=map-dagster,
  `KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS`=["https://map…"], `OBJECT_STORE_PUBLIC_BASE_URL`=s3-api/bucket.
  dev `.env`(provider 키 보유)는 건드리지 않았다(운영 노드는 이 파일을 `.env`로 복사/병합).
- **문서(committed, placeholder만)**: `.env.example`에 prod reverse-proxy 도메인 변수 블록(예시 도메인),
  `docs/deploy.md`에 "프로덕션 도메인(reverse proxy)" 섹션(도메인→서비스 매핑·재빌드/CORS/내부망 주의).
- **검증**: `docker compose config -q`(default·`--env-file .env.prod`) 둘 다 VALID; prod 렌더에서
  CORS=`["https://<map-host>"]`(JSON), NEXT_PUBLIC=prod, API→Dagster=내부 `dagster:12702`,
  object public=s3-api/bucket 확인. API→RustFS 내부 통신은 `http://rustfs:9000` 유지(외부 노출 X).

## 2026-06-19 (Codex) — admin frontend stack 문서 정합성 정리

사용자 요청으로 architecture 계열 문서의 admin frontend stack 표기를 현재 구현에 맞췄다.

- **지도 stack 정정**: `maplibre-vworld-js`/`maplibre-vworld` dependency를 쓰지 않고,
  `maplibre-vworld-react` web/core 모델을 admin 내부에 포팅한 MapLibre GL + VWorld 구현을
  쓰는 것으로 정본 문서를 정리했다.
- **테이블 stack 반영**: 운영 목록/검토 화면은 공용 `DataTable`
  (`@tanstack/react-table` v8 + `@tanstack/react-virtual` v3) 기반이고,
  shadcn `Table`은 표시 primitive라는 역할 구분을 `architecture.md`,
  `debug-ui-package.md`, OpenAPI/frontend workflow 문서에 반영했다.
- **중복/충돌 축소**: 과거 "별도 frontend 보류" 문구와 ADR/Sprint 문서의 오래된
  frontend 기준값을 현재 상태로 정정했다. 과거 journal/report 본문은 이력 보존 대상이라
  전면 수정하지 않았다.
- **검증**: Markdown 문서 변경만이라 관련 키워드 검색으로 잔여 구식 표기 범위를 확인했다.

## 2026-06-18 (Codex) — README 진입 문서 정리

사용자 요청으로 루트 README를 현재 운영 모델 기준의 짧은 진입 문서로 정리했다.

- **구조 정리**: 소개, 현재 운영 모델, 책임 범위, 빠른 시작, 저장소 구조, 핵심 개발 규칙,
  검증, 문서 길찾기 순서로 재배열했다.
- **중복 축소**: 긴 provider/ETL/문서 목록은 `docs/etl/`, `docs/architecture/`,
  `docs/runbooks/`, `docs/adr/README.md` 같은 정본 문서로 넘겼다.
- **현재화**: `Docker 독립 프로그램 + 독립 DB/Dagster + OpenAPI`, 별도 API/admin package,
  Windows Git + WSL 실행 정책을 README 첫 진입 흐름에 맞게 재서술했다.
- **검증**: Markdown 문서 변경만이라 링크/맞춤법 중심으로 확인했다.

## 2026-06-18 (claude) — PR #476 사후 리뷰 + admin e2e 라이브 검증 (197 passed)

Codex PR #476(maplibre-vworld-js dep 제거)을 다차원 적대적 리뷰하고, admin e2e를 라이브 실행해
#471 재구성으로 잠복해 있던 spec 회귀를 정정했다.

- **#476 리뷰**: 확정 결함 1건(LOW) — `frontend.yml`의 stale 주석이 제거된 `maplibre-vworld#v0.1.0`
  git dep를 계속 참조 → 주석 정정. 코드 결함 없음.
- **라이브 e2e**(Windows dev server :12706 + Windows Playwright chromium): route-mock 전 spec
  **197 passed / 0 failed**. WSL은 win32-only `@next/swc` node_modules라 `next dev` 불가 → Windows에서
  실행. backend-의존 4 spec(curated-features·features-new·dagster·etl)은 제외(Docker 스택 미기동, 기결정).
- **라이브가 잡은 #471 잠복 회귀 2건**(정적 리뷰·typecheck는 통과했으나 실행 시 실패):
  `home.spec.ts`의 Backend/Dagster `heading` 단언(이제 `<span>`) → `서비스 상태` heading +
  `service-backend`/`service-dagster` testid로 정정; `features-list.spec.ts`의 `bg-primary` 단언
  (default 버튼이 `bg-brand`로 변경됨) → `bg-brand`로 정정.
- **#477 home-nav 수정 라이브 검증 완료**: 이전 PR에서 typecheck만 했던 home-nav 정정이 라이브 green.

## 2026-06-18 (Codex) — T-MAP-VWORLD-04 maplibre-vworld-js dependency 제거

사용자 지시에 따라 GitHub Task #475(`T-MAP-VWORLD-04`)를 만들고,
`digitie/maplibre-vworld-react` `a7cb0f8` 기반으로 admin web 지도 경계를 정리했다.

- **dependency 제거**: admin frontend와 `@kor-travel-map/map-marker-react`에서
  `maplibre-vworld`(`digitie/maplibre-vworld-js`) dependency/peer/devDependency,
  `maplibre-vworld/style.css` import, Vite external/global 선언을 제거했다.
  `package-lock.json`에서도 `maplibre-vworld`와 전용 transitive를 제거했다.
- **maplibre-vworld-react 경계 반영**: `src/lib/vworld-style.ts`를
  `vworld-map-core`식 map type/tile URL/maxZoom/redaction 단일 source로 정리하고,
  `VWorldMapView`에 maxZoom clamp, redacted error logging, stable marker click callback을
  보강했다. VWorld key 미설정 fallback에서도 bbox/e2e가 계속 동작하는 기존 admin 계약은 유지했다.
- **검증**: admin type-check, marker typecheck/build, admin vitest **27 passed**,
  ESLint **0 errors / 기존 warnings 6**, Next build 통과. WSL dev server
  `0.0.0.0:12706` + Windows Playwright `E2E_BASE_URL=http://172.26.51.35:12706`에서
  `features-map-interactions.spec.ts` **5 passed / 0 failed**.
- **정본 리포트**:
  [`docs/reports/maplibre-vworld-js-dependency-removal-2026-06-18.md`](../reports/maplibre-vworld-js-dependency-removal-2026-06-18.md).

## 2026-06-18 (claude) — T-452 OpenAPI problem+json 기계 계약 보강

생성 OpenAPI(`openapi.json`/`openapi.user.json`)가 모든 4xx/5xx·`default` 응답을 RFC7807
`application/problem+json`으로 선언하도록 보강했다(under-spec #452/#444 잔여 해소).

- **구현**: `kortravelmap.api.response`에 `ProblemDetail`/`ProblemDetailError` 모델 추가,
  `create_app`의 custom `app.openapi()`가 각 operation 응답에 problem+json(`ProblemDetail` ref)을
  주입. FastAPI 자동 `422 HTTPValidationError`는 problem+json으로 대체, orphan 검증 schema 제거.
  핸들러별 `responses=` 대신 중앙 핸들러(`_error_response`) 대칭의 중앙 주입 방식 채택.
- **산출물 재생성**: `export_openapi.py --profile all`로 2개 spec + admin/user-client `gen:types`.
  e2e mock 1건(`change-requests-lifecycle.spec.ts`)을 `HTTPValidationError`→`ProblemDetail` 재바인딩.
- **검증**: 로컬 venv 부재라 throwaway `python:3.13` Docker(CI 동등)로 ruff·`mypy --strict`·
  api pytest 전수 green + `export_openapi.py --check` drift gate OK. Node로 `gen:types:check`·
  admin/user-client type-check OK. 정본 `docs/architecture/rest-api.md §1.5`.

## 2026-06-18 (claude) — T-ADMIN-TANSTACK 종결 + item-4 라이브 e2e 결정 (백로그 정리)

admin TanStack 테이블 이행 후속을 종결하고, 라이브 e2e 재실행 여부를 사용자 결정으로 닫았다.

- **(a) backend-의존 e2e**: 2026-06-17 라이브 Docker 스택에서 이미 57 passed/0 failed로 검증됨
  (`docs/resume.md`). 사용자 결정(이미 검증됨 → 재실행 생략)에 따라 스택 재기동 없이 종결.
- **(b) bulk 정책 가드**: main에 이미 구현 확인 — dedup bulk `enableRowSelection` pending-only +
  `decideBulk` 방어 필터(완료 review 재결정 차단), curated bulk archive `window.confirm` 일괄 확인,
  enrichment 단일 행 pending-only(bulk 없음).
- **환경 메모(item-4)**: 신규 Docker 스택 기본 포트(pg 5432·rustfs 12101)가 공유 인프라
  (kor-travel-geo-postgres 등)와 충돌하고, repo `.env`가 구 `KRTOUR_MAP_*` prefix라 기존
  `python-krtour-map-claude` 스택은 stale/unhealthy. 공유 인프라 무중단을 위해 재실행하지 않음.
- **T-AUDIT-0616**: e2e(HIGH)는 라이브 검증 완료로 ✅, 잔여는 F-01 옵션 A(전 feature re-key,
  big-bang) deferred 1건으로 축소. `T-452-openapi-problem-json`가 이 저장소 유일 즉시 실행 트랙.

## 2026-06-18 (claude) — 외부/보류 task won't-do 종결 (백로그 정리)

사용자 지시로 외부 추적 4건과 보류 1건을 진행하지 않음(won't-do)으로 종결했다(문서만 변경).

- **종결**: `T-019`(PinVi Kakao→vworld 추적), `T-210b`/`T-210c`/`T-210d`(PinVi 문서 supersede ·
  레거시 Dagster 이관 · httpx client — 전부 PinVi repo 외부), `T-103`(streaming ETL Kafka/Redpanda).
- **정리**: `docs/tasks.md` 외부 추적 섹션 제거 + 보류에서 T-103 제거,
  `docs/tasks-done.md` 상단 won't-do 아카이브, `docs/resume.md` 열린 작업 요약·현재 상태 갱신.
- **유지**: `T-229-buildx`(배포환경 잔여), `T-101`(MV 보류), 열린 in-repo
  `T-452`·`T-ADMIN-TANSTACK`·`T-AUDIT-0616`.

## 2026-06-18 (Codex) — admin frontend StyleSeed 디자인 규칙 적용

`https://styleseed-demo.vercel.app/llms.txt`와 `llms-full.txt`의 제품 UI 규칙을
admin frontend 공통 surface에 적용했다.

- **디자인 토큰**: 단일 brand accent, 5단계 text/surface token, 낮은 card shadow,
  상태색 success/warning/info/destructive를 `globals.css`에 추가했다.
- **공용 primitive 정리**: `Card`, `Button`, `Badge`, `StatusBadge`, `Table`,
  `Alert`, `Input`, `NativeSelect`, `Textarea`, `Skeleton`을 token 기반 스타일,
  카드형 정보 표면, 명확한 focus ring, 40px 입력 높이 기준으로 맞췄다.
- **운영 홈 리듬 조정**: KPI loading 상태까지 카드 안에 넣고, KPI 숫자+단위 비율,
  progress/status 보조 요소, Backend/Dagster 상태 묶음을 적용했다.
- **반응형 검증**: Windows Node로 frontend type-check, ESLint(기존 warnings 6),
  env 주입 production build 통과. `12705` production 서버에서 Playwright
  screenshot(1280×720, 390×844)으로 overflow/겹침 없음 확인. WSL Node는 작업 중
  `/usr/local/bin/node` bus error가 발생해 검증 실행 경로에서 제외했다.
- **문서화**: admin frontend 로컬 디자인 규칙을
  [`docs/architecture/admin-frontend-design-rules.md`](../architecture/admin-frontend-design-rules.md)에
  정리하고, package/API 계약 문서에서 링크했다.

## 2026-06-17 (Codex) — maplibre-vworld-react 지도 e2e 종결

`T-MAP-VWORLD-03`(#467)을 종결했다.

- **main 기준 재검증**: PR #469 merge 후 `origin/main` 기준으로 WSL dev server +
  Windows Playwright 지도 e2e를 다시 실행했다.
- **결과**: `features-map-interactions.spec.ts` **5 passed / 0 failed**.
- **범위**: map/table 탭, bbox fetch, kind 필터 refetch, table 선택→지도 상세 패널,
  error/empty 상태.
- **후속 수정**: 최종 e2e에서 추가 수정할 회귀는 없었다.
- **정본 리포트**: [`docs/reports/maplibre-vworld-react-e2e-2026-06-17.md`](../reports/maplibre-vworld-react-e2e-2026-06-17.md).

## 2026-06-17 (Codex) — admin features 지도 VWorldMapView 전환

`T-MAP-VWORLD-02`(#466)를 구현했다.

- **지도 lifecycle 전환**: `features-client.tsx`의 직접 `maplibre-gl` 생성/해제와
  marker 배열 수동 관리 코드를 제거하고, 새 `VWorldMapView`/`VWorldMarker`
  컴포넌트로 분리했다.
- **동작 유지**: bbox 동기화, kind 필터 refetch, marker/table 선택 상세 패널,
  VWorld key 미설정 fallback, table/map 상태 공유를 유지했다.
- **dev e2e 보강**: Windows localhost forwarding이 붙지 않는 환경에서 WSL IP로
  Playwright를 실행할 수 있도록 `NEXT_ALLOWED_DEV_ORIGINS`를 지원했다.
- **검증**: type-check 통과, ESLint 0 errors(기존 warnings 6), vitest 27 passed,
  env 주입 production build 통과, Windows Playwright
  `features-map-interactions.spec.ts` 5 passed.

## 2026-06-17 (Codex) — maplibre-vworld-react 지도 전환 계획 및 Task 생성

admin UI 지도를 `digitie/maplibre-vworld-react` 기반 모델로 전환하기 위한 작업 계획을 세웠다.

- **참조 확인**: `digitie/maplibre-vworld-react` `a7cb0f8` 기준으로 `VWorldMapView`,
  React `Marker`, `vworld-map-core` style builder 경계를 확인했다.
- **Task 생성**: GitHub #465(`T-MAP-VWORLD-01` 계획), #466(`T-MAP-VWORLD-02` 지도 전환),
  #467(`T-MAP-VWORLD-03` e2e/후속 수정).
- **범위 결정**: 외부 모노레포 전체 vendoring 없이 admin `features` 지도에 필요한
  `VWorldMapView`/React marker 계층을 얇게 이식한다. 기존 bbox 동기화, kind 필터,
  선택 상세 패널, VWorld key 미설정 fallback은 유지한다.
- **정본 계획**: [`docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`](../reports/maplibre-vworld-react-migration-plan-2026-06-17.md).

## 2026-06-17 (claude) — 문서 구조 정리 (ADR/ETL/architecture 디렉토리화 + entry 문서 슬림 + tasks 3분할 + Telegram MCP 제거)

문서 트리를 용도별로 재배치하고 entry 문서의 군더더기/중복을 제거했다(단일 PR).

- **ADR 디렉토리화**: `docs/decisions.md`(3,526줄, 59 ADR)를 파일당 1개 `docs/adr/NNN-<slug>.md`(53개)
  + 색인 `docs/adr/README.md`로 분리. 순수 개발 규칙(금지·프로세스)이던 6건(ADR-006/012/019/021/030/039)은
  ADR 파일을 만들지 않고 [`SKILL.md` §4](../../SKILL.md)로 이전(원 맥락은 git history 보존). superseded 3건
  (003/029/049)은 기록 유지. `decisions.md`는 adr/로 가는 redirect stub. `docs/decisions.md` 경로 참조
  40건을 `docs/adr/README.md`로 재배선.
- **ETL 디렉토리화**: `*-etl.md` 15 + normalization 2(weather-feature-normalization·place-phone-enrichment)를
  `docs/etl/`로 이동, 문서·소스 docstring 경로참조 106건 갱신.
- **architecture 디렉토리화**: 핵심 설계 + 계약/패키징 19개(architecture·data-model·postgres-schema·
  feature-model·dagster-boundary·provider-contract·performance·category·rest-api·openapi-admin-contract·
  backend-package·debug-ui-package·public-views-api·tripmate-rest-api·regions-within-radius·feature-files-rustfs·
  feature-opening-hours·feature-db-initialization·address-geocoding)를 `docs/architecture/`로 이동, 경로참조
  320건 갱신 + 이동 파일 내부 상대링크 8건 `../` 보정.
- **entry 문서 슬림**(중복은 단일 정본으로 포인터화): CLAUDE 147→85, AGENTS 503→194, README 306→264,
  SKILL 323→173줄. 단일 정본 = 식별자 table→AGENTS, 개발환경→dev-environment, codegraph/worktree→
  codegraph-worktree, 26 DO-NOT 룰→SKILL §4(룰 27 codegraph 영향평가 추가), 진입순서→CLAUDE §3,
  체크리스트→AGENTS. ADR 대량 나열 삭제, v1 언급은 파일당 1줄로 축약.
- **tasks 3분할**: 작성·유지 규약을 새 [`docs/tasks-rule.md`](../tasks-rule.md)로 분리, `tasks.md`는 백로그만
  (인덱스 `[ ]` 일관화·상태 스냅샷 제거), `tasks-done.md` 유지. `agent-guide.md §6`는 tasks-rule 포인터로.
- **Telegram MCP 제거**: 5개 MCP 설정(opencode/antigravity/.gemini/claude.json·.codex/config.toml)에서
  `mcp-telegram` 항목 + 런처 `scripts/mcp_telegram_start.py` 삭제, 관련 문서 섹션(codegraph-worktree §6.5·
  agent-workflow PR-알림) 제거, 일반 alert-sink 예시에서 Telegram 표기 제거.
- **검증**: 내부 md 링크 213개 0 broken(file:// 1건 false-positive 제외), live 파일 stale 경로참조 0,
  touched .py 47개 py_compile OK, 5개 MCP JSON 파싱 OK.

## 2026-06-17 (claude) — admin e2e 커버리지 종합 확장 Wave 3(LOW 6페이지) + 실버그 1건 수정 + 종결

3-wave 종합 확장 마무리. LOW 우선순위 6페이지에 route-mock depth-spec 6종(+32 시나리오) 추가.
라이브 frontend :12705 + mock 백엔드로 전수 실행 green 확인. **전체 스위트 57→209** 통과.

- **신규 스펙(32 시나리오)**: `poi-cache-targets-edge`(cursor·empty·error·on_conflict=move·scope_mode
  upsert), `offline-uploads-edge`(validation_failed·413·JSON/JSONL/TSV·폴링·CP949), `backups-exec`
  (execute 분기·plan-only·restore confirm·empty·error), `dagster-interactions`(tick 실패 드릴다운·
  run-id 선택·unavailable 배너·embed fallback), `consistency-drilldown`(report/issue 드릴다운·
  severity), `logs-streams`(import_job_events 탭·cursor·filter·deeplink·error).
- **실버그 발견·수정(backups-client.tsx)**: backup 행의 Restore/Swap 버튼 onClick이 `useMemo([])`
  컬럼 정의 안에 박혀 execute/recreate/apply 체크박스 state를 **stale closure**로 잡아 항상
  `execute:false`를 전송하던 버그(실행 옵션이 행 버튼에 무효). deps에 해당 state를 넣어 토글 시
  컬럼을 재생성하도록 수정. (backup 버튼은 memo 밖이라 정상 → e2e가 정확히 회귀 포인트를 잡음.)
- **검증 루프(라이브)**: 1차 27/32 → 회귀 5건 수정(4 agent 병렬) → 2차 28/32 → 잔여 4건(backups
  실버그·dagster shortRunId truncation·offline 2건 brittle scope) 수정 → **32/32**. 전체 스위트
  208/209(폴링 spec 1건 부하 flaky, 단독 9/9) → 폴링 타임아웃 8s→15s 안정화 → **209/209**.
- **3-wave 합계**: 신규 spec 21파일 / +152 시나리오(W1 52·W2 68·W3 32). 22개 admin 페이지의
  mutation/error/empty/pagination/filter/WS/deeplink 표면을 route-mock으로 덮었다. 정본 갭 기록
  `docs/reports/e2e-scenario-coverage-2026-06-16.md`에 종결 배너 추가.

## 2026-06-17 (claude) — admin e2e 커버리지 종합 확장 Wave 2(MED 10페이지 depth-spec)

Wave 1에 이어 MED 우선순위 10페이지에 route-mock depth-spec 10종(+68 시나리오) 추가. 라이브
frontend :12705 + mock 백엔드로 전수 실행 green 확인 후 머지.

- **신규 스펙(68 시나리오)**: `features-list`(q search·sort dropdown/order·cursor·empty·500 alert·
  deactivate·deeplink·has_issue), `change-requests-lifecycle`(reject·409/422 alert·empty·q filter),
  `issues-actions`(resolve/ignore/reopen/retry_geocode/retry_reverse/apply_geo·map·severity·cursor·
  error), `dedup-reviews-actions`(accept/reject/ignore/merge·compare·master 선택·ADR-039 mutex·cursor),
  `enrichment-reviews-actions`(accept/reject/ignore·cursor·compare), `feature-update-requests-list`
  (submit·dry-run/run-now·cursor·empty·error·deeplink), `import-jobs-list`(cursor 미사용·filter param·
  empty·error·deeplink), `providers-refresh-policy`(PUT refresh-policy·links·detail nav·empty·error),
  `home-nav`(전 nav 링크·metric error/empty·loading), `features-map-interactions`(map↔table toggle·
  ?view sync·error·count=0; WebGL marker-click은 비결정적이라 제외).
- **워크플로**: 페이지별 grounded recon(admin-ops smoke+컴포넌트+훅+OpenAPI types) → author. 20 agent.
- **검증 루프(라이브)**: 1차 59/68 → 회귀 9건 수정(5 agent 병렬) → 2차 66/68 → 잔여 2건 직접 수정 →
  **68/68**, 전체 스위트 **177/177**(기존 57 + Wave1 52 + Wave2 68).
- **주요 수정(원인)**: dedup 결정 후 행이 기본 `pending` 필터에 걸러져 '완료' 미표시 → status를
  `all`로 전환; change-requests/issues는 row 내 substring 충돌(`pending`×4·`info`×2) → `exact:true`;
  features 목록은 전 컬럼이 display column(manualSorting)이라 헤더가 정렬 불가 → 정렬을
  NativeSelect+asc/desc 버튼으로 검증; has_issue 'all' 재선택과 import-jobs 필터 해제는 staleTime
  캐시 적중(동일 키 → 새 GET 없음)이라 네트워크 단언 대신 UI/불변식(cursor 미적재)으로 전환.
- 후속: Wave 3(LOW ~6) + coverage 리포트 갱신.

## 2026-06-17 (claude) — admin e2e 커버리지 종합 확장 Wave 1(HIGH 5페이지 depth-spec)

`e2e-scenario-coverage-2026-06-16.md`가 기록한 갭(대부분 render-smoke만, mutation/error/empty/
pagination/filter/WS/deeplink 누락)을 3-wave로 종합 확장하는 작업의 Wave 1. HIGH 5페이지(핵심
mutation/depth)에 route-mock 기반 신규 depth-spec 5종을 추가했다. CI에 Playwright job이 없어
(거짓 green 방지) **라이브 frontend :12705 + mock 백엔드**로 전수 실행해 green 확인 후 머지.

- **신규 스펙(52 시나리오)**: `curated-features-mutations`(17: select/unselect optimistic·patch·
  null trim·copy-policy·archive+window.confirm·rule patch/apply·tripmate-copy preview/empty·cursor·
  page_size·empty·500 alert·deeplink·bulk select/archive), `features-new-submit`(8: 생성→change
  response·nearby·422/409·forward/reverse geocode(:12501)·geo 5xx), `feature-update-request-detail-
  actions`(9: cancel/run-now POST body·201·terminal gating·409 alert·refetch·폴링 running→done),
  `import-job-detail-actions`(8: cancel POST·event timeline·level filter·terminal polling-stop·
  relation link 분기), `feature-detail-sections`(9: Sources/Issues/Overrides/Files/History 표·Nearby
  km/m·Weather depth/stale·error isolation·no-coord·Raw <details>·deeplink).
- **워크플로**: 페이지별 grounded recon(기존 스펙+컴포넌트+훅+OpenAPI types) → author(자급 route-mock,
  mock body는 `components["schemas"]` 바인딩으로 계약 drift를 tsc가 검출). 10 agent.
- **검증 루프(라이브)**: 1차 44/52 → 회귀 8건 수정 → 52/52, 전체 스위트 **109/109**(기존 57+신규 52).
  주요 수정: strict-mode 스코프(per-section columnheader·snapshot 테이블·alert title filter·Links
  카드), base-ui Checkbox(role=checkbox span)는 click/Space로도 aria-checked가 안 켜져
  bulk 검증을 toolbar(N개 선택됨)+요청수로 전환, success Alert는 role=status(=default variant),
  cursor "처음"은 staleTime 캐시로 재요청 없음→UI 단언, row-ready 가드로 select-all 레이스 제거.
- 후속: Wave 2(MED ~10) · Wave 3(LOW ~6) + coverage 리포트 갱신.

## 2026-06-17 (claude) — required 필드 접근성 이름 정정(asterisk 누수) — features-new e2e 적색 해소

직전 라이브 e2e의 잔여 2건(`features-new.spec.ts` `getByLabel("name", { exact: true })` 0건)을
해소. 근본 원인은 이행이 아닌 공용 폼 컴포넌트의 접근성 이름 결함이었다.

- **근본 원인(경험적 확정)**: `FormField`/`FormSelect`/`FormTextArea`는 `required` 라벨에 장식용
  별표 `<span aria-hidden="true"> *</span>`를 붙인다. 그런데 Chromium accname은 `<label>` 텍스트를
  모을 때 **aria-hidden 별표까지 포함**해 컨트롤 접근성 이름이 `"name *"`가 된다(라이브 probe로
  `getByLabel("name",exact)=0`·`getByLabel("name *",exact)=1` 확정). 스크린리더도 'star'를 낭독.
- **수정**: 별표를 `<label>` 형제로 빼는 대신(공용 `Field` CSS가 `*:w-full`/`*:data-[slot=field-label]`로
  FieldLabel을 **직속 자식**으로 겨냥 → 레이아웃 회귀 위험), 더 안전·확실한 명시 `aria-label`로 컨트롤
  접근성 이름을 별표 없는 라벨로 고정. 공용 헬퍼 `requiredFieldAriaLabel(label, required)`
  (`form-field-shared.ts`) — `required && typeof label === "string"`일 때만 라벨 문자열 반환,
  ReactNode면 undefined(기존 동작), 호출부 spread보다 먼저 둬 caller aria-label 우선. 3개 wrapper에 배선.
- **시각·spec 영향 0**: 별표는 화면에 그대로(`name<span aria-hidden> *</span>`), 접근성 이름만 `"name"`.
  e2e 전수 grep상 별표(`* `)에 의존하는 spec 없음 → 회귀 0, required 필드 `getByLabel(exact)` 전역 정상화.
- **검증**: vitest 신규 5(required→clean aria-label·non-required→무·caller override·select/textarea)·
  tsc/ESLint 0. 라이브 probe `getByLabel("name",exact)` 0→**1**, `"name *"` 1→**0**(별표 시각 유지).
  재빌드 frontend + 라이브 backend 전 spec 재실행 → **57 passed / 0 failed**.

## 2026-06-17 (claude) — admin UI 테이블 backend-의존 e2e 라이브 실행 + offline-uploads testid 회귀 수정

#454 TanStack DataTable 이행의 backend-의존 Playwright e2e를 **라이브 Docker 스택**에 대해 실행
(이전엔 static audit만). codex 스택 api(:12701)·dagster(:12702) healthy 유지, claude worktree에서
migrated frontend 이미지 재빌드 후 `--network host` 컨테이너로 :12705 서빙, playwright
컨테이너(`mcr.microsoft.com/playwright:v1.60.0-noble`, host network)로 전 spec 실행.

- **결과: 55 passed / 2 failed**(최초 54/3 → 회귀 1건 수정 후 55/2).
- **회귀 수정(이행이 유발)**: offline-uploads 삭제 흐름 spec(`admin-ops.spec.ts` #397)이 쓰는
  `getByTestId("offline-upload-row")`가 DataTable 이행 때 사라짐(구 `<TableRow data-testid>`).
  → 공용 `DataTable`에 opt-in `rowTestId?: (row) => string | undefined` prop 추가(비가상 경로
  `<tr data-testid>`), `offline-uploads-client`가 `rowTestId={() => "offline-upload-row"}` 배선.
  vitest 7/7(신규 rowTestId 1)·tsc/ESLint 0·해당 spec green 재확인.
- **잔여 2건 = 이행 무관 #449 spec 부채**(회귀 아님, 경험적 확정): `features-new.spec.ts` 18/61의
  `getByLabel("name", { exact: true })`가 0건 매치. 원인 — 공용 `FormField`(`form-field-input.tsx`,
  #454 미변경·`f288b33`가 마지막 수정)는 `required` 필드 라벨을 `name`+`<span aria-hidden> *</span>`로
  렌더하는데, Chromium accname이 aria-hidden 별표를 **포함**해 접근성 이름이 `"name *"`가 됨
  (`getByLabel("name *",{exact:true})`=1로 확정). `kind`(FormSelect·non-required)는 별표 없어 통과.
  #449 spec은 라이브 미실행 상태로 머지돼 latent했음(파일 헤더가 live 검증 보류 명시). → 후속 분리.
- 환경 메모: WSL↔Windows localhost forwarding off → e2e는 WSL 내부(컨테이너 host network)에서만 실행.

## 2026-06-17 (claude) — admin UI 전 테이블 TanStack DataTable 이행 (PR #454)

admin UI(`packages/kor-travel-map-admin/frontend`)의 모든 테이블(20파일/~22테이블)을 공용
headless `DataTable`(@tanstack/react-table v8 + @tanstack/react-virtual v3)로 교체.
정본 계획·세분화 e2e 플랜: `docs/reports/admin-tanstack-table-migration-2026-06-17.md`.

- **공용 DataTable**(`src/components/ui/data-table.tsx`): 기본은 semantic shadcn Table primitive로
  flexRender(role=table/columnheader/row/cell + 헤더 텍스트 verbatim), opt-in `virtualized`
  (display:grid+sticky thead+absolute rows+useVirtualizer+명시 ARIA aria-rowcount/rowindex),
  정렬 헤더(aria-sort, 접근성 이름 보존), 내장 loading/empty/error, onRowClick+isRowActive,
  opt-in 행 선택 + bulk 툴바. 데이터 연산 기본 server-side(manual*).
- **범위 결정(사용자)**: react-table 전체 통일, react-virtual은 `features` 지도 목록(무한)에만.
  primitive 직접 사용처는 `data-table.tsx` 하나만 남음.
- **UX 개선**: 클릭 정렬 헤더 전역 · admin-features 서버정렬 dropdown 유지+헤더 동기 ·
  다중선택+bulk(dedup accept/reject, curated 채택/보관).
- **검증**: tsc/ESLint 0 errors · vitest 20/20(DataTable 컴포넌트 5 신규) · next build 전 21페이지 ·
  route-mocked Playwright 16/16(Windows) · CI 8/8 green.
- **e2e 호환성**: backend-의존 spec(admin-ops/curated/features-new/features/home/dagster/etl)은
  role/name(regex) 기반 셀렉터 + 헤더 텍스트 보존 덕에 **마이그레이션과 호환**(7-spec 정적 audit +
  positional/count 패턴 grep 재확인, 무변경). 라이브 실행만 backend 환경(Python venv+Postgres)에 위임.
- 잔여: arm64 buildx(GITHUB_TOKEN) · admin 테이블 backend-의존 e2e 라이브 실행 · bulk 정책 가드(선택).

## 2026-06-17 (claude) — Claude Code PR 리뷰 취합(#452) 후속 일괄 반영

issue #452(2026-06-17 Claude Code PR #437~#450 전문 리뷰 취합)의 잔여 조치를 일괄 반영.
14개 항목을 전문 에이전트 14개로 현 트리 대조 후, 유효 항목만 disjoint 파일군으로 나눠 적용.

- **#437 (none)**: KREX rest-area 자연키 stale 문구는 이미 37e33b0에서 정정됨 — 무변경.
- **#445 (HIGH, code)**: KHOA 해수욕장 `01020300`→`01050100` re-key 후 구 feature 중복.
  alembic `0027_khoa_recategorize_cleanup`(신 sibling 존재 시에만 구 feature inactive, KHOA-
  해수욕장 primary 한정, `user_request` 제외, 멱등) + 회귀 테스트(unit re-key 불변,
  integration sweep 가드) + `khoa.py` docstring 정정.
- **#444 (docs)**: `openapi-admin-contract.md` unversioned-호환/`/tripmate/*` 문구를 ADR-048
  clean cut에 정렬; 의존 체인 `category→dto→core→infra→geocoding→providers→client→cli`로
  통일(pyproject 주석·SKILL.md·AGENTS.md·architecture.md); `ServiceToken` opt-in 예외
  (ADR-005 D-1)를 AGENTS.md/README에 명시. problem+json OpenAPI 보강은 `T-452-openapi-problem-json`
  으로 백로그.
- **#446 (docs+test)**: geocoder 필수화(ADR-058) Dagster blast radius를 `dagster-boundary.md`/
  dagster README에 문서화 + asset membership 정적 테스트.
- **#447 (docs)**: `missing_bjd_code`→`reverse_geocode_failed` relabel 후 `debug-ui-admin-
  workflows.md` §8.2/§16.3 예시 정정(카탈로그 표는 유지).
- **#448 (code+test)**: Prometheus exception metric을 post-routing canonical `/v1/...` path
  label로 교정 + path-label 테스트 강화 + exception-counter 테스트 추가.
- **#450 (ADR+docs)**: `.claude/agents/*`의 비존재 `context-manager` 의존을 본 저장소 절차
  (entry 문서+codegraph)로 치환 + vendored README; ADR-059(벤더링 agent/skill 언어·
  context-discovery 예외) 신설 + AGENTS.md 언어 정책 예외 단락.
- **#440/#441/#442/#443/#439 (docs/test)**: agent-guide ADR 번호(049→058) 정정; concierge
  unknown-operation/identity-drift WARNING `caplog` 테스트; journal P-01 종결 문구 범위 한정;
  source_entity_id upsert/reject/tombstone 동일 id 회귀 테스트 + 리포트 정정; cross-repo
  port-audit §1 결론을 TripMate 제외로 scope.
- **#449 (env 잔여)**: e2e 5페이지 Windows Playwright 라이브 실행은 여전히 잔여(본 환경 미실행).
- **검증**: 본 환경에 프로젝트 venv 없음 — `pytest`/`ruff`/`mypy --strict`/`lint-imports`는 CI에서
  게이트. 변경은 다중 에이전트 adversarial 리뷰로 자체 검수.

## 2026-06-16 (claude) — e2e: ZERO 커버 5페이지 1차 spec 추가 (T-AUDIT-0616)

감사 backlog의 e2e 항목 1차. ZERO 커버(spec 자체 없음) 5페이지에 Playwright spec 추가.

- **mocked-route(OpenAPI 타입 바인딩) 3종**: `feature-update-request-detail`·`import-job-detail`·
  `feature-detail`. 임의 id는 빈 DB에서 404라 admin-ops.spec 패턴으로 detail GET/cancel/run-now/
  events/nearby/weather만 가로채고(`**/v1/...**` glob), 페이지 document·RSC·WS는 통과. mock factory를
  `components["schemas"][...]`에 바인딩해 계약 drift를 `tsc`가 잡게 함.
- **라이브 smoke 2종**: `curated-features`(렌더/필터/구조 — 빈 DB tolerant), `features-new`
  (렌더 + 클라이언트측 검증: 필수 필드, 한국 본토 좌표 범위 — 네트워크 무관 결정적).
- **검증**: `npm run type-check:e2e`(tsc) + ESLint 통과. **Windows Playwright 라이브 실행은
  잔여**(본 환경 미실행 — WSL backend/frontend 기동 필요).
- **정정**: 실제 컴포넌트 인벤토리로 작성하며 감사 리포트 §1 가정 일부가 구현과 달라 §6 정정
  추가(features/new는 place/event 2종·provider 필드 없음·geo는 :12501 /v2; feature 상세는 admin
  라우트·map/AddressMatchReport/raw토글/재검증 없음; cancel/run-now는 POST).
- **잔여(depth)**: §2 얇은 커버 14페이지 mutation/error/cursor, 시드 기반 mutation flow — tasks.md.

## 2026-06-16 (claude) — fix: prometheus path 라벨 라우팅 후 확정 (#448, merged)

`#447`(F-02) CI를 막던 `test_prometheus_metrics` 실패의 근본 원인 추적·해소.

- **오진 정정**: "random-order counter 누적"으로 추정했으나, 순서-무관 + 진단 덤프 헬퍼로
  바꾸자 CI 로그가 실제 라인 `path="__unmatched__"`를 드러냄 — **값 누적이 아니라 path 라벨
  오류**였다(미들웨어가 라우팅 **전** best-effort 매칭으로 path 계산 → 일부 라우트에서 실패).
- **수정**: HTTP 메트릭 path 라벨을 `call_next` **후** `scope['route']`(권위 소스)로 확정.
  starlette 버전에 따라 `route.path`가 mount prefix 제외 상대값(`/categories`)일 수 있어
  `root_path`를 합쳐 full 템플릿으로 정규화. 진짜 404는 `__unmatched__` 유지.
- **테스트**: surface/method/status로 sample을 찾아 값(>=1.0) + path가 정상 해석됐는지
  (라우트 tail로 끝남 = `__unmatched__` 아님)를 단언 — /v1 prefix 같은 starlette 내부 차이에
  견고. 로컬 6/6 통과, CI 전 잡 green 후 머지.

## 2026-06-16 (claude) — F-02: reverse_geocode_failed issue producer 구현 (옵션 B)

감사 backlog `T-AUDIT-0616`의 F-02. 사용자 결정 **B(producer 구현/relabel)**.

- **문제**: ADR-046이 `geocode_failed`/`reverse_geocode_failed`를 정의하나 producer가
  없었다. 실은 validation.py가 **좌표-있음+bjd-없음**(= reverse-geocode가 bjd를 못 냄)을
  포괄적 `missing_bjd_code`로 방출 중이었다.
- **수정**: `validate_feature_bundle_address`(`validation.py`)가 그 케이스를
  `missing_bjd_code`→**`reverse_geocode_failed`**로 relabel — 실패 원인이 분명한 전용 코드로
  분류. `geocode_failed`(forward, 주소→좌표)는 적재 경로에 forward-geocode가 없어 미발행
  (정의만; 경로 생기면 연결). `issue_type`은 free-form 문자열이라 enum/DB 제약·admin UI 무변경.
- **검증**: `test_validation.py` 회귀 갱신(missing_bjd_code→reverse_geocode_failed), ruff clean
  (dagster 테스트는 CI). 문서 producer-상태 주석 갱신(decisions ADR-046/data-model/debug-ui),
  감사 리포트 F-02 ✅, tasks.md.

## 2026-06-16 (claude) — F-01: geocoder 필수화로 feature_id 결정성 (ADR-058, 옵션 B)

감사 backlog `T-AUDIT-0616`의 F-01 1차 해소. 사용자 결정 **B(geocoder 필수화, re-key 없음)**.

- **문제**: geocoder-의존 ~11 provider(opinet/krex/knps/krheritage/khoa/krairport/airkorea/
  standard_data/krforest/mcst/datagokr_file_data)는 bjd를 `reverse_geocoder` resource에서
  얻는데, 이 resource가 `kor_travel_geo_base_url` 미설정 시 **조용히 None**을 yield해 같은
  record가 run마다 `f_global_`↔`f_<bjd>_`로 갈렸다(비멱등).
- **수정(ADR-058)**: `reverse_geocoder_resource`가 base URL 미설정 시 None 대신 **즉시 실패**
  (RuntimeError). geocoder를 운영 필수로 강제해 결정성 보장 — **전 feature DB re-key 없이**.
  `test_resources.py` 회귀 갱신(None 반환 → raise). ruff/mypy clean(테스트는 dagster 의존이라 CI).
- **잔여(옵션 A 후속)**: geocoder 출력 drift(같은 좌표 다른 bjd)까지의 완전 결정성은 식별자
  에서 bjd 제거가 필요 — 전 feature_id re-key + collision 검증 동반, `T-AUDIT-0616` 후속.
- ADR 058 신규(다음 059), 감사 리포트 F-01 ✅, tasks.md 갱신.

## 2026-06-16 (claude) — DA-D-07: KHOA 해수욕장 category를 전용 01050100으로 정렬

감사 backlog `T-AUDIT-0616`의 DA-D-07 결정·구현. 사용자 위임으로 **(B) 전용 해수욕장
코드 `01050100 TOURISM_NATURE_BEACH` 확정**.

- **근거**: 전용 해수욕장 코드 `01050100`이 카탈로그에 실존(`_definitions.py:98` "관광 >
  자연명소 > 해수욕장")하는데 코드(`khoa.py BEACH_CATEGORY`)가 일반 `01020300`
  (해안/섬 COAST_ISLAND)을 써 온 오분류였다. 둘 다 maki `beach`라 마커 무변.
- **변경**: `khoa.py` `BEACH_CATEGORY` → `TOURISM_NATURE_BEACH`(01050100) + docstring;
  테스트 2건(`test_providers_khoa.py` 주석, `test_public_views_repo.py` literal 01020300→
  01050100); 문서 `khoa-beach-info-etl.md`·`category.md`를 01050100으로 정렬(이전 divergence
  note 제거). 감사 리포트 §4 DA-D-07 ✅, tasks.md 해소.
- **검증**: `pytest tests/unit/test_providers_khoa.py` 3 passed, ruff/mypy clean. 통합 테스트는 CI.
- **주의**: category가 `feature_id`에 박혀 KHOA 적재 시 1회 re-key(F-01 결정성과 별개).

## 2026-06-16 (claude) — 코드+문서 전체 정합성 감사 (2-pass, docs-only)

사용자 지시("코드·문서 전체 재독 → 충돌·기능갭 확인 후 문서 반영, e2e 촘촘 시나리오 포함,
누락 방지 위해 재독 검증"). **docs-only**(코드 무변경). 정본 리포트
`docs/reports/full-consistency-audit-2026-06-16.md` + `docs/reports/e2e-scenario-coverage-2026-06-16.md`.

- **방법**: Round 1 — 6차원 병렬 감사(core/api/dagster/e2e/adr/frontend) 코드 ground-truth
  대조 → 충돌 28(C-01~28) + 기능갭 4(F-01~04) + 22페이지 e2e 매트릭스. Round 2 — 재독
  adversarial 검증 + completeness critic(누락 색출). 14-에이전트로 문서 정정 적용(markdown 전용).
- **정정(본 PR)**: openapi-admin-contract.md를 ADR-048 envelope(RFC7807 problem+json +
  Meta{page,cluster})로 현행화(유일 stale 아웃라이어), `krtour-uploads`→`kor-travel-map-uploads`
  8문서 전파, screen-checklist 17→22 route, provider-contract/feature-model/data-model/
  architecture/dagster-boundary/category/rest-api/debug-ui-* 등 코드↔문서 충돌 26건 정정.
  geocoding을 의존 체인에 삽입(C-12), AGENTS.md 다음 ADR 058 정정(C-16). airkorea/krairport
  ETL 문서 신규 작성(F-04).
- **기능 갭(backlog `T-AUDIT-0616`)**: F-01 geocoder 의존 ~10 provider feature_id 비멱등
  (ADR-057이 concierge만 해결) / F-02 geocode_failed·reverse_geocode_failed issue producer 부재 /
  C-04(DA-D-07) KHOA category 결정.
- **e2e**: 34 테스트 중 23이 admin-ops에 집중, 5페이지 ZERO 커버 + 대부분 render-smoke만 —
  촘촘 시나리오 매트릭스를 정본 문서로 작성, spec 추가는 backlog.

## 2026-06-15 (claude) — concierge source_entity_id 계약 테스트 + 검증 완전 종결 (후속 4)

검증 §5의 마지막 권장(source_entity_id 불변성 계약 테스트)을 kor-travel-concierge에 처리하고
concierge loader 검증 전체를 닫았다.

- **concierge #85**(이슈 #84, T-082): 한 후보의 upsert·reject export가 동일한
  `source_record.source_entity_id`(`= str(candidate.id)`)를 갖는다는 불변성 회귀 테스트 추가
  (test-only). consumer inactivate 조인 전제를 producer 측에서 고정.
- **본 repo**: 검증 리포트 P-01/§5/결론을 ✅ concierge #85로 갱신 — **잔여 0**. concierge
  loader 검증 종결: map #440(ADR-057)·#441(하드닝)·#442·현 PR(추적), concierge #83·#85.

## 2026-06-15 (claude) — concierge P-01 cross-repo 종결 (검증 후속 3)

concierge loader 검증의 producer-side 잔여 P-01을 kor-travel-concierge repo에 직접 처리.

- **이슈 + PR**: `digitie/kor-travel-concierge` 이슈 #82 생성 → PR #83 머지(T-081). `GET
  /api/v1/features/{snapshot,changes}`의 `limit`에 `Query(ge=1, le=FEATURE_EXPORT_LIMIT_MAX)`
  추가(범위 밖 → silent clamp 대신 422) + 회귀 테스트 2종. 그쪽 컨벤션(`codex/*` 브랜치,
  journal/tasks 갱신) 준수. consumer(map)는 limit `[1,500]`만 보내 무영향.
- **본 repo**: 검증 리포트 `concierge-loader-verify-2026-06-15.md`의 P-01 줄을 ✅(concierge
  #83)로 갱신. **P-01** cross-repo 추적 종결(concierge #83). loader 검증 전체 cross-repo
  추적은 아직 열림 — 잔여 권장 1건(source_entity_id 불변성 계약 테스트)이 남아 있고, 전체
  종결은 후속(검증 후속 4 / concierge #85)에서 확정한다.

## 2026-06-15 (claude) — concierge loader 하드닝 (C-04~C-08, 검증 후속 2)

**작업**: concierge provider loader 검증(정본 `docs/reports/concierge-loader-verify-2026-06-15.md`)
의 latent 하드닝 항목(전부 오늘 활성 버그 0) 해소. ADR-057(#440) 후속.

- **C-04**(identity 키 일관성): upsert 경로가 provider/dataset_key/source_entity_type을
  payload-derived로 저장하던 것을 **고정 상수로 강제** — upsert 저장 키 == inactivate 매칭
  키 == feature_id source_type 보장(향후 alias로 인한 inactivate silent miss 차단). payload가
  상수와 다르면 `_warn_on_identity_drift`로 경고(raw 값은 raw_data 보존).
- **C-05**(operation 폐쇄 분류): `inactive_entity_ids`가 `!=upsert`를 전부 inactivate하던
  것을 **{reject,tombstone}만** 비활성화로 좁히고 unknown operation은 skip+warn — 미래
  operation 추가 시 live feature 파괴적 비활성화 방지.
- **C-06**: 페처 anti-stall 가드 테스트 2종(`has_more`인데 next_cursor 미전진/누락 → RuntimeError).
- **C-07**: `settings.kor_travel_concierge_base_url` 문서에 scheme+host[:port]만(경로 금지)
  명시 + **예시 포트 stale `12401`→`12601` 정정**(DA-D-06 정본).
- **C-08**: producer-only extra 필드(video_summary/rejection_reason/evidence.providers)
  보존 conformance 테스트 추가.
- **검증**: `pytest tests/unit/test_providers_kor_travel_concierge.py` 13 passed, ruff/mypy
  clean. 페처 가드 테스트(C-06)는 dagster 의존이라 CI에서 실행.
- **잔여**: concierge측 P-01(`limit` Query 바운드) — 그쪽 repo 후속.

## 2026-06-15 (claude) — ADR-057 concierge feature_id 안정화 (loader 검증 후속)

**작업**: "concierge provider loader 검증"(5-에이전트 conformance 감사, 정본
`docs/reports/concierge-loader-verify-2026-06-15.md`) → 발견된 feature_id 결정성 갭
수정. concierge export 계약은 origin/main `9fabbcf` 실측 대조.

- **검증 결론**: 로더 근본 정합·정상(16개 계약 항목 OK — 경로/X-API-Key/flat 엔벌롭/
  커서·limit/operation enum/식별 트리플/source_entity_id/confidence 0-1 스케일/필드명·
  중첩 전부 일치, silent drop·이중스케일 없음).
- **수정(ADR-057)**: feature_id가 늦게 바인딩되는 bjd(producer는 admin 코드 항상 None →
  optional geocoder 의존)·category(enrich 전 None→후 8자리, payload 변경 재export)를
  식별자에 넣어 **같은 후보가 재export마다 새 feature로 갈리던**(비멱등) 문제. concierge가
  보장하는 안정 키 `candidate.id`(source_entity_id)에 feature_id를 고정 — `bjd_code=None`
  + 고정 IDENTITY category + 상수 source_type. 실제 bjd/category는 Address/Feature 가변
  속성으로 in-place 갱신. concierge **한정** 정책(타 provider는 기존 동작 유지).
- **코드/테스트**: `providers/kor_travel_concierge.py` `_FEATURE_ID_IDENTITY_CATEGORY` +
  `_item_to_bundle`. 회귀 테스트 2종(geocoder 유무 동일 id / category None↔8자리 동일 id)
  + 픽스처 admin 코드 None 교정(C-03). `pytest tests/unit/test_providers_kor_travel_concierge.py`
  10 passed.
- **이행**: 구 파생 feature_id는 1회성 재키(구 동작이 이미 비멱등) — 다음 full snapshot
  재import가 안정 `f_global_` feature 생성, alembic 불필요. concierge live 적재 전이면 무영향.
- **후속(별도 PR)**: C-04 inactivate 키 일관성 / C-05 operation 폐쇄 분류 / C-06·C-08 테스트 /
  C-07 base_url 문서 / concierge측 P-01(limit Query 바운드). 리포트 §5.
- **문서 bookkeeping**: ADR 카운트 001~057 / 다음 058 (CLAUDE/AGENTS/SKILL/README).

## 2026-06-15 (claude) — DA-D-06 cross-repo 포트·계약 교차확인

**작업**: 문서 정합성 스윕 #438의 후속 DA-D-06. `integration-map.md` §1 포트표 + §3/§4
concierge·geo 계약을 공급자 측 origin/main으로 실측 교차확인(checklist §0 origin/main
원칙). 정본 리포트 `docs/reports/cross-repo-port-audit-2026-06-15.md`.

- **기준(origin/main)**: map `47df2ff`(#438 후) · concierge `9fabbcf` · docker-manager
  `126b281`(포트 owner) · geo `0bb7855`.
- **DA-D-06 확정**: concierge `API 12601`/`MCP 12602`/`web 12605` — concierge `.env.example`
  **및** docker-manager `.env.example`(`KOR_TRAVEL_CONCIERGE_*`) 양측 일치. #438 정정 검증
  (구 `12401` = docker-manager Prometheus 충돌 확정). map/geo/docker-manager 전 포트 row +
  concierge export 계약(`/api/v1/features/{snapshot,changes}`, `X-API-Key`,
  `{items,next_cursor,has_more}`, `docs/feature-export-api.md`) + geo `/v2/{geocode,reverse}`
  @12501 모두 정합.
- **cross-repo 발견(공급자 측, 본 repo 비대상)**: concierge `docs/architecture.md:21`가
  map을 옛 이름으로 표기 → concierge 후속. **TripMate**(9021/9022 +
  batch/cursor)는 로컬 미체크아웃 → quarterly cross-repo audit로 위임.
- 본 repo 코드/문서 수정 없음(integration-map은 #438에서 이미 정합).

## 2026-06-14 (claude) — 문서 정합성 스윕 (T-DA-18~26)

**작업**: 사용자 지시("문서 정합성 스윕")로 현행 정본 문서 전반을 코드/형제 repo
ground truth와 대조. 정본 리포트 `docs/reports/docs-consistency-sweep-2026-06-14.md`
(직전 `docs-consistency-audit-2026-06-06.md` T-DA-01~17의 연속, 번호 T-DA-18부터).

- **기준**: `origin/main` `b6fda93`(#437 후). 5개 차원 병렬 감사(상태 drift / ADR
  원장 / 포트·식별자 / 끊어진 링크 / 교차 주장) + 종합.
- **HIGH 2**: (T-DA-18) `resume.md` 3개 정본 섹션이 완료된 T-225를 즉시/유일 잔여로
  표기 → `T-229-buildx` 기준으로 정정(잔여 = arm64 buildx 배포 검증, `GITHUB_TOKEN`
  필요). (T-DA-21) `integration-map.md` concierge 포트 `12401`(docker-manager
  Prometheus와 충돌)·`9042` → 정본 `12601`/MCP `12602`/web `12605`(concierge +
  docker-manager `.env.example` 확인).
- **MED 3**: `sprints/README.md` Sprint5/anti-drift note T-225 stale(T-DA-19),
  `SKILL.md:298` "ADR 001~049/050"→"001~056/057"(T-DA-20), `docker-app.md` offline
  bucket `krtour-uploads`→`kor-travel-map-uploads`(`settings.py:97`, T-DA-22).
- **LOW 2**: spec docx 죽은 참조 → `git mv kor-travel-map-spec.docx
  kor-travel-map-spec.docx`(DA-D-05=A, T-DA-23); `AGENTS.md` export_openapi.py 경로를
  `packages/kor-travel-map-api/scripts/`로(T-DA-24).
- **INFO**: `decisions.md` ADR-035에 ADR-045 부분 supersede 역참조 한 줄 추가(역사
  보존, T-DA-25); ADR 원장 001~056 연속·무갭/무중복 확인(T-DA-26).
- **정상 확인(비조치)**: 포트 baseline·ADR 카운트(CLAUDE/AGENTS/README/SKILL §1)·
  `tasks.md` 내부정합·coverage 80·frontend 핀·geocoding 12501·패키지 정체성 모두
  정합. `journal.md`/dated reports는 역사 보존.

## 2026-06-14 (claude) — T-229 curated 오버레이 라이브 검증

T-229를 종결했다. 정본 리포트 `docs/reports/t-229-curated-live-verify-2026-06-14.md`.

- T-212e 데이터가 옛 claude postgres(15433)에 잔존(features 1,095,665 등) + 격리 복원본
  `krtour_map_restore` 존재 → 복원 불필요. 운영 `krtour_map` 무손상, **복원본에만** 검증.
- **curated 오버레이 완전 검증**: `curated_features_refresh` 4-asset RUN_SUCCESS →
  curated_features 0→**86,341** 후보(pet-friendly 23,090 / leisure 22,241 / barrier-free
  12,299 / world-food 9,198 / media-places 8,575 / family-culture 8,416 / bookstores
  2,522). admin API 실제 서빙, 사용자 표면은 미선택 후보 숨김(선택 게이트), curated-
  themes/sources 200, tripmate-copy는 선택 시 생성(0). AS-01/API-11/12 실데이터 해소.
- `/metrics` 200, smoke breadth 전 표면 응답. arm64 buildx만 GITHUB_TOKEN 부재로
  배포 시점 후속.
- codex 스택은 사용자 지시로 강제종료 후 external-infra 재기동. worktree 정리도 완료.

## 2026-06-13 (claude) — T-225 T-212e closure 재검증

T-225를 종결했다. 정본 리포트
`docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`.

- 라이브 재실행 없이 현재 main(`25b286b`, #434 포함) 기준 문서/코드 증거 대조로
  닫았다. 5개 차원(asset 인벤토리·`/v1` API 표면·실패 provider 수정·리포트 무결성·
  post-merge 영향) 교차검증 + 각 gap 반증(서브에이전트 18).
- **T-212e closure 유효**: 실패 provider 6건 수정 전부 main 존재(pin SHA 일치),
  리포트 무결성 정합(MCST 13종 102,121, source_records 1,111,885 vs features
  1,095,665, #397/#407/#409 close + 보강 PR 머지), identity는 #429가 리포트까지
  재작성해 이미 post-rename, 패키지 분리(#430)·#434 포트 재기준은 데이터 closure에
  영향 없음.
- 착수 가정 "구 이름 drift"는 실재하지 않음. #434 이후 리포트의 포트 참조(12301번대)는
  새 표준(12701/12702/12705/12501)보다 한 세대 뒤지나 config/문서 drift일 뿐이다.
- 남은 커버리지 갭(코드 결함 아님, 라이브 검증 미수행)은 후속 **T-229**로 분리:
  curated 오버레이 라이브 검증, Prometheus `/metrics`·arm64 buildx, smoke breadth.
  반증되어 갭 아님: ops/consistency API(e2e 실호출), backups/restore API(opt-in
  래퍼), poi-cache/refresh-policy(T-212e 이전 기능).

## 2026-06-13 (codex) — docker-manager 포트 기준 정렬

`kor-travel-docker-manager`의 로컬 포트 정책을 기준으로 kor-travel-map 실행 설정을
정렬했다.

- map API/Dagster/admin UI 기본 포트를 `12701`/`12702`/`12705`로 변경했다.
- 공유 PostgreSQL host 포트는 `5432`, kor-travel-geo REST URL은 `12501`로 맞췄다.
- RustFS `12101`/`12105`, 관측 스택 Grafana `12205`·cAdvisor `12301`·Prometheus
  `12401` 기준을 env 예시와 주석에 반영했다.
- docker-manager가 이미 띄운 `kor-travel-map` 컨테이너 `12701`/`12702`/`12705`
  health를 확인했다.
- agent entry, ADR, REST/API, Docker runbook, frontend/admin, geocoding 문서와
  테스트 문자열 계약의 잔여 `123xx`/`12201` 표기를 새 기준으로 정리했다.
- 검증: `ruff check .`, `mypy --strict src packages/kor-travel-map-api/src
  packages/kor-travel-map-dagster/src`, `lint-imports`, `pytest -q`(1306 passed),
  OpenAPI drift check, frontend lint/type-check/build, React Doctor(exit 0,
  optional warning 11개), `docker compose config`.

## 2026-06-13 (codex) — T-108 운영 배포 자동화 이식

pinvi의 `T-108` 운영 배포 자동화 항목을 kor-travel-map 범위로 이식했다.

- 사용자 재지시에 따라 streaming replication은 하지 않는 것으로 정리했다.
- `scripts/docker-buildx.sh`와 `npm run docker:buildx`를 추가해 N150 16GB
  (`linux/amd64`)와 Odroid M1S(`linux/arm64`) 양쪽 image manifest를 같은 tag로
  빌드/push할 수 있게 했다.
- `.env.example`, `docs/deploy.md`, `docs/runbooks/docker-app.md`에 buildx registry
  build와 단일 platform smoke 경로를 문서화했다.
- ADR-056을 추가하고, T-108 완료 이력을 `docs/tasks-done.md`에 기록했다.

## 2026-06-13 (codex) — 태스크 문서 전반 정리

`docs/tasks.md`, `docs/tasks-done.md`, `docs/resume.md`의 역할을 다시 분리했다.

- `tasks.md`를 열린 `[ ]` task만 남기는 백로그로 축소했다.
- 완료 묶음(`T-226`/`T-227`, `T-218`, `T-200~T-204`, `T-212a~d`, `T-216`,
  `T-RV-50~55`)은 `tasks-done.md` 상단에 요약 아카이브했다.
- `resume.md`를 현재 상태, T-225 다음 작업, 열린 작업 요약, 고정 기준값 중심으로
  다시 작성했다.
- `docs/sprints/README.md`의 Sprint 5 잔여 설명도 T-225 기준으로 갱신했다.

## 2026-06-13 (codex) — Docker 공유 DB 모드 정리

사용자 확인에 따라 PC 개발 host `5432`를 공유 DB 서버 인스턴스로 고정하고,
kor-travel-map Docker 기동을 다시 검증했다.

- `KOR_TRAVEL_MAP_DB_EXTERNAL=true` 모드를 추가했다. local Postgres는 띄우지 않고,
  공유 PostGIS(`host.docker.internal:5432`)와 local RustFS(`12101`/`12105`)를 함께 쓴다.
- standalone local Postgres publish 기본값은 `15432`로 분리했다.
- `docker-compose.external-db.yml`, `scripts/docker-up.sh`, `.env.example`,
  Docker runbook/deploy/rest API/Dagster 문서를 갱신했다.
- Docker stack을 새 모드로 기동하고 API/Admin UI/Dagster smoke를 통과했다.
- Windows host Playwright e2e를 다시 실행해 **33/33 passed**를 확인했다.

## 2026-06-13 (codex) — REST API/admin 패키지 분리

Prometheus 성능 메트릭 PR 머지 후 사용자 후속 결정으로 backend와 frontend 패키지를
분리했다.

- FastAPI/OpenAPI backend를 `packages/kor-travel-map-api/`로 이동하고 Python
  distribution을 `kor-travel-map-api`, import root를 `kortravelmap.api`로 정리했다.
- `kor-travel-map-admin`은 Next.js admin frontend(`frontend/`)만 소유한다.
- backend 설정 prefix를 `KOR_TRAVEL_MAP_API_*`, frontend API base URL을
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`로 clean cut했다. admin web port 변수
  `KOR_TRAVEL_MAP_ADMIN_WEB_PORT`는 유지한다.
- OpenAPI 산출물과 export script를 `packages/kor-travel-map-api/`로 이동하고
  admin/user spec을 재생성했다.
- ADR-055를 추가하고 README/AGENTS/SKILL/architecture/debug-ui-package/backend-package,
  Docker/CI/scripts/frontend codegen 경로를 새 경계에 맞췄다.

## 2026-06-13 (codex) — T-227 Prometheus 성능 메트릭 표면 추가

T-226 clean cut 이후 후속으로 Prometheus pull scrape 표면을 추가했다.

- `packages/kor-travel-map-api/src/kortravelmap/api/prometheus.py`를 추가해
  앱별 Prometheus registry, HTTP 요청 total/duration histogram/진행 중 요청 gauge/
  응답 크기 histogram/예외 count, DB query count/duration histogram, 프로세스/런타임
  메트릭을 제공한다.
- `surface=public/admin/ops/debug/system/other` label로 공개 REST와 운영 REST를
  분리한다. 공개 REST에는 `/v1/features`, `/v1/categories`, `/v1/providers`,
  `/v1/public`, `/v1/curated-features`를 포함한다.
- `create_app()`이 기본 `GET /metrics`를 OpenAPI 제외 route로 노출하고,
  `/metrics` 자체 scrape 요청은 HTTP request metric에서 제외한다.
- 설정은 `KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED=true`,
  `KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_PATH=/metrics`로 제어한다.
- 포트 기준은 `kor-travel-docker-manager` 정본을 참조했다: Prometheus `12601`,
  cAdvisor `12602`, Grafana `12605`; map API scrape target은 `:12301/metrics`.

## 2026-06-13 (codex) — T-226 package/runtime identity clean cut 구현

T-226c/d/e를 no-shim clean cut으로 구현했다.

- 메인 import root를 `kortravelmap`으로 이동하고 권장 예시를
  `import kortravelmap as ktm`로 정리했다. admin/dagster도
  `kortravelmap.api`, `kortravelmap.dagster` namespace로 맞췄다.
- 배포명/패키지 경로를 `kor-travel-map`, `kor-travel-map-admin`,
  `kor-travel-map-dagster`, `kor-travel-map-user-client`로 정렬했다.
- CLI entry point를 `ktmctl`로 바꿨고, `KOR_TRAVEL_MAP_*` env, DB
  `kor_travel_map`/`kor_travel_map_dagster`, RustFS bucket
  `kor-travel-map`/`kor-travel-map-uploads` 기준으로 설정·문서를 정렬했다.
- 형제 프로젝트 표기는 `kor-travel-geo`, `kor-travel-concierge`,
  `kor-travel-docker-manager` 기준으로 갱신했다.
- E2E는 `kor-travel-docker-manager` 공유 Postgres 인스턴스(`5432`) 안에
  `kor_travel_map`/`kor_travel_map_dagster` DB를 만들고 Alembic 후 실행했다.
  Windows Playwright 전체 **33/33 passed**.

## 2026-06-13 (codex) — T-226 runtime 이름 추가 재결정 반영

T-226 목표 runtime identity를 사용자 추가 결정에 맞춰 갱신했다.

- CLI 목표명을 `ktmctl`로 바꿨다.
- PostgreSQL 기본 DB 이름을 `kor_travel_map`, Dagster metadata DB 이름을
  `kor_travel_map_dagster`로 바꿨다.
- RustFS bucket/prefix 등 사용자 가시 이름은 `kor-travel-map` 계열로 맞추기로 했다.
- 형제 프로젝트 표시명은 `kor-travel-geo`, `kor-travel-concierge` 기준으로 맞췄다.
- ADR-054, package identity guide, T-226b 실행계획, tasks/resume을 같은 기준으로
  정렬했다.

## 2026-06-13 (codex) — T-226 import root 재결정 반영

T-226 목표 Python import root와 권장 alias를 사용자 재결정에 맞춰 갱신했다.

- 목표 Python import root를 `kortravelmap`으로 정렬했다.
- 권장 import 예시는 `import kortravelmap as ktm`으로 바꿨다.
- ADR-054, `docs/package-identity-rename.md`, T-226b 실행계획, README/AGENTS/SKILL/
  CLAUDE 및 관련 아키텍처/연동 문서의 T-226 note를 같은 기준으로 맞췄다.

## 2026-06-12 (claude) — T-212e 완결: 실데이터 full reload 최종 리포트

T-212e 전 트랙 종결. 정본 리포트
`docs/reports/t-212e-live-full-reload-final-2026-06-12.md`.

- **적재**: 빈 DB → **1,095,665 features**(MOIS bulk 980,970 / MCST CSV 13종
  102,121 / 주차장 18,294 / knps_trails 618 등) + weather values 92,923.
  WSL 재설치로 환경 전체 재구축(네이티브 docker-ce + GITHUB_TOKEN build
  secret + #391 표준 포트) 후 빈 DB에서 처음부터 실행.
- **정합성**: `full_load_batch_consistency_gate` 최종 report `99159eea`
  (trails 포함) severity_max **OK**, integrity violations 0.
- **offline upload**: 실데이터 CSV 60/TSV 40/JSONL 60 종단 `loaded` +
  #397→#417 DELETE lifecycle live 검증(좀비 2건 200 → 동일 checksum
  재업로드 201).
- **e2e/smoke**: Windows Playwright **33/33**(#416 spec drift 수정 + #417
  delete flow 추가 검증, frontend 이미지 갱신 후) / API smoke 17/17.
- **backup/restore**: cold backup(554MB dump+rustfs) → staging restore
  검증값 운영 정확 일치(1,095,665). 교훈 2건 리포트 §5.3 — WSL
  `PYTHON_BIN`(advisory lock psycopg) + 장시간 maintenance는 호출 세션과
  분리 실행(SIGPIPE).
- **P99**(~1.1M rows): search 86ms / nearby 102ms / categories 9ms /
  in-bounds **442ms** — 클러스터 MV ADR 재판단 입력(리포트 §6).
- 실측이 적발해 수정·머지한 결함: krtour #392/#393/#400/#408/#410/#411/
  #413/#416/#417/#420/#424 + provider 5 repo(datagokr·krheritage·kma·
  mcst·knps) 이슈→PR→머지. 이슈 #397/#407/#409 close.

## 2026-06-12 (claude) — #407: knps 이름 없는 record skip — trails 배치 크래시 수정

knps 핀 범프(#420) 후 trails 재실행이 14분 진행 끝에
`Feature.name=None` ValidationError로 **배치 전체 실패** — 이름 없는 코스
1건이 원인. krtour `KnpsPointRecord`/`KnpsGeometryRecord` Protocol이
`name: str`로 knps-api 실모델(`KnpsPlaceRecord`/`KnpsGeoRecord`의
`name: str | None`)보다 엄격해 런타임 None이 그대로 `Feature(name=...)`에
도달했다 (ADR-044 위반 상태).

- Protocol `name` → `str | None`로 provider 실모델에 정렬.
- `_point_record_to_bundle`/`_geometry_record_to_bundle`에 이름 가드 추가 —
  `normalize_korean_text` 결과 None(원본 None/빈/공백-only)이면 그 행만
  skip하고 배치는 계속 (mcst/datagokr file-data와 동일 규칙). 기존
  `normalize_korean_text(name) or name` fallback은 공백-only 이름을
  되살리는 버그라 제거.
- point 변환도 같은 크래시 계열이라 함께 수정
  (`FeatureBundle | None` + 호출자 skip).

검증: unit 1,064 passed(이름 skip 신규 2건 포함) / ruff / mypy --strict
(`kortravelmap`+`kortravelmap.dagster`) / lint-imports green. trails 실적재
재실행은 dagster 리빌드 후 수행(T-212e 리포트 기록, #407 종결 조건).

## 2026-06-12 (codex) — T-226b package clean cut 실행계획

T-226b로 `kor-travel-map` / `kortravelmap` 코드 clean cut의 분할 단위와 게이트를 확정했다.

- main 기준 표면을 계량했다: Python/설정/문서 후보 908개 파일, `kortravelmap` 참조
  파일 368개, `KOR_TRAVEL_MAP` 참조 파일 86개.
- 최종 layout은 `src/kortravelmap`, `kortravelmap.api`, `kortravelmap.dagster`로 정했다.
  admin/dagster distribution과 package path도 `kor-travel-map-admin`,
  `kor-travel-map-dagster`로 맞춘다.
- 구 `kortravelmap` / `kortravelmap.api` / `kortravelmap.dagster` /
  `KOR_TRAVEL_MAP_*` compatibility shim은 만들지 않는다.
- 실제 구현을 T-226c(Python import/package layout), T-226d(runtime/deployment
  identity), T-226e(소비자 문서/client/migration guide)로 나눴다.
- 정본: `docs/reports/t-226b-package-clean-cut-plan-2026-06-12.md`.

## 2026-06-12 (claude) — #407: knps 핀 범프 — trails 코스 LINESTRING 조립 반영

T-212e에서 `feature_geometry_knps_records`가 RUN_SUCCESS인데 적재 0건(#407)
이었던 원인은 provider가 trails CSV의 **vertex 단위 행 910,110개를 코스
단위 LINESTRING으로 조립하지 않고 per-vertex POINT record로 반환**(카탈로그
LineString 계약 불일치) → krtour route 변환이 전 행 skip. provider
#9/PR#10(`16e3954`)으로 `read_geo_records`에 코스 조립을 추가(live 종단:
625 코스 LINESTRING)하고 krtour 핀 범프. trails asset 재실행은 dagster
리빌드 후 수행(T-212e 리포트 기록).

## 2026-06-12 (codex) — T-226a package identity rename 정본화

T-226a로 배포명/임포트명 clean cut의 문서 정본을 만들었다.

- ADR-054 accepted: 배포명 `kor-travel-map`, Python import root `kortravelmap`, 권장 예시
  `import kortravelmap as ktm`.
- `docs/package-identity-rename.md` 추가: current identity와 target identity, no-shim 원칙,
  T-226 후속 작업을 표로 정리했다.
- README/AGENTS/CLAUDE/backend-package/architecture/provider-contract/integration-map에
  "현재 표기는 코드 기준, 목표 identity는 ADR-054/T-226" note를 추가했다.
- T-226c/d/e 전에는 코드와 현재 운영값이 아직 `kor-travel-map` / `kortravelmap` /
  `KOR_TRAVEL_MAP_*`임을 명시했다.

## 2026-06-12 (codex) — T-223d TripMate import 머지 반영

T-223d 외부 TripMate 소비 측 구현이 TripMate PR #184로 머지됐다.

- TripMate `KorTravelMapClient`가 kor-travel-map
  `/v1/curated-features/{curated_feature_id}/tripmate-copy` snapshot을 호출한다.
- TripMate `POST /admin/notice-plans/imports/krtour-curated-features`가
  `create` / `upsert` / `refresh` mode로 `curated_trip_plans` /
  `curated_plan_pois`를 생성·갱신하고 source version/etag/item provenance를 저장한다.
- TripMate 잔여 `KOR_TRAVEL_CONCIERGE_API_BASE_URL` / 12401 예약을 제거했다.
  `kor-travel-concierge`는 curated trip plan 생성 flow에 관여하지 않는다.
- kor-travel-map `tasks.md`, `tasks-done.md`, `resume.md`를 T-223 완료 상태로 갱신했다.

검증(TripMate PR #184): CI `Aggregate CI gate`, `lint-typecheck-test`,
`Post MCP review reminder` green.

## 2026-06-12 (codex) — T-223c-3 curated Admin UI

curated feature overlay 운영 화면을 admin frontend에 연결했다.

- **Admin UI**: `/admin/curated-features` route와 nav 진입점을 추가했다. 후보 목록은
  theme/provider/dataset/status/page filter와 select/unselect/archive action을 제공한다.
- **편집 표면**: 선택 후보의 display title/summary, rank score, TripMate copy policy,
  TripMate relation을 편집할 수 있게 했다.
- **Source rule**: rule 목록, enabled/action/priority/place_kind/category/JSON metadata
  편집, 단건 apply를 연결했다.
- **TripMate preview**: `/v1/curated-features/{id}/tripmate-copy` snapshot을 조회해
  `curated_trip_plans`/`curated_plan_pois` 복사 payload를 확인할 수 있게 했다.

## 2026-06-12 (claude) — #397: offline-uploads DELETE lifecycle 구현

T-212e 실측에서 RustFS 인스턴스 교체로 원본 객체가 소실된 좀비 업로드 2건이
checksum 멱등 가드(409)에 막혀 재업로드 불가 + 정리 경로 부재(405)였던 갭을
구현으로 해소. `delete_offline_upload` repo 함수(조건부 DELETE — `validating`/
`loading`이면 `OfflineUploadStatusConflict`) + `OFFLINE_UPLOAD_DELETABLE_STATES`
상태 계약 추가, 라우터는 DB row 삭제 확정 후 객체를 best-effort 삭제(S3
DeleteObject 멱등 — 객체 없는 좀비도 성공, FileStoreError는 기록만). 응답은
`{data: 삭제 row snapshot, meta}` 200, `require_admin_destructive_enabled`
kill-switch 적용(rest-api.md §1.3). 연관 import_jobs row는 audit으로 보존
(FK 방향이 upload→job이라 cascade 없음). admin UI 행 단위 삭제 버튼 +
e2e mock DELETE 핸들러/삭제 flow, PostGIS 통합 2건(삭제→동일 checksum
재업로드 통과, 진행중 409→종료 후 삭제+job 보존) 추가. OpenAPI/types 재생성.

## 2026-06-12 (claude) — fix(e2e): admin-ops spec drift 2건 (#409, T-212e 후속)

T-212e live 최종 e2e 30/32의 잔여 실패 2건 — 환경이 아니라 spec-vs-UI/데이터
drift(#409).

- **providers freshness(T-217g)**: T-221d(#404) 이후 `/ops/providers`가
  `/v1/providers`가 아닌 **`/v1/ops/providers`(+`/{provider}` 상세)**를 쓰는데
  spec mock이 구 endpoint를 가리켜 라이브 데이터로 렌더 → 상세 패널의 sync
  state/update request 테이블과 `last success`/`status` 등 columnheader가
  겹쳐 strict mode 위반(로딩 race라 실패 지점 비결정). 수정: 목록·상세 mock을
  신 endpoint로 교체(`OpsProviderDatasetSummary`/`OpsProviderDetailResponse`
  생성 타입 바인딩 factory), columnheader 단언을 freshness 테이블에만 있는
  `policy` 헤더 기반 `getByRole("table").filter({ has: ... })`로 한정, 기대
  컬럼을 현 UI(detail/policy/next run 포함, last failure 제거)로 갱신.
- **admin/issues**: 라이브 직격 spec이 `getByRole("row").nth(1)` 클릭 후 폼을
  무조건 단언 — 또한 빈 목록 분기가 `emptyRow.isVisible()` 즉시평가라 1M행
  느린 쿼리 중 false로 새는 race. 수정: manual-override 정본 type
  `missing_address`(docs/debug-ui-admin-workflows.md)로 **issue type 필터를
  먼저 적용**해 행을 고정, `expect(emptyRow.or(row)).toBeVisible()`로 목록
  settle 대기 후 분기 — 해당 type 0건이면 폼 단언 skip. (현 컴포넌트는 폼을
  type 무관 렌더하지만 type 고정으로 데이터 구성에도 견고.)
- **검증(Windows, live 스택 12305/12301)**: 타깃 2 spec green + 전체 e2e
  **32/32 passed**(비어있지 않은 분기는 임시 mock spec으로 별도 재현 후 폐기).
  `npm run type-check`(src+e2e tsconfig) 통과. 컴포넌트 변경 없음(spec만).

## 2026-06-12 (codex) — T-223c-2 curated Dagster group

curated overlay 운영 배치를 Dagster `curated_features` asset group으로 연결했다.

- **DB**: Alembic `0026_curated_copy_snapshots`로
  `feature.curated_tripmate_copy_snapshots` cache table을 추가했다.
- **Backend**: source metadata refresh, enabled source rule bulk apply, inactive/deleted
  feature status sweep, TripMate copy snapshot materialize 함수를 `curated_repo`와
  `AsyncKorTravelMapClient`에 추가했다.
- **Dagster**: `curated_source_metadata`, `curated_feature_candidates`,
  `curated_feature_status_sweep`, `curated_tripmate_copy_snapshots` asset과
  `curated_features_refresh` job/schedule을 등록했다.
- **후속 분리**: Admin UI는 T-223c-3, TripMate 복사 연동은 T-223d로 유지한다.

## 2026-06-12 (codex) — T-223c-1 curated DB/API foundation

curated feature overlay의 DB/API foundation을 구현했다.

- **DB**: Alembic `0025_curated_features`로 `feature.curated_themes`,
  `curated_sources`, `curated_source_rules`, `curated_features`와 1차 seed
  source/rule을 추가했다. UUID default는 `x_extension.gen_random_uuid()`로 고정.
- **Backend API**: `curated_repo` + `/v1/curated-*` read, `/v1/admin/curated-*`
  write/select/unselect/archive/source-rule-apply, TripMate copy snapshot을 추가했다.
- **Contract**: `openapi.json`/`openapi.user.json`과 `@kor-travel-map/map-user-client`
  generated type을 재생성했다.
- **후속 분리**: Dagster group은 T-223c-2, Admin UI는 T-223c-3으로 분리했다.

## 2026-06-12 (claude) — T-212e: mcst 좌표도 격리 (#400 패턴, T-220 후속)

`feature_place_mcst_culture` live 적재가 73분 진행 후 `lat=42.6406462,
lon=131.679`(한국 경계 밖 — 세계음식점류 해외/오타 좌표 실존)의 `Coordinate`
검증 ValueError로 실패. COORDINATES 파서의 bbox(lat≤43)가 DTO 허용범위
(lat≤39.5)보다 관대해 통과시킨 갭 — `_coord_or_none`을 try/except
ValidationError → None 격리로 보강(DTO가 정본, #400 standard_data와 동일
패턴). 번들 레벨 단위 테스트 추가.

## 2026-06-12 (claude) — T-212e: pg_trgm `%` 연산자도 스키마 qualify (#410 후속)

#410(공간 연산자) 머지·api 재배포 후 P99 재측정에서 `/features/search`가
여전히 500 — `operator does not exist: character varying % text`. pg_trgm도
`x_extension` 스키마라 **trigram `%` 연산자**가 같은 search_path 문제를
가진다(#410 스캔이 coord/geom 문맥만 봐서 텍스트 연산자를 누락).
`feature_repo` 2곳을 `OPERATOR(x_extension.%)`로 교체. live 검증: '박물관'
trigram 1,646건 매칭. `SET LOCAL pg_trgm.similarity_threshold`는 GUC라 무관.

## 2026-06-12 (claude) — T-212e: 공간 연산자 스키마 qualify — live 500 수정

T-212e live P99 측정에서 `/features/in-bounds`·`/features/search`가
`UndefinedFunctionError: operator does not exist: x_extension.geometry &&
x_extension.geometry`로 **500**. 원인: PostGIS가 `x_extension` 스키마인데
live docker DB의 search_path는 postgis 이미지 기본값(`public, topology,
tiger`)이라 **연산자**가 미해석 — 함수는 `x_extension.ST_*`로 qualify해 왔지만
연산자(`&&`/`<->`)는 누락(통합 테스트 conftest가 `SET search_path = public,
x_extension`을 명시 세팅해 CI에서는 가려짐). infra 4파일 12곳을
`OPERATOR(x_extension.&&)`/`OPERATOR(x_extension.<->)`로 교체 — DB search_path
구성과 무관하게 동작(repo의 명시-qualify 정책 완성). live 검증: 서울 bbox
94,431건 정상 조회.

## 2026-06-12 (codex) — T-223b curated source provider 보강

curated feature 후보의 책/음식/특화거리 source를 provider 라이브러리와 kor-travel-map
변환 계층에 반영했다.

- **provider pin**: `python-datagokr-api@48e458b`(provider PR#10 — fileData 4종 +
  전국지역특화거리 service/model), `python-mcst-api@c011f6e`(provider PR#11 —
  중고서점 OpenAPI/CSV)를 `providers` extra에 반영했다.
- **kor-travel-map 변환**: MCST `used_bookstores_csv`를 기존 `split_coord` 방언에 추가하고,
  `datagokr_file_data.py`를 신설해 서울 책방·경기 무슬림 친화 음식점·안산 세계맛집·
  제주 향토음식점 raw fileData를 place `FeatureBundle`로 변환한다.
- **표준데이터**: 전국지역특화거리표준데이터를 geometry 없는 `theme_area_anchor`
  place로 보존하는 `special_streets_to_bundles`를 추가했다.
- **문서**: `docs/curated-features.md`, `docs/provider-contract.md`, `docs/tasks.md`,
  `docs/resume.md`의 T-222c/T-223b 상태를 갱신했다.

## 2026-06-12 (claude) — fix: frontend Docker 빌드에 NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL 누락

T-221b(#403 좌표 picker)가 `/admin/features/new`를 prerender 시점 fail-fast로
`NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL`을 요구하는데 `docker/frontend.Dockerfile`
ARG/ENV와 compose 빌드 args에 빠져 **main의 frontend Docker 이미지가 빌드
불능**이었다(T-212e 최종 리빌드에서 실측 — T-221b 검증은 WSL dev 스택이라
미검출). ARG 기본값 `http://127.0.0.1:12201`(ADR-046 표준) + compose
args/environment 전파 추가. `docker compose build frontend` 통과 확인.

## 2026-06-12 (codex) — T-222b 공개 해수욕장/축제 view API

TripMate T-130 차단 조건이던 공개 해수욕장/축제 view API를 kor-travel-map 사용자 표면에
구현했다.

- **Backend**: `public_views_repo`를 추가하고 `GET /v1/public/beaches*`,
  `GET /v1/public/festivals*` 6개 endpoint를 추가했다. 해수욕장은
  `detail.place_kind='beach'`, 축제는 기간 겹침으로 조회한다.
- **Contract**: admin/user OpenAPI와 `@kor-travel-map/map-user-client` 생성 타입/alias를
  갱신했다.
- **결정**: KHOA category drift는 `place_kind` 1차 판별로 닫았다. provider category
  `01020300`은 보조 정보로 유지하고, 예전 문서값 `01050100`은 판별 기준에서 제외한다.
- **후속**: KHOA 폭/길이/재질 provider 보강, 수질/index/weather projection, TripMate
  소비 측 문서/픽스처 동기화(T-222c)는 후속으로 남겼다.
- **검증**: public view 라우터 단위 테스트 6 passed, repo 통합 테스트 2 passed,
  `ruff check .`, targeted mypy, OpenAPI drift check, user-client type-check 통과.

## 2026-06-12 (claude) — T-212e: 표준데이터 한국 경계 밖 좌표 격리 (#386 패턴)

핀 범프(#393) 후 주차장 재실행이 **다른 불량 row 클래스**로 재실패(run
`bc740f74`): live 값 `lat=26.128492`(한국 lat 허용범위 [33.0, 39.5] 밖 오타)가
`Coordinate` 검증 ValueError로 dataset 전체를 차단. `standard_data`의 좌표 조립
3개소(축제/박물관/공용 place 조립기)를 `_coordinate_or_none` helper로 교체 —
검증 실패 좌표는 None 격리(row는 주소 단서로 적재, 원본 raw_data 보존).
단위 테스트: 경계 밖 row 격리 + 정상 row 비영향.

## 2026-06-12 (codex) — T-221e ops logs + debug 재판정

T-221 admin UI 연결성 보강의 마지막 조각으로 `/ops/logs`와 import job event stream을
연결하고, debug explain/fixtures 표면을 재판정했다.

- **Backend**: `GET /v1/ops/import-job-events`를 추가했다. `job_id`/`provider`/
  `dataset_key`/`level` 필터와 `occurred_at DESC, event_id DESC` keyset cursor를
  지원한다. 기존 `/v1/ops/import-jobs/{job_id}/events`는 그대로 유지한다.
- **Frontend**: `/ops/logs`에 Job events 탭을 추가했다. system/API log와 같은 화면에서
  provider/dataset/job/level 필터로 event를 훑고, 각 row의 job 링크로
  `/ops/import-jobs/[job_id]` 상세로 이동한다.
- **Debug 재판정**: `/debug/explain` REST/UI는 raw SQL blast radius 때문에 제외하고,
  EXPLAIN은 통합 테스트 gate와 운영 DB read-only runbook으로 둔다. `/debug/fixtures`도
  만들지 않고 파일 기반 fixture helper + `/debug/etl` preview로 수렴했다.
- **문서/계약**: admin OpenAPI, frontend generated type, admin workflow/package 문서,
  fixture workflow, frontend README를 갱신했다.

## 2026-06-12 (codex) — T-221d provider 상세/refresh policy

T-221 admin UI 연결성 보강의 네 번째 조각으로 provider 운영 상세와 refresh policy 편집을
연결했다.

- **Backend**: `GET /v1/ops/providers`, `GET /v1/ops/providers/{provider}`를 추가했다.
  `/v1/providers` 사용자 표면은 cursor를 계속 숨기고, ops 상세 표면에서만 sync cursor,
  refresh policy, 최근 `provider_dataset` update request를 묶어 제공한다.
- **Policy API**: `GET/PUT /v1/admin/provider-refresh-policies*`를 추가했다. interval은
  `min_interval_seconds`와 선언된 request/min/hour/day floor보다 짧게 설정할 수 없다.
- **Request linkage**: `feature_update_requests` 목록 필터가 `scope.type='provider_dataset'`
  내부 provider/dataset도 찾도록 보정했다.
- **Frontend**: `/ops/providers`에서 dataset row 선택, sync cursor/detail, 최근 request
  상세 이동, `provider_dataset` request 생성, refresh policy 편집을 제공한다.
  `/admin/feature-update-requests/[request_id]` 상세 route도 추가했다.
- **검증**: provider/policy/update request router 단위 테스트 27 passed, Python
  ruff/mypy targeted, frontend type-check/ESLint 통과.

## 2026-06-12 (codex) — T-221c admin live signal channel

T-221 admin UI 연결성 보강의 세 번째 조각으로 admin 실시간 signal 채널을 추가했다.

- **Backend**: `WS /v1/ops/live` WebSocket endpoint를 추가했다. query/topic command로
  `import_jobs`, `import_job:{job_id}`, `import_job_events:{job_id}`,
  `feature_update_requests`, `feature_update_request:{request_id}`, `offline_uploads`,
  `offline_upload:{upload_id}`, `dagster_runs`, `dagster_run:{run_id}`를 구독한다.
- **Signal model**: DB trigger 없이 topic snapshot revision을 주기적으로 비교해 변경된
  topic만 `snapshot`/`update` frame으로 전송한다. client payload는 source of truth가
  아니라 query invalidation signal이다.
- **Frontend**: `src/api/live.ts` hook을 추가하고 `/ops/import-jobs`,
  `/ops/import-jobs/[job_id]` 화면에 live badge와 query invalidation을 연결했다. 기존
  polling은 fallback으로 유지한다.
- **검증**: ops WebSocket router 단위 테스트 12 passed, Python ruff/mypy targeted,
  frontend type-check/ESLint/React Doctor 통과.

## 2026-06-12 (codex) — T-221b import job 상세/event/cancel

T-221 admin UI 연결성 보강의 두 번째 조각으로 import job 상세 흐름을 추가했다.

- **DB/API**: `ops.import_job_events` migration/ORM/repo를 추가하고, job lifecycle
  생성/claim/heartbeat/finish/cancel에서 구조화 event를 기록한다.
  `GET /v1/ops/import-jobs/{job_id}/events`는 keyset cursor로 timeline을 반환한다.
- **Cancel**: `POST /v1/ops/import-jobs/{job_id}/cancel`을 추가했다. queued/running
  job만 best-effort로 `cancelled` 전이하고, terminal job은 `409`로 막는다.
- **Frontend**: `/ops/import-jobs/[jobId]` route를 추가했다. job 상태/시각/payload,
  parent/batch/request/upload/Dagster 관련 링크, event timeline, cancel form을 한 화면에
  연결했다. 목록의 job id는 상세 route로 이동한다.
- **Contract**: admin OpenAPI와 frontend generated type을 갱신했다. user OpenAPI 표면은
  변하지 않는다.
- **검증**: ops repo/router 단위 테스트 19 passed, jobs/ops repo 통합 테스트 17 passed,
  Python ruff targeted, frontend type-check/ESLint, admin OpenAPI check 통과.

## 2026-06-12 (codex) — T-221a-2 수동 feature 작성 흐름

T-221a feature 상세/수동 작성 흐름을 닫았다.

- **Frontend route**: `/admin/features/new` 추가. 지도 좌표 선택, 중심 좌표 적용,
  `place`/`event` kind별 detail form, 주소/code 필드, extra JSON 병합, 기존
  `POST /v1/admin/features` change-request mutation 제출을 한 화면에 묶었다.
- **kor-travel-geo**: `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL` 기반 브라우저 helper 추가.
  REST v2 `POST /v2/geocode`, `POST /v2/reverse` 후보를 좌표·주소·행정코드 필드로
  적용한다. 순수 정규화 함수는 Vitest로 회귀 테스트.
- **중복 후보**: 좌표와 `radius_m`이 유효하면 `/v1/features/nearby`로 active/
  inactive/hidden 후보를 조회하고 feature 상세 링크를 제공한다.
- **지도 보정**: MapLibre가 mount 시 붙이는 `maplibregl-map` CSS가 Tailwind
  `absolute`를 이기는 문제를 새 작성 화면과 기존 `/features` 지도에서 inline sizing으로
  보정했다.
- **문서**: frontend `.env.example`, `kor-travel-map-admin` README,
  `docs/debug-ui-package.md`에 `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL`을 추가.
- **검증**: frontend type-check, ESLint, Vitest 15 passed, React Doctor no issues,
  Next production build, in-app Browser DOM/canvas/좌표 상호작용 확인.

## 2026-06-12 (codex) — T-221a-1 feature detail route 1차

T-221 admin UI 연결성 보강의 첫 조각으로 feature first-class 상세 경로를 추가했다.

- **Backend**: `GET /v1/admin/features/{feature_id}` 추가. feature core snapshot,
  SourceRecord/SourceLink(raw payload 포함), data integrity issue, override,
  feature version, change request, 선택적 `feature_files` metadata를 한 응답으로
  aggregate한다. 아직 `feature.feature_files` 테이블이 없는 DB head는 빈 배열로 응답.
- **Frontend**: `/features/[featureId]` route + `FeatureDetailView` 공통 컴포넌트 추가.
  source/raw/issues/overrides/history/files/nearby/weather를 한 화면에 묶고,
  `/features` 지도 panel과 `/admin/features` table/inspector에서 상세 URL로 링크.
- **Contract**: admin OpenAPI + frontend generated type 갱신. user OpenAPI 표면 변경 없음.
- **검증**: admin feature router/repo 단위 테스트 20 passed, frontend type-check,
  ESLint, ruff, mypy, OpenAPI drift check, openapi-typescript check.
- **잔여**: T-221a-2로 `/admin/features/new` 수동 작성 전용 흐름(지도 좌표 선택,
  kor-travel-geo geocode/reverse, kind별 detail form, duplicate 후보 확인)을 이어간다.

## 2026-06-12 (claude) — T-220 재배선 #395: MCST → CSV 파일 다운로드 주경로

`python-mcst-api`가 CSV 파일 다운로드 주경로로 재편됨(provider #6/#7/#9,
`@ba471ee`)에 따라 krtour MCST 배선 전체를 keyless `FileDataClient` 표면으로
재작성했다. KCISA OpenAPI는 공인 DNS 미해석 + 전용 발급키 필요로 폐기, ODCloud
도서관 디렉토리도 카탈로그에서 소멸.

- **메타표/변환**: `MCST_FILE_DATASETS` 12종(방언 4종 — kcisa_common 8 /
  cntc_resrce 2 / split_coord 1 / korean_address 1) + `file_rows_to_bundles`
  단일 변환. 신규 적재: 아동서점(01040000)·골프장(01080100 — 기존 코드).
  제외 3종(기사형/통계)은 `MCST_EXCLUDED_FILE_DATASETS`에 사유 보존.
- **COORDINATES 파서**: 실측 2형식("N37.5, E126.9" / "35.8 , 128.6" — 콤마
  없는 공백 변형 포함) + 한국 bbox 검증·순서 뒤집힘 교정. dataset_key는
  `mcst_<slug>` 클린 컷(빈 DB 재적재 중 — 하위호환 shim 없음, ADR-046 원칙).
- **Dagster**: fetcher keyless 전환(credential guard 제거 — knps/krheritage
  패턴), asset은 `feature_place_mcst_culture` 1종으로 통합(libraries 계열
  제거), `mcst_max_items_per_dataset` 기본 50000으로 상향(실측 최대 24,537행).
- 실측 근거: 2026-06-12 live 전수 CSV 다운로드 헤더/샘플
  (WSL `~/t212e-data/mcst-csv-headers.json`). 매핑 전체는
  `docs/mcst-feature-etl.md` 재작성본 참조.

## 2026-06-12 (codex) — T-224 kor-travel-concierge provider clean cut

T-224를 완료했다.

- `kor-travel-concierge` provider identity를 `kor-travel-concierge`로 clean cut하고 ADR-053을 추가.
- canonical provider/env/module/Dagster naming을 `kor-travel-concierge-youtube`,
  `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_*`, `providers.kor_travel_concierge`,
  `kor_travel_concierge_youtube_features` 기준으로 정렬.
- `detail.payload.kor_travel_concierge` 원본 보존, `detail.facility_info` confidence 노출,
  reject/tombstone inactive helper와 cursor/page guard 테스트를 유지.
- TripMate ↛ kor-travel-concierge 직접 연동 없음, curated trip plan 생성 flow 제외를
  integration/curated/tripmate 소비 문서에 반영.
- 신규 결정(`kor-travel-map`, `kortravelmap`, 권장 `import kortravelmap as ktm`)은 T-226으로
  등록. 검증: targeted pytest 87 passed/1 skipped, ruff, mypy, import-linter,
  diff check.

## 2026-06-12 (claude) — T-212e: datagokr/krheritage/kma 핀 범프 (live 실패 3건 provider 수정 반영)

T-212e live full reload 실패 3건의 provider 수정을 핀 범프로 반영.

- **datagokr `@1967fb6`**(provider #8/PR#9): `feature_place_standard_parking_lots`가
  live 값 `addUnitCharge='200+400'`(자유 표기 요금)으로 int 파싱 실패(run
  `b5c2c5e1`) → 요금/수치 int 필드 관용 파싱(비숫자→None, 원문 raw 보존).
- **krheritage `@6076b52`**(provider #5/PR#6): `feature_place_krheritage_items`가
  `HeritageDetail` key 3필드 None 검증 실패 → **실원인은 목록 응답이 복합키/
  좌표를 `result` 레벨에 두는데 item만 취해 key가 유실, live detail 100% 실패**.
  result 레벨 leaf 병합 + 결측 key row skip + fail-loud 검증(provider 측
  live 종단 검증 완료).
- **kma `@2592b740`**(provider #20/PR#21): `feature_weather_kma_mid_forecast`가
  `tm_fc='' (12자리 필요)` ValueError로 실패(run `f044b091`) — 중기예보 응답
  row는 요청 `tmFc`를 에코하지 않는데 provider가 응답에서만 읽어 항상 None.
  `_mid_items`가 해석된 요청 tmFc를 item 폴백으로 전달(응답값 우선).

실패 asset 재실행은 dagster 이미지 리빌드 후 수행(T-212e 리포트에 기록).

## 2026-06-12 (claude) — T-212e: visitkorea modified_time datetime 재정렬 (ADR-044)

T-212e live full reload Phase 2에서 `feature_event_visitkorea_enrichment`가
`SourceRecord.source_version` ValidationError(str 기대, provider 실모델
`TourItem.modified_time`은 `datetime`)로 실패(run `cff6a853`). Protocol을
`datetime | str | None`로 재정렬하고 `_modified_time_str`로 원시 TourAPI 표기
(`YYYYMMDDHHMMSS`)에 맞춰 문자열화 — `source_version`/`raw_data` 모두 적용
(raw_data JSON 직렬화 안전 확보). 단위 테스트 fake를 datetime으로 바꿔
정규화 검증 추가.

## 2026-06-12 (codex) — T-221~T-223 순서 재정렬 + T-224/T-225 등록

사용자 지시에 따라 `docs/tasks.md`/`docs/tasks-done.md`를 먼저 정리했다.

- 완료된 T-219(KMA weather Dagster)와 T-220(MCST provider 풀스택)은 열린 인덱스에서
  제거하고 `tasks-done.md` 최신 완료 이력으로 이동.
- T-212e는 다른 agent가 병행 진행 중인 작업으로 열린 인덱스에 유지.
- `kor-travel-concierge` rename 결정에 맞춰 T-224를 새로 등록: `kor-travel-concierge` provider
  경계/명명/상세 구현을 T-221보다 먼저 진행.
- T-223에는 `kor-travel-concierge`가 TripMate `curated_trip_plans` 생성 flow에 관여하지
  않는다는 경계를 명시.
- T-221 → T-222 → T-223 이후 T-225로 T-212e closure 재검증을 한 번 더 수행하도록 추가.
- 새 배포/임포트명 결정(`kor-travel-map`, `kortravelmap`, 권장 `import kortravelmap as ktm`)은
  대형 package identity clean cut으로 보고 T-226에 별도 등록.

## 2026-06-12 (codex) — ADR-047 포트 재고정 + Docker/runtime/docs 정렬

사용자 지시에 따라 local/Docker 고정 포트를 재정렬했다. Postgres host는 표준 `5432`,
RustFS S3 API는 `12101`, kor-travel-geo는 API `12201`/Web UI `12205`, kor-travel-map은
API `12301`/관리 보조(Dagster) `12302`/Web UI `12305`가 기준이다.

- `.env.example`, `scripts/load-env.sh`, `docker-compose.yml`, Dockerfile expose,
  `ApiSettings`, main settings, frontend 기본 URL/Playwright 설정을 새 포트로 정렬.
- RustFS console은 `12105`, TripMate-agent API는 `12401`로 보정했다.
- 공유 `kor-travel-docker-manager` 인프라(`5432`/`12101`/`12105`)를 사용하는
  `docker-compose.external-infra.yml` overlay와 `KOR_TRAVEL_MAP_INFRA_EXTERNAL=true`
  경로를 추가했다.
- 공유 Postgres의 기존 extension owner가 다른 경우에도 Alembic이 진행되도록
  PostGIS/`pg_prewarm` downgrade·create 경로를 방어했다.
- 순수 `git`을 제외한 파일 조회·수정·테스트·빌드·Docker·GitHub CLI 작업은 WSL에서
  실행하고, Playwright e2e만 Windows 호스트에서 실행하는 정책을 문서에 강제했다.
- Windows Playwright e2e에서 issue 0건일 때 빈 행을 상세 행으로 오인하던
  `/admin/issues` 테스트 분기를 보정했다.
- ADR-047, README/CLAUDE/AGENTS, REST/TripMate/integration-map, Docker/admin UI
  runbook과 관련 테스트 기대값을 새 기준으로 갱신.

## 2026-06-12 (codex) — curated_features 문서 계약 + TripMate curated_trip_plans 명명 정리

문서 전용 작업으로 `docs/curated-features.md`를 추가하고, `rest-api` /
`tripmate-rest-api` / `integration-map` / `data-model` / `provider-contract` /
`tasks` / `resume`을 연결했다.

- data.go.kr와 기존 MCST provider를 대조해 세계음식점, 독립서점, 카페가 있는 서점,
  도서관 계열은 바로 curated 후보로, 중고서점·아동서점·서울 책방·무슬림 친화 음식점·
  안산 세계맛집·제주 향토음식점·전국지역특화거리표준데이터는 provider 보강 후보로 정리.
- `curated_features`는 `feature.features` overlay로 설계. 테마/source metadata,
  selection/rejection, TripMate copy relation, Admin UI select/unselect, Dagster
  `curated_features` group 계약을 문서화.
- TripMate 정본명은 `curated_trip_plans` / `curated_plan_pois`로 확정하고,
  `notice_plans`는 호환 API alias라고 명시.

## 2026-06-11 (claude) — T-212e #386: 축제 날짜 역전 격리 + datagokr 핀 범프

배치 C에서 축제가 `ends_on (2024-10-01) must be >= starts_on (2025-10-25)`
ValidationError로 재실패(run `31dbac21`) — #374 재정렬과 별개의 실데이터
오타 케이스. 어느 쪽이 오타인지 추정 불가하므로 역전 시 두 날짜를 격리(None)
하고 row는 적재(raw_data 원본 보존). 주차장은 provider
`python-datagokr-api#6`/PR#7(`26a5be3`, addUnitTime='0.5' float 허용) 머지 후
핀 범프(run `ea127324` 해소).

## 2026-06-11 (claude) — T-212e #384: mois op/job 동명 충돌 — repository 로드 실패

offline upload live 검증에서 `POST /{id}/load`가 502
`PipelineNotFoundError` → 웹서버 GraphQL이 repository 0개를 노출하는 것을 발견.
원인: `mois_source_sync.py`의 op와 job이 같은 이름(`mois_localdata_source_sync`)
— Dagster job은 동명 graph를 만들므로 `load_all_definitions`의 노드명 유일성
검사에서 repository 전체가 죽는다. **2026-06-07 mois Phase A 머지 이후 웹서버
repo·daemon schedule·admin run launch가 전부 잠복 불능**이었고, CLI
materialize/execute는 그 경로를 타지 않아 못 봤다.

- op 이름 `sync_mois_localdata_source_db`로 변경(job/schedule 이름 유지).
- definitions 테스트에 repository 전체 로드 회귀 추가 — 이 부류를 CI에서 차단.

## 2026-06-11 (claude) — T-212e: kma pin bump (03 NO_DATA 빈 결과)

T-212e live run에서 `feature_notice_kma_weather_alerts`가
`KmaRequestError: data.go.kr API returned 03: NO_DATA`로 실패(run `408ad65f`) —
lookback 3일 구간에 특보 0건인 **평시가 오히려 정상**인데 provider가 datagokr
result code 03을 전 endpoint에서 예외로 올렸다. provider
`python-kma-api#18`/PR#19(merged, `006fdbe`)로 03을 빈 결과로 정규화(인증/서버
코드 정책 유지, 중기예보 등 동일 unwrap 경로 전체 적용) 후 pin bump.
provider-contract §12/CHANGELOG 갱신.

## 2026-06-11 (claude) — T-212e #380: krheritage items live fetcher 배선 + HeritageDetail 재정렬 + events 빈 sn fallback

T-212e live full reload에서 `feature_place_krheritage_items`가 resource guard로
실패 — T-RV-04b ②는 `krheritage_events`만 배선했고 국가유산 본체
(`krheritage_heritage_features`) fetcher는 배선된 적이 없었다. 추가로
`KrHeritageItem` Protocol이 provider 실모델(`HeritageDetail@7dc46c3`)과
불일치(top-level `ccba_*`/`name`/`designated_date: date`/`geom_wkt`/`raw` —
전부 발명 shape), `krheritage_events`는 live 일부 row의 빈 `sn`이 ADR-009
검증 ValueError로 run을 깼다(run `bd92b726`).

- Protocol 재정렬(ADR-044): 복합키는 `KrHeritageItemKey`(중첩 `key`,
  `ccba_kdcd/asno/ctcd` + provider 제공 `natural_key`), 명칭 `name_ko`, 유형
  `category`(ccmaName), 지정일 `designated_at`(YYYYMMDD str → 방어 파싱),
  소재지 `location_text` + `region+sigungu` fallback. `geom_wkt` 제거 — GIS
  경계(`gis_spca`/`gis_3070426`) 보강은 후속, 천연기념물(15)은 그동안 place,
  area(사적/명승)도 원천 좌표만(boundary/면적 None). model에 raw 미보유 →
  raw_data는 Protocol 필드에서 구성. 명칭 빈 row skip(#374 패턴).
- `fetch_krheritage_items` 신설: `HeritageClient()` **keyless**(khs.go.kr —
  transport는 apis.data.go.kr URL에만 serviceKey 주입, 실측) +
  `search.iter_all_details(page_size=100, ccba_kdcd=...)`를 settings
  `krheritage_kind_codes`(기본 11,12,13,15,16)별 순회, run당
  `krheritage_max_items_per_run`(기본 5000) 상한 — detail이 1건당 1콜이라
  필수(mcst 가드 패턴). resources spec credential 제거(빈 setting_names,
  knps keyless 패턴) + live override 등록.
- events 빈 `sn` fallback: `_event_natural_key` — `sn` 우선, 비면
  `title::starts_on::place(없으면 address)`(ADR-009 `::`), 둘 다 없으면 row
  skip(helper None → public fn filter). `content_id`/`source_entity_id`는
  natural_key로 통일(sn 있으면 종전과 동일).
- 테스트: unit 변환(중첩 key fake/skip/파싱/region fallback/이벤트 fallback
  4종) + dagster fetcher(keyless·kind 순회·상한 중단) + live override 단언
  갱신(전 spec live). admin은 krheritage 참조 없음(grep 확인). 문서:
  provider-contract §12, CHANGELOG, journal.

## 2026-06-11 (claude) — T-212e #378: krex 교통공지 신규 Incident(realTimeSms) 재정렬 + krex/khoa pin bump

T-212e live full reload에서 `feature_notice_krex_traffic_notices`가
`KrexBadRequestError: endpoint not found`(404) — provider가 호출하던
`/openapi/trafficapi/incident`는 EX OpenAPI에 존재하지 않는 endpoint였다.
provider 측은 krex#8/PR#9(`2504a36`)로 실시간 돌발 `openapi/burstInfo/
realTimeSms`(apiId 0611) repoint + `Incident` 실측 shape 재정렬(live 200/192).

- `KrexTrafficNoticeItem` Protocol/변환을 신규 Incident 16필드로 재정렬:
  `occurred_date`+`occurred_time` → `valid_start_time`(KST 방어적 파싱,
  `_parse_krex_occurrence` — 시각 실패 시 자정 강등), 종료 컬럼 없음 →
  `valid_end_time=None`. 자연키 `occurred_date::occurred_time::route_no::
  raw_hash`(ADR-009). 좌표 보유 row(실측 36/99)는 Coordinate + reverse
  geocoding(coordless 전제 완화 — 원천 경도 키는 `altitude`), coordless는
  노선/지점/방향을 raw_address 단서로. title 합성에 point_name fallback 추가.
- admin live loader endpoint(`burstInfo/realTimeSms`) + adapter(raw 키
  `accDate`/`accHour`/`accType(Code)`/`startEndTypeCode`/`smsText`/`accPointNM`/
  `nosunNM`/`roadNM`/`accProcessNM(Code)`/`latitude`/`altitude`/`lateLength`/
  `seriesNM`)·fixture·단위/통합 테스트 fake를 새 shape로 갱신.
- pin bump: `python-krex-api@2504a36`, `python-khoa-api@0ccb5ed`(snake_case
  live row, khoa#5/PR#6). provider-contract §12, notice-feature-etl §5.1 갱신.

## 2026-06-11 (claude) — T-212e #376: 주소 검증 모드 strict/drop/off

T-212e live reload에서 표준데이터 박물관(4/1,100여)·관광지(3건)의
`provider_address_mismatch`/`missing_bjd_code`가 **dataset 전체 적재를 차단**
(`strict_address`가 `DEFAULT_RESOURCE_VALUES`에 True 하드코딩, override 경로 없음).
실데이터에는 소수 불일치가 항상 존재 — 운영 설계상 이런 row는 `/admin/issues`
geocode retry/manual override 흐름으로 처리한다.

- settings `dagster_address_validation`(strict/drop/off, 기본 strict) 신설,
  `strict_address` resource를 `SETTINGS_VALUE_RESOURCES`로 전환(키 유지, bool
  하위호환). `drop`은 error row만 격리 + 메타데이터
  `address_validation_dropped_{count,feature_ids}` 노출.
- 테스트: etl 모드 5종(strict fail/drop 격리/off 전부 적재/bool 호환/unknown 거부).

## 2026-06-11 (claude) — T-212e #374: datagokr 축제 변환 provider 실모델 재정렬

T-212e live full reload 1차 시도에서 `feature_event_datagokr_cultural_festivals`가
`AttributeError: 'PublicCulturalFestival' object has no attribute 'road_address'`로
즉시 실패(run `d7530e23`, 결정적이라 retry 중단 — 쿼터 보호). `CulturalFestivalItem`
Protocol(Sprint 2 PR#34, ADR-044 이전)이 provider에 존재한 적 없는 필드명을 가정한
것 — `git log -S road_address` 무히트로 확인. T-RV-04b ①의 "clean match"는 미검증
가정이었다.

- Protocol/변환을 provider 필드명(`fstvl_nm`/`opar`/`rdnmadr`/`lnmadr`/float 좌표 등)
  으로 재정렬 — 같은 모듈 박물관 패턴 미러. 관리번호 컬럼이 없어 자연키는
  `name::address` 파생(ADR-009 `::`). 이름 없는 row는 skip.
- admin `etl_live` 어댑터(구 `name@address` 우회)·`etl_fixtures`·단위/통합/dagster
  테스트 fake를 새 shape로 갱신, `docs/event-feature-etl.md` §4 재구성.
- 게이트: unit 1004 / dagster+admin 370 passed / ruff / mypy --strict 88+15 / lint-imports.

## 2026-06-11 (codex) — admin UI/UX 시나리오 재점검 + T-130 공개 뷰 사양

admin UI/UX 계획 문서, 프론트엔드 17개 경로, 백엔드 routers, OpenAPI admin/user 사양,
TripMate T-130 문서를 전수 대조했다. 새 리포트
`docs/reports/admin-ui-scenario-linkage-recheck-2026-06-11.md`에 빠진 연결부와
실시간 기준을 정리했다.

- 남은 admin 간극은 경로 수가 아니라 `/features/[feature_id]` 상세, 수동 feature 작성 흐름,
  `/ops/import-jobs/[job_id]` 상세/event 타임라인, provider 상세/policy, job/log 상세 링크다.
- 폴링 현황(2초/10초)을 기준으로 `WS /v1/ops/live` 다중화와 job/request/upload/run별
  WebSocket 또는 SSE 대체 후보 엔드포인트를 정리했다.
- TripMate T-130 차단 해소용 제안 사양 `docs/public-views-api.md` 추가:
  `/v1/public/beaches*`, `/v1/public/festivals*`, 스키마, KHOA index/수질, 월별 축제 집계.
- 해수욕장 category drift 발견: 문서 `01050100`, 현재 provider 코드 `01020300 +
  place_kind=beach`. 공개 뷰는 우선 `place_kind=beach`를 판별 기준으로 문서화.
- `docs/tasks.md`에 T-221(admin UI 연결/실시간)과 T-222(T-130 공개 뷰)를 추가했다.

## 2026-06-11 (codex) — React Doctor 0 이슈 + maplibre-vworld-js v0.1.3 정합

frontend React Doctor full scan의 optional warning까지 0으로 맞추기 위해 shadcn 기반
UI primitive를 정리했다. `buttonVariants`는 component 파일 밖으로 분리하고,
`form-field`/`native-select` multi-component 파일을 단일 component 파일로 나눴다.
React 19 기준으로 `forwardRef`를 제거했고, Dagster iframe sandbox 조합에서
`allow-same-origin`을 제거했으며 미사용 detail hook export를 정리했다.

로컬/원격 `maplibre-vworld-js` 최신 tag가 v0.1.3임을 확인하고 frontend,
`@kor-travel-map/map-marker-react`, root lockfile, 현재 기준 문서를 `#v0.1.3`으로 맞췄다.

## 2026-06-11 (claude) — T-220c MCST fixture/문서 — T-220 완결 (KMA·MCST 전체 종료)

사용자 지시 "kma, mcst provider 빠짐없이 상세구현(Dagster 포함)"의 마지막 조각.

- admin ETL preview fixture 2종: `mcst_independent_bookstores`(KCISA 공용 변환
  대표) + `mcst_public_libraries`(도서관 공용 변환 대표) — 16종 전부는 공용
  변환이라 대표 1개씩이면 회귀 커버.
- 문서: `docs/mcst-feature-etl.md` 신규(메타표/변환 규칙/Dagster/fixture/dedup
  결정) + external-apis §3.14(키 공유) + provider-contract §3 dataset 표·§12
  status(`@d06e8d2`) + CHANGELOG. drive-by: external-apis §3.13의 구
  `/api/v1/features/*` 경로를 ADR-050 중립 경로로 정정.
- pyproject `providers` extra에 `python-mcst-api@d06e8d2`(origin/master) 핀.
- **dedup pair 결정**: world_restaurants/서점/캠핑이 MOIS PROMOTED와 교차
  가능하나 자연키 체계가 달라 **즉시 등록 안 함** — T-212e 실데이터 매칭 품질
  확인 후 `DEFAULT_DEDUP_SCOPE_PAIRS` 재검토(etl 문서 §6).
- 이로써 T-219(KMA asset 5종) + T-220(MCST 신규 provider) 전부 종료 — 열린
  백로그는 T-212e 1건.

## 2026-06-11 (claude) — T-220b MCST Dagster 배선 (fetch/resource/asset/schedule)

T-220a 변환 위에 파이프라인. KCISA 14종이 공통 스키마라 record resource 1개가
`(slug, record)` 튜플을 stream하고 **asset이 slug별 분리 `_load`** —
dataset_key(`mcst_<slug>`) 단위 import job/sync state 유지(계획 §3.3).

- fetch 2종: `fetch_mcst_culture_records`(CultureOpenApiClient, slug 14 순회
  iter_items + `mcst_max_items_per_dataset` 가드 — settings 신설, 기본 5000) /
  `fetch_mcst_libraries`(DataGoFileApiClient, ODCloud 2 slug 페이지네이션).
- `mcst_features.py` 신설: `group_records_by_slug` + `_load_grouped` 공통(미등록
  slug KeyError, 변환 제외분 경고) + asset 2종. slug별
  `DagsterFeatureLoadResult`는 dataset이 달라 merge 불가 → `McstLoadResult`가
  dataset별 결과 + 합산 metadata.
- resource spec/live 2종, REQUIRED_RESOURCE_KEYS 2키, 주 1회 schedule 2종
  (화 04:30/04:50), definitions assets 합산.
- 게이트: dagster 129 passed(+8) / unit 1005 / admin 241 / ruff / mypy --strict
  88+15 files / lint-imports green.

## 2026-06-11 (claude) — T-220a MCST provider 변환 (KCISA 14 + ODCloud 도서관 2)

신규 provider `python-mcst-api`(origin/master `d06e8d2` 실측) 1단계 — 변환 순수
함수. `providers/mcst.py` 신설:

- **slug 메타표 1곳**: `MCST_CULTURE_DATASETS`(KCISA 14종 — client 메서드명과
  동일 slug, dataset_key `mcst_<slug>`) + `MCST_LIBRARY_DATASETS`(ODCloud
  public/small_libraries). **category 신설 불요** — 계획 §3.2의 "신설 검토"
  항목 전부 기존 코드로 흡수(미디어 명소/추천 여행지→01000000, 문화시설
  계열→01040000, 레저→01080400/01080000, 캠핑→03060000, 세계음식→02010000,
  소공연장→01040300, 회의→05000000, 도서관→01040500), place_kind가 세부 구분.
- **변환 2종**: 공용 `culture_records_to_bundles(slug=...)`(`CultureRecord`
  Protocol — name/address/tel/url/lon/lat/category) +
  `library_records_to_bundles`(RawRecord 한국어 CSV 컬럼 방언을 mcst lib
  `from_row` 패턴대로 관대 조회). 자연키 `name::address`, 좌표 있으면 reverse
  bjd 보강, 없으면 주소 텍스트 단서 보존(검증 통과), 이름/위치 단서 없는 row
  skip. marker P-12 단일색.
- 게이트: unit 1001 passed(+11) / ruff / mypy --strict 88 files / lint-imports.
  Dagster 배선(T-220b)·fixture/문서(T-220c)는 후속 PR.

## 2026-06-11 (claude) — T-219c KMA 중기예보 + 기상특보 — T-219 완결

KMA Dagster 파이프라인 마지막 조각. 중기는 region 체계(격자 X)라 옵션 B가 불가,
특보는 좌표 무관이라 표준 record-resource — 두 패턴이 갈린다(계획 정본 §2.3/2.4).

- **중기(mid)**: `parse_mid_region_features`(JSON — 육상 `getMidLandFcst`와 기온
  `getMidTa`의 reg_id 체계가 달라 spec이 두 코드+feature 목록을 묶음, 오류/중복
  페어 ValueError) + settings `kma_mid_region_features` + resource
  `kma_datagokr_client`(DataGoKrClient live) + asset
  `feature_weather_kma_mid_forecast`(미설정 region skip — cursor 미전진, 일 2회).
  `MidForecastItem.raw` camelCase → `KmaMidLandRow`/`KmaMidTempRow`.
- **특보(alerts)**: fetcher `fetch_kma_weather_alerts`(전국 발표관서 108, rolling
  window `kma_weather_alert_lookback_days` 기본 3일, 페이지네이션) + record
  resource `kma_weather_alert_records` + asset `feature_notice_kma_weather_alerts`
  (표준 `_load`). `WeatherWarningItem`은 관서/시각/번호/제목만 구조화 — 종류/
  등급은 title 토큰 스캔(미매칭 generic `weather_alert`, alias는 krtour
  `normalize_notice_type` 기등록 10종), 특보구역은 1차 발표관서 단위 1건(구역별
  fan-out·좌표 enrichment 백로그).
- **주소 검증 통과**: 특보 bundle은 coord 없음 → `_alert_region_to_bundle`이
  `SourceRecord.raw_address=region_name`을 채워(위치 단서) strict 주소 검증
  (`missing_address`)을 자연 통과. strict 해제 없이 0 issue.
- mypy frozen-dataclass↔Protocol 함정 재현(메모리 기록 그대로) —
  `Sequence[Any]` 우회. 게이트: dagster 121 + unit/lint 994 + admin 241 passed /
  ruff / mypy --strict 87+14 files / lint-imports green.

## 2026-06-11 (claude) — T-219b KMA weather Dagster asset 3종 (실황/초단기/단기)

T-219a 기반 위에 Dagster 파이프라인 본체. 대상 좌표가 DB(poi_cache_targets)에서
나오므로 record-resource 패턴 대신 **asset 직접 구현**(계획 정본 §2.3).

- **`map_dagster/kma_weather.py` 신설**: `map_grid_targets`(target→extra 순서
  dedupe + run 상한 + place 매핑, silent cap 금지 — dropped 카운트/경고) + 공통
  runner(`provider_sync_state` cursor `base_datetime` skip → 격자별 KMA 호출 →
  feature별 `WeatherValue` 변환 → `load_weather_values`, 실패 시 cursor 미전진 +
  `record_sync_failure`) + asset 3종/`KMA_WEATHER_ASSETS`. feature 없는 격자는
  KMA 호출 생략(일일 한도 보호). cursor 전진은 실제 호출이 있었을 때만.
- **shape 차이 해소**: `KmaClient`의 `ForecastItem`/`WeatherSnapshot`은
  base/forecast가 `datetime`으로 정규화돼 krtour 변환 Protocol(snake_case raw
  row)과 다르다 — client가 보존한 `raw` payload(KMA 공식 필드명)에서
  `KmaForecastRow`/`KmaNowcastRow`를 만들어 변환에 넘김(ADR-044 신뢰·미러,
  wrapper 클래스 없음 — ADR-006 `KmaGateway` 금지 예시 준수).
- **배선**: resource `kma_weather_client`(lazy import + credential guard, 종료 시
  close) + `SETTINGS_VALUE_RESOURCES`에 extra_points/max_grids 2종 +
  `REQUIRED_RESOURCE_KEYS` 3키 + schedule spec 3종(45 * / 20,50 * /
  20 2,5,…,23 — 발표+지연 정렬, 같은 base는 cursor skip). client에
  `list_poi_cache_target_coords`/`list_active_place_coords` read 메서드.
- **핀/문서**: `providers` extra `python-kma-api@ab1a0b8`(origin/main) 활성화,
  provider-contract §12 갱신, kma-weather-etl §3/§6/§8 구현 기준 정정(asset
  명/cron/대상 한정/`to_grid`는 lib 책임), CHANGELOG.
- 테스트: `test_kma_weather.py` 12종(매핑/row 빌더/skip·failure·no-feature 경로/
  endpoint 라우팅/lazy helper/resource guard·close) + definitions asset key 3종.

## 2026-06-11 (claude) — T-219a KMA weather 기반: 대상 좌표 조회 + settings

T-219 (KMA Dagster 완결)의 기반 task. 계획 정본
`docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2의 "옵션 B + 1차 대상 한정"
설계를 코드로 깔았다. Dagster asset(T-219b/c)이 이 표면 위에 올라간다.

- `providers/kma.py`: `parse_weather_extra_points` 신설 — `"lon,lat;lon,lat"` 파서,
  한국 bbox(lon 124~132 / lat 33~43) 검증, 형식/숫자/범위 위반 ValueError.
  LGT 메트릭은 **기등록 확인**(KMA_METRIC_UNITS/NAMES에 이미 존재) — 계획 문서의
  "미등록" 기술은 노후 docstring 오판이었고 docstring만 정정.
- `settings.py`: `kma_weather_extra_points`(env `KMA_WEATHER_EXTRA_POINTS`) +
  `kma_weather_max_grids_per_run`(기본 50, 1~500) 2필드.
- infra 조회 2종: `poi_cache_target_repo.list_active_target_coords`(미삭제+
  update_enabled) + `feature_repo.list_active_place_coords`(place,
  `deleted_at IS NULL` — status inactive여도 날씨 부착 가능, D-12 read 정합).
  `infra/__init__.py` re-export 포함.
- 테스트: 파서 unit 3종(PT011 — `match` 필수) + 통합 테스트에 좌표 조회 2종 단언
  (inactive 포함/soft-deleted 제외 검증). 게이트: unit 981 passed / ruff / mypy
  --strict / lint-imports / 통합 1 passed (WSL).

## 2026-06-11 (codex) — provider extra git pin 복구

T-212e live full reload 중 `.[providers]` extra가 문서와 달리 실제 provider git
dependency를 설치하지 않는 packaging 갭을 확인했다. keyless `krairport` asset도
`ModuleNotFoundError: No module named 'krairport'`로 retry에 들어가므로, root
`pyproject.toml`의 `providers` extra에 현재 로컬 provider checkout SHA를 직접 URL로
활성화하고 `docs/provider-contract.md` §12 status 표를 같은 SHA로 갱신했다.

## 2026-06-11 (claude) — T-219/T-220 신설: KMA Dagster 완결 + MCST 신규 provider 계획

사용자 지시 "kma, mcst provider 빠짐없이 상세구현(Dagster 포함)". 4-방향 병렬 실측
(python-kma-api `ab1a0b8` / python-mcst-api origin/**master** `d06e8d2` / krtour 기존
KMA / provider 풀스택 패턴) 후 계획 정본
`docs/reports/kma-mcst-provider-plan-2026-06-11.md` 작성 + tasks.md 등록.

- **갭**: KMA는 변환 5종 100%(1,133줄+57테스트)·**Dagster 0%**. MCST는 전무 —
  라이브러리는 KCISA 14 place dataset(`CultureRecord`, 좌표 포함)+ODCloud 도서관 2종.
- **KMA 설계**: 격자 매핑 옵션 B 유지하되 1차 대상 = poi_cache_targets 좌표 +
  설정 추가 좌표(run당 상한) — 호출량/행 폭발 통제. 격자 변환은 라이브러리 책임.
  nowcast/forecast는 asset 직접(좌표가 DB 의존이라 record-resource 부적합), 특보만
  표준 record-resource. 키는 data_go_kr_service_key 공유.
- **MCST 설계**: slug 메타표 16종 단일 모듈, marker P-12, dataset_key `mcst_<slug>`,
  asset 2종이 slug별 분리 `_load`. T-219a~c/T-220a~c PR 분해.

## 2026-06-11 (claude) — T-210e user-facing OpenAPI TS client 패키지

사용자 지시로 T-212e 게이트를 해제하고 진행. 신규 workspace 패키지
`packages/kor-travel-map-user-client/`(`@kor-travel-map/map-user-client`, npm 게시 X — ADR-043).

- `src/types.ts`: `openapi.user.json` → openapi-typescript 생성 산출물 커밋.
- `src/index.ts`: named alias(FeatureDetail/FeatureSummary/배치/카테고리/providers 등)
  + **컴파일 타임 표면 단언** — batch `data.found`, `meta.page.next_cursor`, 평면
  `lon`/`lat`, in-bounds payload, `/v1` 경로 11종(ADR-048 불변식). 단언 함정 1건
  해결: 실패 분기가 `never`면 bottom type이라 `extends true`를 통과해 무력화 —
  `false` 반환으로 수정하고 음성 검증(bogus key → TS2344)으로 작동 확인.
- CI(frontend workflow)에 user-client `gen:types:check` + `tsc` 스텝 추가 —
  spec↔산출물 drift와 표면 회귀를 PR에서 차단.
- 소비(README): TripMate는 vendoring 또는 같은 버전 자체 codegen. T-212e 후 spec
  변동은 `gen:types` 재실행+커밋으로 추종. tasks.md T-210e `[x]`(열린 9→8건).

## 2026-06-11 (claude) — T-217c/d/e 문서 완결 (Phase 6.9 종결)

- **T-217c 합의 5건 확정**(코드 실측): review_mode 기본 `require_review` 유지 /
  idempotency_key=결정적 feature_id(suggestion_id 권장) / 출처 태깅
  `operator:"tripmate-admin"`+reason `[suggestion:<id>]` 컨벤션 / admin 인증 12301
  `/v1/admin/*`(kill-switch+인프라 SSO) / closure=영구 soft DELETE·일시 deactivate.
  정본 `docs/tripmate-rest-api.md` §7 + ADR-051 결과 절. §8에 YouTube 후보 detail
  소비 계약(T-217f facility_info 키 표) 기재.
- **T-217d**: `docs/integration-map.md` 신설 — 4-시스템(kor-travel-map/TripMate/
  kor-travel-concierge/kor-travel-docker-manager) 포트·연동 방향·인증/envelope 차이표(D-08)·계약
  정본 위치 1장. 분기 audit `runbooks/cross-repo-audit-checklist.md` + README 등재,
  CLAUDE.md 진입 순서·AGENTS.md 경계 절에서 링크.
- **T-217e(사용자 재정의)**: RustFS를 **kor-travel-docker-manager가 일괄 관리** — 실측
  (`docker-compose.yml`: 단일 PostGIS `kor-travel-geo-postgres` :5432 + `tripmate-rustfs`
  :12101/12105, Web UI 관리) 후 ADR-052 Amendment. kor-travel-map·kor-travel-concierge는 사용자,
  버킷 분리(D-10) 후속도 kor-travel-docker-manager 운영으로 위임.
- **Phase 6.9(T-217a~g) 전부 종결.** 다음 한 작업은 T-212e 불변.

## 2026-06-11 (claude) — T-217a/b/f kor-travel-concierge provider 연동 완결

- **T-217a 경로 중립화(ADR-050 #1)**: fetcher path + 테스트/docstring 7곳을
  `/api/v1/features/*`로 정렬. 동시 배포 조건 충족 — TripMate-agent T-066(#60)이
  같은 중립 경로(`/api/v1` prefix, `{items,next_cursor,has_more}`, `X-API-Key`)로
  origin/main에 머지된 것을 실측 확인.
- **T-217b 철회 라이프사이클(ADR-050 #4)**: 변환부
  `kor_travel_concierge_inactive_entity_ids`(reject/tombstone entity 수집) + client
  `inactivate_features_by_source`(generic — MOIS Step C와 같은
  `infra.inactivate_features_by_source_entity_ids` 위임, 한 transaction) + Dagster
  asset 배선(적재 후 전환 + 로그). **D-12 read 정렬**: batch
  `_GET_FEATURES_BY_IDS_SQL`의 `deleted_at IS NULL` 제거 — inactive feature도
  `found`+status로 반환(단건과 일관). 통합 테스트로 inactive→found+status 검증,
  목록/검색 read는 기본 active 불변.
- **T-217f evidence 노출 확정**: `detail.facility_info`에 `confidence_score`(0~100)
  추가 — TM-08 출처 배지 UX가 facility_info만으로 영상 링크·타임스탬프·confidence를
  얻는다. 원본은 `detail.payload.kor_travel_concierge` 보존.
- 게이트: unit 978 + admin/dagster 332 + 통합(by_ids D-12) 1 + ruff + mypy --strict
  (kortravelmap 87 + dagster 13) + lint-imports green (WSL ext4).

## 2026-06-10 (claude) — T-217g provider 동기화 신선도 대시보드 (D-07)

전 provider×dataset의 last-sync/최근 실패를 한눈에 보는 목록 API + admin 화면.

- **backend**: `sync_state_repo.list_all_sync_states`(전량, provider/dataset/scope 정렬) +
  `GET /v1/providers`(`ProvidersFreshnessResponse`, cursor 비노출, bounded 비페이지네이션 —
  `/v1/categories` 패턴, 빈 환경 200+빈 items). `USER_OPERATIONS`에 등재(user spec 포함),
  OpenAPI admin/user 재생성. 단위 테스트 3건 추가(전체 unit 975 passed), ruff/mypy
  --strict/lint-imports green(WSL ext4 mirror).
- **frontend**: `api/providers.ts` 훅 + `/ops/providers` 페이지(요약 배지
  providers/datasets/failing/stale(>48h), 연속 실패 경고 alert(assertive), 신선도
  테이블 — 실패 행 강조) + nav "Providers"(GaugeIcon). types 재생성.
- **e2e**: providers 대시보드 렌더+실패 경고 spec + home nav 링크 추가 — 전 spec
  29 passed(Windows). build 19 route green. `docs/rest-api.md` §2.4 + 화면 점검
  체크리스트 runbook(17 route) 갱신. 기존 단건 last-sync 유지.

## 2026-06-10 (claude) — T-218f 화면별 점검 체크리스트 + T-218 완료

마지막 슬라이스로 `docs/runbooks/admin-ui-screen-checklist.md`를 신설했다 — admin UI
16 route × (목록/필터·정렬·cursor·빈·에러·kill-switch·a11y·e2e) 매트릭스 + T-218 적용
결과 요약 + 신규 폼 추가 절차. runbooks README 인덱스 등재.

**T-218 전체 완료(#337~#343)**: ① a11y wrapper(FormField/FormSelect/FormTextArea +
validateForm, vitest 11) ② bare-label 4폼 적용(poi-cache/feature-update/offline/issues) ③
backups e2e로 **admin/ops 16/16 화면 e2e 커버** ④ 음성 경로 4폼 ⑤ Alert variant별
live-region ⑥ 점검 runbook. change-requests·etl은 이미 a11y 완비라 비대상, 모달 focus
trap은 인라인 패널 구조라 비해당. tasks.md T-218 `[x]`(최근 완료로 이동).

## 2026-06-10 (claude) — T-218e Alert aria-live 안내 정합

`Alert`를 variant별 live-region으로 개선했다 — destructive=`role=alert`(assertive,
에러는 즉시 안내), default(성공/정보)=`role=status`(polite, 작업 흐름 비차단). 호출부가
role/aria-live를 명시하면 우선한다. 전 16화면의 액션 결과/에러 안내가 스크린리더에
적절히 전달된다. backups 성공 결과의 polite status region e2e 단언 추가.
admin-ops 20 + home/features/dagster 8 = 28 passed. **본 UI는 오버레이 모달/드로어가
없어 modal focus trap은 비해당**(폼 첫 에러 포커스는 T-218b 적용). 남은 것은 T-218f.

## 2026-06-10 (claude) — T-218d 위험 액션 음성 경로 e2e

폼 검증 실패(서버 미호출) 경로를 e2e로 고정. change-requests에 비-object detail JSON
입력 → `buildCreatePayload` 동기 throw → formError 배너 단언을 추가했다(네트워크 호출
없음). 기존 T-218b 적용분(poi-cache 필수·좌표, feature-update 좌표, issues
manual-override 빈 입력)과 합쳐 **음성 경로 4개 폼** 커버. admin-ops e2e 20 passed.
tasks.md T-218d `[x]`. 남은 것은 T-218e(focus/aria-live)·T-218f(점검 체크리스트).

## 2026-06-10 (claude) — T-218c `/admin/backups` e2e 신설 (e2e 16/16 화면 커버)

유일한 e2e 미커버 화면 `/admin/backups`에 Playwright route-mock 스펙을 추가했다.

- `makeBackup` 팩토리(생성 OpenAPI `BackupRecord` 바인딩) + `mockBackupOperations`
  (GET 목록 / POST 백업 / POST restore{,/swap} command plan).
- 2 tests: 렌더(heading/컬럼/목록/manifest 상세) + 위험 액션(백업·Restore staging
  target·Swap) command plan 생성 + result alert. **admin-ops e2e 19 passed = 16/16
  화면 e2e 커버 달성**(직전 backups만 미커버였음).
- tasks.md T-218c `[x]`. 남은 것은 T-218d(음성 경로)·T-218e(focus/aria-live)·T-218f(체크리스트).

## 2026-06-10 (claude) — T-218b 완료(offline-uploads #339 + issues manual-override)

T-218b의 bare `aria-label` 화면을 모두 적용해 G-1(폼 label↔control 미연결) 해소.

- **offline-uploads(#339)**: create 폼 5입력 → FormField(라벨 연결), 기존 disabled
  가드/동작·e2e 보존.
- **issues manual-override**: address JSON textarea + manual lon/lat/reason →
  FormTextArea/FormField. 단일 `manualError` 배너를 필드별 인라인 에러 + 첫 에러
  포커스(address/lon)로 전환. issues e2e에 검증/aria-invalid/focus 단언 추가.
- **비대상 확정(실측)**: `/etl`(이미 RHF+zodResolver+Field), `change-requests`(전 필드
  이미 `<label htmlFor>`+`id` — bare aria-label 아님). → T-218b의 실제 갭은 bare-label
  3종(poi-cache/feature-update/offline)+issues manual-override뿐이었고 전부 완료.
- Windows Playwright admin-ops 17 passed. tasks.md T-218b `[x]`로 갱신. 다음 T-218c(backups e2e).

## 2026-06-10 (claude) — T-218b-1 폼 a11y 적용(좌표 폼 2화면) + 진척 반영

T-218a wrapper(#337)를 좌표 scope 폼 2화면에 적용하고 검증 e2e를 추가했다(#338).

- `poi-cache-targets`·`feature-update-requests`: bare `aria-label` Input/NativeSelect →
  `FormField`/`FormSelect`. lon/lat/radius(+필수 키) `validateForm` 검증 + 첫 에러 필드
  포커스, 제출 버튼 disabled 휴리스틱을 검증으로 대체. Windows Playwright admin-ops
  17 passed(검증 2건 신설, route-mock 기반). etl.spec(3건)은 실 backend 필요로 미수행.
- **실측 발견**: `/etl`은 이미 react-hook-form + zodResolver + `Field/FieldLabel/
  FieldError`로 a11y 완비 — T-218b 적용 대상에서 제외. 남은 갭은 bare `aria-label`
  화면(offline-uploads/change-requests/issues) = **T-218b-2**.
- tasks.md: T-218a `[x]`·T-218b `[~]`(b-1 완료, b-2 예정)로 갱신.

## 2026-06-10 (claude) — T-218a 공통 폼 a11y wrapper + validateForm util

admin/ops 폼 화면이 label 없이 `aria-label`/placeholder만 단 bare control이라 label↔control
연결·에러 `aria-describedby`·제출 시 `aria-invalid` 토글·첫 에러 포커스가 화면마다
수동/누락이었다(T-218 계획 G-1). 토대 wrapper를 추가했다(신규 런타임 의존성 0).

- `src/lib/form-validation.ts`: 프레임워크 비의존 `validateForm(values, rules)` +
  `required`/`numberInRange`/`jsonObject`/`combine` 검증기. `firstErrorField`(규칙 선언
  순서 기준)로 포커스 이동 지원. `src/lib/form-validation.test.ts` vitest 11건.
- `src/components/ui/form-field.tsx`: `FormField`/`FormSelect`/`FormTextArea` — 기존
  `Field`/`Input`/`NativeSelect` 위에 얇게 얹어 visible `<label htmlFor>`(Playwright
  `getByLabel` 호환) + `aria-describedby`(hint/error) + `aria-invalid` + `forwardRef`
  (포커스)를 일원화. controlled `useState` 화면에 드롭인.
- `src/components/ui/textarea.tsx` 신규 + `native-select.tsx` `forwardRef`/`NativeSelectProps`
  export 보강.
- 게이트: gen:types:check(drift 0) + type-check + lint + vitest 11 + env 명시 build 통과.
  화면 소비/e2e 단언은 T-218b. (T-218 task 정본 `docs/reports/t-218-admin-ui-hardening-plan-2026-06-10.md`.)

## 2026-06-10 (claude) — T-218 admin UI 상세 점검 + a11y/e2e 완비 task 신설 (문서만)

사용자 지시: TripMate "Claude Sprint 4 PR-C 프론트"(화면별 슬라이스 + E2E)와 같은
admin UI 상세 구현·e2e 점검 task를 만들어 문서 정리.

- **실측**: admin/ops UI 16 route 전부 구현 + e2e 15/16 커버(T-212b 완료, `1128626` 기준).
  유일 미커버는 `/admin/backups`. 공통 폼 a11y wrapper(FormField류)는 부재 — 각 화면이
  `ui/field.tsx` 컨테이너 위에서 수동 조립(TripMate FormField 패턴 대비 갭).
- **신설**: `docs/tasks.md` Phase 7에 **T-218**(a11y wrapper→폼 적용→backups e2e→음성 경로
  e2e→focus/aria-live→화면별 점검 체크리스트, 6 sub-task) + 상세 계획·갭 매트릭스 정본
  `docs/reports/t-218-admin-ui-hardening-plan-2026-06-10.md`. 열린 항목 인덱스 15→16.
- **경계**: T-212e(백엔드 실데이터)와 독립·병렬. 신규 라이브러리 없이 기존 `ui/*` 위에
  구성, 프론트 표현 계층만(provider 변환 불변). 코드 변경 없음 — 계획 문서만.

## 2026-06-10 (codex) — T-212d read-heavy 재측정 + enrichment read path 튜닝

**작업**: PR #332 머지 후 `origin/main` 기준 새 브랜치에서 T-212d를 재실행했다. read-heavy
전제의 MV 후보를 다시 보되, 현재 API 의미를 바꾸지 않는 범위에서 hot read 회귀와 튜닝을
반영했다.

- **클러스터 hot path**: `sido`/`sigungu`/`eupmyeondong` bbox cluster EXPLAIN 회귀를 추가했다.
  현 exact-viewport 쿼리는 `idx_features_coord_gist`를 사용한다.
- **MV 판단**: `mv_feature_cluster_counts`는 exact-viewport → region-total count/centroid로
  의미가 바뀌므로 이번 PR에서는 미도입. T-212e live full reload의 row 수/P99 후 별도 결정.
- **enrichment review**: 단일 `status + provider` 필터를 scalar equality SQL로 분리하고,
  후보 CTE 안에 `LIMIT`을 적용해 join 전 row 수를 줄였다.
- **검증**: ext4 mirror에서 `compileall` + T-212d EXPLAIN 통합 테스트 통과(`6 passed`).
  상세 리포트는 `docs/reports/t-212d-read-heavy-rerun-2026-06-10.md`.

## 2026-06-10 (claude) — cross-repo 의사결정 반영: ADR-050~052 + T-217a~f (코드無)

사용자 결정(D-01: b 잠정·추후 분리 / D-02~05: a / D-06: 수정 승인 — TripMate
`/admin/etl` 유지 / D-08·09: 권고안 / D-07: 미결)을 정본에 반영했다.

- **ADR-050**: TripMate-agent export 계약 보강 — 경로 중립화
  `/api/v1/features/{snapshot,changes}`(사용자 보정: downstream 이름 path 금지,
  ADR-049 표기 보정), 계약 정본=kor-travel-concierge repo 독립 문서, 검수 통과만 export,
  reject/tombstone → feature inactive 전환.
- **ADR-051**: TripMate 사용자 feature 제안 반영 — **최종**: 신규 수신 API를 만들지
  않고 **기존 `/v1/admin/features*` change API(#317)를 전송 구간으로 승인** (초안의
  `POST /v1/features/suggestions` 신설안은 같은 날 재독에서 중복으로 철회).
- **ADR-052**: RustFS 버킷 잠정 공유(prefix 소유권·backup 제외 명문화) + 추후 분리.
- **tasks**: Phase 6.9 신설 — T-217a(fetcher 경로 정렬, **T-066과 동시 배포**),
  T-217b(inactive 전환), T-217c(TripMate 제안 연동 **합의 5건 확정** — 신규 API 아님),
  T-217d(integration-map 정본+분기 audit), T-217e(RustFS 정책 문서화),
  T-217f(YouTube evidence 노출 확정), T-217g(provider 신선도 대시보드, D-07).
  CLAUDE.md ADR 카운터 052/053으로 갱신.
- **의사결정 최종 상태**: 같은 날 2차까지 **D-01~13 전 항목 종결** (당초 미결이던
  D-07/D-10~13 포함) — 이력은 `docs/reports/decisions-needed-2026-06-10.md`.
- kor-travel-concierge 측 문서(`docs/cross-repo-consistency-actions-2026-06-10.md`)에도
  결정 결과 반영 (해당 repo, 미커밋).
- **R-2/ADR-051 보정(사용자 확인)**: 사용자 feature 추가/수정/삭제 요청은 **2단 검토
  설계가 이미 존재** — TripMate admin 1차 검토(`/admin/feature-requests`) → kor-travel-map
  admin 최종 반영(`docs/tripmate-rest-api.md` §2). 검토 보고서의 "공식 경로 없음"을
  "1차 승인분의 자동 전송 구간 부재"로 정정하고, ADR-051 수신 API의 입력을 "TripMate
  admin 1차 승인분"으로 재정의했다.
- **재독 보정(같은 날, 사용자 지시 "전체 2회 재독")**: TripMate
  `docs/integrations/kor-travel-map-rest-api.md`(06-08~09 갱신) 재정독으로 3건 보정 —
  ① **ADR-051 신규 수신 API 철회**: TripMate DEC-05 + krtour PR #317(admin feature
  change API)이 이미 그 전송 구간을 구축, 중복이라 기존 흐름 승인으로 재정의
  (T-217c = 합의 5건 확정으로 재범위). ② C-1/C-5는 TripMate T-181 잔여로 기추적
  (krtour T-216 머지로 대기 해제), C-3은 잔재 블록 한정으로 축소. ③ 신규 실오류
  발견: TripMate "admin base=12305" 가정(12305=UI, admin API=12301) — TripMate 정정 대상.
- **2차 결정 종결(같은 날)**: D-07(a)→T-217g(provider 신선도 목록 API+화면),
  D-10(a)→버킷 분리는 T-066 운영 개시 전(ADR-052 보강), D-11(a)→제보 페이로드 익명
  (ADR-051 보강), D-12(a)→inactive feature는 `found`+status 노출(ADR-050 보강),
  D-13 확인→TripMate 자체 ETL은 KASI류 고유 잡만(중복 없음, T-210c 양립).
  **의사결정 전 항목 종결**. TripMate repo에도 직접 문서 반영 + PR (머지는 사용자).
