# resume.md — 현재 진척도와 다음 한 작업

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
- 본 저장소에서 즉시 실행 가능한 남은 큰 트랙은 T-225 하나다. TripMate 쪽 작업은
  외부 추적으로만 남긴다.

## 다음 한 작업

### T-225 — T-212e closure 재검증

목표:

- `docs/reports/t-212e-live-full-reload-final-2026-06-12.md` 결과가 최신 main 기준의
  provider/API/admin 표면을 충분히 포괄하는지 재대조한다.
- full reload 재실행이 필요할 만큼 큰 drift가 없으면, 기존 evidence를 확인해
  closure 리포트로 닫는다.

확인할 증거:

- live row 수와 provider별 실패 여부.
- P99 수치와 클러스터 MV 재판단 입력.
- offline upload 실데이터 증거와 DELETE lifecycle.
- API smoke, Windows Playwright e2e, backup/restore smoke.
- T-221/T-222/T-223/T-224/T-226/T-227/T-228 이후 추가된 표면이 closure 조건에서
  빠지지 않았는지.

완료 시:

- `docs/reports/`에 재검증 결과를 남기거나 기존 리포트가 충분하다는 근거를 기록한다.
- `docs/tasks.md`에서 T-225를 제거하고 `docs/tasks-done.md`로 이동한다.
- `docs/journal.md`에 역시간순 엔트리를 추가한다.

## 열린 작업 요약

즉시:

- `T-225` — T-212e closure 재검증.

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
- 로컬 고정 포트: API `12301`, admin UI `12305`, Dagster `12302`,
  RustFS S3 `12101`, RustFS console `12105`.
- TripMate 연동: OpenAPI HTTP. 직접 import와 DB 직접 접근 없음.

## 참고 위치

- 백로그: `docs/tasks.md`.
- 완료/아카이브: `docs/tasks-done.md`.
- 작업 일지: `docs/journal.md`.
- Sprint 계획: `docs/sprints/`.
- REST 단일 정본: `docs/rest-api.md`.
- Cross-repo 정본: `docs/integration-map.md`.
