# krtour-map-debug-ui-frontend

`python-krtour-map` 디버그 UI의 **Next.js** 프론트엔드. **ADR-025**에 따라
`maplibre-vworld-js` (VWorld 지도) 기반.

> **PR#36 (2026-05-27)**: Sprint 2 §2.5 frontend skeleton 진입. Next.js 15
> App Router + TanStack Query + Zustand (ADR-037) 최소 골격 박음.
> `src/api/{client,queries}.ts` (`/debug/health`/`/debug/version` 호출 hook) +
> `src/state/map.ts` (Zustand map viewport store) + `src/providers/query-
> client-provider.tsx` (`QueryClientProvider`) + `src/app/{layout,page}.tsx`
> (root layout + landing page). 실제 지도 화면 + `/features/*` 라우터 wiring
> 은 후속 PR에서 (`infra/feature_repo.py` + `routers/features.py` 진입 후).

## 기술 스택 (ADR-025, Next.js 기반 — 2026-05-25 사용자 보강)

- **Next.js 15** (App Router) + **React 19** + **TypeScript** —
  `kraddr-geo-ui` / TripMate `apps/web`와 동일 stack
- **maplibre-vworld** v1.0.0 (`digitie/maplibre-vworld-js`) — VWorld 지도 React
  컴포넌트 (ADR-036 — Sprint 3 후반 v0.1.0 분리)
- **maplibre-gl** — WebGL 지도 엔진
- **zod** — 좌표 검증
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
| `NEXT_PUBLIC_KRTOUR_MAP_DEBUG_UI_API` | 백엔드 base URL (`http://127.0.0.1:8600` 기본) |

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

```bash
cd packages/krtour-map-debug-ui/frontend
cp .env.example .env.local
$EDITOR .env.local
npm ci
npm run dev                  # http://127.0.0.1:8610
```

`next dev`의 기본 포트는 3000이지만, TripMate `apps/web` 개발 충돌 회피를
위해 `--port 8610`을 강제한다 (`package.json` scripts).

## 빌드 / 배포

```bash
npm run build                # .next/ — Next.js production build
npm run start                # next start — production server
```

운영 옵션:
- **A. standalone**: `next build` + `next start` — FastAPI(8600)와 별도 포트
  (8610)로 동일 호스트에서 동작.
- **B. FastAPI proxy**: FastAPI가 `/ui/*`로 reverse proxy. Next.js는
  `basePath: '/ui'` 설정.
- **C. static export (`next export`)**: SSR 미필요 페이지만 가능. App Router의
  client-side 페이지는 동작하나 server actions는 disabled — 본 디버그 UI는
  read-mostly이므로 가능. backend가 `.next/` 또는 `out/` static mount.

## 주요 페이지 (계획, App Router)

| Route | 백엔드 API | 비고 |
|-------|-----------|------|
| `/` (FeatureMap) | `/features/in-bounds`, `/features/nearby` | VWorld 지도 + MakiMarker + Clusterer |
| `/features/[id]` | `/features/{id}` | feature detail + sources + files |
| `/import-jobs` | `/import-jobs` | 작업 큐 상태 |
| `/dedup-review` | `/dedup-review` | dedup 검토 큐 |
| `/integrity` | `/integrity-violations` | 정합성 위반 |
| `/debug/explain` | `/debug/explain` | SQL EXPLAIN viewer (read-only) |
| `/debug/fixtures` | `/debug/fixtures` | fixture 저장/replay |

자세한 사양: `../../../docs/debug-ui-package.md` §14.

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
