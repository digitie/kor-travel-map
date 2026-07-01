# resume.md — 현재 진척도와 다음 한 작업

## 2026-07-02 (codex) — Feature 지도 notice 최신 표시/이력화 로컬 구현 완료

- **완료(UI)**: Feature 지도 겹친 점 선택 팝업을 선택 메뉴처럼 보이도록 정리했다. 기존 `겹친 지점 N개`
  텍스트와 선택 흐름은 유지한다.
- **완료(데이터)**: `provider_sync.source_records.last_seen_at`을 추가하고, 동일 source payload 재수집은
  Feature 본문/version을 갱신하지 않고 마지막 확인 시각만 갱신한다.
- **완료(notice)**: KREX 교통공지 notice는 사건 단서 기반 stable key로 같은 사건의 payload 변경을
  같은 Feature에 누적한다. Feature 지도 bbox 조회는 같은 notice lineage의 최신 feature만 표시한다.
- **완료(상세)**: admin feature 상세 API/source row에 `last_seen_at`을 노출하고, notice 상세 화면에
  `Notice History` 표를 추가했다. OpenAPI와 frontend generated types를 갱신했다.
- **검증**: targeted unit/API 63 passed, Dagster runner/load enrichment 11 passed, integration 28 passed,
  perf EXPLAIN 7 passed, frontend type-check/gen:types:check/OpenAPI drift/frontend lint(기존 경고 4건)/
  frontend unit 45 passed, frontend production build 통과(필수 env 로컬값 지정), 전체 pytest 1378 passed,
  전체 ruff, `mypy src/kortravelmap`, import-linter 4 contracts, `git diff --check` 통과.
- **미검증**: mocked Playwright e2e는 WSL Playwright Chromium 미설치 + Ubuntu 26.04 미지원으로 실행 불가.
  Windows Chrome fallback launch도 remote debugging pipe 문제로 실패했다.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 작성 폼 장소 종류 최상위화 로컬 구현 중

- **완료(UI)**: 새 Feature 작성과 변경 요청 작성 화면에서 `장소 종류(place_kind)`를 상세 섹션에서
  기본 정보 섹션으로 올렸다. `Feature 종류`가 `place`일 때만 표시한다.
- **완료(UI)**: `area`/`route` Feature는 수동 생성·수정 대상이 아니므로, 변경 요청 작성 화면에서
  기존 `area`/`route` Feature를 불러오면 경고를 표시하고 요청 생성을 막는다.
- **검증**: frontend type-check 통과, frontend lint 오류 없음(기존 경고 4건), frontend unit
  45 passed, `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 지도/주소 코드 후속 보강 로컬 구현 완료

- **완료(UI)**: 겹친 Feature 점 마커 선택 팝업이 즉시 닫히지 않도록 마커/클러스터 클릭 이벤트와
  팝업 닫힘 동작을 보정했다.
- **완료(UI)**: 새 Feature 작성과 Feature 변경 요청 작성의 시도/시군구/법정동/행정동 코드 입력을
  같은 자동검색 팝업으로 통일하고, 코드 길이 검증을 추가했다.
- **완료(UI)**: 새 Feature 작성 화면의 좌표 지도 높이를 오른쪽 보조 위젯에 맞춰 늘리고,
  역지오코딩/주소 후보 선택 시 주소 검색 필드와 선택 강조 상태를 갱신한다.
- **검증**: frontend type-check 통과, frontend lint 오류 없음(기존 경고 4건), frontend unit
  45 passed, `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 운영 경로 일원화 로컬 구현 완료

- **완료(UI)**: Feature 큐레이션/중복 검토/보강 검토/갱신 요청 화면을
  `/admin/features/...` 아래로 이동했고, 기존 경로는 새 경로로 redirect한다.
- **완료(API)**: 관련 admin API를 `/v1/admin/features/...` 하위로 노출하고 OpenAPI 정본은 새
  경로만 포함하도록 했다. 기존 API path는 호환 alias로 남겼다.
- **완료(UI 통일)**: 중복 검토 테이블과 상세 다이얼로그를 보강 검토 화면 기준으로 맞추고,
  완료 row에서도 `detail` 버튼으로 상세 비교를 열 수 있게 했다.
- **검증**: ruff targeted clean, OpenAPI drift check, frontend type-check, frontend
  gen:types:check, frontend lint(기존 경고 4건), frontend unit 45 passed, API router targeted
  35 passed, provider/ops targeted 23 passed, `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green 확인 뒤 머지한다.

## 2026-07-01 (codex) — Feature 작성/변경 요청 폼 공용화 로컬 구현 완료

- **완료(로컬)**: 새 Feature 작성 화면과 변경 요청 작성 화면의 기본 정보·좌표·주소·상세 입력 섹션을
  공용 컴포넌트로 정리했다.
- **완료(UI)**: 변경 요청 작성 화면은 `변경 요청 작성` 카드 바로 아래에 `기본 정보`를 표시한다.
  좌표가 없어도 기본 한국 본토 중심 지도 뷰를 렌더링하고, 지도 아래 빈 안내 영역은 제거했다.
- **완료(UI)**: 변경 요청 작성 화면의 본문 시군구 입력은 새 Feature 작성 화면과 같은 자동검색 필드를
  사용한다. 후보 선택 시 주소·행정코드·좌표를 함께 채운다.
- **검증**: frontend type-check, frontend lint(기존 경고 4건), frontend unit 45 passed,
  production build 통과(`NEXT_PUBLIC_KOR_TRAVEL_MAP_API`,
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` 임시 지정), `git diff --check` 통과.
- **다음 한 작업**: 보안 스캔 후 PR을 올리고 CI green을 확인한다.

## 2026-07-01 (codex) — route/Feature 지도/OpiNet 유가 회귀 수정 배포 완료

- **완료**: PR #619(`fix/route-marker-price-regressions`)는 CI green 후 main에 머지했고, n150에
  API/UI/Dagster/Dagster daemon을 재빌드·재시작했다.
- **완료(코드)**: KNPS `knps_trails`는 `비매칭코스` 정확 일치뿐 아니라 변형 표기와 매칭 실패 상태값도
  제외한다. Feature 지도 숫자 클러스터는 더 이상 확대되지 않으면 기존 겹침 선택 팝업을 연다.
  OpiNet `low_top_area`는 시도별 시군구 round-robin으로 호출 상한 전 전국 표본을 먼저 확보한다.
- **완료(설정)**: `api`/`dagster`/`dagster-daemon` compose env에 `KOR_TRAVEL_MAP_OPINET_SCOPE_*`
  매핑을 명시했다.
- **검증**: KNPS provider 53 passed, Dagster provider fetcher 75 passed/1 skipped, Docker Dagster
  runtime 9 passed, targeted ruff, frontend type-check, frontend lint(기존 경고 4건), frontend unit
  45 passed, compose config, `git diff --check`.
- **완료(후속 보강)**: n150 수동 유가 materialize 중 OpiNet root area 응답의 invalid 시도 코드가 자식
  조회로 들어가 retry되는 것을 확인했고, PR #620에서 유효 OpiNet 시도 코드만 자식 area 조회 대상으로
  쓰도록 보강했다.
- **완료(배포 검증)**: PR #620도 CI green 후 main에 머지하고 n150에 재배포했다. Alembic head, map
  컨테이너 health, 공개 UI 로그인 POST, Dagster hotfix 코드 반영을 확인했다. OpiNet price asset
  materialize는 `RUN_SUCCESS`, 운영 price feature는 15개 시도 코드/2,624건, 활성 `비매칭` route는
  0건이다.
- **검증(Windows live e2e)**: Feature 지도 마커 렌더와 클러스터 클릭 zoom 증가 targeted live run은
  인증 setup 포함 3 passed. 실제 점 마커 클릭 상세 패널 round-trip 테스트는 운영 타일/응답 대기에서
  5분 timeout이 나 후속 검증 대상으로 남았다.
- **다음 한 작업**: 실제 점 마커 클릭 상세 패널 live round-trip timeout 원인을 별도 조사한다.

## 2026-06-30 (codex) — 세션 개선 요청 후속 반영

- **완료**: PR #615는 문서 복기 PR로 재구성한 뒤 merge commit
  `ecf638701761441b94846350864711ef43f78c69`로 병합됐다.
- **진행 중**: 병합된 `main` 기준 후속 브랜치 `fix/session-improvement-followups`에서 세션 중 요청됐던
  MOIS/Dagster/UI 개선 누락분을 다시 반영했다.
- **완료**: MOIS bulk/resource/feature update runner가 `mois_localdata_source_sync`를 먼저 실행하도록
  연결했고, 고속도로 교통공지 notice schedule은 10분 주기로 바꿨다.
- **완료**: 중복/보강 검토 다중 combobox 필터, 신규 Feature 시군구 자동검색, Dagster 실행 기록
  collapsible/시각 보정/시작·중지 spinner, 적재 작업 한국어화·payload 시각화, 로그 `live live` 중복
  제거, Feature 지도 초기화 버튼을 보강했다.
- **검증**: Dagster 대상 pytest 37 passed, ruff, compose config, frontend type-check, frontend
  lint(기존 경고 4건), frontend unit 45 passed, Dagster mypy 19 source, import-linter 4 contracts kept.
- **다음 한 작업**: 보안 스캔 후 후속 PR을 올리고 CI green을 확인한다. 머지 뒤 n150 반영과 live UI e2e를
  진행한다.
## 2026-06-30 (claude) — MOIS WAL 사고 후속 하드닝 (#614 리뷰 반영)

- **완료**: `mois_source_sync.py` — checkpoint를 AUTOCOMMIT + busy 경고로 관측 가능화, 빈 slug
  fail-fast, `sync_kind` distinct 합산, WAL checkpoint 호출 회귀 spy 테스트 추가.
  (상세: journal 2026-06-30 (claude))
- **다음 한 작업**: MOIS 재가동은 `docs/runbooks/docker-app.md` §MOIS 재가동 체크리스트대로 — fix 배포
  후 source sync 1회 수동 materialize로 `*-wal`·디스크 헤드룸이 bound됨을 확인한 뒤 스케줄 재가동.
  provider(python-mois-api) batch별 commit과 디스크 영구 가드는 별도 후속 이슈.

## 2026-06-30 (codex) — PR #615 보존 브랜치 정리와 복기 문서화

- **완료**: n150 UI image inspect 시각은 UTC임을 runbook에 명시했다. 예:
  `2026-06-30T10:49:30Z`는 `2026-06-30 19:49:30 KST`이며, 이 시각 이후 UI 변경은 별도 rebuild/recreate
  전까지 반영되지 않는다.
- **완료**: UI 최신 여부 확인 절차를 image created/started 시각, 실제 `.next` bundle marker,
  로그인된 public DOM marker, route/cache-buster 확인으로 분리했다.
- **완료**: git worktree metadata가 깨졌을 때 바로 `git add -A`하지 말고 repair → status/stat/name-only
  확인 → 관련 파일 stage 또는 draft 보존 PR로 전환하는 절차를 문서화했다.
- **완료**: PR #615의 기존 보존 스냅샷은 현재 `main` 대비 회귀가 있어 로컬
  `backup/pr615-before-cleanup-20260630`에 남기고, PR head는 현재 `main` 위에 문서 보강만 남기도록
  재구성했다.
- **다음 한 작업**: PR #615의 CI와 리뷰를 확인한다. 머지는 별도 지시 전까지 진행하지 않는다.

## 2026-06-30 (codex) — Feature 변경/작업 자동화 운영 UI n150 배포

- **완료**: `/admin/dagster` 작업 자동화 화면에서 스케줄 cron 수정, 기본값 복귀, 시작/중지, 즉시 실행
  명령을 수행할 수 있게 했다.
- **완료**: Dagster asset 한국어 표기 상수를 추가하고, UI는 한국어명을 우선 표시하며 코드 레벨 이름은
  하단/작은 글씨/말줄임/툴팁으로 표시한다.
- **완료**: Feature 변경 요청 작성 화면과 검수 화면을 분리했다. 작성 화면은 form 중심, 검수 화면은
  목록/필터/상세/승인·반려 중심으로 정리했다.
- **완료**: Admin UI 메뉴명과 live e2e 기대값을 한글 UI에 맞췄고, 모바일 메뉴는 선택 항목이
  중앙으로 오도록 스크롤된다.
- **배포**: n150에서 API/UI/Dagster/Dagster daemon을 재빌드·재시작했고 Alembic head
  `0037_dagster_schedule_overrides`와 UI 로그인 POST를 확인했다.
- **검증**: n150 공식 Playwright Docker image로 Dagster 스케줄 write live spec 3 passed / 1 skipped,
  Feature 변경 write live spec 3 passed, misc live smoke 182 passed를 확인했다.
- **검증**: 로컬 frontend `type-check`, `lint`(기존 경고 4개), 관련 pytest 22건, ruff,
  `git diff --check` 통과.
- **다음 한 작업**: PR 전 보안 스캔과 CI green 확인 후 머지한다.

## 2026-06-29 (codex) — Feature change requests 편집 UX 보강

- **완료**: `/admin/features` detail에서 `편집` 링크로 change request update form을 열고, 대상
  feature detail을 prefill하도록 연결했다.
- **완료**: `/features/[featureId]` Feature 상세의 `수정` 링크도 같은 update prefill 경로로
  연결하고, prefill 시 주소/행정코드/관계 id/좌표 정밀도/전화·행사·URL 값을 개별 필드로 채운다.
