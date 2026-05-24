# krtour-map-debug-ui-frontend

`python-krtour-map` 디버그 UI의 React 프론트엔드. **ADR-025**에 따라
`maplibre-vworld-js` (VWorld 지도) 기반.

> **현재 상태 (v2 설계 단계)**: 본 디렉토리는 ADR-025 결정에 따른 placeholder.
> 실제 코드는 별도 코드 작성 단계 PR에서. 본 README + `.env.example` +
> `package.json`(의존성 placeholder) + `.gitignore`만 박혀 있음.

## 기술 스택 (ADR-025)

- **maplibre-vworld** v1.0.0 (`digitie/maplibre-vworld-js`) — VWorld 지도 React
  컴포넌트
- **maplibre-gl** — WebGL 지도 엔진
- **zod** — 좌표 검증
- **React 19** + **Vite** + **TypeScript**
- **@tanstack/react-query** — 데이터 페칭/캐시
- Kakao Maps SDK 미사용 (ADR-025)

## 환경변수

`.env.example` 참고:

| 변수 | 의미 |
|------|------|
| `VITE_VWORLD_API_KEY` | VWorld API key. **`python-kraddr-geo`의 `KRADDR_GEO_VWORLD_API_KEY`와 동일 값 공유** (ADR-025 사용자 보강 2026-05-25). 별도 발급 금지. |
| `VITE_KRTOUR_MAP_DEBUG_UI_API` | 백엔드 base URL (`http://127.0.0.1:8600` 기본) |

> **VWorld key 공유 정책**: 본 frontend가 사용하는 VWorld key는
> `python-kraddr-geo` ADR-019의 `KRADDR_GEO_VWORLD_API_KEY`와 동일하다.
> 별도 발급 / 별도 운영하지 않는다. 운영 시 backend `.env`에서 동일 키를
> 읽어 빌드/런타임에 frontend의 `VITE_VWORLD_API_KEY`로 주입한다
> (CI/CD 또는 운영 셸 스크립트 책임). **TripMate 사용자 UI** (ADR-026)도
> 동일 키를 공유한다.

## 개발

```bash
cd packages/krtour-map-debug-ui/frontend
cp .env.example .env.local
$EDITOR .env.local
npm ci
npm run dev                  # http://localhost:8610
```

## 빌드

```bash
npm run build                # → dist/
# FastAPI가 dist/를 static mount해서 http://127.0.0.1:8600/에서 같이 서빙
```

## 주요 페이지 (계획)

| 페이지 | 백엔드 API | 비고 |
|-------|-----------|------|
| `/` (FeatureMap) | `/features/in-bounds`, `/features/nearby` | VWorld 지도 + MakiMarker + Clusterer |
| `/features/:id` | `/features/{id}` | feature detail + sources + files |
| `/import-jobs` | `/import-jobs` | 작업 큐 상태 |
| `/dedup-review` | `/dedup-review` | dedup 검토 큐 |
| `/integrity` | `/integrity-violations` | 정합성 위반 |
| `/debug/explain` | `/debug/explain` | SQL EXPLAIN viewer (read-only) |
| `/debug/fixtures` | `/debug/fixtures` | fixture 저장/replay |

자세한 사양: `../../../docs/debug-ui-package.md` §14.

## 카테고리 → maki icon 매핑

`src/lib/categoryMaki.ts` — `krtour.map.category` Tier 1~4 코드(141건)를 maki
icon(55종)으로 dispatch. 자세히는 `../../../docs/category.md` §4.

## 라이선스

GPL-3.0-or-later (메인 패키지와 동일). 외부 의존성: `maplibre-vworld` (ISC),
`maplibre-gl` (BSD-3), `zod` (MIT), React/TanStack (MIT) — 모두 호환.

## 비책임

- TripMate 사용자 가시 지도 UI (ADR-026으로 동일하게 maplibre-vworld 채택,
  SPEC V8 v8_3 supersede) — 본 frontend는 디버그 전용 (TripMate `apps/web`과
  별도 코드베이스, 추후 공통 마커 npm 패키지로 분리 후보)
- 인증 / 세션 / 권한 (ADR-005 + ADR-020: 내부망 전용, no auth)
- DB 직접 접근 (모두 backend API 경유)
