# krtour-map-admin-frontend

`python-krtour-map` 디버그 UI의 **Next.js** 프론트엔드. **ADR-025**에 따라
`maplibre-vworld-js` (VWorld 지도) 기반. ADR-035에 따라 debug 화면뿐 아니라
feature 운영, provider 적재, dedup/결측 검토, 오프라인 업로드를 다루는 admin
운영 콘솔로 확장한다. 상세 화면/워크플로/API 기준은
`../../../docs/debug-ui-admin-workflows.md`.

> **PR#36 (2026-05-27)**: Sprint 2 §2.5 frontend skeleton 진입. Next.js 15
> App Router + TanStack Query + Zustand (ADR-037) 최소 골격 박음.
> `src/api/{client,queries}.ts` (`/debug/health`/`/debug/version` 호출 hook) +
> `src/state/map.ts` (Zustand map viewport store) + `src/providers/query-
> client-provider.tsx` (`QueryClientProvider`) + `src/app/{layout,page}.tsx`
> (root layout + landing page). 실제 지도 화면 + `/features/*` 라우터 wiring
> 은 후속 PR에서 (`infra/feature_repo.py` + `routers/features.py` 진입 후).

## 기술 스택 (ADR-025, Next.js 기반 — 2026-05-25 사용자 보강)

- **Next.js 16** (App Router) + **React 19** + **TypeScript** —
  `kraddr-geo-ui` / TripMate `apps/web`와 동일 stack
- **maplibre-vworld** v0.1.2 (`github:digitie/maplibre-vworld-js#v0.1.2`) —
  VWorld 지도 React 컴포넌트 (ADR-036). **npm 미게시** — git URL + release
  tag로 핀 (ADR-043 형제 라이브러리 패턴). 공개 API: `VWorldMap`(apiKey/
  center/zoom) + `MapStore`/`useMap*` hook + `MakiMarker`/`PlaceMarker`/
  `PriceMarker`/`WeatherMarker` 등 마커 13종 + `ClusterLayer`/`RouteLine`.
- **maplibre-gl** ^5.24.0 — WebGL 지도 엔진 (maplibre-vworld v0.1.2 peer)
- **zod** ^4.4.3 — 좌표 검증 (maplibre-vworld v0.1.2 peer — schemas 모듈)
- **React Hook Form** — 수동 feature 추가, provider 실행, offline upload,
  feature update request form 상태
- **shadcn/ui** — admin UI primitive(Button/Input/Select/Dialog/Sheet/Tabs/Table/
  Badge/Toast/Form/DropdownMenu 등)