- **완료**: change request form을 요청/기본 정보/위치·마커/payload 구조로 정리하고, category,
  marker icon, marker color를 dropdown으로 바꿨다.
- **완료**: 위치/마커 다이얼로그를 추가해 지도 우클릭 좌표 선택, marker icon/color 선택,
  모바일 오래누르기 좌표 선택, `적용`/`취소`, reverse geocoder 기반 시군구 코드·이름 표시를 지원한다.
- **완료**: `sigungu_code` 입력은 숫자 prefix와 한글 검색어 모두 geocoder 후보를 즉시 보여주며,
  실제 코드가 있으면 시군구명을 표시한다.
- **완료**: enrichment/dedup review 상세 다이얼로그 지도는 두 좌표가 모두 보이도록 bounds fit을
  적용했다.
- **완료**: Admin UI 사이드 메뉴를 한글 중심으로 정리했다. Feature 관련 메뉴는 `Feature 지도`,
  `Feature 목록`, `Feature 변경`처럼 같은 접두어로 맞췄다.
- **완료**: Playwright UI/e2e는 WSL에서 실행하지 않고 n150을 1순위, Windows 호스트 브라우저를
  2순위 fallback으로 쓰도록 개발 환경 문서와 config 주석에 명시했다.
- **검증**: frontend `type-check`, `type-check:e2e`, `lint`(기존 경고만), `test` 45건, `build`,
  `git diff --check` 통과. n150 배포 후 targeted live UI e2e는 인증 setup과 read/edit UI 시나리오
  2 passed, write opt-in spec 1 skipped로 통과했다.
- **다음 한 작업**: PR 전 보안 스캔과 CI green 확인 후 머지한다.

## 2026-06-29 (codex) — tasks 백로그 정리

- **완료**: `T-229-buildx`는 사용자 결정에 따라 추가 추적하지 않기로 하고 열린 백로그에서 제거했다.
- **완료**: `T-AUDIT-0616` F-01 옵션 A는 ADR-058의 옵션 B(re-key 없음, geocoder 필수화) 채택으로
  필수 진행 백로그에서 제외했다.
- **완료**: `docs/tasks.md`의 열린 항목은 보류/결정 대기인 `T-101`만 남겼다.
- **다음 한 작업**: 즉시 실행 백로그 없음. `T-101`은 Materialized View 도입 조건이 생길 때 재검토한다.

## 2026-06-29 (codex) — n150 live e2e backup runner tracked 전환

- **진행 중**: n150 local `live-e2e-backup-runner`를 repo tracked 파일로 전환해 다음 배포/rsync에서
  runner가 다시 삭제되지 않게 한다.
- **완료**: runner는 민감정보 없이 API/Dagster 컨테이너 DSN과 host-network PostgreSQL client,
  RustFS volume archive 경로를 사용하도록 작성했다.
- **완료**: `swap.sh`는 자동 hot-swap apply를 거부한다.
- **검증**: `bash -n live-e2e-backup-runner/{backup,restore,swap}.sh` 통과. tracked runner 내용을
  n150에 반영한 뒤 targeted `backups-restore.live.spec.ts`는 8 passed / 1 skipped로 통과.
- **다음 한 작업**: 보안 스캔/CI green 후 PR을 머지하고 n150 untracked runner를 tracked 파일로 치환한다.

## 2026-06-29 (codex) — n150 full admin live e2e 완료

- **완료**: PR #596은 CI green 후 squash merge됐고, n150 운영 디렉터리는 `main@860a987`로
  동기화됐다.
- **완료**: n150 local `live-e2e-backup-runner`를 복구하고 docker-manager 배포 topology에 맞춰
  backup/restore runner를 조정했다. targeted backup/restore live spec은 실제 backup execute와
  staging restore execute 포함 8 passed / 1 skipped로 통과했다.
- **완료**: 최종 full live e2e `playwright-live-full-20260629T054002Z`는 status 0으로 종료했다.
  결과는 1,886 passed / 2 flaky / 22 skipped, 실패 0건이다.
- **메모**: flaky 2건은 full 부하 중 일시적인 `Failed to fetch`/`ERR_NETWORK_CHANGED`였고 둘 다
  retry #1에서 통과했다.
- **다음 한 작업**: 별도 기능 작업 전에는 남은 flaky 2건을 낮은 우선순위 안정화 후보로만 추적한다.

## 2026-06-29 (codex) — feature-update live spec refreshable 계약 정합화

- **완료**: PR #595는 CI green 후 squash merge됐고 n150 운영 디렉터리/컨테이너는 `main@9af83b1`로
  재배포됐다. Alembic head, UI auth hash, 로그인 POST 200 + Set-Cookie를 확인했다.
- **진행 중**: full live e2e 전 점검에서 feature-update live write spec이 PR #595의
  refreshable provider/dataset 검증과 충돌하는 bogus provider 전략을 쓰고 있음을 확인했다.
- **진행 중**: spec을 실제 refreshable pair + 극소 반경 + `request_id` short link row 식별로
  정합화했다. 다중 provider×dataset 가정은 단일 provider의 다중 refreshable dataset 검증으로
  바꿨다.
- **검증**: frontend `type-check:e2e`, `git diff --check` 통과.
- **다음 한 작업**: 이 e2e spec 보정을 PR/CI/머지하고 n150에 반영한 뒤 targeted live smoke와 full
  live e2e를 실행한다.

## 2026-06-29 (codex) — Claude 후속 이슈 #589~#594 정리

- **완료**: feature-update enqueue 경로는 `catalog_refreshable_entries()` 기준으로
  non-refreshable provider/dataset 조합을 422로 거절한다.
- **완료**: dedup/enrichment review list 응답은 `OffsetMeta`로 분리해 `meta.page.next_cursor`
  영구 null 직렬화를 제거했고, OpenAPI/admin generated type을 갱신했다.
- **완료**: backup/restore/swap execute live spec에서 죽은 UI 토글을 제거하고 swap execute도
  `/api/proxy` 직접 POST로 통일했다.
- **완료**: #590/#591/#592의 테스트 스타일·관심사 분리·문서 stale 문구를 반영했다.
- **검증**: 관련 pytest 56건, `ruff`, OpenAPI drift, admin/user generated type drift,
  frontend `type-check`/`type-check:e2e`, 대상 mypy, import-linter 통과. 로컬 mocked Playwright는
  현재 WSL 배포판 미지원으로 Chromium 설치 단계에서 중단.
- **다음 한 작업**: 이 변경과 n150 long-tail e2e 안정화 변경을 PR/CI/머지한 뒤 n150에 반영하고
  full live e2e를 재실행한다.

## 2026-06-29 (codex) — n150 full live e2e long-tail 안정화

- **완료**: PR #588을 CI green 후 머지했고, n150 UI는 새 image로 재빌드/재생성했다.
- **완료**: n150 full live e2e 1차 재실행은 1,869 passed / 12 flaky / 17 skipped / 7 failed /
  5 did not run으로 종료했다.
- **완료**: 실패 7건은 strict duplicate locator, import-jobs navigation `ERR_NETWORK_CHANGED`, ETL
  provider catalog loading wait, enrichment deep pagination response wait로 분해했고 spec 안정화를 적용했다.
- **검증**: 실패 축 targeted 재실행은 12 passed로 통과했다.
- **다음 한 작업**: 안정화 변경을 PR/CI/머지한 뒤 full n150 live e2e를 다시 실행한다.

## 2026-06-29 (codex) — Enrichment review detail live smoke 클릭 안정화

- **완료**: PR #586으로 backup/restore destructive 실행 경로 분리 변경을 CI green 후 머지했다.
- **완료**: n150 targeted backup/restore live spec은 실제 backup execute와 restore execute를 포함해
  8 passed / 1 skipped로 통과했다.
- **완료**: targeted enrichment review live spec은 actions 컬럼 `detail` 버튼을 통해 detail GET과
  상세 다이얼로그/지도 smoke까지 3 passed로 통과했다.
- **다음 한 작업**: UI/spec 변경을 PR/CI/머지한 뒤 full n150 live e2e를 재실행한다.

## 2026-06-29 (codex) — Backup destructive live e2e 실행 경로 분리

- **진행 중**: n150에서 직접 `/api/proxy` backup/restore execute는 200 completed로 통과했지만,
  Playwright UI destructive button 응답 대기만 장시간 닫히지 않는 현상을 확인했다.
- **진행 중**: backup/restore plan은 Admin UI 버튼 경로로 유지하고, 실제 destructive execute는 인증된
  API 요청 후 Admin UI 목록 반영을 확인하는 end-to-end 시나리오로 분리했다.
- **다음 한 작업**: frontend e2e type-check/CI/PR 머지 후 n150 targeted backup/review와 full live e2e를
  재실행한다.

## 2026-06-29 (codex) — Backup live e2e 상태 배지 assertion 안정화

- **진행 중**: n150 targeted backup live e2e에서 `/admin/backups` 기본 옵션 테스트가
  `plan only`/`execute enabled` 상태 배지의 순간 상태를 분기형으로 읽다가 실패했다.
- **진행 중**: 해당 assertion을 현재 렌더링된 두 상태 배지 중 하나를 단일 locator로 확인하도록
  단순화했다.
- **다음 한 작업**: frontend e2e type-check와 CI를 통과시켜 PR 머지 후 n150에 반영하고 backup/review
  targeted live e2e를 재실행한다.

## 2026-06-29 (codex) — n150 live e2e 실패 보강

- **완료**: n150 full live e2e write 실행에서 백업 command 시작 실패와 enrichment review 조회 500을
  재현했고, 두 실패를 각각 API 503 계약화와 거리 점수 clamp로 보강했다.
- **완료**: backup/restore/swap command의 `asyncio.create_subprocess_exec` 시작 실패를
  `BACKUP_COMMAND_UNAVAILABLE` 문제 응답으로 반환한다.
- **완료**: enrichment review 목록/상세 SQL은 35km 이상 후보의 `spatial_score`를 0으로 고정해
  numeric underflow 없이 조회된다.
- **검증**: admin backup router 단위 테스트 12건, enrichment review integration 대상 2건, 변경 파일
  ruff 통과.
- **다음 한 작업**: PR을 올리고 CI green 후 머지한 뒤 n150에 재배포하고 backup/review targeted e2e와
  full live e2e를 다시 실행한다.

## 2026-06-29 (codex) — #572 Enrichment review 지도 비교 surface 일원화

- **완료**: enrichment review 목록의 `mapReviewId` state, 행별 `지도` 버튼, 별도
  `enrichment coordinate map` section을 제거하고 상세 다이얼로그 지도만 남겼다.
- **완료**: mocked/live e2e는 목록 인라인 지도 대신 행 클릭 상세 다이얼로그 지도와 `지도` 버튼 부재를
  검증하도록 갱신했다.
- **검증**: `type-check`, `lint`(기존 6 warnings), production `build`, `git diff --check`,
  Docker Playwright 수동 시나리오(로그인 → enrichment review 목록 mock → 행 클릭 → 상세 다이얼로그 지도)
  통과.
- **다음 한 작업**: PR을 올리고 CI green 후 머지해 #572를 닫는다.

## 2026-06-29 (codex) — #571 Dedup/Enrichment review page-only 계약 정리

- **완료**: `GET /v1/admin/dedup-reviews`와 `GET /v1/admin/enrichment-reviews`의 이중
  pagination 계약을 제거해 `cursor` query parameter 없이 `page`/`page_size`/`meta.page.total`만
  사용하도록 바꿨다.
- **완료**: repository의 review cursor decode/encode 경로, `next_cursor` 산출, UI의 죽은
  `nextCursor` fallback을 삭제했다.
- **검증**: 변경 파일 `ruff`, 대상 mypy 3파일, OpenAPI drift check, frontend `gen:types:check`/
  `type-check`/`lint`(0 errors, 기존 warnings 6개), 대상 pytest 29건을 통과했다.
- **다음 한 작업**: PR을 올리고 CI green 후 머지해 #571을 닫는다.

## 2026-06-29 (codex) — #570 Linux/WSL 개발 실행 정책 문서 정합성 보정

- **진행 중**: `docs/agent-guide.md`의 Windows `git.exe` 예시와 Windows Git 허용 문구를 제거하고,
  Linux/WSL `git`·`gh`·`codegraph` 단일 실행 기준으로 §9를 재작성했다.
- **진행 중**: `CLAUDE.md`와 `docs/debug-ui-admin-workflows.md`의 Windows Playwright 표준 문구를
  n150 Linux 우선, Windows 호스트 브라우저 fallback 기준으로 고쳤다.
- **다음 한 작업**: 문서 내 잔여 `git.exe`/Windows Playwright 표준 문구를 재검색하고 lint 성격의
  whitespace check 후 PR을 올려 CI green 뒤 merge하고 #570을 닫는다.

## 2026-06-29 (codex) — #568 data.go.kr curated fileData 4종 schedule 보강

- **완료**: data.go.kr curated fileData 4개 dataset마다 별도 Dagster monthly schedule을 만들고,
  각 schedule이 `datagokr_file_data_records`와 `datagokr_file_data_dataset_key` resource에 같은
  dataset_key를 주입하도록 했다.
- **완료**: fileData resource는 schedule `run_config` dataset_key를 우선하고, config가 없으면 기존
  `KorTravelMapSettings.datagokr_file_data_dataset_key` 기본값을 유지한다.
- **검증**: Dagster definitions/resource 테스트 22건, feature-update runner 테스트 7건, Dagster package
  mypy를 통과했다.
