# ADR-025: 디버그 UI frontend는 `maplibre-vworld-js` 채택

> **현행 기준(2026-06-13)**: frontend는 **Next.js 16**(ADR-036 amendment 2026-05-31),
> dev 포트는 admin UI **12705**(ADR-047). 본문의 "Next.js 15"·"`next dev --port 8610`"
> 은 채택/2차 보강 당시 값이며 위 ADR이 정본이다.

- **상태**: accepted
- **날짜**: 2026-05-25
- **결정자**: 사용자
- **컨텍스트**: ADR-020으로 디버그 UI를 별도 패키지 `kor-travel-map-admin`로
  분리. FastAPI backend는 결정되었지만 frontend 기술 선택이 미정이었다.
  v1은 Kakao Maps JS SDK 사용. v2 후보:
  - Kakao Maps JS SDK (Canvas, JS key 필요, 일 호출 한도, 오프라인 캐싱 금지)
  - MapLibre GL JS + raster tile (OpenStreetMap 또는 VWorld raster 직접)
  - **MapLibre GL JS + `maplibre-vworld-js`** (`digitie/maplibre-vworld-js`,
    React/TS, WebGL 60fps, `MakiMarker` + cluster layer 내장, `zod` 좌표 검증,
    Next.js App Router 지원) — *실제 릴리스 버전 **v0.1.0**, npm 미게시(git
    URL+tag 핀). 결정 당시 추정한 v1.0.0은 ADR-036 amendment(2026-05-28)로 정정.*

  사용자가 maplibre-vworld-js 채택을 지시.

- **결정** (2차 보강 적용 — Vite → Next.js):
  - 디버그 UI frontend: **Next.js 15 (App Router) + React 19 + TypeScript +
    `maplibre-vworld` + `maplibre-gl` + `zod`**. (1차 결정의 "Vite"는 2차
    보강으로 정정 — 본 ADR 하단 §사용자 보강 2차 참조).
  - VWorld 지도 (국토교통부) — **Kakao Maps SDK 사용 안 함**.
    `NEXT_PUBLIC_KAKAO_JS_KEY` 같은 변수 미사용.
  - 마커: `MakiMarker` (kraddr-base / `kortravelmap.category` maki icon 55종과
    정합) + `MarkerClusterer` (10만+ feature viewport culling + KDBush).
  - 라이선스: `maplibre-vworld` ISC license + `maplibre-gl` BSD-3 + 본 라이브러리
    GPL-3.0 호환.
  - 디렉토리: `packages/kor-travel-map-admin/frontend/` (`kor-travel-geo`의
    `kor-travel-geo-ui` 패턴 미러).
  - 빌드: Next.js (2차 보강 — 1차의 Vite에서 정정). 개발 `next dev --port 8610`
    (kor-travel-geo-ui와 동일 stack). 운영은 `next build` + standalone /
    FastAPI proxy / static export 중 선택 (`debug-ui-package.md §14.3`).
  - 백엔드 API 경유: 환경변수 `NEXT_PUBLIC_KOR_TRAVEL_MAP_API` (Next.js
    rewrites 또는 fetch base URL).
  - SPA로 충분 — SSR 불필요 (디버그 UI는 내부망 전용).
  - 인증 없음 (ADR-005 + ADR-020 그대로). VWorld API key만 frontend에 안전하게
    전달 (key restriction by HTTP referrer).
- **근거**:
  - **VWorld 우선**: 국토교통부 공식 지도. 한국 행정구역 경계·도로명주소
    레이어와 정합. `kor-travel-geo`와 동일한 source.
  - **WebGL 렌더링**: 10만+ feature (MOIS 인허가, krheritage, opinet 주유소
    등)을 Canvas 기반보다 부드럽게 60fps 렌더링.
  - **선언형 React**: `map.panTo()` 같은 명령형 API 없음 → Props 조작만으로
    상태 동기 (디버그 콘솔에서 feature 클릭 → 지도 이동 단순).
  - **MakiMarker 내장**: 본 라이브러리의 `kortravelmap.category` maki icon
    매핑(55종)을 그대로 활용.
  - **클러스터링 내장**: viewport culling + KDBush로 zoom-level별 마커 자동
    합치기 — 본 라이브러리의 `cluster_unit` (`sido`/`sigungu`/`eupmyeondong`)
    개념과 정합.
  - **TypeScript**: openapi-typescript로 본 라이브러리 디버그 REST와 타입 동기
    가능.
  - **kor-travel-geo-ui 패턴 일관**: 운영자/에이전트 학습 비용 절감. (2차 보강에
    따라 Next.js stack 통일 — 1차의 Vite 가설보다 정확.)
