# resume.md — 현재 진척도와 다음 한 작업

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
배포 시점 검증**(GITHUB_TOKEN 필요)뿐. (운영 외 작업: GitHub repo rename
`python-krtour-map`→`kor-travel-map` 진행 중.)

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
  curated feature/TripMate import, `T-224` concierge provider 경계 정리는 완료됐다.
- `T-226` 패키지/runtime identity clean cut, `T-227` Prometheus 메트릭, `T-228`
  API/backend와 admin frontend 패키지 분리도 완료됐다.
- `T-225`(T-212e closure 재검증, 2026-06-13)·`T-229`(curated 오버레이 + post-reload
  표면 라이브 검증, 2026-06-14)는 완료됐다. 본 저장소에서 즉시 실행 가능한 큰 트랙은
  없고, 유일 잔여는 **arm64 multi-arch buildx 배포 검증**(`T-229-buildx`, `GITHUB_TOKEN`이
  주입된 배포 환경 필요)뿐이다. TripMate 쪽 작업은 외부 추적으로만 남긴다.

## 다음 한 작업

### T-229-buildx — arm64 multi-arch buildx 배포 검증 (T-229 잔여)

T-229의 라이브 검증(curated 오버레이 0→86,341 후보, `/metrics` 200, smoke breadth)은
완료됐다(정본 `docs/reports/t-229-curated-live-verify-2026-06-14.md`). 유일 잔여는
T-108/ADR-056의 arm64 multi-arch buildx 이미지 build+boot smoke다.

목표:

- `scripts/docker-buildx.sh`로 `linux/arm64`(Odroid M1S) 이미지를 빌드하고 단일
  platform 부팅 smoke를 통과시킨다.

전제:

- private provider pin 빌드에 `GITHUB_TOKEN`이 필요하므로 **토큰이 주입된 배포
  환경**에서만 수행 가능하다(코드/데이터 결함 아님).

완료 시:

- arm64 빌드+부팅 smoke 결과 또는 불가 사유를 `docs/reports/`에 기록한다.
- `docs/tasks.md`에서 `T-229-buildx`를 제거하고 `docs/tasks-done.md`로 이동한다.
- `docs/journal.md`에 역시간순 엔트리를 추가한다.

## 열린 작업 요약

즉시:

- `T-229-buildx` — arm64 multi-arch buildx 배포 검증 (T-229 잔여, `GITHUB_TOKEN` 필요).

외부 추적:

- `T-019` — TripMate Kakao Maps → maplibre-vworld 교체와 SPEC supersede.
- `T-210b` — TripMate 문서 supersede.
- `T-210c` — TripMate `apps/etl` 레거시 Dagster 이관/삭제.
- `T-210d` — TripMate httpx OpenAPI client 신규.

보류:

- `T-101` — Materialized View 도입 검토.
- `T-103` — streaming ETL 대응.

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
- TripMate 연동: OpenAPI HTTP. 직접 import와 DB 직접 접근 없음.

## 참고 위치

- 백로그: `docs/tasks.md`.
- 완료/아카이브: `docs/tasks-done.md`.
- 작업 일지: `docs/journal.md`.
- Sprint 계획: `docs/sprints/`.
- REST 단일 정본: `docs/rest-api.md`.
- Cross-repo 정본: `docs/integration-map.md`.