- **완료(PR)**: PR #579를 squash merge했고 #568은 닫혔다.

## 2026-06-29 (codex) — #567 Enrichment detail source audit-only 계약 명시

- **완료**: enrichment 상세 비교 다이얼로그의 `정리된 datagokr`/`visitkorea` 선택이 적용 데이터를
  바꾸는 것처럼 보이지 않도록 UI 문구를 기록용으로 낮추고, detail/decision API 응답에
  `detail_source_effect: "audit_only"`를 추가했다.
- **완료**: `PATCH /v1/admin/enrichment-reviews/{review_id}` 응답은 요청의
  `selected_detail_source`를 함께 반환해 선택값이 decision reason audit marker로 기록됐는지 확인할 수 있다.
- **완료(PR)**: PR #578을 squash merge했고 #567은 닫혔다.

## 2026-06-29 (codex) — #566 Dedup review count 성능 보강

- **완료**: dedup review 목록 count가 확장 필터 없이 호출될 때 `feature.features`/`provider_sync`
  join을 materialize하지 않고 `ops.dedup_review_queue`만 count하도록 fast path를 추가했다.
- **검증**: 관련 unit 9건, T-212d EXPLAIN 대상 테스트 1건, 변경 파일 ruff와 CI를 통과했다.
- **완료(PR)**: PR #577을 squash merge했고 #566은 닫혔다.

## 2026-06-29 (codex) — PR #564 사후 리뷰 반영

- **진행 중**: #569/#574 반영 브랜치에서 admin live e2e 실제 write spec을 opt-in 게이트 뒤로 옮겼다.
  feature write는 `E2E_ADMIN_FEATURES_WRITE=1` 또는 `E2E_ADMIN_WRITE=1`, Settings write/audit은
  `E2E_SETTINGS_WRITE=1` 또는 `E2E_ADMIN_WRITE=1`일 때만 실행한다.
- **진행 중**: scenario catalog의 13,651건 수치를 실행 커버리지 단언으로 쓰지 않도록 threshold 테스트와
  문서 표현을 정리했다. 대표 route smoke는 catalog의 `live_smoke` 항목을 실제 네비게이션으로 돈다.
- **진행 중**: backup artifact 정리용 `DELETE /v1/admin/backups/{backup_id}` 계약을 추가하고
  `openapi.json`/frontend generated type/API hook을 갱신했다.
- **다음 한 작업**: 로컬 API/frontend 타입·lint·대상 pytest를 통과시킨 뒤 PR을 올리고 CI green 후 머지한다.

## 2026-06-28 (codex) — Admin UI 전체 live e2e 시나리오 평가

- **완료(catalog)**: Admin UI와 public reflection 표면을 24개 surface로 나누고, route smoke/write
  contract/admin feature matrix/features map/detail/curated/logs/reviews/change request/category cross 축을
  합쳐 13,651건의 논리 live e2e surface taxonomy catalog를 추가했다.
- **완료(write 반영)**: `/admin/settings`에서 public API key 생성 → API list 확인 → UI revoke →
  API/UI revoked 확인, API auth audit event 생성 → Settings UI 확인 흐름을 새 serial live spec으로
  추가했다. 2026-06-29 후속 반영 이후 이 실제 write spec은 opt-in일 때만 실행한다.
- **완료(수정)**: n150 live fixture feature id를 현재 active id로 갱신했고, curated 후보 0건 상태에서
  empty-state row를 실제 후보로 오인하던 문제를 candidate row test id로 수정했다. Settings route/nav/문서
  누락도 보강했다.
- **검증(n150)**: full live suite 수정본은 공식 Playwright Docker image + host network에서
  1,828 passed / 5 skipped / 0 failed (34.1분)로 통과했다.
- **검증(로컬)**: `npm -w packages/kor-travel-map-admin/frontend run type-check:e2e`,
  `npm -w packages/kor-travel-map-admin/frontend run lint`(0 errors, 기존 warnings 6개),
  `git diff --check`를 통과했다.
- **다음 한 작업**: PR을 올리고 CI green 및 review 조건을 확인한 뒤 머지한다.

## 2026-06-28 (codex) — Admin features/change requests UI live write e2e

- **완료(e2e)**: `/admin/features/new` → `/admin/features/change-requests` → `/admin/features`를 잇는
  실제 write live spec을 추가했다. add 요청 생성/승인, admin/public 상세 반영, 목록 검색/필터/preview/detail,
  update 승인, update 거절 후 미변경 확인, deactivate, delete 승인, public detail 404까지 직렬로 검증한다.
- **완료(서비스 반영)**: write 동작 뒤에는 UI assertion만 보지 않고 `/api/proxy` admin/public API를
  브라우저 세션으로 조회해 실제 서비스 상태를 확인한다. 실패 시 `finally`에서 테스트 feature 삭제 승인을
  시도하도록 cleanup도 넣었다.
- **n150 실행**: 새 write live spec은 n150의 공식 Playwright Docker image에서 2 passed. admin features
  read-only 목록 suite도 333 passed로 함께 확인했다.
- **cleanup 확인**: n150 DB에서 `user_request::e2e_admin_features::live-*` synthetic feature를 점검해
  모두 `deleted` 상태이며 활성/미삭제 feature가 0건임을 확인했다.
- **다음 한 작업**: 이 branch의 backup/restore live e2e와 admin features/change requests live e2e 변경을
  PR로 올리고, CI green 확인 뒤 머지한다.

## 2026-06-28 (codex) — Backup/restore UI live e2e 실제 실행 시나리오

- **완료(e2e)**: `/admin/backups` live spec을 추가해 실행 옵션 기본값, invalid backup id 오류,
  backup command plan, 실제 backup execute, 생성 artifact 기준 restore plan/execute,
  swap plan, 선택적 swap execute를 직렬 시나리오로 검증한다.
- **안전장치**: 실제 backup/restore는 `E2E_BACKUP_RESTORE_EXECUTE=1`일 때만 돌고, swap command 실행은
  별도 `E2E_BACKUP_RESTORE_EXECUTE_SWAP=1`일 때만 돈다. `swap 즉시 적용`은
  `E2E_BACKUP_RESTORE_EXECUTE_SWAP_APPLY=1`일 때만 켠다.
- **n150 실행**: n150 host에는 Playwright browser runtime deps가 없어 공식 Playwright Docker image
  + host network로 실행했다. 기본 run은 4 passed / 5 skipped, execute/apply run은 9 passed.
- **n150 execute/apply**: n150 API에 backup command enable과 runner mount를 붙여 UI에서 실제
  backup artifact 생성, staging DB/RustFS volume restore, swap `apply=true` 요청까지 통과시켰다.
  apply helper 재기동 뒤 map API/UI/Dagster 컨테이너가 healthy이고, API/Dagster DSN이 restore DB를
  바라보는 것을 확인했다. 배포 후 로그인 POST도 200 + Set-Cookie로 확인했다.
- **다음 한 작업**: n150에 임시로 붙인 backup/restore runner를 정식 배포 모델로 정리한다. 특히
  docker-manager 배포에서 restore swap apply를 API 요청 생명주기 밖 helper로 실행하는 방식을 문서화하고,
  정식 스크립트/compose 설정으로 승격할지 결정한다.

## 2026-06-28 (codex) — Refreshable provider catalog / MOIS detail runner

- **완료(분류)**: `is_feature_load`는 새 `FeatureBundle` 생성 여부로 유지하고, Dagster feature update
  request로 실행 가능한지는 `is_refreshable`로 분리했다.
- **완료(노출)**: `/ops/providers` never-run 목록은 `catalog_refreshable_entries()` 기준으로 바꿔
  OpiNet 가격, KREX 가격/기상, KMA 예보/실황, VisitKorea 축제 보강처럼 `is_feature_load=False`이지만
  runner가 있는 dataset을 운영 실행 목록에 표시한다.
- **완료(MOIS detail)**: `mois_license_detail`을 refreshable로 전환하고, 기존 MOIS Dagster asset runner가
  `dataset_key=mois_license_detail` 요청을 받을 수 있게 했다. 상세 API는 detail source record 우선,
  bulk source record fallback으로 조회한다.
- **유지(전화번호 보강)**: `place_phone_enrichment`는 runner/운영 실행 목록에 추가하지 않았다.
- **검증(로컬)**: refreshable catalog 56개와 runner spec 비교에서 누락 0건,
  `runner_not_in_catalog` 0건 확인. 관련 pytest 32건, 변경 파일 `ruff`, 대상 mypy 통과.
- **다음 한 작업**: PR 생성, CI green 확인 후 머지하고 N150 배포 뒤 `/ops/providers`에서 MOIS detail과
  non-feature-load 실행 대상이 queue/run/done으로 전환되는지 UI e2e로 확인한다.

## 2026-06-28 (codex) — Feature update provider/Dagster 정렬

- **완료(원인)**: AirKorea 실패는 UI/catalog가 `airkorea_stations`를 feature-load 대상으로 노출했지만
  Dagster runner는 `airkorea_air_quality`만 지원해서 발생했다. OpiNet 실패는 Dagster runtime에
  `KOR_TRAVEL_MAP_OPINET_API_KEY`가 비어 있어 provider client 인증 오류가 난 것이었다.
- **완료(수정)**: AirKorea catalog는 `airkorea_air_quality`를 feature-load 대상으로 정렬하고,
  기존 `airkorea_stations` 요청은 같은 asset alias로 실행한다. OpiNet은 key 누락을 runner 단계에서
  명확한 credential 오류로 실패시킨다.
- **완료(누락 Dagster)**: MOIS history/closed, `standard_special_streets`, data.go.kr curated fileData
  4종을 feature update runner에 추가했다. 지역특화거리와 fileData 공용 Dagster asset/resource/schedule을
  추가했다.
- **완료(전체 점검)**: provider catalog의 `is_feature_load=True` 47개와 runner spec을 비교해 runner
  미지원 0건을 확인했고, 이 비교를 회귀 테스트로 고정했다.
- **검증(로컬)**: `ruff check .`, 대상 mypy, Dagster 테스트 199건(1 skipped), API provider
  catalog/router 테스트 19건 통과. API router 테스트는 현재 셸 인증 env 때문에
  `KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED=false`를 명시해 실행했다.
- **다음 한 작업**: PR/CI green 후 N150에 배포하고, UI e2e로 feature update 요청이 queue에 들어가고
  Dagster 실행으로 성공 완료되며 반복 작업이 정상 노출/실행되는지 확인한다.

## 2026-06-28 (codex) — Linux/WSL 개발 실행 정책

- **완료(환경 정책)**: `git`/`gh`/`codegraph`를 포함한 모든 개발 명령을 Linux/WSL에서 실행하도록
  `AGENTS.md`, `SKILL.md`, `README.md`, `docs/dev-environment.md`를 정리했다.
- **완료(runbook)**: agent workflow, codegraph worktree, failure patterns, runbook index의 Windows Git
  전제를 제거하고, Windows 경로 기반 worktree metadata 복구 절차를 추가했다.
- **완료(e2e 정책)**: Playwright e2e는 n150 Linux 우선, n150에서 불가할 때만 Windows browser
  fallback으로 실행하도록 frontend README와 Playwright config 주석까지 문서화했다.
- **검증(로컬)**: 문서 변경만 수행했으며 `git diff --check`를 실행했다.
- **다음 한 작업**: PR 생성, CI green 확인 후 머지한다.

## 2026-06-28 (codex) — Review 상세 비교 다이얼로그

- **완료(API)**: `/admin/dedup-reviews/{review_id}`와 `/admin/enrichment-reviews/{review_id}` 상세
  조회 API를 추가했다. 응답은 양쪽 feature/source 상세, raw payload, 좌표, 기간, 거리/score를 포함한다.
- **완료(UI)**: Dedup review와 Enrichment review 테이블 행 클릭 시 상세 비교 다이얼로그를 열고,
  두 자료의 핵심 필드/detail/raw JSON과 하나의 지도에 표시한 두 좌표를 보여준다.
- **완료(Enrichment 선택)**: 축제 enrichment 상세에서 `정리된 datagokr`와 `visitkorea` 중 사용할
  상세 source를 고를 수 있다. 정리된 target detail이 없으면 VisitKorea가 기본 선택되며, accept 요청에
  선택값을 기록한다.
- **검증(로컬)**: 전체 pytest 1367건, 전체 `ruff`, `mypy src/kortravelmap`, import-linter,
  OpenAPI drift check, admin frontend `type-check`/대상 ESLint/`gen:types:check`,
  Windows Playwright mocked review e2e 23건 통과.
- **다음 한 작업**: PR 생성/CI green 후 머지하고, N150 배포 뒤 운영 데이터에서 dedup/enrichment 행
  클릭 상세와 enrichment 선택 fallback을 smoke 확인한다.

## 2026-06-28 (codex) — Feature update request queue 실행 복구

- **완료(Dagster)**: `feature_update_runner` 기본 resource를 등록해
  `feature_update_request_worker`가 missing resource 대신 실제 provider/dataset asset dispatcher를
  받도록 했다.
- **완료(실행 경로)**: run-now/queued request는 기존 queue/sensor/worker 구조를 유지하면서,
  OpiNet·KREX·KMA·AirKorea 등 live fetcher가 있는 provider dataset을 lazy resource로 실행한다.
