# kor-travel-map-admin-frontend

`kor-travel-map` 디버그 UI의 **Next.js** 프론트엔드. **ADR-025**에 따라
MapLibre GL + VWorld tile style 기반. ADR-035에 따라 debug 화면뿐 아니라
feature 운영, provider 적재, dedup/결측 검토, 오프라인 업로드를 다루는 admin
운영 콘솔로 확장한다. 상세 화면/워크플로/API 기준은
`../../../docs/debug-ui-admin-workflows.md`.

> **PR#36 (2026-05-27)**: Sprint 2 §2.5 frontend skeleton 진입. Next.js 15
> App Router + TanStack Query + Zustand (ADR-037) 최소 골격 박음.
> `src/api/{client,queries}.ts` (`/health`/`/version` 호출 hook) +
> `src/state/map.ts` (Zustand map viewport store) + `src/providers/query-
> client-provider.tsx` (`QueryClientProvider`) + `src/app/{layout,page}.tsx`
> (root layout + landing page). 실제 지도 화면 + `/features/*` 라우터 wiring
> 은 후속 PR에서 (`infra/feature_repo.py` + `routers/features.py` 진입 후).

## 기술 스택 (ADR-025, Next.js 기반 — 2026-05-25 사용자 보강)

- **Next.js 16** (App Router) + **React 19** + **TypeScript** —
  `kor-travel-geo-ui` / PinVi `apps/web`와 동일 stack
- **maplibre-gl** ^5.24.0 — WebGL 지도 엔진.
- **VWorld style builder** — `src/lib/vworld-style.ts`가 VWorld WMTS tile URL과
  MapLibre style을 직접 만든다. `features` 지도는 `maplibre-vworld-react`
  참조 모델의 `VWorldMapView`/React marker 구조를 admin 내부 컴포넌트로 얇게
  이식한다.
- **controlled React state + `src/lib/form-validation.ts`** — runtime form framework 없이
  제출 경계에서 typed field 검증·첫 오류 focus를 처리한다.
- **shadcn/ui generated source + Base UI** — admin UI primitive(Button/Input/Select/Dialog/
  Sheet/Tabs/Table/Badge/Toast/Form/DropdownMenu 등). shadcn CLI/MCP npm package는 설치하지 않고,
  실제 component source와 사용 중인 Tailwind variant 4개를 저장소가 직접 소유한다.
