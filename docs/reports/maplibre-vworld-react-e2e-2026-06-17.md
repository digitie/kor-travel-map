# maplibre-vworld-react 지도 e2e 검증 (2026-06-17)

## 대상

- Task: `T-MAP-VWORLD-03` (#467)
- 기준 커밋: PR #469 merge 후 `origin/main` (`9c57c32`)
- 화면: admin `/features`
- 스펙: `packages/kor-travel-map-admin/frontend/e2e/features-map-interactions.spec.ts`

## 환경

- Next.js dev server: WSL, `0.0.0.0:12706`
- Windows Playwright base URL: `http://172.26.51.35:12706`
- dev origin 허용: `NEXT_ALLOWED_DEV_ORIGINS=172.26.51.35`
- VWorld key: 미설정 fallback 상태. 회색 background style에서도 bbox 조회와 marker/table
  상호작용이 동작하는지 검증했다.

## 실행 명령

```powershell
$env:E2E_BASE_URL='http://172.26.51.35:12706'
npm run e2e -- features-map-interactions.spec.ts
```

## 결과

- `features-map-interactions.spec.ts`: **5 passed / 0 failed**

통과한 시나리오:

- map/table 탭 토글과 bbox 데이터 공유.
- table row 선택 후 지도 탭 상세 패널 노출.
- bbox list 5xx error alert surface.
- count=0 empty 상태.
- 초기 bbox fetch와 kind 필터 refetch.

## 후속 수정

최종 e2e에서 추가 수정할 회귀는 발견되지 않았다. e2e 직전 PR #469에서 이미 반영한 수정은
다음 두 가지다.

- `VWorldMapView` load 알림을 `load`/`idle` + next frame guard로 보강해 VWorld key 미설정
  fallback style에서도 bbox가 세팅되게 했다.
- Windows localhost forwarding이 붙지 않는 환경을 위해 `NEXT_ALLOWED_DEV_ORIGINS`로 WSL IP
  dev origin을 허용할 수 있게 했다.