- **완료(테스트)**: runner dispatch 단위 테스트와 Definitions 기본 resource 등록 회귀 테스트를 추가했다.
- **검증(로컬)**: `pytest` targeted 21건, 변경 파일 `ruff`, `mypy --python-version 3.12` 3파일 통과.
  기본 mypy 실행은 현 환경의 `numpy` stub/Python version 설정 충돌로 중단된다.
- **다음 한 작업**: PR/CI green 후 N150에 배포하고, update requests에서 KMA weather 또는 OpiNet price
  run-now 요청이 `running`/`done`으로 전환되는지 Dagster run과 admin UI에서 확인한다.

## 2026-06-28 (codex) — Review 테이블 페이지네이션 상/하단 보강

- **완료(API)**: dedup/enrichment review 목록에 `page` 쿼리와 `meta.page.total`을 추가했다.
  기존 `cursor`는 호환용으로 유지한다.
- **완료(UI)**: Dedup review와 Enrichment review 테이블의 바로 위/아래에 동일한 페이지바를 배치했다.
  첫/이전/다음/마지막 페이지 이동과 `현재 페이지 / 총 페이지`, 총 아이템 수, 현재 페이지 아이템 수를
  표시한다.
- **완료(e2e)**: mocked review e2e는 page 번호 전진, 상/하단 버튼 2벌, 마지막 페이지 버튼,
  빈 목록 비활성 상태를 검증한다. admin review smoke도 페이지바 2벌을 확인한다.
- **검증(로컬)**: targeted ruff, mypy 3파일, router/unit pytest 20건, SQL integration 2건,
  OpenAPI drift check, admin frontend type-check/lint, mocked review e2e 21건, review smoke e2e 2건 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150 배포와 live review e2e로 운영 화면을 확인한다.

## 2026-06-27 (codex) — Enrichment/Dedup review 검수 UX 보강

- **완료(API)**: enrichment review 목록에 대상/source 좌표·기간, 거리(`distance_m`), 거리 기반
  유사도(`spatial_score`)를 추가했다. VisitKorea enrichment source record도 TourAPI 좌표를 보존한다.
- **완료(UI)**: enrichment/dedup review 테이블에 검색, 상태/성격별 필터, score band, page size,
  cursor pagination을 추가했다. enrichment 테이블은 시작-종료 날짜와 거리 컬럼을 표시하고, 좌표가
  있는 행은 하나의 VWorld 지도에 datagokr/visitkorea 마커와 이름을 함께 보여준다.
- **완료(e2e)**: mocked review e2e에 enrichment 필터·페이지네이션·지도와 dedup 전용
  필터·페이지네이션 회귀 테스트를 추가했다. N150 live spec에도 두 review 화면의 필터/페이지네이션/
  지도 smoke를 추가했다.
- **검증(로컬)**: Python unit 1109건, enrichment repository integration 9건, API/router targeted
  28건, ruff, mypy, import-linter, admin frontend lint/type-check/gen:types, Vitest 45건, mocked review
  e2e 21건 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150에 배포하고 live review e2e로 운영 화면을
  평가한다.

## 2026-06-27 (codex) — Curated place-search 반영 정책 수정

- **완료(UI)**: `/admin/curated-features`의 place-search 결과 `반영`이 `display_title`과
  metadata만 저장하던 문제를 고쳐, `reuse_policy=allowed`도 함께 PATCH하도록 했다.
- **완료(e2e)**: manual_review 후보에서 검색 결과를 반영하면 PATCH body, REUSE 행 badge,
  editor select가 모두 `allowed`로 바뀌는 mocked Playwright 회귀 테스트를 추가했다.
- **검증(로컬)**: admin frontend type-check, 변경 파일 ESLint, curated mutations mocked e2e 21건,
  `git diff --check` 통과.
- **다음 한 작업**: N150 배포 뒤 운영 데이터에서 manual_review 후보 1건으로 place-search 반영 smoke를
  확인한다.

## 2026-06-27 (codex) — Feature update request UI live e2e

- **완료(UI/e2e)**: `/admin/feature-update-requests` live Playwright spec을 추가했다. form controls,
  validation errors, 실제 API dry-run preview, `/features` 지도 화면의 `Update` 링크 이동을 확인한다.
- **완료(에러 케이스)**: mocked update request e2e에 lon 필수, lat 범위, radius 최소값, create API
  422 alert 케이스를 추가했다.
- **완료(지도 반영)**: update request create/run-now와 ops-live `feature_update_requests` 이벤트가
  `features`/`feature`/`admin-features` query를 invalidate해 feature 지도와 상세/목록이 재조회되도록
  연결했다.
- **검증(로컬/live)**: admin frontend type-check, 변경 파일 ESLint, mocked update request e2e 8건,
  live update request e2e 5건, `git diff --check` 통과. Vitest unit은 WSL `node_modules`의
  `@vitejs/plugin-react` 누락 및 NTFS 권한 문제로 실행하지 못했다.
- **다음 한 작업**: WSL Node 의존성 설치 상태를 복구한 뒤 `src/api/live.test.ts`를 포함한 frontend
  unit test를 재실행하고, 필요하면 features map WebGL 초기화 실패 원인을 별도 점검한다.

## 2026-06-27 (codex) — Curated place search provider 직접 호출

- **완료(API)**: admin curated feature 주소/POI 검색은 kor-travel-concierge를 경유하지 않고 Kakao
  Local, NAVER Search, Google Places API를 직접 호출한다. provider별 키 누락/호출 실패는 `errors`
  필드에 담아 반환한다.
- **완료(설정)**: `KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY`,
  `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID`, `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET`,
  `KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY`를 settings/env 예시에 추가했고, 기존 짧은 env 이름은
  load-env/compose에서 매핑한다.
- **검증(로컬)**: `tests/unit/test_curated_routes.py` 3건과 변경 파일 ruff 통과.
- **다음 한 작업**: 실제 운영 env에 위 provider 키가 들어간 상태로 API 컨테이너를 재배포하고,
  curated feature detail에서 검색 결과가 provider별로 표시되는지 smoke 확인한다.

## 2026-06-27 (codex) — Admin 후속 보강: curated/detail/OpiNet/Dagster

- **완료(UI)**: curated feature place 검색 자동 실행/누적을 끊고 명시 검색으로 변경했다. 화면의
  `concierge` 표시명은 중립 라벨로 바꿨고, 해당 provider 선택 시 source rule의 실제 theme으로
  filter가 이동한다.
- **완료(상세/지도)**: admin curated feature 전용 상세 화면을 추가했다. admin features 목록 우측
  preview와 `/features/{feature_id}` 상세에는 지도 패널을 추가했고, 목록 `detail` 버튼은 상세
  route로 바로 이동한다.
- **완료(Dagster/OpiNet)**: OpiNet `low_top_area` no-data 예외 처리와 호출 상한 이후 fallback을
  추가했다. Dagster feature load schedule은 누락된 krforest/standard/khoa/krairport/airkorea/
  visitkorea asset까지 포함하고, admin Dagster 화면은 asset을 4개로 자르지 않는다.
- **검증(로컬)**: admin frontend type-check/e2e type-check, 변경 파일 ESLint, Dagster/API targeted
  pytest 84 passed/1 skipped, ruff, OpenAPI export drift test 통과.
- **다음 한 작업**: PR/CI green 후 N150에 배포하고 OpiNet price job과 누락 Dagster schedule/job
  노출, curated 상세/검색 UI를 운영 데이터로 smoke 확인한다.

## 2026-06-27 (codex) — Admin live review 데이터/표시 보강

- **완료(원인 확인)**: N150에서 KMA `TMP` weather 값은 존재한다. price feature는 OpiNet 부분 응답
  처리 때문에 여전히 제주/완도권에 머물렀고, enrichment/dedup review queue와 ops log table은 0건,
  provider sync state는 KMA만 기록되어 있었다.
- **완료(코드)**: OpiNet `low_top_area` 부분 응답에도 전국 fallback을 타게 했고, VisitKorea
  enrichment Dagster asset은 review queue refresh 경로를 호출하게 했다. feature load asset은 성공
  provider sync state를 기록한다.
- **완료(UI)**: curated review 우측에 위치 지도/상세/place-search 반영 패널을 추가했다.
  admin features/curated/logs table pagination 정보와 MOIS place 특화 상세 패널을 보강했다.
- **검증(로컬/live)**: Dagster/API targeted pytest와 ruff, admin frontend type-check/e2e type-check,
  변경 파일 ESLint, `git diff --check`, `/admin/enrichment-reviews` live Playwright 34건 통과.
- **다음 한 작업**: PR 생성/CI green 후 N150에 배포하고 OpiNet price, VisitKorea enrichment,
  dedup refresh, concierge curated source 적재 job을 재실행해 운영 DB row 수와 UI 표시를 재확인한다.

## 2026-06-26 (codex) — OpiNet fallback 도심 anchor hotfix

- **운영 확인**: N150에서 `low_top_area` 배포 후 `feature_price_opinet_stations_job`은 성공했지만
  price feature는 295건 그대로였고, 좌표 범위도 제주권에 머물렀다. 최근 `PriceValue` 갱신도 0건이었다.
- **진행 중**: `lowTop10` 빈 응답 fallback이 기존 sparse grid만 쓰던 문제를 보강해, 전국 주요 도심
  anchor를 먼저 `aroundAll`로 조회한 뒤 기존 grid를 보조로 사용하게 한다.
- **다음 한 작업**: targeted pytest/ruff/mypy 통과 후 PR을 만들고, CI green이면 머지·N150 재배포·
  OpiNet price job 재실행으로 price 좌표 범위가 제주권 밖으로 확장되는지 확인한다.

## 2026-06-26 (codex) — Feature별 상세 패널 + 좌측 메뉴/Dagster 보강

- **완료(API)**: area 포함 feature 조회 API(`/v1/features/{feature_id}/contained-features`)를 추가하고,
  weather marker용 현재기온 summary와 area 면적 필드를 OpenAPI에 반영했다.
- **완료(UI)**: feature 상세 패널을 kind별로 분리했다. weather는 weather feature에서만 표시하고,
  price는 이력 그래프, event는 기간/장소, area는 포함 feature, route는 구간 메타를 보여준다.
- **완료(지도/메뉴)**: weather marker에 현재기온을 표시하고, `/features` 지도 화면에도 좌측 메뉴를
  노출했다. 데스크톱 sidebar는 접기/펼치기 상태를 저장한다.
- **완료(Dagster)**: feature load schedule을 weather 시간당 1회, 유가 일 2회, 기타 월 1회로
  정리하고, run 상세에 실패 원인/stack 요약을 추가했다.
- **검증(로컬)**: 전체 pytest 1,357건, 전체 ruff, import-linter, strict mypy, admin frontend
  type-check/lint, OpenAPI generated type drift check, production build, `git diff --check` 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150 배포와 live smoke를 완료한다.

## 2026-06-26 (codex) — OpiNet price 제주 bbox 원인 + low-top/fallback 전국 모드

- **원인 확인**: N150 운영 env가 OpiNet scope를 제주/완도권 bbox
  `126.15,33.19,126.98,34.21`로 고정하고 있어 좌표 있는 active price feature 196건이 해당
  권역에만 존재했다. KREX price 99건은 좌표가 없어 지도 marker에 표시되지 않는다.
- **결정**: OpiNet 전국 bbox 격자 수집은 `aroundAll` 1만 회 이상 호출로 일일 한도 위험이 있어
  바로 쓰지 않는다.
- **진행 중**: `OPINET_SCOPE_MODE=low_top_area`를 추가했다. 시군구별 `lowTop10`을
  휘발유/경유/고급휘발유 3종으로 호출하고, 운영 `areaCode`/`lowTop10`이 빈 응답이면 전국 샘플
  그리드의 `aroundAll`로 fallback한다.
- **검증**: OpiNet provider unit, Dagster provider fetcher, Dagster definitions targeted pytest,
  수정 파일 ruff, strict mypy 통과.
- **다음 한 작업**: fallback PR 생성/CI green/머지 후 N150을 재배포하고 OpiNet price asset을
  재실행해 전국 분포 smoke를 확인한다.

## 2026-06-26 (codex) — Admin price feature 표시 + Dagster 주기 정리

- **완료(API)**: `/v1/features/{feature_id}/price`를 추가해 제품별 최신 가격(`current`)과 최근
  가격 이력(`history`)을 반환한다. `/v1/features` summary에는 price feature용
  `price_summary`를 붙여 지도 marker가 추가 호출 없이 최신 유가를 표시할 수 있게 했다.
- **완료(UI)**: admin `/features` 지도 marker가 `price` feature에 대해 휘발유/경유/고급휘발유
  최신 가격을 표시한다. `price` feature 선택/상세 화면은 `FeaturePricePanel`로 가격 요약과
  history 표를 보여준다. 가격 history 그래프는 후속 PR 범위다.
- **완료(Dagster)**: OpiNet/KREX price Feature schedule은 일 2회(`06/18시`)로 조정했고,
  KMA/KREX weather 관련 schedule은 시간당 1회 기준으로 정렬했다.
- **완료(OpenAPI/types)**: admin/user OpenAPI와 admin/user TypeScript generated types를 재생성했다.
- **검증(로컬)**: API targeted pytest 20건, Dagster definitions 10건, OpenAPI drift check,
  admin frontend type-check, user-client type-check, admin frontend lint(기존 warning 7건), targeted
  ruff, `git diff --check` 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 후속 UI PR을 진행한다. 후속 범위는 feature
  kind별 우측 메뉴 분기(price history 그래프, weather는 weather feature 전용, event 기간 표시,
  route 구간 상세 표시)와 로그인 후 좌측 메뉴의 전 화면 노출/접기 기능이다.

