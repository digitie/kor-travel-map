# ADR-036: `maplibre-vworld-js` 라이브러리 분리 + v0.1.0 — 공통 기능은 상류, TripMate 전용만 본 저장소

> **현행 핀(2026-06-11 기준)**: `maplibre-vworld-js#v0.1.3` + Next.js 16. 본 ADR
> 제목/초기 본문의 `v0.1.0`은 채택 당시 값이며, v0.1.2 + Next.js 16 정합은
> "Amendment (2026-05-31, PR#114)", v0.1.3 docs-sync patch 정합은
> "Amendment (2026-06-11)"가 정본이다.

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-025/ADR-026에서 디버그 UI frontend + TripMate 사용자 UI 모두 `maplibre-
vworld` 통일. 현재 `packages/kor-travel-map-admin/frontend/`에 vworld basemap +
maki marker + 카테고리 토글 + bounds 검색 등 공통 기능이 빠르게 자란다. 이중
중복 위험:

- TripMate apps/web도 같은 vworld basemap 코드를 재구현해야 함.
- 공통 기능 버그 수정이 두 코드베이스를 동시에 손봐야 함.

별도 라이브러리 `maplibre-vworld-js`(또는 `maplibre-vworld`)로 빼서 한쪽에서
유지보수 + 두 UI에서 import.

### 결정

- **공통 frontend 기능**(vworld basemap 설정 / maki marker render / 카테고리
  legend / bounds 검색 helper / tile cache)는 **`maplibre-vworld-js` 별도
  라이브러리**로 분리. 본 저장소 외부에 둔다 (사용자가 `digitie/maplibre-
  vworld-js` 신규 GitHub repo 신설 예정).
- **TripMate 전용 기능**(adminUI 시각화 / debug fixture replay / map overlay
  on top of TripMate route plan 등)은 본 저장소(`packages/kor-travel-map-debug-
  ui/frontend/` + 향후 `packages/tripmate-map-extensions/`)에 둔다.
- 목표 release: **`maplibre-vworld-js@0.1.0`** — vworld basemap + maki marker
  + 카테고리 legend 3종 안정화.

### 근거

- 공통 라이브러리 분리는 `kor-travel-geo` / `python-knps-api`와 동일 패턴.
- 분리 시점이 빠를수록 cross-cutting 책임 분리 비용이 작음.

### 결과 (긍정)

- TripMate apps/web이 본 저장소 디버그 UI와 vworld basemap 코드를 공유.
- 라이브러리 단위로 semver 관리 + 회귀 테스트.

### 결과 (부정)

- 라이브러리 분리 작업 자체가 추가 PR/유지보수 비용.
- npm registry 게시는 보류(ADR-043) — 형제 라이브러리 git URL + commit sha
  핀으로 import.

### 후속

- 신규 저장소 `digitie/maplibre-vworld-js` 생성 (별도 작업, 사용자 직접 또는
  Sprint 3 진입 시 본 라이브러리 측에서 PR 보조).
- 본 저장소 `packages/kor-travel-map-admin/frontend/` 코드 중 공통 부분을
  `maplibre-vworld-js`로 이전 (Sprint 3 후반 PR).
- `docs/adr/README.md` ADR-025 amendment — 라이브러리 분리 시점/책임 분배 명시.
- `packages/kor-travel-map-admin/README.md` 의존성 트리 갱신.

### Amendment (2026-05-28, PR#49) — v0.1.0 릴리스 + 의존 핀 정합

`digitie/maplibre-vworld-js` **v0.1.0 태그가 실제 릴리스됨**. 이에 본 저장소
의존 핀을 v0.1.0 기준으로 정정:

- **npm 미게시 확인** — `maplibre-vworld`는 npm registry에 없음. 따라서
  semver(`^1.0.0`)로는 설치 불가. **git URL + release tag**로 핀:
  `"maplibre-vworld": "github:digitie/maplibre-vworld-js#v0.1.0"` (ADR-043
  형제 라이브러리 git 핀 패턴과 동일 정신).
