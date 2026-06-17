# maplibre-vworld-react 기반 지도 전환 계획 (2026-06-17)

## 배경

사용자 요청에 따라 admin UI의 지도 구현을
[`digitie/maplibre-vworld-react`](https://github.com/digitie/maplibre-vworld-react)
기반 모델로 전환한다. 참조 repo는 2026-06-17 기준 `a7cb0f8`를 확인했다.

현재 `packages/kor-travel-map-admin/frontend/src/app/features/features-client.tsx`는
`maplibre-gl` 인스턴스를 직접 만들고, `@kor-travel-map/map-marker-react`의
`createMarkerElement()`로 DOM marker를 수동 추가·제거한다. VWorld style은
`src/lib/vworld-style.ts`에서 직접 만든다.

참조 repo의 핵심 경계는 다음과 같다.

- `VWorldMapView`: VWorld key, layer type, camera, control, fallback, MapLibre event를
  React props로 받는 최상위 지도 컨테이너.
- `Marker`: React child를 portal로 MapLibre marker element에 연결하고, click/context
  event와 선택 상태를 props로 관리하는 marker primitive.
- `vworld-map-core`: VWorld tile URL, style, max zoom을 MapLibre 비의존 순수 TS로 제공.

## 해석

이번 저장소에서 바로 필요한 표면은 admin `features` 지도 하나다. 따라서 전체 외부
모노레포를 vendoring하거나 공개 package처럼 끌어오지 않고, admin UI 안에 얇은
`VWorldMapView` 계층을 두는 것이 가장 작은 변경이다.

이 얇은 계층은 참조 repo의 구조를 따른다.

- 지도 생성·해제·resize·load/moveend event는 컴포넌트 내부에서 소유한다.
- marker는 React 컴포넌트로 선언하고, MapLibre marker lifecycle은 marker 컴포넌트가
  소유한다.
- 기존 `buildVWorldStyle()` fallback은 유지한다. VWorld key 미설정 상태에서도
  회색 배경으로 MapLibre를 띄워 bbox/e2e가 계속 동작해야 하기 때문이다.

## 작업 단위

### T-MAP-VWORLD-01 — 계획 및 Task 생성

- GitHub Issue: #465.
- 이 문서와 `docs/tasks.md`에 후속 Task를 만든다.
- 완료 PR은 후속 구현 범위와 검증 게이트를 고정한다.

### T-MAP-VWORLD-02 — admin features 지도 전환

- GitHub Issue: #466.
- `features-client.tsx`에서 직접 `new maplibregl.Map()`과 marker 배열 관리 코드를 제거한다.
- `VWorldMapView` 스타일의 내부 컴포넌트와 React marker 컴포넌트를 도입한다.
- 기존 동작을 유지한다: bbox 동기화, kind 필터 refetch, marker 선택, table/map 선택
  상태 공유, VWorld key 미설정 안내.
- 검증: frontend type-check, lint, vitest, route-mocked 지도 e2e.

### T-MAP-VWORLD-03 — 지도 e2e 라이브 검증 및 후속 수정

- GitHub Issue: #467.
- WSL 서버 + Windows Playwright 흐름으로 지도 e2e를 실행한다.
- canvas/container 렌더링, bbox 조회, 필터 refetch, 선택 상세 패널을 확인한다.
- 실패가 있으면 별도 수정 PR로 반영한다.

## PR 순서

1. `docs/maplibre-vworld-react-plan`: 계획/Task 문서화, #465 닫기.
2. `feat/admin-vworld-map-view`: admin `features` 지도 전환, #466 닫기.
3. 필요 시 `fix/admin-vworld-map-e2e`: e2e 실패 수정, #467 닫기.

각 PR은 로컬 검증 결과와 CI 상태를 PR 본문에 적는다. 사용자 요청은 PR 후 머지를
반복하는 것이므로, 한 PR이 main에 반영된 뒤 다음 브랜치를 시작한다.

## 비범위

- `digitie/maplibre-vworld-react` 전체 패키지 vendoring.
- React Native/Expo 지도 지원.
- public user UI 지도 신설.
- VWorld key/타일 proxy 정책 변경.