## 2026-06-25 (codex) — 가격 시계열 테이블 설계 + OpiNet/KREX 유가 적재

- **완료(로컬 설계/코드)**: `feature.feature_price_values`를 추가하고 price anchor
  `FeatureBundle` + `PriceValue`를 한 transaction으로 적재하는 client/repository 경로를 구현했다.
- **완료(provider)**: OpiNet station detail 중첩 가격과 KREX 휴게소 유가 snapshot을 각각
  `kind=price` feature + 제품별 `PriceValue`로 변환한다.
- **완료(Dagster)**: `feature_price_opinet_stations`, `feature_price_krex_rest_areas` asset/job/schedule과
  live resource를 추가했다.
- **완료(문서)**: `data-model.md`, `postgres-schema.md`, 성능/ETL 문서를 실제
  `feature_price_values` 설계로 갱신했다.
- **완료(Alembic graph)**: main hotfix의 `0035_merge_price_and_curated`와 N150 선배포의
  `0035_merge_curated_price`를 모두 보존하고, `0036_merge_price_merge_aliases` no-op merge
  revision으로 최종 단일 head를 만든다.
- **완료(N150 배포/적재)**: API/Dagster/UI 재빌드·재기동 후 KREX/OpiNet price job을 재실행했다.
  운영 DB Alembic revision은 `0036_merge_price_merge_aliases`이고, 최종 active price feature 295건,
  `feature.feature_price_values` 1,132건
  (`python-opinet-api/opinet_gas_station` 874건, `python-krex-api/rest_area_fuel` 258건).
- **완료(live smoke)**: N150 `/health` 200, trusted admin proxy read-only `/v1/features`
  `kind=price` bbox 조회 200, UI `/login` 200, API/UI/Dagster healthy 확인.
- **완료(로그인/UI live e2e)**: Windows Playwright live config로 N150 공개 prod URL admin 로그인 setup
  1건 통과. 같은 인증 세션으로 `features-list`/`features-map`의 `price` 대상 16건 통과.
- **검증(로컬)**: provider/Dagster unit, Alembic+Dagster 통합, ruff, strict mypy,
  import-linter, `git diff --check` 통과.
- **다음 한 작업**: PR 생성, CI green 확인, 머지를 완료한다.

## 2026-06-25 (codex) — Alembic curated 배포 체인 hotfix

- **완료(원인 확인)**: N150 운영 DB의 `alembic_version`이 `0034_feature_price_values`인데 main
  코드에 해당 리비전 파일이 없어 API 부팅 중 `alembic upgrade head`가 실패했다.
- **완료(체인 수정)**: 운영 DB의 `feature.feature_price_values` 스키마와 동일한
  `0034_feature_price_values` 리비전을 복원하고, 기존 `0034_generic_curated_contract`와
  `0035_merge_price_and_curated` no-op merge 리비전으로 합쳤다.
- **다음 한 작업**: hotfix PR 생성, CI green 확인, 머지 후 N150 API/Dagster/UI를 재기동하고
  live schema/API smoke를 완료한다.

## 2026-06-25 (codex) — Curated API 범용 계약 정리

- **완료(API 정책)**: public curated API는 임의 외부 사용자가 curated feature 목록/상세를 조회하는
  범용 계약으로 정리했다. user OpenAPI profile에는 `/v1/curated-features`와
  `/v1/curated-features/{curated_feature_id}`만 남긴다.
- **완료(DB/API rename)**: curated 재사용 속성은 `curation_relation`/`reuse_policy`/
  `content_version`, snapshot table은 `feature.curated_feature_detail_snapshots`로 정리했다.
  source rule metadata, snapshot JSON, admin UI preview API도 같은 범용 명칭으로 migration한다.
- **완료(POI metadata)**: POI cache target metadata의 외부 POI 식별자는 `external_poi_id`로만
  저장·노출한다.
- **완료(검증)**: targeted curated/POI API 21건, curated/POI/schema integration 14건, OpenAPI
  drift, generated type drift, admin/user type-check, frontend unit 43건, curated mocked e2e 22건,
  ruff, strict mypy, import-linter 통과. 전체 pytest는 1,345건 통과, 외부 `kor-travel-geo`
  live reverse geocoder 400으로 5건 실패.
- **다음 한 작업**: PR 생성, CI green 확인, 머지 후 N150 배포와 live smoke를 완료한다.

## 2026-06-25 (codex) — KNPS 비매칭코스 제외 + N150 재검증

- **완료(코드)**: KNPS `knps_trails` 변환에서 `비매칭코스`/`Nonmatching Course`를 공식 route로
  적재하지 않도록 제외했다. 한글 raw name과 영문 raw name을 모두 확인한다.
- **완료(회귀 테스트)**: `tests/unit/test_providers_knps.py`에 단건 skip과 배치 내 정상 route 유지
  케이스를 추가했다.
- **완료(N150)**: 수정 provider를 배포하고 기존 active `비매칭코스` route 1건을 soft delete했다.
  최종 active unmatched route 0건, active route 617건을 확인했다.
- **완료(OpiNet/env)**: 로컬 `python-opinet-api`의 키를 N150 `.env`에
  `KOR_TRAVEL_MAP_OPINET_API_KEY`로 저장하고 bbox scope도 `KOR_TRAVEL_MAP_OPINET_SCOPE_*`로
  저장했다. OpiNet station job 재실행 후 source record 196건, active place feature 196건을
  확인했다.
- **완료(N150 rename)**: 운영 DB/role/env/compose의 잔여 `krtour_map`/`KRTOUR_MAP*`을 최신
  `kor_travel_map`/`KOR_TRAVEL_MAP*` 기준으로 정리했고 API/Dagster healthy를 확인했다.
- **완료(live e2e)**: UI live Playwright `features-map` 118건, `features-list`/`features-detail`/
  `providers-consistency` 753건, 나머지 live 묶음 896건을 검증했다. 남은 묶음 중 모바일 reviews
  1건은 최초 묶음 실행에서 실패했지만 단독 재실행 2건 통과했다.
- **다음 한 작업**: 로컬 전체 게이트 실행 후 PR 생성, CI green 확인, 머지를 완료한다.

## 2026-06-25 (codex) — Concierge curated source + curated 계약 보강

- **완료(map 코드)**: concierge YouTube 장소 후보 provider/dataset을 `media-places` curated source rule로
  seed하고, rule apply가 기본 `curated` 상태와 source title 기반 `display_title`을 만들도록 보강했다.
- **완료(DB/API rename)**: curated 재사용 계약은 제품명 없는 detail snapshot 계약으로 정리한다.
  POI cache target metadata의 외부 POI 식별자도 범용 key로 표현한다.
- **완료(concierge 연동)**: concierge export payload에 source target type/value/search query와
  `youtube.source_title`을 추가해 채널명·플레이리스트명·보정 검색어명을 map이 title로 쓸 수 있게 했다.
- **검증 진행**: map targeted unit/API/Dagster/integration, OpenAPI drift, frontend/user type-check,
  ruff, strict mypy, import-linter 통과. concierge targeted backend 26건 통과.
- **다음 한 작업**: 전체/확장 게이트 후 양쪽 PR 생성, CI green 확인, 머지, N150 배포와 live smoke를 완료한다.

## 2026-06-25 (codex) — KNPS protected area 한글명 보정 + N150 재적재

- **완료(번역)**: N150 active `area` 중 KNPS `knps_protected_areas` 영어/로마자 source name을 모아
  Gemini 2.5 Flash에 JSON 입력/출력으로 일괄 번역했다. `kor-travel-concierge`의
  `GEMINI_API_KEY`/`gemini-2.5-flash`/JSON schema/retry 패턴을 참고했고, 런타임에는 Gemini를
  호출하지 않는 정적 한글명 테이블 1,431건으로 반영했다.
- **완료(코드)**: KNPS protected area 이름 결정 로직이 raw 한글 복구 후 번역 테이블을 사용한다.
  라틴 문자와 손상 한글 음절이 섞인 raw `ORIG_NAME`은 정상 한글 후보로 보지 않도록 보강했다.
- **완료(N150)**: API/Dagster/daemon 이미지를 재빌드·재기동하고 `knps_protected_areas` 1,516건을
  재적재했다. 기존 `f_global_*` 중복은 inactive 처리했고, geocoder fallback으로 현재도 global이
  정본인 130건은 active 유지했다.
- **완료(검증)**: 최종 N150 active `area`는 `knps_park_boundaries` 23건,
  `knps_protected_areas` 1,516건이며 active area 라틴 이름은 0건이다. 공식 UI live Playwright
  2개 smoke와 커스텀 BFF/UI smoke(1,516건 전체 cursor 순회, 라틴 이름 0건, console error 0건)가
  통과했다.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-25 (codex) — Admin 로그인 submit 보강 + N150 area live smoke

- **완료(코드)**: 로그인 form submit이 React state 대신 현재 `FormData` 값을 읽어 username/password를
  전송한다. 자동입력/테스트 입력 경로에서 DOM value와 React state가 어긋나도 빈 password가
  전송되지 않도록 input `name` 속성과 회귀 테스트를 추가했다.
- **완료(N150)**: 수정 frontend를 N150 production에 반영하고 `kor-travel-map-ui`를 재빌드·재기동했다.
  UI/API 컨테이너 모두 healthy 상태다.
- **완료(live e2e)**: 공식 live Playwright 인증 setup + `/features` 지도 smoke 통과. 추가 계측 smoke에서
  로그인 POST 200, 낮은 줌 area `include_geometry=false`/cluster 25개/partial 없음, 높은 줌
  `보성` area `include_geometry=true`/geometry source 및 area layer 렌더를 확인했다.
- **검증**: `npm run test -- src/components/login-form.test.tsx`, `npm run type-check`, 대상 ESLint,
  `git diff --check`, N150 Next production build 통과.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-24 (codex) — Admin area 클러스터링 + KNPS protected area 한글명 보정

- **완료(코드)**: 낮은 줌의 admin feature 지도에서는 `area` geometry를 요청하지 않고 centroid
  marker를 cluster source에 포함한다. 줌 14 이상에서만 area polygon/label geometry를 요청·표시하며,
  query 전환 중 이전 데이터를 유지해 지도 flicker를 줄인다.
- **완료(성능)**: area/route 중심 필터에서는 tile별 `page_size` 분할을 끄고, area-only 지도 조회가
  전체 bbox를 과도하게 잘라 false partial을 만들지 않도록 tile zoom을 한 단계 더 잘게 보정했다.
  tile별 `next_cursor`가 남는 경우 이어 받아 낮은 줌 area 누락 가능성을 줄인다.
- **완료(KNPS)**: `knps_protected_areas`는 raw 한글 후보(`ORIG_NAME` 등)를 우선하고,
  CP949로 잘못 decode된 recoverable UTF-8 문자열은 한글명으로 복구한다. 원문 byte가 이미 손상된
  값이나 repair 실패 후 CJK mojibake가 남는 값은 영어 fallback을 유지한다.
- **검증**: KNPS unit test, frontend type-check/build, 수정 frontend ESLint, `ruff check .`,
  `python -m mypy --strict src/kortravelmap`, import-linter, `git diff --check` 통과.
- **다음 한 작업**: PR 생성 후 CI green/머지, N150 prod 배포, 운영 area live smoke를 완료한다.

## 2026-06-24 (codex) — KNPS area 이름 복구 + N150 feature 화면 확인

- **완료(운영 확인)**: N150 `/features`에서 로그인 후 `area` 필터를 켜면 `203건 표시`,
  maplibre marker 203개, 테이블 `AREA active` 행이 표시된다. 운영 DB 기준 active `area`는
  KNPS 1,539건이고, geometry 없는 `krheritage` area 1,178건은 inactive 상태다.
- **완료(코드)**: KNPS `knps_park_boundaries`/`knps_protected_areas`는 provider normalized
  `name`이 비어도 raw 속성(`NPK_NM`, `NAME` 등)에서 이름을 복구해 area bundle을 만든다.
  이름 없는 trail/route record는 기존처럼 skip한다.
- **완료(N150)**: 수정 provider 파일을 N150에 반영하고 map API/Dagster/daemon을
  재빌드·재기동했다. 배포 후 API/Dagster 이미지의 반영과 `/features` area UI smoke를 확인했다.
- **검증**: `tests/unit/test_providers_knps.py` 45건 통과, `ruff check .` 통과,
  `python -m mypy --strict src/kortravelmap` 통과, import-linter 4계약 통과.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-24 (codex) — krheritage area 보정 + concierge 적재/N150 live 검증

- **완료(코드)**: `krheritage` provider는 Polygon/MultiPolygon 경계 geometry가 있을 때만
  `area` feature를 만들고, 좌표만 있는 유산은 `place`로 적재한다. 실제 면 geometry가 있을 때만
  centroid 좌표, 면적, `AreaDetail`을 기록한다.
- **완료(DB 정리 경로)**: 특정 provider source에서 생성된 active geometryless `area` feature를
  inactive 처리하는 repository/client 메서드를 추가했고, `krheritage_heritage_features` asset 적재
  후 자동 정리하도록 연결했다.
- **완료(provider 점검)**: 현재 `area` 생성 provider는 `knps`와 `krheritage`뿐이다. `knps`는 기존부터
  polygon geometry gate가 있고, `krforest`는 현재 point place dataset만 적재한다.