- **@tanstack/react-query** — 서버 데이터 페칭/캐시 (ADR-037)
- **zustand** — UI 클라이언트 상태(map viewport / filter / 선택된 feature
  등). ADR-037 (PR#36에 처음 추가)
- **@kor-travel-map/map-marker-react** (`packages/map-marker-react`, ADR-029 + ADR-043
  — npm 게시 X, `"private": true`, workspace 내부 share만) — 공통 마커/
  카테고리-maki 매핑
- Kakao Maps SDK 미사용 (ADR-025/026)

> Vite 채택은 잠정 가설이었고, kor-travel-geo-ui 및 PinVi `apps/web`와의
> 일관성을 위해 **Next.js**로 정정 (ADR-025 §사용자 보강 2026-05-25).

## 환경변수

`.env.example` 참고:

| 변수 | 의미 |
|------|------|
| `NEXT_PUBLIC_VWORLD_API_KEY` | VWorld API key. **`kor-travel-geo`의 `KOR_TRAVEL_GEO_VWORLD_API_KEY`와 동일 값 공유** (ADR-025 사용자 보강 2026-05-25). 별도 발급 금지. |
| `NEXT_PUBLIC_KOR_TRAVEL_MAP_API` | 백엔드 base URL (`http://127.0.0.1:12701` 기본) |
| `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` | Dagster UI/embed base URL (`http://127.0.0.1:12702` 기본) |
| `KOR_TRAVEL_GEO_API_KEY` | `/api/geo` BFF가 `X-KTG-API-Key` header로 보내는 server-only kor-travel-geo public API key. geo가 Map consumer에 발급하며 VWorld 키로는 인증되지 않는다(401 `E0401`). docker-manager가 root `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`에서 이 이름으로 결선한다. |
| `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` | root `.env` 한 곳에서 API와 frontend가 함께 읽는 REST BFF/ops-live ticket server-only secret(32자 이상) |
| `KOR_TRAVEL_MAP_UI_SESSION_SECRET` | admin session HMAC secret(32자 이상, browser 미노출) |

> **VWorld key 공유 정책**: 본 frontend가 사용하는 VWorld key는
> `kor-travel-geo` ADR-019의 `KOR_TRAVEL_GEO_VWORLD_API_KEY`와 동일하다.
> 별도 발급 / 별도 운영하지 않는다. 운영 시 backend `.env`에서 동일 키를
> 읽어 빌드/런타임에 frontend의 `NEXT_PUBLIC_VWORLD_API_KEY`로 주입한다
> (CI/CD 또는 운영 셸 스크립트 책임). **PinVi 사용자 UI** (ADR-026)도
> 동일 키를 공유한다.
>
> Next.js env 규약상 `NEXT_PUBLIC_*` 만 브라우저로 노출된다. 다른 키
> (server-only)는 prefix 없이 박는다.

`WS /v1/ops/live`는 browser가 backend secret을 직접 갖지 않는다. 로그인 session으로
same-origin `POST /api/auth/live-ticket`을 호출해 60초 ticket을 받고, ticket은 URL/query가
아닌 WebSocket subprotocol로만 전달한다. ticket 발급 또는 연결 실패가 3회 이어지면 UI는
`polling` fallback을 표시하면서 background reconnect를 계속한다. ticket BFF는 browser의
`Origin`과 `Sec-Fetch-Site: same-origin`을 모두 확인하며, `4401`에서는 재시도를 중단하고
healthy snapshot/update 또는 일치하는 topic heartbeat를 받은 연결의 `4408`에서만 새
ticket으로 즉시 rotation한다. healthy 전 `4408`은 일반 backoff에 포함한다. ticket fetch,
handshake, heartbeat에는 각각 timeout/watchdog가 있어 close event가 유실된 silent network
failure도 socket을 분리하고 active 실행 polling을 유지한 채 재연결한다. 3회 연속 실패부터
inactive grid/detail도 REST polling fallback으로 전환한다. `subscribed`와 heartbeat의
topic은 wire 표시 순서가 아니라 문자열 타입·중복 없음·동일 원소인 exact set으로 요청과
비교한다. snapshot/update는 v1 envelope, 단조 증가 safe-integer sequence, 요청 topic,
비어 있지 않은 revision, object data를 모두 만족해야 live로 전이하며, 형식 오류는 즉시
socket을 폐기하고 `standby` 재연결로 내리되 기존 watchdog을 갱신하지 않는다. 3회 연속
실패부터 inactive REST polling fallback을 켠다. protocol 위반 뒤에는 heartbeat만으로
복귀하지 않고 exact 재구독 뒤 유효 snapshot을 받아야 같은 socket을 다시 신뢰한다.

## 개발

Frontend 개발 서버는 **Linux/WSL에서 실행**한다. Windows에서 직접 `npm run dev` /
`npm run start`를 돌리지 않는다. Windows는 n150에서 Playwright e2e를 실행할 수 없을 때의
fallback 용도로만 사용한다. `which node`/`which npm`이 `/mnt/c/Program Files/nodejs/...`를
가리키면 Windows Node가 섞인 상태이므로 WSL nvm Node를 먼저 활성화한다.

```bash
# 저장소 루트의 Linux/WSL 셸에서 실행(Node 22.22.2+/24.15.0+/26+, npm 12.0.1)
which node npm              # /home/.../.nvm/... 등 Linux 경로여야 함
npx --yes npm@12.0.1 ci --workspaces --include=optional
npx --yes npm@12.0.1 run audit:high
cd packages/kor-travel-map-admin/frontend
cp .env.example .env.local
$EDITOR .env.local
npx --yes npm@12.0.1 run gen:types  # ../../kor-travel-map-api/openapi.json -> src/api/types.ts
npx --yes npm@12.0.1 run dev        # http://127.0.0.1:12705
```

`src/api/types.ts`는 `openapi-typescript` 자동 생성 파일이다. 라우터/DTO 변경으로
`../../kor-travel-map-api/openapi.json`을 갱신했다면 `npm run gen:types`를 함께 실행하고,
`npm run gen:types:check`로 drift가 없는지 확인한다.


### npm 보안·OpenAPI codegen 경계

root install은 선언된 npm 12.0.1로 실행한다. `openapi-typescript` 7과 호환되는
Redocly 1.34.22를 고정하며, 자체 수정된 하위 의존성을 사용하므로 이전 minimatch override와
postinstall 보정은 제거했다. `gen:types:check`로 생성 결과를 비교한다.
의존성 설치 스크립트는 root `allowScripts`와 `.npmrc`의 `strict-allow-scripts`로 제한하며,
`verify:npm-tree`는 `npm ls --all --json`의 `problems` 0개를 검사한다.
`scripts/verify-next-sharp.mjs`는 Next optimizer의 실제 이미지 변환과 크기를 검증한다.
CI와 frontend/C7 Docker build가 설치 직후 이 검증을 실행한다.
Playwright client와 digest로 고정한 C7 browser 이미지는 같은 1.64.1을 사용한다.
