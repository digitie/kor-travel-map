# @kor-travel-map/user-client

kor-travel-map **user-facing** OpenAPI(`packages/kor-travel-map-api/openapi.user.json`,
ADR-048/T-216g 기계 정본)에서 `openapi-typescript`로 생성한 **TypeScript 타입
산출물**이다 (T-210e). downstream frontend codegen 기준점이다.

- **런타임 코드 없음** — HTTP client는 소비자 소유다. prose 계약:
  `docs/architecture/rest-api.md` ·
  `docs/architecture/rest-api.md`.
- **npm 게시 안 함**(ADR-043 관행) — 산출물(`src/types.ts`)을 커밋하고 CI drift
  gate(`gen:types:check`)로 spec과 고정한다.
- T-222b부터 `BeachPublicView`/`FestivalPublicView`와 `/v1/public/*` 공개 해수욕장·
  축제 view 경로를 named alias와 compile-time 경로 단언에 포함한다.

## 소비 방법 (downstream)

1. **vendoring** — `src/types.ts` + `src/index.ts`(named alias)를 복사해 commit
   hash 기준으로 pin. 본 repo CI가 spec↔산출물 drift를 차단하므로 hash만 맞추면
   안전하다.
2. **자체 codegen** — 같은 `openapi.user.json`을 같은 `openapi-typescript` 버전
   (`package.json` devDependencies 참조)으로 생성. 본 패키지의 컴파일 타임 표면
   단언(`_SurfaceAssertions`)이 ADR-048 불변식(batch `found`/`meta.page`/평면
   `lon`·`lat`/`/v1` 경로)을 CI에서 보증한다.

## 갱신 절차 (본 repo)

API/DTO 변경 → `scripts/export_openapi.py --profile all`(openapi-drift gate) →
`npm -w packages/kor-travel-map-user-client run gen:types` → `type-check` →
산출물 커밋. CI(frontend workflow)가 `gen:types:check` + `tsc`로 drift·표면
회귀를 차단한다.