- **완료(N150)**: 수정 파일을 N150 `~/kor-travel-map`에 반영하고 map API/Dagster를 재빌드/재기동했다.
  `kor-travel-concierge-youtube/youtube_place_candidates` snapshot 79건을 active `place`로 적재했다.
  기존 `krheritage` active geometryless `area` 1,178건은 inactive 처리했고, 최종 active
  geometryless `area`는 0건이다.
- **검증**: 로컬 targeted unit/integration pytest, 수정 파일 ruff, 수정 Python strict mypy 통과.
  N150 API live e2e 통과. N150 UI live e2e는 admin 로그인 세션으로 features list/map smoke 4건과
  실제 concierge feature detail smoke 통과.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-23 (codex) — Admin 로그인 + public API key 관리

- **완료(코드)**: Next.js admin frontend에 `/login`, HttpOnly 세션, logout, `/api/proxy`
  BFF를 추가했다. 기존 REST client는 `/api/proxy`를 기본 base로 사용한다.
- **완료(API/DB)**: `ops.admin_auth_events`, `ops.public_api_keys` migration과 repo/router를
  추가했다. FastAPI admin router는 proxy secret 설정 시 trusted frontend proxy header를 요구하고,
  public REST surface는 `key` query 검증을 지원한다.
- **완료(env)**: gitignored `.env`에 `admin/ad.min`의 PBKDF2-SHA256 hash, session secret,
  admin proxy secret을 저장했다. 예시 env에는 placeholder만 추가했다. `kor-travel-geo` v2 key는
  현재 VWorld key와 동일하게 쓰도록 설정했다. Docker/env scripts도 VWorld key를
  `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` / `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`로 같은 값
  매핑하고, `$` 포함 secret을 보존하도록 raw dotenv 로딩으로 보강했다.
- **완료(PR#399 리뷰 반영)**: XFF/X-Real-IP 기본 불신, username mismatch PBKDF2 수행,
  proxy-secret deny 테스트, 401 로그인 리다이렉트, 로그인 실패 a11y, clipboard fallback,
  invalid UUID revoke 404화, Alembic revision id 32자 제한 대응을 반영했다.
- **검증**: `pytest -q` 1326 passed, `ruff check .` passed, `mypy --strict` 142 files passed,
  import-linter 4 contracts kept, admin frontend `npm run test` 37 passed, `npm run type-check`
  passed, `npm run lint` 0 errors / 기존 warnings 6, OpenAPI/type drift check passed,
  user-client typegen/type-check passed, compose config + shell syntax check passed.
- **prod smoke**: N150 production 서버에 반영했고, geo v2 `POST /v2/reverse`는 key 없이 `400`,
  VWorld와 같은 key로 `200`을 반환했다. map API `/v1/categories`도 key 없이 `401`, public key로
  `200`을 반환했다. map API 컨테이너 내부 `KorTravelGeoRestClient(api_key=...)` reverse 호출은
  `status=OK`, 후보 11건, 주소/법정동 코드 포함으로 성공했다.
- **다음 한 작업**: PR 생성 후 CI green 확인과 머지를 완료한다.

## 2026-06-23 (codex) — Admin 지도 route/area 렌더링 + N150 prod 반영

- **완료(코드)**: admin Feature 지도에 `marker_icon`/`marker_color` 기반 maki 마커를 적용하고,
  `weather` feature는 날씨 아이콘 대신 단순 색상 마커로 표시한다. `route`는 GeoJSON 선+이름
  라벨, `area`는 면+외곽선+이름·면적 라벨로 표시한다.
- **완료(API/DB)**: `/v1/features`와 `/v1/features/in-bounds`에 선택적
  `include_geometry`를 추가해 route/area `geometry`, area `area_square_meters`를 반환한다.
  낮은 축척 bbox SQL에서 `MATERIALIZED` CTE를 제거해 prod 109만 건 기준 큰 bbox plan을
  약 2.4초에서 약 3ms 수준으로 낮췄다. route/area 지도용 GeoJSON은 표시용 단순화와
  좌표 정밀도 제한을 적용해 대형 route 응답 크기를 줄였다. admin frontend는 viewport를
  WebMercator tile bbox로 나눠 tile별 react-query 캐시를 쓰도록 바꿨고, tile별
  `page_size` 자동 조정으로 낮은 축척 응답 총량을 제한한다.
- **완료(prod)**: N150 production 서버(`<prod-host-alias>`, `<prod-host-ip>`)의 기존 map
  컨테이너를 내리고 `~/kor-travel-map` rsync + docker-manager compose 재빌드/재기동으로
  직접 반영했다.
- **검증**: API 단위 테스트 `13 passed`, 신규 PostGIS geometry 통합 테스트 `1 passed`,
  admin `type-check`, ESLint 0 errors(기존 warnings 8), 수정 Python ruff 통과. WSL
  Playwright는 Chromium binary 미설치로 실행 불가.
- **다음 한 작업**: PR 생성/머지 흐름으로 정식 main 반영 후, 필요하면 서버 측 vector tile/MVT
  엔드포인트까지 확장할지 결정한다.

## 2026-06-23 (claude) — KMA 날씨 복제 제거 마이그레이션 + krex 휴게소 관측 기상 weather source

- **완료**: prod DB의 KMA 복제 날씨(30.3M행/15GB)를 batched DELETE + VACUUM FULL로 제거 →
  디스크 24G 회수, 60격자 anchor로 KMA 재적재(`feature_weather_values=66,766`, 복제 0).
- **완료(코드, PR 진행)**: krex 고속도로 휴게소 관측 기상을 weather-kind Feature로 적재
  (`feature_weather_krex_rest_areas` asset + `fetch_krex_rest_area_weather` + provider 변환
  `rest_area_weather_records_to_{bundles,values}`). `temperature→T1H`로 KMA 기온 빈틈 보강.
  CI-parity 통과(ruff/mypy×3/lint-imports/pytest). 자세한 내용은 journal 2026-06-23.
- **다음 한 작업**: PR 머지 후 prod dagster 이미지 재배포 → `feature_weather_krex_rest_areas`
  materialize → 휴게소 weather feature 생성 + 기온 nearest 커버리지(울진/태안 등 gap) 검증.
  EX key는 기존 `KEX_GO_API_KEY` 재사용(신규 env 불필요).

## 2026-06-21 Codex 작업 메모 — UI live e2e 재실행

사용자 지시에 따라 live UI e2e를 재실행했다. 정본 보고서:
[`docs/reports/ui-live-e2e-rerun-2026-06-21.md`](reports/ui-live-e2e-rerun-2026-06-21.md).

- live stack health 확인: API `:12701`, admin/user UI `:12705`, Dagster `:12702`.
- 1차 전체 suite: 629 passed / 1 failed.
- 실패는 제품 기능이 아니라 `home-density-matrix.spec.ts`의 `page.goto("/")`가 full `load`를
  기다리던 하네스 민감도 문제였다.
- `T-UI-E2E-LIVE-20260621`로 잡고 `gotoHome()`을
  `waitUntil: "domcontentloaded"`로 조정했다.
- 재검증: `npm run type-check:e2e` passed, 실패 케이스 단독 passed,
  리베이스 후 현재 브랜치 별도 live stack(`api :12711`, `admin/user UI :12715`,
  `dagster :12712`)에서 전체 live UI e2e `631 passed`.

## 2026-06-21 Codex 작업 메모 — UI e2e 테스트 3배 확장

사용자 지시에 따라 UI e2e를 기존 209개에서 631개로 확장했다. 정본 보고서:
[`docs/reports/ui-e2e-density-expansion-2026-06-21.md`](reports/ui-e2e-density-expansion-2026-06-21.md).

- 신규 `home-density-matrix.spec.ts` 422개 추가:
  - 공용 shell/nav 18개 항목의 href/icon/same-tab/a11y name/mobile/viewport matrix
  - 홈 metric count 포맷, import job/dedup summary, Backend/Dagster 상태 badge
  - endpoint 실패 노출/비노출 정책, 새로고침 refetch
- 검증:
  - `npm run type-check:e2e` passed
  - 신규 spec 단독 `422 passed`
  - 전체 Playwright e2e `631 passed`

## 2026-06-21 Codex 작업 메모 — 사용자/admin UI live e2e dev/prod green

사용자 지시에 따라 dev에서 사용자/admin UI live e2e를 먼저 평가했다. 정본 보고서:
[`docs/reports/ui-live-e2e-dev-prod-copy-2026-06-21.md`](reports/ui-live-e2e-dev-prod-copy-2026-06-21.md).

- WSL dev stack: API `:12701`, Dagster `:12702`, admin/user UI `:12705` ready.
- 안정화:
  - `run-admin-stack.sh`가 깨진 Dagster console-script shebang을 현재 venv Python entrypoint로
    fallback 한다.
  - Next 16 dev server는 e2e 스택에서 `next dev --webpack`으로 띄워 Turbopack panic을 우회한다.
  - Playwright artifact/report는 OS temp로 이동해 Next watcher 간섭을 제거한다.
  - mock e2e의 `/_next/` 정적 자산 passthrough, `home-nav` deep-link 안정화,
    feature-update-request 폴링 race gate를 반영했다.
- 검증:
  - unmocked live spec 6개/19 tests passed
  - 전체 admin e2e `209 passed`
  - `npm run type-check:e2e`, `bash -n scripts/run-admin-stack.sh`, `git diff --check` passed
- prod 복사/검증:
  - dev 변경과 `.env` 계열 설정을 `F:\dev\kor-travel-map` prod worktree로 복사했다.
  - 기존 `.env`는 `.backup-20260621-115048`로 백업했고, 최종 재복사 전
    `.backup-20260621-122939`도 추가로 남겼다.
  - prod stack을 새 `.env` 기준으로 재기동한 뒤 전체 admin e2e `209 passed`를 다시 확인했다.

## 2026-06-21 Codex 작업 메모 — concierge/geo prod API 계약 재점검

사용자 지시에 따라 형제 repo를 로컬에서 다시 읽고 prod live smoke를 수행했다. 정본 보고서:
[`docs/reports/prod-api-live-contract-check-2026-06-21.md`](reports/prod-api-live-contract-check-2026-06-21.md).

- `kor-travel-concierge`는 `origin/main` `bec63ad2ab39` 기준 export 계약
  (`/api/v1/features/{snapshot,changes}`, `X-API-Key`, `{items,next_cursor,has_more}`,
  `limit<=500`, provider/dataset/source identity)이 현재 Dagster fetcher와 provider
  loader에 맞았다. prod env에서 snapshot/changes `limit=1` 200, fetcher 첫 item read,
  live item → `FeatureBundle` 변환 성공.
- `kor-travel-geo`는 `origin/main` `8b7efbe20e92` 기준 v2 후보 좌표가
  `PointV2{lon,lat}` 정본이다. `kortravelmap.geocoding`의 REST 파서가 구 `x/y`만
  읽던 drift를 수정해 `lon/lat` 우선 + `x/y` fallback으로 맞췄다.
- live smoke: geo geocode/reverse/regions-within-radius 통과, concierge export/loader
  read-only smoke 통과. DB write나 Dagster materialize는 실행하지 않았다.
- 검증: `test_geocoding.py` 58 passed, 관련 ruff passed,
  `test_providers_kor_travel_concierge.py` + Dagster `test_provider_fetchers.py`
  71 passed / 1 skipped(`mois.db` optional).

**다음 한 작업은 기존과 동일하게 T-229-buildx**(GITHUB_TOKEN이 있는 배포 환경에서
arm64 multi-arch buildx 검증)이다.

## 2026-06-20 Codex 작업 메모 — Claude PR #481~#484 리뷰 후속

사용자 요청으로 2026-06-19 00:00 KST 이후 Claude Code가 올린 merged/closed PR #481~#484를
확인했다. 기존 리뷰 스레드는 없었고, closed PR #481/#482/#483에 리뷰 코멘트를 남긴 뒤 세
결함과 full-run 검증 중 드러난 logging 격리 결함을 하나의 후속 브랜치에서 수정했다.

- **#481 후속**: 직접 `docker compose` 실행 또는 `KOR_TRAVEL_MAP_ADMIN_WEB_PORT` 커스텀 포트에서
  API CORS fallback이 `12705`로 고정되던 문제를 고쳤다.
- **#482 후속**: live `kor-travel-geo` v2 응답의 `point: {lon, lat}`를 기존 `{x, y}` 전용
  파서가 처리하지 못하던 문제를 고쳤다. geocode/reverse 경로 모두 `x/y`와 `lon/lat`를 수용한다.
- **#483 후속**: host network override가 bridge용 `KOR_TRAVEL_MAP_DOCKER_*` 기본값을 물어
  `dagster`/`rustfs` 주소를 유지하거나 external Postgres 포트/DSN override를 덮던 문제를 고쳤다.
  host 모드는 `127.0.0.1:<12xxx>`를 기본으로 렌더하고, 명시 external override를 보존한다.
- **검증 후속**: Alembic migration logging 설정이 기존 `kortravelmap.*` logger를 disable해
  full-run 순서에서 `caplog` 테스트가 실패하던 문제를 `disable_existing_loggers=False`로 고쳤다.
- **검증**: `docker compose config`로 default/host/external 렌더와 커스텀 admin port CORS를 확인하고,
  geocoding 단위 테스트에 `point.lon/lat` 케이스를 추가했다.

**다음 한 작업**: 기존과 동일하게 **T-229-buildx — arm64 multi-arch buildx 배포 검증**
(`GITHUB_TOKEN` 필요).

## 2026-06-19 Codex 작업 메모 — admin frontend stack 문서 정합성 정리

사용자 요청으로 architecture 계열 문서의 frontend stack 표현을 현재 구현 기준으로
정리했다.

- **지도**: admin frontend는 `maplibre-vworld-js`/`maplibre-vworld` dependency를 쓰지 않고,
  `maplibre-vworld-react` web/core 모델을 내부 포팅한 MapLibre GL + VWorld 구현을 쓴다고
  정정했다.
- **테이블**: 운영 목록/검토 화면은 공용 `DataTable`
  (`@tanstack/react-table` v8 + `@tanstack/react-virtual` v3) 기반이며,
  shadcn `Table`은 표시 primitive라고 명시했다.
- **정리 대상**: `architecture.md`, `debug-ui-package.md`, OpenAPI/frontend workflow 문서,
  ADR index/ADR-045, Sprint 문서, VWorld key 문서.

**다음 한 작업**: 기존과 동일하게 **T-229-buildx — arm64 multi-arch buildx 배포 검증**
(`GITHUB_TOKEN` 필요).

## 2026-06-18 Codex 작업 메모 — README 진입 문서 정리 PR 대기

사용자 요청으로 루트 README를 현재 운영 모델 기준의 짧은 진입 문서로 정리했다.

- **정리 범위**: 소개/운영 모델/책임 범위/빠른 시작/저장소 구조/핵심 규칙/검증/문서 길찾기.
- **중복 제거**: 긴 provider·ETL·문서 세부 목록은 `docs/etl/`, `docs/architecture/`,
  `docs/runbooks/`, `docs/adr/README.md` 등 정본 문서로 포인터화했다.
- **다음 한 작업**: 기존과 동일하게 **T-229-buildx — arm64 multi-arch buildx 배포 검증**
  (`GITHUB_TOKEN` 필요).

## 2026-06-18 claude 작업 메모 — PR #476 리뷰 + admin e2e 라이브 검증

- **#476 리뷰**: LOW 1건(`frontend.yml` stale 주석 — 제거된 maplibre-vworld git dep 참조) 정정,
  코드 결함 없음.
- **admin e2e 라이브**: Windows dev server :12706 + Playwright chromium으로 route-mock 전 spec
  **197 passed / 0 failed**. WSL은 win32-only `@next/swc` node_modules라 `next dev` 불가 → Windows 실행.
  backend-의존 4 spec(curated-features·features-new·dagster·etl)은 제외(Docker 미기동, 기결정).
- **라이브가 잡은 #471 잠복 회귀 정정**: `home.spec.ts`(Backend/Dagster heading → `서비스 상태` +
  service-backend/dagster testid), `features-list.spec.ts`(`bg-primary` → `bg-brand`). #477 home-nav
  수정도 라이브 green 확인.