- **@tanstack/react-query** — 서버 데이터 페칭/캐시 (ADR-037)
- **zustand** — UI 클라이언트 상태(map viewport / filter / 선택된 feature
  등). ADR-037 (PR#36에 처음 추가)
- **@krtour/map-marker-react** (`packages/map-marker-react`, ADR-029 + ADR-043
  — npm 게시 X, `"private": true`, workspace 내부 share만) — 공통 마커/
  카테고리-maki 매핑
- Kakao Maps SDK 미사용 (ADR-025/026)

> Vite 채택은 잠정 가설이었고, kraddr-geo-ui 및 TripMate `apps/web`와의
> 일관성을 위해 **Next.js**로 정정 (ADR-025 §사용자 보강 2026-05-25).

## 환경변수

`.env.example` 참고:

| 변수 | 의미 |
|------|------|
| `NEXT_PUBLIC_VWORLD_API_KEY` | VWorld API key. **`python-kraddr-geo`의 `KRADDR_GEO_VWORLD_API_KEY`와 동일 값 공유** (ADR-025 사용자 보강 2026-05-25). 별도 발급 금지. |
| `NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API` | 백엔드 base URL (`http://127.0.0.1:9011` 기본) |
| `NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL` | Dagster UI/embed base URL (`http://127.0.0.1:9013` 기본) |

> **VWorld key 공유 정책**: 본 frontend가 사용하는 VWorld key는
> `python-kraddr-geo` ADR-019의 `KRADDR_GEO_VWORLD_API_KEY`와 동일하다.
> 별도 발급 / 별도 운영하지 않는다. 운영 시 backend `.env`에서 동일 키를
> 읽어 빌드/런타임에 frontend의 `NEXT_PUBLIC_VWORLD_API_KEY`로 주입한다
> (CI/CD 또는 운영 셸 스크립트 책임). **TripMate 사용자 UI** (ADR-026)도
> 동일 키를 공유한다.
>
> Next.js env 규약상 `NEXT_PUBLIC_*` 만 브라우저로 노출된다. 다른 키
> (server-only)는 prefix 없이 박는다.

## 개발

Frontend 개발 서버는 **WSL에서 실행**한다. Windows에서 직접 `npm run dev` /
`npm run start`를 돌리지 않는다. Windows는 e2e 검증 시 Playwright Chromium 실행
용도로만 사용한다. `which node`/`which npm`이 `/mnt/c/Program Files/nodejs/...`를
가리키면 Windows Node가 섞인 상태이므로 WSL nvm Node를 먼저 활성화한다.

```bash
# WSL 셸에서 실행
cd packages/krtour-map-admin/frontend
which node npm              # /home/.../.nvm/... 등 WSL 경로여야 함
cp .env.example .env.local
$EDITOR .env.local
npm install
npm run dev                  # http://127.0.0.1:9012
```

`next dev`의 기본 포트는 3000이지만, TripMate `apps/web` 개발 충돌 회피를
위해 `--port 9012`을 강제한다 (`package.json` scripts).

### WSL 실행 실패 방지 체크리스트

같은 명령을 반복하지 말고 이 순서대로 본다.

1. `command -v node npm`이 WSL 경로인지 확인한다. `/mnt/c/Program Files/nodejs/...`
   가 나오면 WSL nvm Node를 활성화한다.
2. Windows npm으로 설치한 흔적이 있으면 WSL Node로 optional dependency를 보강한다.
   ```bash
   npm install -w packages/krtour-map-admin/frontend --include=optional
   ```
3. `Cannot find module '../lightningcss.linux-x64-gnu.node'` 또는 `@next/swc` native
   binary 누락은 2번 문제다. Windows npm으로 다시 실행하지 않는다.
4. `An IO error occurred while attempting to create and acquire the lockfile`가 나오면
   `.next`를 지운 뒤 재시도한다.
   ```bash
   rm -rf packages/krtour-map-admin/frontend/.next
   ```
5. `0.0.0.0` 바인드가 필요하면 `npm run dev`의 `127.0.0.1` script를 쓰지 말고
   명시적으로 실행한다.
   ```bash
   npx next dev --port 9012 --hostname 0.0.0.0
   ```
6. background 실행은 `setsid -f bash -lc 'source ~/.nvm/nvm.sh; nvm use 20.20.2;
   exec npx next dev ...'` 형태를 쓴다. `env PATH=...$PATH`는 Windows 경로의 공백
   때문에 깨질 수 있다.
7. 성공 여부는 로그가 아니라 listener와 HTTP 응답으로 확인한다.
   ```bash
   ss -ltnp | rg ':9012\b'
   curl -fsS -I http://127.0.0.1:9012/ | sed -n '1,8p'
   ```

## 빌드 / 배포

```bash
npm run build                # .next/ — Next.js production build
npm run start                # next start — production server
```

운영 옵션:
- **A. standalone**: `next build` + `next start` — FastAPI(9011)와 별도 포트
  (9012)로 동일 호스트에서 동작.
- **B. FastAPI proxy**: FastAPI가 `/ui/*`로 reverse proxy. Next.js는
  `basePath: '/ui'` 설정.
- **C. static export (`next export`)**: SSR 미필요 페이지만 가능. App Router의
  client-side 페이지는 동작하나 server actions는 disabled — 본 디버그 UI는
  read-mostly이므로 가능. backend가 `.next/` 또는 `out/` static mount.

## React Doctor

frontend 작업이 포함된 PR은 React Doctor 실행과 결과 검토/개선이 필수다.

```bash
cd packages/krtour-map-admin/frontend
npm run lint
npm run type-check
npm run build
npm run doctor
```

`doctor` script가 아직 없으면 첫 frontend PR에서 추가한다. 실행 결과의 실제 위험
항목은 개선하고, false positive 또는 의도적으로 남기는 항목은 PR 설명이나
`docs/journal.md`에 근거를 남긴다.

## e2e (Playwright)

> ⚠️ **Playwright e2e는 Windows 호스트에서 실행한다 (WSL 아님).**
> 실행 모델: debug UI 서버(backend `uvicorn … :9011` + frontend
> `next start :9012`)는 **WSL ext4**에서 띄우고, **Playwright
> (`npx playwright test`)는 Windows에서** 돌린다. WSL2
> `localhostForwarding=true` 덕분에 Windows의 `http://127.0.0.1:9012`(frontend)
> / `:9011`(backend) 요청이 WSL 서버에 그대로 도달한다.
>
> **이유**: WSL Ubuntu에는 Playwright chromium 구동에 필요한 system lib
> (`libasound.so.2` 등)가 없고, `sudo`가 비밀번호를 요구해 WSL 안에서의
> `playwright install-deps` 자동 설치가 불가하다. Windows에는 node + chromium이
> 이미 갖춰져 있어 **e2e는 Windows에서 수행하는 것을 표준**으로 한다.
> (`playwright.config.ts`는 `webServer`를 두지 않아 서버가 외부(WSL)에 떠 있다고
> 가정한다.)

```powershell
# 1) WSL 셸에서 서버 2개 기동 (frontend도 WSL에서 실행)
#    backend : .venv/bin/uvicorn krtour.map_admin.app:create_app --factory --port 9011
#    frontend: npm run start   # next start :9012

# 2) Windows(PowerShell)에서는 Playwright만 실행
cd packages\krtour-map-admin\frontend
npm install              # 최초 1회 (workspace deps)
npm run e2e:install      # chromium 설치 (최초 1회)
npm run e2e              # playwright test (servers는 WSL에 떠 있어야 함)
npm run e2e:ui           # --ui 모드
```

baseURL은 `E2E_BASE_URL` env로 override 가능(기본 `http://127.0.0.1:9012`).
자세한 실행 모델은 `playwright.config.ts` 상단 주석 참고.

Windows localhost relay가 stale listener 정리 뒤 바로 복구되지 않으면 WSL IP와 같은
고정 포트로 검증한다. 이때 frontend를 띄울 때도 브라우저가 접근할 수 있는 API/
Dagster URL을 `NEXT_PUBLIC_*`로 넣는다. `scripts/load-env.sh`는 기본 CORS origin에
WSL IP 기반 `http://<WSL-IP>:9012`를 포함한다.

```bash
WSL_IP="$(hostname -I | awk '{print $1}')"
NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API="http://$WSL_IP:9011" \
NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL="http://$WSL_IP:9013" \
  scripts/run-admin-stack.sh
```

```powershell
$env:E2E_BASE_URL = "http://<WSL-IP>:9012"
npm run e2e
```

e2e 전 Windows `:9012`을 점유한 프로세스가 `wslrelay`인지 확인한다. 과거에
Windows Node로 띄운 Next.js가 남아 있으면 Playwright가 WSL 서버 대신 stale
Windows 서버를 보고 실패한다.

```powershell
netstat -ano | findstr :9012
Get-Process -Id <PID> | Select-Object Id,ProcessName,Path
```

`ProcessName`이 `node`이고 path가 `C:\Program Files\nodejs\node.exe`면 해당
PID를 종료한 뒤 WSL frontend를 다시 띄운다. 정상은 `wslrelay`다.

## 주요 페이지 (App Router)

| Route | 백엔드 API | 비고 |
|-------|-----------|------|
| `/` | `/ops/metrics`, `/ops/import-jobs`, `/admin/dedup-review`, `/ops/dagster/summary` | 구현됨. 운영 홈: feature/import job/dedup/이슈/Dagster 요약 |
| `/features` | `/features`, `/features/{id}` | 구현됨. 지도/테이블/상세 panel + 운영 quick link |
| `/ops/import-jobs` | `/ops/import-jobs` | 구현됨. 작업 큐 read-only 상태, state/kind filter |
| `/ops/consistency` | `/ops/metrics`, `/ops/consistency/reports`, `/ops/consistency/issues` | 구현됨. 정합성 보고서/이슈 |
| `/admin/dedup-review` | `/admin/dedup-review` | 구현됨. dedup 검토 큐와 결정 mutation |
| `/admin/feature-update-requests` | `/admin/feature-update-requests` | 구현됨. 좌표/반경/provider 업데이트 큐잉, cancel, run-now |
| `/admin/poi-cache-targets` | `/admin/poi-cache-targets`, `/features/nearby/by-target` | 구현됨. 외부 POI key 기반 주변 feature 캐시 |
| `/admin/dagster` | `/ops/dagster/summary` | 구현됨. Dagster 운영 요약 + Dagster webserver embed |
| `/etl` | `/debug/etl/*` | 구현됨. fixture/live ETL preview |
| `/features/new` | `/admin/features` | 후속. 수동 feature 추가는 audit log/API 필요 |
| `/features/[id]` | `/features/{id}` | 후속. 별도 route 대신 현재 `/features` 상세 panel 사용 |
| `/admin/providers` | 없음 | 후속. 별도 provider REST 없음 |
| `/admin/offline-uploads` | `/admin/offline-uploads`, `/admin/offline-uploads/{upload_id}/load` | 구현됨. JSON/JSONL upload/list/detail + Dagster load launch. CSV/TSV wizard는 후속 |
| `/admin/provider-refresh-policies` | 없음 | 후속. provider policy REST 필요 |
| `/ops/error-logs` | 없음 | 후속. `ops.import_job_events`/error log API 필요 |
| `/debug/explain` | 없음 | 후속. SQL EXPLAIN viewer |
| `/debug/fixtures` | 없음 | 후속. fixture 저장/replay |

패키지 경계: `../../../docs/debug-ui-package.md` §14. Admin 상세 구현 사양:
`../../../docs/debug-ui-admin-workflows.md`.

## 카테고리 → maki icon 매핑

`@krtour/map-marker-react`의 `categoryMaki` 사용 (ADR-029). 본 frontend는
**중복 정의 금지** — drift gate가 Python ↔ TypeScript 1:1을 검증한다.

자세히는 `../../../docs/category.md` §4 + `../../map-marker-react/README.md`.

## 라이선스

GPL-3.0-or-later (메인 패키지와 동일). 외부 의존성: `next` (MIT),
`maplibre-vworld` (ISC), `maplibre-gl` (BSD-3), `zod` (MIT), React/TanStack
(MIT) — 모두 호환.

## 비책임

- TripMate 사용자 가시 지도 UI (ADR-026으로 동일하게 Next.js + maplibre-vworld
  채택, SPEC V8 v8_3 supersede) — 본 frontend는 디버그 전용 (TripMate
  `apps/web`과 별도 코드베이스, 공통 마커는 `@krtour/map-marker-react` npm
  패키지로 공유)
- 인증 / 세션 / 권한 (ADR-005 + ADR-020: 내부망 전용, no auth)
- DB 직접 접근 (모두 backend API 경유)
