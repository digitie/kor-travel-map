# @kor-travel-map/map-marker-react

`kor-travel-map` 디버그 UI와 TripMate 사용자 UI에서 공통으로 쓰는 마커/
카테고리-maki 매핑/색상 팔레트 React 컴포넌트 라이브러리 (ADR-029).

> **현재 상태 (Sprint 1 skeleton)**: 본 패키지는 ADR-029 결정에 따른 npm
> package skeleton이다. 본 README + `package.json` + `vite.config.ts`
> (skeleton)가 있으며, 실제 marker/component 구현은 category/notice 매핑
> drift gate와 함께 후속 PR에서 진행한다.

## 라이선스

**MIT** — TripMate(proprietary)와 본 라이브러리(`kor-travel-map`, GPL-3.0)
양쪽에서 import 가능하도록 의도적 분리 (ADR-029 §결정).

본 패키지는 *UI 유틸*이지 비즈니스 로직이 아니다 — MIT로 분리해도 본 라이브
러리의 GPL 보호는 손상되지 않는다.

## 정체성

| 항목 | 값 |
|------|----|
| 패키지명 | `@kor-travel-map/map-marker-react` |
| 위치 | `packages/map-marker-react/` (`kor-travel-map` monorepo) |
| import | `import { MakiMarker, categoryMakiIcon } from "@kor-travel-map/map-marker-react"` |
| 라이선스 | MIT |
| peer deps | `react@^19.2`, `maplibre-gl@^5.24`, `maplibre-vworld@0.1.3` (설치는 `github:digitie/maplibre-vworld-js#v0.1.3`, npm 미게시), `zod@^4.4` |

## 포함 항목 (계획)

| 모듈 | 역할 |
|------|------|
| `categoryMaki.ts` | `kortravelmap.category` PlaceCategoryCode (144건, ADR-027 반영) → maki icon (55종 + shelter) dispatch |
| `noticeMaki.ts` | `notice_type` (14건, ADR-027 반영) → maki icon dispatch |
| `<MakiMarker>` | maplibre-gl Marker 래핑 React 컴포넌트 |
| `markerColor.ts` | P-01~P-16 팔레트 + severity → color helper |
| 타입 (`PlaceCategoryCode`, `NoticeType`, `MakiIconName`) | 본 라이브러리 Pydantic DTO와 정합 (수동 mirror 또는 openapi-typescript) |

## 두 UI에서의 사용

```typescript
// debug UI (packages/kor-travel-map-admin/frontend/src/pages/FeatureMap.tsx)
// 또는 TripMate apps/web/components/FeatureMap.tsx
import { MakiMarker, categoryMakiIcon } from "@kor-travel-map/map-marker-react";

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

- `scripts/sync_from_python.ts` — `kortravelmap.category` Python 매핑을 읽어
  TypeScript 테이블 생성. PR diff에서 누락 시 fail.
- `tests/unit/test_category_maki_consistency.py` (Python 측) — Python ↔
  TypeScript 매핑 표 1:1 일치 검증.

## 배포

- 빌드: `npm run build` → `dist/` ESM + CJS + d.ts (Vite library mode).
- 게시: ADR-043에 따라 npm registry 게시 보류. 현재 공유는 monorepo workspace 또는
  git URL 기준이다.
- 버저닝: SemVer 0.x로 시작 (breaking change 자유), 본 라이브러리
  `kortravelmap.category` 변경 시 minor bump. 1.0.0은 Sprint 5 운영 진입과
  함께.

## monorepo + npm workspace

본 패키지가 `kor-travel-map` 저장소 안에 있어, 본 라이브러리 PR에서
Python 카테고리/notice 변경과 동시에 TypeScript 매핑도 변경할 수 있다 →
drift 0.

- 디버그 UI frontend(`packages/kor-travel-map-admin/frontend/`)는
  `"@kor-travel-map/map-marker-react": "workspace:*"`로 참조.
- TripMate `apps/web`은 현 단계에서 git URL 또는 monorepo/workspace 배포본을
  import한다. npm registry 게시는 ADR-043에 따라 보류한다.

## 사양

자세한 설계 의도: `../../docs/adr/README.md` ADR-029.