**다음 한 작업**: in-repo 즉시 실행 트랙 없음(잔여 `T-229-buildx` 배포환경 · `T-101` 보류 ·
`T-AUDIT-0616` F-01 옵션 A deferred).

## 2026-06-18 Codex 작업 메모 — T-MAP-VWORLD-04 dependency 제거 완료

사용자 요청으로 GitHub Task #475(`T-MAP-VWORLD-04`)를 만들고,
`digitie/maplibre-vworld-react` `a7cb0f8` 기반 admin web 지도 정리를 완료했다.

- **제거**: admin frontend와 `@kor-travel-map/map-marker-react`에서
  `maplibre-vworld`(`digitie/maplibre-vworld-js`) dependency/peer/devDependency,
  `maplibre-vworld/style.css` import, Vite external/global 선언 제거. lockfile에서도
  `maplibre-vworld`와 전용 transitive 제거.
- **보강**: `vworld-style.ts`를 `vworld-map-core`식 tile URL/style/maxZoom/redaction
  경계로 정리하고, `VWorldMapView`에 maxZoom clamp, redacted error logging, stable marker
  click callback을 반영. VWorld key 미설정 fallback 계약은 유지.
- **검증**: admin type-check, marker typecheck/build, admin vitest 27 passed,
  ESLint 0 errors(기존 warnings 6), Next build, Windows Playwright 지도 e2e
  `features-map-interactions.spec.ts` 5 passed.

**다음 한 작업**: **T-229-buildx — arm64 multi-arch buildx 배포 검증** (`GITHUB_TOKEN` 필요).

## 2026-06-18 claude 작업 메모 — T-452 OpenAPI problem+json 보강 완료

`T-452-openapi-problem-json`을 종결했다. 생성 OpenAPI가 에러 응답을 problem+json으로 선언한다.

- **구현**: `create_app`의 custom `app.openapi()`가 모든 operation의 4xx/5xx·`default` 응답을
  RFC7807 `application/problem+json`(`ProblemDetail`/`ProblemDetailError`)으로 선언. FastAPI 자동
  422도 problem+json으로 대체, orphan(`HTTPValidationError`) 제거. 핸들러별 `responses=` 대신
  중앙 핸들러(`_error_response`)와 대칭인 중앙 주입 방식.
- **산출물**: `openapi.json`/`openapi.user.json` 재생성 + admin/user-client `gen:types`. e2e mock 1건
  (`change-requests-lifecycle.spec.ts`)을 `ProblemDetail`로 재바인딩.
- **검증(Python 3.13 컨테이너)**: ruff·`mypy --strict -p kortravelmap.api`·api pytest 전수 green,
  `export_openapi.py --check` drift gate OK, admin/user-client `gen:types:check`·type-check OK.
  로컬 venv 부재라 throwaway `python:3.13` Docker로 CI 동등 환경 재현.

**다음 한 작업**: 이 저장소 즉시 실행 가능한 in-repo 트랙 없음. 잔여는 `T-229-buildx`
(배포환경 `GITHUB_TOKEN`)·`T-101`(MV 보류)·`T-AUDIT-0616` F-01 옵션 A(deferred)뿐.

## 2026-06-18 claude 작업 메모 — T-ADMIN-TANSTACK 종결 + item-4(라이브 e2e) 결정

- **T-ADMIN-TANSTACK 종결**: (a) backend-의존 e2e는 2026-06-17 라이브 스택에서 이미 57/0
  통과로 검증됨 — 사용자 결정(이미 검증됨 → 재실행 생략)에 따라 재기동 없이 닫음. (b) bulk 정책
  가드(완료 review 재결정 차단 · curated bulk archive confirm)는 main에 이미 구현됨 확인.
- **item-4 라이브 Docker 결정**: 신규 스택 기본 포트(pg 5432 · rustfs 12101)가 공유 인프라
  (kor-travel-geo-postgres 등)와 충돌하고, 로컬(Claude worktree) ignored `.env`가 구
  `KRTOUR_MAP_*` prefix(현 코드는 `KOR_TRAVEL_MAP_*` — 미스매치)라 기존
  `python-krtour-map-claude` 스택은 stale/unhealthy다.
  e2e는 이미 라이브 검증(57/0 · 209 passed)됐으므로 공유 인프라 무중단을 위해 재실행하지 않는다.
- **T-AUDIT-0616**: e2e(HIGH)는 라이브 검증 완료로 ✅, 잔여는 F-01 옵션 A(전 feature re-key)
  deferred 1건.

**다음 한 작업**: `T-452-openapi-problem-json`(OpenAPI 에러 본문 RFC7807 problem+json 보강) —
이 저장소 유일 즉시 실행 트랙.

## 2026-06-18 claude 작업 메모 — 외부/보류 task won't-do 종결

