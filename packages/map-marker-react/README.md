# @krtour/map-marker-react

`python-krtour-map` 디버그 UI와 TripMate 사용자 UI에서 공통으로 쓰는 마커/
카테고리-maki 매핑/색상 팔레트 React 컴포넌트 라이브러리 (ADR-029).

> **현재 상태 (Sprint 1 skeleton)**: 본 패키지는 ADR-029 결정에 따른 npm
> package skeleton이다. 본 README + `package.json` + `vite.config.ts`
> (skeleton)가 있으며, 실제 marker/component 구현은 category/notice 매핑
> drift gate와 함께 후속 PR에서 진행한다.

## 라이선스

**MIT** — TripMate(proprietary)와 본 라이브러리(`python-krtour-map`, GPL-3.0)
양쪽에서 import 가능하도록 의도적 분리 (ADR-029 §결정).

본 패키지는 *UI 유틸*이지 비즈니스 로직이 아니다 — MIT로 분리해도 본 라이브
러리의 GPL 보호는 손상되지 않는다.

## 정체성

| 항목 | 값 |
|------|----|
| 패키지명 | `@krtour/map-marker-react` |
| 위치 | `packages/map-marker-react/` (`python-krtour-map` monorepo) |
| import | `import { MakiMarker, categoryMakiIcon } from "@krtour/map-marker-react"` |
| 라이선스 | MIT |
| peer deps | `react@^19.2`, `maplibre-gl@^5.24`, `maplibre-vworld@^0.1.2` (git URL+tag, npm 미게시), `zod@^4.4` |

## 포함 항목 (계획)

| 모듈 | 역할 |
|------|------|
| `categoryMaki.ts` | `krtour.map.category` PlaceCategoryCode (144건, ADR-027 반영) → maki icon (55종 + shelter) dispatch |
| `noticeMaki.ts` | `notice_type` (14건, ADR-027 반영) → maki icon dispatch |
| `<MakiMarker>` | maplibre-gl Marker 래핑 React 컴포넌트 |
| `markerColor.ts` | P-01~P-16 팔레트 + severity → color helper |
| 타입 (`PlaceCategoryCode`, `NoticeType`, `MakiIconName`) | 본 라이브러리 Pydantic DTO와 정합 (수동 mirror 또는 openapi-typescript) |

## 두 UI에서의 사용

```typescript
// debug UI (packages/krtour-map-debug-ui/frontend/src/pages/FeatureMap.tsx)
// 또는 TripMate apps/web/components/FeatureMap.tsx
import { MakiMarker, categoryMakiIcon } from "@krtour/map-marker-react";

<VWorldMap>
  {features.map(f => (
    <MakiMarker
      key={f.feature_id}
      lon={f.lon} lat={f.lat}
      icon={categoryMakiIcon(f.category)}
      color={f.marker_color}
    />
  ))}
</VWorldMap>
```

## drift gate (코드 작성 단계)

- `scripts/sync_from_python.ts` — `krtour.map.category` Python 매핑을 읽어
  TypeScript 테이블 생성. PR diff에서 누락 시 fail.
- `tests/unit/test_category_maki_consistency.py` (Python 측) — Python ↔
  TypeScript 매핑 표 1:1 일치 검증.

## 배포

- 빌드: `npm run build` → `dist/` ESM + CJS + d.ts (Vite library mode).
- 게시: GitHub Packages (npm) 또는 npm public. **공개 npm 권고** (ADR-029).
- 버저닝: SemVer 0.x로 시작 (breaking change 자유), 본 라이브러리
  `krtour.map.category` 변경 시 minor bump. 1.0.0은 Sprint 5 운영 진입과
  함께.

## monorepo + npm workspace

본 패키지가 `python-krtour-map` 저장소 안에 있어, 본 라이브러리 PR에서
Python 카테고리/notice 변경과 동시에 TypeScript 매핑도 변경할 수 있다 →
drift 0.

- 디버그 UI frontend(`packages/krtour-map-debug-ui/frontend/`)는
  `"@krtour/map-marker-react": "workspace:*"`로 참조.
- TripMate `apps/web`은 npm 게시본을 import.

## 사양

자세한 설계 의도: `../../docs/decisions.md` ADR-029.