- **결과 (긍정)**:
  - 한국 운영 환경(VWorld, 행정구역, 도로명주소)에 정합.
  - kor-travel-geo-ui 및 TripMate `apps/web`와 같은 frontend stack (Next.js +
    React + TS, 2차 보강) → 형제 라이브러리 + 상위 app 운영 일관성.
  - Kakao 호출 한도 / JS key 발급 부담 없음.
  - 대용량 feature 렌더링 성능 우수.
  - maki icon이 본 라이브러리 category 체계와 자동 정합.
- **결과 (부정)**:
  - VWorld API key 필요 — `kor-travel-geo` ADR-019의
    `KOR_TRAVEL_GEO_VWORLD_API_KEY` **공유** (별도 발급 X, 사용자 결정 2026-05-25).
  - 디버그 UI 운영자는 React/Next.js/TypeScript 기본 지식 필요 (운영자는 한
    명 이상이라 학습 부담 있음 — 단 TripMate `apps/web` 운영 학습이 그대로
    이전됨).
- **사용자 보강 (2026-05-25, 1차)**:
  1. **VWorld API key 공유 정책 확정**: 디버그 UI는 `kor-travel-geo`의
     `KOR_TRAVEL_GEO_VWORLD_API_KEY`를 **공유 사용**. 별도 발급 / 별도 환경변수
     금지. frontend는 backend가 주입한 값을 `NEXT_PUBLIC_VWORLD_API_KEY`로
     노출 (이름은 Next.js 규약 — 2차 보강으로 정정, 값은 동일 출처). HTTP
     referrer 제한은 backend가 서빙하는 호스트(`127.0.0.1` + 내부망 운영
     호스트)로 통일.
  2. **maplibre-vworld-js 유지보수 정책**: provider 라이브러리에서 문제
     발생 시 `digitie/maplibre-vworld-js` 저장소에 **직접 PR로 적극 수정**.
     본 사용자가 직접 운영하는 저장소이므로 stability 우려는 "외부 의존"이
     아닌 "관리 부담"으로 분류 — wrapper 도입(ADR-006 위배) 대신 upstream
     수정으로 해소. 이로써 `maplibre-vworld` (v0.1.0) 채택의 부정적 결과
     "stability 모니터링 필요" 항목은 **해소됨**.
- **사용자 보강 (2026-05-25, 2차) — 빌드 도구 정정 Vite → Next.js**:
  3. **디버그 UI frontend = Next.js (App Router)**. 1차 결정의 "React + Vite"
     는 잠정 가설이었고, **kor-travel-geo-ui** 및 **TripMate `apps/web`**(ADR-026)
     이 모두 Next.js이므로 **단일 stack 통일**을 위해 Next.js로 정정.
     - 빌드: `next build` → `.next/`. 운영 옵션 3가지 (standalone /
       FastAPI reverse proxy / static export — `debug-ui-package.md §14.3`).
     - 개발: `next dev --port 8610 --hostname 127.0.0.1` (포트 8610은 TripMate
       `apps/web` dev (3000) 충돌 회피).
     - Env 규약: `NEXT_PUBLIC_*` 만 브라우저 노출. `VITE_*` 미사용. 1차 결정의
       `VITE_VWORLD_API_KEY` / `VITE_KOR_TRAVEL_MAP_API_API`는 각각
       `NEXT_PUBLIC_VWORLD_API_KEY` / `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`
       로 정정.
     - 본 패키지 `@kor-travel-map/map-marker-react` (ADR-029)는 React 19 라이브러리로
       framework-agnostic. Next.js의 `transpilePackages`로 monorepo workspace
       에서 직접 import.
     - **근거**: (1) kor-travel-geo-ui와 동일 stack — 학습 비용 0. (2) TripMate
       `apps/web`와 동일 stack — 운영자가 두 UI 사이 학습 부담 0. (3) App
       Router의 server actions / streaming SSR은 본 디버그 UI는 read-mostly
       이라 미필요하지만, 향후 server-side admin 기능 (SQL EXPLAIN bulk,
       fixture management 등) 확장 시 유용.
- **후속**:
  - `docs/architecture/debug-ui-package.md` 갱신 — frontend 디렉토리/기동/Env/마커 매핑
    + key 공유 정책 §14.2 + **Next.js 기반으로 §14.3 운영 옵션 (standalone /
    proxy / export) 명기**.
  - `packages/kor-travel-map-admin/README.md` 갱신.
  - `packages/kor-travel-map-admin/frontend/` skeleton — Vite 가정의
    `package.json`/`README`/`.env.example`/`.gitignore`를 **Next.js로 일괄
    전환** + `next.config.js` 신설 (본 PR#11에서 완료).
  - 환경변수 prefix: `NEXT_PUBLIC_*` (Next.js 규약).
  - VWorld API key 발급 절차는 `docs/external-apis.md` 갱신 (공유 정책 +
    Next.js env 명기).
  - `docs/etl/forest-feature-etl.md` §11.6의 "ADR-025 후보" 카테고리 확장은 번호
    충돌 회피로 **ADR-027 후보**로 변경 (ADR-026은 TripMate UI 통일 ADR이
    선점).
