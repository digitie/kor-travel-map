# maplibre-vworld-js dependency 제거 검증 (2026-06-18)

## 대상

- Task: `T-MAP-VWORLD-04` (#475)
- 기준: `digitie/maplibre-vworld-react` `a7cb0f8f41ec00b44b1d106664506730b87033bd`
- 화면: admin `/features`, `/admin/features/new`
- 목표: admin web 지도 표면을 `maplibre-vworld-react`의 `vworld-map-core`/`vworld-map-web`
  경계에 맞추고, `maplibre-vworld`(`digitie/maplibre-vworld-js`) npm dependency를 제거한다.

## 변경

- `packages/kor-travel-map-admin/frontend`에서 `maplibre-vworld/style.css` import와
  `maplibre-vworld` dependency를 제거했다.
- `packages/map-marker-react`에서 실제 사용하지 않는 `maplibre-vworld` peer/devDependency와
  Vite external/global 선언을 제거했다.
- `src/lib/vworld-style.ts`는 `maplibre-vworld-react`의 core 모델처럼 lower-case map type,
  VWorld tile URL, max zoom, key redaction, tile error 판별을 단일화했다.
- `VWorldMapView`는 `maplibre-vworld-react` web adapter의 경계를 따라 maxZoom clamp,
  redacted error logging, optional controls, stable marker click callback을 갖는다.
- `package-lock.json`에서 `maplibre-vworld`와 전용 transitive(`supercluster`,
  `use-supercluster`, `use-deep-compare-effect`)를 제거했다.

## 검증

WSL:

```bash
npm -w packages/kor-travel-map-admin/frontend run type-check
npm -w packages/map-marker-react run typecheck
npm -w packages/kor-travel-map-admin/frontend run test
npm -w packages/map-marker-react run build
npm -w packages/kor-travel-map-admin/frontend run lint
NEXT_PUBLIC_VWORLD_API_KEY=CHANGE_ME \
NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://127.0.0.1:12701 \
NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=http://127.0.0.1:12702 \
NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=http://127.0.0.1:12501 \
npm -w packages/kor-travel-map-admin/frontend run build
```

결과:

- admin type-check 통과.
- marker typecheck 통과.
- admin vitest **27 passed**.
- marker Vite build 통과.
- admin ESLint **0 errors / 기존 warning 6**.
- admin Next production build 통과.

Windows Playwright + WSL dev server:

```powershell
$env:E2E_BASE_URL='http://172.26.51.35:12706'
npm run e2e -- features-map-interactions.spec.ts
```

결과:

- `features-map-interactions.spec.ts` **5 passed / 0 failed**.
- WSL dev server는 `0.0.0.0:12706`, Windows base URL은
  `http://172.26.51.35:12706`으로 실행했다.
