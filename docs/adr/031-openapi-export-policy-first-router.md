# ADR-031: 디버그 패키지 OpenAPI export 정책 (첫 라우터부터 활성화)

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25)
- **Amendment (2026-06-02, ADR-045 D-3)**: ADR-045로 API가 admin과 사용자(공개)
  양쪽에 서비스되므로 OpenAPI를 **이원화**한다 — admin schema(`/admin`·`/ops`·
  `/debug`·`/features` admin 뷰)와 사용자 schema(`/features` 공개 뷰, `tripmate-rest-
  api.md`)를 **별도 export + 별도 drift gate**(CI 2개). versioning은 **SemVer**
  (필드 추가=minor / 제거·의미변경=major, breaking 시 구버전 한동안 유지),
  CHANGELOG `### API` 섹션에 변경 기록(D-16). frontend client는 `openapi-typescript`
  codegen(D-4).
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (2026-05-29 승인 확정)
- **컨텍스트**: `packages/kor-travel-map-admin`가 FastAPI 라우터를 노출하면
  OpenAPI spec (`openapi.json`)이 자동 생성된다. 이를 저장소에 커밋하고
  drift gate를 두는 정책은 `kor-travel-geo` ADR-015 패턴이 있으나, 본 저장소는
  *언제* 활성화할지 미정. 활용 측은 (1) 디버그 UI frontend `openapi-typescript`
  → `src/api/types.ts` 생성, (2) 운영자/에이전트 API spec 참조, (3) 외부
  도구(curl/postman) 검증.

- **결정**:
  - **첫 FastAPI 라우터 등장 PR부터 즉시 활성화** (Sprint 1, 메인 라이브러리
    코어 ETL이 아직 부분 구현이어도 무관).
  - `packages/kor-travel-map-api/openapi.json`과
    `packages/kor-travel-map-api/openapi.user.json`을 저장소에 커밋.
  - `packages/kor-travel-map-api/scripts/export_openapi.py` 신설 (이미
    `docs/architecture/debug-ui-package.md §8`에 사양 박힘).
  - `.github/workflows/openapi.yml` — admin/user 이원 `--profile all --check` drift 게이트:
    ```yaml
    - run: python packages/kor-travel-map-api/scripts/export_openapi.py \
             --profile all --check
    ```
  - 라우터/DTO/디버그 패키지 의존성 변경 PR은 반드시 `openapi.json` 또는
    `openapi.user.json` diff 동반 — 누락 시 CI fail.
  - 메인 라이브러리(`kortravelmap`)는 FastAPI 미의존(ADR-020)이라 본 ADR
    범위에 들어오지 않음. **항상 디버그 패키지 한정**.

- **근거**:
  - **활성화 비용 cheap**: 스크립트 ~30줄 + workflow ~10줄.
  - **frontend 도입 시점 부채 회피**: frontend가 도입되기 전부터 drift gate가
    돌고 있으면, frontend 첫 PR에서 `npm run gen:types`가 깨끗하게 동작 →
    type drift 회귀 0회.
  - **운영자/에이전트 진입 비용 절감**: 저장소에 `openapi.json`이 박혀 있으면
    backend 미기동 상태에서도 API 표면 확인 가능 (Swagger Viewer 등).
  - **kor-travel-geo 패턴 일관**: 형제 라이브러리 운영 일관성.

- **결과 (긍정)**:
  - 라우터 변경의 외부 효과(frontend type / 외부 도구)가 PR diff에서 즉시
    가시화.
  - 디버그 UI frontend 도입 시 type drift 부담 0.
  - 외부 운영자가 spec을 PR diff로 review 가능 (코드 + spec이 한 PR에).

- **결과 (부정)**:
  - 라우터 PR마다 `openapi.json` 갱신 강제 — 운영자가 잊을 수 있음. CI 게이트
    + agent-guide 체크리스트에 명기로 완화.

- **후속**:
  - `packages/kor-travel-map-api/scripts/export_openapi.py` 작성 (코드 작성
    단계).
  - `.github/workflows/openapi.yml` 신설 (T-203 일부).
  - `docs/agent-guide.md` §체크리스트에 "라우터 변경 시 `openapi.json` 갱신"
    추가.
  - `docs/architecture/debug-ui-package.md §8` + `§14.6`에 본 ADR 링크 + drift gate 명기
    (현재 "kor-travel-geo ADR-015 패턴 미러"로만 표기됨).