- 기존 `frontend/package.json` + `packages/map-marker-react/package.json`의
  `"^1.0.0"`은 **이중으로 잘못됨** (그 버전 미존재 + npm 미게시) → 정정.
- v0.1.0 **peerDependencies 정합**: `maplibre-gl ^5.24.0` / `react >=18 <20`
  / `zod ^4.4.3`. 본 저장소 frontend의 `zod`를 `^3.23.0` → `^4.4.3`으로 상향.
  `map-marker-react` peer/dev도 동일 정합 (zod peer 추가).
- v0.1.0 공개 API 표면(참고): `VWorldMap`(`apiKey`/`center`/`zoom`/`fallback`)
  + `MapStore`/`useMap`/`useMapZoom`/`useMapSelector` hook + 마커 13종
  (`MakiMarker`/`PlaceMarker`/`PriceMarker`/`WeatherMarker`/`ClusterMarker`
  등) + 레이어(`ClusterLayer`/`ServerClusterLayer`/`RouteLine`/`PolygonArea`)
  + `zod` schemas(`LngLatSchema`/`BoundsSchema` + `parseBoundsParam` 등).
- 본 저장소 frontend의 Zustand `useMapStore`(viewport/selectedFeatureId/
  activeCategoryCodes)는 v0.1.0의 map-인스턴스 바인딩 `MapStore`와 **역할이
  다르다**(앱 UI 상태 vs 지도 인스턴스 상태) — 병존 OK, 중복 아님.

### Amendment (2026-05-31, PR#114) — v0.1.2 + Next.js 16 최신화

로컬 `F:\dev\maplibre-vworld-js` 당시 `main`/tag를 확인한 결과
`maplibre-vworld-js` 최신 릴리스는 **v0.1.2**였다. 본 저장소 frontend와
`@kor-travel-map/map-marker-react`의 git URL 핀을 `#v0.1.2`로 올리고, Next.js는 공식
v16 업그레이드 가이드에 따라 **Next.js 16 + ESLint CLI(flat config)** 기준으로
정렬한다.

- `next lint`는 Next.js 16에서 제거되었으므로 `npm run lint`는 `eslint .`를
  실행한다.

### Amendment (2026-06-11) — v0.1.3 docs-sync patch 핀 정합

로컬 `F:\dev\maplibre-vworld-js`와 원격 tag를 확인한 결과 최신 릴리스는 **v0.1.3**다.
tag 주석 기준 v0.1.3은 v0.1.2와 `src/dist`가 같은 문서 동기화 patch release지만,
consumer pin과 lockfile drift를 피하기 위해 본 저장소 frontend, root `package-lock.json`,
`@kor-travel-map/map-marker-react` peer/dev dependency, 진입 문서의 현재 기준값을 모두
`github:digitie/maplibre-vworld-js#v0.1.3`으로 맞춘다.
- `packages/kor-travel-map-admin/frontend/eslint.config.mjs`는
  `eslint-config-next/core-web-vitals` + `eslint-config-next/typescript` flat config를
  사용한다.
- npm workspace에서 Next.js 16 production build(Turbopack)가 root를 `src/app`으로
  오판하지 않도록 `next.config.ts`에 repo root 기준 `turbopack.root`를 명시한다.
- Next.js 16.2.6 stable은 아직 transitive `postcss 8.4.31`을 선언하므로
  npm audit의 `GHSA-qx2v-qp2m-jg93` 차단을 위해 root `package.json`에서
  `next > postcss`를 `^8.5.15`로 override한다. canary(`16.3.0-canary.*`)로
  넘어가지 않고 stable을 유지한다.
- `maplibre-gl ^5.24.0`, `zod ^4.4.3`, React 19 계열은 v0.1.2 peer와 정합하다.
