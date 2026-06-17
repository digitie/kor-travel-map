# ADR-037: 디버그/관리 UI frontend state 관리 — TanStack Query + Zustand

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-025에서 frontend는 Next.js + maplibre-vworld로 정의. state 관리 라이브러리
는 미정. Sprint 2/3에서 라우터/UI 추가가 본격 시작되므로 표준 박음:

- 서버 상태(REST 응답 캐싱/refetch): TanStack Query (구 react-query).
- 클라이언트 상태(UI toggle / map viewport / filter chip 등): Zustand.

### 결정

- **TanStack Query** — REST API 데이터 fetching/캐싱/invalidation. 모든
  `/admin/...`, `/ops/...`, `/features/...` 라우터 응답은 TanStack Query hook
  으로 래핑.
- **Zustand** — UI 클라이언트 상태(map viewport / 선택된 feature / 카테고리
  filter / debug fixture playback 상태 등). Redux/MobX/Context-API 대신.
- Redux Toolkit / SWR / Jotai / Recoil 검토했으나 본 use case 규모에 과함 —
  Zustand의 hook 기반 store + TanStack의 query/mutation hook이 가장 가볍고
  타입 강함.

### 근거

- TanStack Query는 stale-while-revalidate / refetch on focus / mutation
  invalidation이 기본 → admin/유지보수 UI에서 운영자가 새로고침 의식 없이
  최신 상태 보임.
- Zustand는 React 18 concurrent feature 호환 + boilerplate 적음.

### 결과 (긍정)

- 두 라이브러리 모두 npm 다운로드 수백만/주 + 타입 강함 + 작은 번들.
- 디버그 UI에서 검증한 state 패턴을 maplibre-vworld-js 라이브러리에도 그대로
  이식 가능.

### 결과 (부정)

- 새 frontend 개발자가 두 라이브러리 학습 필요 — 단, learning curve가 낮아
  허용.

### 후속

- `packages/kor-travel-map-admin/frontend/package.json`에 `@tanstack/react-
  query` + `zustand` 추가 (Sprint 2 첫 frontend PR과 함께).
- `docs/adr/README.md` ADR-025 amendment — frontend state stack 박음.
- `packages/kor-travel-map-admin/frontend/src/state/` 컨벤션 폴더 구조 docs.