사용자 지시로 백로그의 외부 추적 4건과 보류 1건을 진행하지 않음(won't-do)으로 종결했다.

- **종결(won't-do)**: `T-019`, `T-210b`, `T-210c`, `T-210d`(전부 PinVi repo 외부),
  `T-103`(streaming ETL — 초 단위 latency 요구 provider 증거 없음). `docs/tasks.md` 외부
  추적 섹션 제거 + 보류에서 T-103 제거, `docs/tasks-done.md` 상단 아카이브.
- **유지**: `T-229-buildx`(arm64 buildx, `GITHUB_TOKEN` 배포환경), `T-101`(MV 보류),
  열린 in-repo task `T-452-openapi-problem-json`·`T-ADMIN-TANSTACK`·`T-AUDIT-0616`.

**다음 한 작업**: 이 저장소 즉시 실행 트랙은 `T-452-openapi-problem-json`(OpenAPI problem+json
보강)과 `T-ADMIN-TANSTACK` 잔여(backend-의존 e2e 라이브·bulk 정책 가드). `T-229-buildx`는
배포환경 잔여로 변동 없음.

## 2026-06-18 Codex 작업 메모 — admin frontend StyleSeed 디자인 규칙 적용

사용자 요청에 따라 `https://styleseed-demo.vercel.app/llms.txt` 및 연결된
`llms-full.txt`의 StyleSeed 규칙을 admin frontend 공통 디자인 표면에 반영했다.

- **적용 범위**: `globals.css` design token, `AdminShell`, 홈 KPI/상태 카드,
  공용 `Card`/`Button`/`Badge`/`StatusBadge`/`Table`/`DataTable`/form primitive.
- **핵심 변경**: 단일 brand accent + grayscale surface, 카드 기반 정보 표면,
  낮은 shadow, 명시적 type scale, 숫자+단위 2:1 표시, KPI secondary element 변형,
  모바일 grid overflow 방지.
- **검증**: frontend type-check 통과, ESLint 0 errors(기존 warnings 6), public env
  주입 `next build` 통과, `12705` production 서버 HTTP 200 및 Playwright screenshot
  1280×720/390×844 확인.
- **문서화**: [`docs/architecture/admin-frontend-design-rules.md`](architecture/admin-frontend-design-rules.md)에
  StyleSeed 기반 로컬 admin frontend 규칙을 정리했다.
- **환경 메모**: WSL `/usr/local/bin/node`가 bus error를 내 Windows Node로 검증을
  대체했다. 현재 `http://127.0.0.1:12705/`에 production frontend 서버가 떠 있다.

**다음 한 작업**: **T-229-buildx — arm64 multi-arch buildx 배포 검증** (`GITHUB_TOKEN` 필요).

## 2026-06-17 Codex 작업 메모 — maplibre-vworld-react 지도 e2e 종결

`T-MAP-VWORLD-03`(#467)을 종결했다. PR #469 merge 후 main 기준으로 WSL dev server +
Windows Playwright 흐름에서 지도 e2e를 다시 실행했고, `features-map-interactions.spec.ts`
**5 passed / 0 failed**를 확인했다.

- **검증 환경**: WSL `0.0.0.0:12706`, Windows `E2E_BASE_URL=http://172.26.51.35:12706`,
  `NEXT_ALLOWED_DEV_ORIGINS=172.26.51.35`.
- **검증 범위**: map/table 탭, bbox fetch, kind 필터 refetch, table 선택→지도 상세 패널,
  error/empty 상태.
- **후속 수정**: 최종 e2e에서 추가 수정할 회귀는 없었다. 정본 리포트는
  `docs/reports/maplibre-vworld-react-e2e-2026-06-17.md`.

**다음 한 작업**: **T-229-buildx — arm64 multi-arch buildx 배포 검증** (`GITHUB_TOKEN` 필요).

## 2026-06-17 Codex 작업 메모 — admin features 지도 VWorldMapView 전환

`T-MAP-VWORLD-02`(#466)를 구현했다. `features-client.tsx`에서 직접
`new maplibregl.Map()`과 marker 배열을 소유하던 코드를 제거하고,
`src/components/vworld-map-view.tsx`의 `VWorldMapView`/`VWorldMarker` 컴포넌트로
전환했다.

- **유지한 동작**: bbox 동기화, kind 필터 refetch, marker/table 선택 상세 패널,
  VWorld key 미설정 fallback, table/map 상태 공유.
- **e2e 환경 보강**: Windows localhost forwarding이 붙지 않는 경우 WSL IP로 dev 서버에
  접근할 수 있도록 `NEXT_ALLOWED_DEV_ORIGINS`를 `next.config.ts`에 반영했다.
- **검증**: frontend type-check 통과, ESLint 0 errors(기존 warnings 6), vitest
  27 passed, `NEXT_PUBLIC_*` env 주입 build 통과, Windows Playwright 지도 e2e
  `features-map-interactions.spec.ts` 5 passed.

**다음 한 작업**: **T-MAP-VWORLD-03 — 지도 e2e 라이브 검증 및 후속 수정**.

## 2026-06-17 Codex 작업 메모 — maplibre-vworld-react 지도 전환 계획 수립

사용자 요청에 따라 admin UI 지도를
[`digitie/maplibre-vworld-react`](https://github.com/digitie/maplibre-vworld-react) 기반으로
전환하는 작업을 시작했다. 참조 repo는 2026-06-17 기준 `a7cb0f8`를 확인했고,
정본 계획은 `docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`다.

- **GitHub Task 생성**: #465(`T-MAP-VWORLD-01` 계획), #466(`T-MAP-VWORLD-02` 지도 전환),
  #467(`T-MAP-VWORLD-03` e2e/후속 수정).
- **범위 결정**: 전체 외부 모노레포 vendoring이 아니라 admin `features` 지도에 필요한
  `VWorldMapView`/React marker 모델을 얇게 이식한다. 기존 bbox 동기화, kind 필터,
  선택 상세 패널, VWorld key 미설정 fallback은 유지한다.

**다음 한 작업**: **T-MAP-VWORLD-02 — admin features 지도를 VWorldMapView 기반으로 전환**.

## 2026-06-17 claude 작업 메모 — 문서 구조 정리 (PR 대기)

문서 트리 재배치 + entry 슬림(단일 PR, 코드 동작 무변경): ADR `docs/decisions.md`→`docs/adr/NNN-*.md`(53)
+ 색인, 개발규칙 6건은 SKILL §4로 이전; ETL 17개→`docs/etl/`; architecture/계약/패키징 19개→
`docs/architecture/`; CLAUDE/AGENTS/README/SKILL 중복 제거·단일정본 포인터화·v1 1줄; tasks 작성규약을
`docs/tasks-rule.md`로 분리; Telegram MCP(설정 5 + 런처 + 문서) 제거. 내부 링크/py_compile/JSON 검증 통과.
정본 색인은 [`docs/adr/README.md`](adr/README.md). **다음 한 작업은 아래 T-229-buildx로 변동 없음.**

## 2026-06-17 claude 작업 메모 — admin UI TanStack 테이블 이행 + #452 후속 종결

- **PR #453 머지**: issue #452(Claude Code PR #437~#450 리뷰 취합)의 잔여 조치 일괄 반영 — KHOA
  re-key cleanup 마이그레이션(alembic 0027)·Prometheus path label·geocoder blast radius 문서/테스트·
  REST/의존체인/ServiceToken 정합·ADR-059(벤더링 agent/skill 예외) 등. CI green.
- **PR #454 머지**: admin UI 전 테이블(20파일/~22테이블)을 공용 `DataTable`(@tanstack/react-table v8
  + react-virtual v3)로 이행. 정렬 헤더(aria-sort)·다중선택/bulk(dedup·curated)·`features` 가상화.
  정본 `docs/reports/admin-tanstack-table-migration-2026-06-17.md`. tsc/ESLint/vitest(20)/next build/
  route-mocked Playwright(16)/CI 전부 green. backend-의존 e2e는 role/name 셀렉터라 호환(audit+grep 무변경).

- **admin UI 테이블 backend-의존 e2e 라이브 실행 완료**(2026-06-17): 라이브 Docker 스택(codex
  api :12701/dagster :12702 + 재빌드한 migrated frontend :12705 + playwright host-network 컨테이너)에서
  전 spec 실행 → 최초 54/3 → **PR #458**(offline-uploads `offline-upload-row` testid 복원, 이행 회귀)
  후 55/2 → **PR #459**(required 필드 접근성 이름 정정, 아래) 후 **57 passed / 0 failed**.
- **PR #459(required 필드 접근성 이름)**: `FormField`/`FormSelect`/`FormTextArea`의 `required` 별표
  `<span aria-hidden> *</span>`가 Chromium accname에 누수돼 접근성 이름이 `"name *"`가 되던 문제를
  공용 헬퍼 `requiredFieldAriaLabel`로 명시 `aria-label` 부여해 정정(별표 시각 유지·spec 회귀 0·
  전역 `getByLabel(exact)` 정상화). features-new.spec 2건 green.

**다음 한 작업**: 즉시 실행 가능한 큰 트랙 없음(admin UI 테이블 이행 + 라이브 e2e 전부 green). 잔여는
(1) **arm64 buildx 배포 검증**(`GITHUB_TOKEN` 필요), (2) bulk 동작 정책 가드(완료 review 재결정·
archive confirm, 선택)뿐.

## 2026-06-14 claude 작업 메모 — T-229 curated 오버레이 라이브 검증 완료

T-229(T-225가 분리한 라이브 검증 후속)를 종결했다. 정본 리포트
`docs/reports/t-229-curated-live-verify-2026-06-14.md`.

- **복원 불필요**: T-212e 데이터가 옛 claude postgres(15433)에 그대로 잔존
  (features 1,095,665 / weather 92,923 / source_records 1,111,885) + 격리 복원본
  `krtour_map_restore` 존재. 운영 데이터 무손상 원칙으로 **복원본에만** 검증 수행.
- **(A) curated 오버레이 완전 검증** [AS-01/API-11/12 해소]: `curated_features_refresh`
  4-asset RUN_SUCCESS → `curated_features` **0 → 86,341** 후보(테마 7종, MCST source
  카운트와 정합). admin API가 실제 서빙(예: 원동탁구클럽/레저), 사용자 표면은 미선택
  후보 숨김(선택 게이트 정상), curated-themes/sources 200, tripmate-copy는 선택 시
  생성(설계대로 0). T-212e reload 때 단지 실행되지 않았을 뿐 파이프라인은 정상.
- **(B) `/metrics` 200 검증**, **(C) smoke breadth 전 표면 응답**(200/정상404).
- **유일 잔여: arm64 buildx** — WSL에 `GITHUB_TOKEN` 부재로 이미지 빌드 불가 →
  토큰 있는 배포 환경의 후속(코드/데이터 결함 아님).
- 환경: codex 스택은 사용자 지시대로 강제종료 후 external-infra로 재기동(이미지 재사용).
  worktree 정리(메인 FF + review 잡파일 104개 제거, claude stray 빌드 산출물 제거)도 완료.

**다음 한 작업**: 본 저장소 즉시 실행 가능한 큰 트랙 없음. 잔여는 **arm64 buildx
배포 시점 검증**(GITHUB_TOKEN 필요)뿐. (운영 외 작업: GitHub repo가
`kor-travel-map`으로 rename됨.)

## 2026-06-13 claude 작업 메모 — T-225 T-212e closure 재검증 완료

T-225를 종결했다. 정본 리포트
`docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`.

- 라이브 재실행 없이 현재 main(`25b286b`, #434 포함) 기준 **문서/코드 증거 대조**로
  닫았다(인수기준 충족). 5개 차원 교차검증 + 각 gap 반증(서브에이전트 18).
- **T-212e closure 유효**: 실패 provider 6건 수정 전부 main에 존재(pin SHA 일치),
  리포트 무결성 정합(MCST 13종 합계 102,121, 이슈 #397/#407/#409 close + 보강 PR
  머지, broken link 없음), identity는 이미 post-rename(#429가 리포트까지 재작성),
  패키지 분리(#430)·#434 포트 재기준은 reload 데이터 closure에 영향 없음.
- 착수 가정이던 "구 이름 drift"는 실재하지 않았다(리포트가 이미 새 identity 기준).
- 남은 것은 **라이브 검증이 미수행된 커버리지 갭**(코드 결함 아님) → 후속 **T-229**로
  분리: (A) curated 오버레이(`curated_features_refresh` + admin/사용자 `curated-*` +
  `tripmate-copy`) 라이브 검증, (B) reload 이후 신규 표면(Prometheus `/metrics`,
  arm64 buildx), (C) smoke breadth(features/batch·by-target, ops/providers, ops 관측,
  governance 리뷰 큐, debug/mois-license).
- 반증되어 갭 아님: ops/consistency API(e2e로 실제 호출), backups/restore API(설계상
  opt-in 래퍼 — 스크립트는 라이브 검증), poi-cache/refresh-policy(T-212e 이전 기능).

**다음 한 작업**: **T-229 — T-212e 후속 라이브 검증**(curated 오버레이 +
post-reload 신규 표면 + smoke breadth). 라이브 Docker 스택 필요.

## 2026-06-13 Codex 작업 메모 — T-108 운영 배포 자동화

pinvi의 `T-108`을 kor-travel-map 운영 범위로 이식했다.

- 사용자 재지시에 따라 streaming replication은 하지 않는 것으로 ADR-056에 명시했다.
- `scripts/docker-buildx.sh` / `npm run docker:buildx`로 N150 16GB(`linux/amd64`)와
  Odroid M1S(`linux/arm64`)용 multi-platform Docker image build/push를 고정했다.
- `.env.example`, `docs/deploy.md`, `docs/runbooks/docker-app.md`, `docs/tasks-done.md`,
  `docs/journal.md`를 같은 기준으로 갱신했다.

**다음 한 작업**: **T-225 — T-212e closure 재검증**.

## 2026-06-13 Codex 작업 메모 — 태스크 문서 정리

태스크 문서의 역할을 다시 분리했다.

- `docs/tasks.md`는 열린 `[ ]` 항목만 남기는 백로그로 축소했다.
- 완료된 `T-RV-*`, `T-200~T-228`, `T-212a~d`, `T-216`, `T-218` 묶음은
  `docs/tasks-done.md`에서 요약 아카이브한다.
- 오래된 Sprint 2/3 미완료 표기와 중복 완료 체크박스가 현재 인수인계에 다시
  노출되지 않게 이 파일을 현재 상태 중심으로 정리했다.

**다음 한 작업**: **T-225 — T-212e closure 재검증**.

## 현재 상태

Sprint 5 운영 진입 마무리다. 핵심 구현과 운영 표면은 대부분 닫혔다.

- `T-212e` 실데이터 full reload 완료: 1,095,665 features, weather values 92,923,
  consistency report `99159eea` OK, offline upload 3포맷 + DELETE lifecycle, Windows
  Playwright 33/33, API smoke 17/17, backup/restore smoke.
- `T-221` admin UI/UX 연결성, `T-222` 공개 해수욕장/축제 뷰 API, `T-223`
  curated feature/PinVi import, `T-224` concierge provider 경계 정리는 완료됐다.
- `T-226` 패키지/runtime identity clean cut, `T-227` Prometheus 메트릭, `T-228`
  API/backend와 admin frontend 패키지 분리도 완료됐다.
- `T-225`(T-212e closure 재검증, 2026-06-13)·`T-229`(curated 오버레이 + post-reload
  표면 라이브 검증, 2026-06-14)는 완료됐다. 본 저장소에서 즉시 실행 가능한 큰 트랙은
  없고, 유일 잔여는 **arm64 multi-arch buildx 배포 검증**(`T-229-buildx`, `GITHUB_TOKEN`이
  주입된 배포 환경 필요)뿐이다. PinVi 쪽 작업(`T-019`/`T-210b`~`d`)과 streaming ETL(`T-103`)은
won't-do로 종결했다(`docs/tasks-done.md`).

## 다음 한 작업

### T-229-buildx — arm64 multi-arch buildx 배포 검증 (T-229 잔여)

T-229의 라이브 검증(curated 오버레이 0→86,341 후보, `/metrics` 200, smoke breadth)은
완료됐다(정본 `docs/reports/t-229-curated-live-verify-2026-06-14.md`). 유일 잔여는
T-108/ADR-056의 arm64 multi-arch buildx 이미지 build+boot smoke다.

목표:

- `scripts/docker-buildx.sh`로 `linux/arm64`(Odroid M1S) 이미지를 빌드하고 단일
  platform 부팅 smoke를 통과시킨다.

전제:

- provider repo(`python-*-api`)가 2026-06-22부로 전부 public 전환되어 `GITHUB_TOKEN`
  없이도 `.[providers]`를 빌드할 수 있다. arm64 빌더(QEMU/네이티브)만 있으면 수행 가능하다.

완료 시:

- arm64 빌드+부팅 smoke 결과 또는 불가 사유를 `docs/reports/`에 기록한다.
- `docs/tasks.md`에서 `T-229-buildx`를 제거하고 `docs/tasks-done.md`로 이동한다.
- `docs/journal.md`에 역시간순 엔트리를 추가한다.

## 열린 작업 요약

즉시(in-repo): 없음 (`T-452` 종결).

배포환경 잔여:

- `T-229-buildx` — arm64 multi-arch buildx 배포 검증 (`GITHUB_TOKEN` 필요).

보류 / deferred:

- `T-101` — Materialized View 도입 검토.
- `T-AUDIT-0616` — 잔여 = F-01 옵션 A(전 feature DB re-key, big-bang) 1건뿐, 별도 시점 결정.

종결 (2026-06-18):

- won't-do: `T-019` · `T-210b`~`d`(PinVi 외부) · `T-103`(streaming ETL).
- `T-ADMIN-TANSTACK`: (a) 라이브 e2e 57/0 검증 · (b) bulk 가드 main 구현.
- `T-452-openapi-problem-json`: OpenAPI 4xx/5xx problem+json 선언 — 상세 `docs/tasks-done.md`.

## 고정 기준값

- 배포명: `kor-travel-map`.
- Python import root: `kortravelmap`, 권장 예시 `import kortravelmap as ktm`.
- REST API backend: `kor-travel-map-api`, import `kortravelmap.api`,
  위치 `packages/kor-travel-map-api/`.
- Admin UI frontend: `kor-travel-map-admin`,
  위치 `packages/kor-travel-map-admin/frontend/`.
- CLI: `ktmctl`.
- Env prefix: `KOR_TRAVEL_MAP_*`, API package prefix `KOR_TRAVEL_MAP_API_*`,
  frontend API base `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`.
- DB: `kor_travel_map`, Dagster metadata DB: `kor_travel_map_dagster`.
- 로컬 고정 포트(docker-manager 기준): API `12701`, admin UI `12705`,
  Dagster `12702`, RustFS S3 `12101`, RustFS console `12105`,
  kor-travel-geo API `12501`.
- PinVi 연동: OpenAPI HTTP. 직접 import와 DB 직접 접근 없음.

## 참고 위치

- 백로그: `docs/tasks.md`.
- 완료/아카이브: `docs/tasks-done.md`.
- 작업 일지: `docs/journal.md`.
- Sprint 계획: `docs/sprints/`.
- REST 단일 정본: `docs/architecture/rest-api.md`.
- Cross-repo 정본: `docs/integration-map.md`.
