# ADR-029: 공통 maki marker / category 매핑 npm 패키지 추출 (`@kor-travel-map/map-marker-react`)

- **상태**: superseded by ADR-043 — npm 게시 보류, `packages/map-marker-react/`
  는 모노레포 내부 share 모듈로만 사용 (코드 자체는 유지, registry publish X).
  (구 상태: accepted at T-014 Sprint 1 진입 2026-05-25.)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (T-014 Sprint 1 진입)
- **컨텍스트**: ADR-025 (디버그 UI = maplibre-vworld)로 frontend stack은
  maplibre-vworld로 일원화됨. 본 라이브러리의 UI에서 쓰는 마커 코드 —
  `kortravelmap.category` Tier 1~4 → maki icon(55종) dispatch, `MakiMarker`
  컴포넌트, marker color 팔레트(P-01~P-16), notice_type → maki 매핑 — 을
  분리·재사용 가능한 단위로 둘 필요가 있다. 이는:
  - 분류 정책 변경(예: ADR-027의 `03.08 shelter` 추가)이 매핑에 누락 없이
    반영되어야 → drift 위험 관리.
  - 마커 컴포넌트를 단일 source로 유지 → maintenance 비용 절감.

  해결: **모노레포 내부 share 모듈로 추출**.

- **결정**:
  - **패키지명**: `@kor-travel-map/map-marker-react`
  - **저장소 위치**: `packages/map-marker-react/` (본 monorepo 내, ADR-020
    debug-ui 패턴 미러). 별도 저장소가 아닌 monorepo로 두는 이유: maki
    매핑/카테고리 코드가 본 라이브러리의 `kortravelmap.category` Tier 1~4 +
    `notice-feature-etl.md` notice_type과 직접 정합 — 같은 PR/commit에서
    동기 변경되어야 한다.
  - **포함 항목**:
    - `categoryMaki.ts` — `kortravelmap.category` PlaceCategoryCode (144건, ADR-027
      반영) → maki icon (55종 + shelter) dispatch 테이블.
    - `noticeMaki.ts` — `notice_type` (14건, ADR-027 반영) → maki icon
      dispatch.
    - `<MakiMarker>` React 컴포넌트 — maplibre-gl `Marker` 래핑.
    - `markerColor.ts` — P-01~P-16 팔레트 + severity → color helper.
    - TypeScript 타입 (`PlaceCategoryCode`, `NoticeType`, `MakiIconName` 등)
      — 본 라이브러리의 Pydantic DTO와 정합 (수동 mirror 또는
      openapi-typescript에서 import).
  - **빌드/배포**:
    - Vite 라이브러리 모드 (`vite build --mode lib`) → ESM + CJS + d.ts.
    - 본 monorepo의 npm workspace 또는 pnpm workspace로 디버그 UI frontend가
      local file:로 참조 (`"@kor-travel-map/map-marker-react": "workspace:*"`).
    - (npm registry 게시는 ADR-043으로 보류 — 내부 share 모듈로만 사용.)
  - **라이선스**: **MIT**. 본 라이브러리(GPL-3.0)와 별도 라이선스인 이유:
    - 본 패키지는 *UI 유틸*이지 비즈니스 로직이 아님 — MIT로 분리해도 본
      라이브러리의 GPL 보호 손상 없음.
    - 본 라이브러리(`kortravelmap` Python)는 GPL 유지. npm 패키지만 MIT.
  - **버저닝**:
    - SemVer 0.x로 시작 (breaking change 자유로움).
    - 본 라이브러리 `kortravelmap.category` 변경 시 npm 패키지 minor bump.
  - **본 라이브러리(`kortravelmap`) 측 정합**:
    - `kortravelmap.category`에 `MAPBOX_MAKI_ICON_FOR_CATEGORY` dict 추가
      (이미 `category.md`에 사양 박힘).
    - 코드 작성 단계에서 `tests/unit/test_category_maki_consistency.py` —
      Python ↔ TypeScript 매핑 표 1:1 일치 검증. drift gate.
    - `packages/map-marker-react/scripts/sync_from_python.ts` — Python 측
      매핑을 읽어 TypeScript 테이블 생성 (또는 build time 검증).

- **근거**:
  - **drift 회피**: 단일 source 매핑. category/notice_type 정책 변경이
    매핑에 자동 반영.
  - **monorepo + npm workspace**: 본 라이브러리 PR에서 동시 변경 가능 → 매핑
    drift 0.
  - **MIT 라이선스**: UI 유틸은 일반 공개에도 무리 없음 — 본 라이브러리의
    GPL 보호와 독립.
  - **wrapper 아님**: ADR-006 위반 아님 — provider client wrapper가 아닌 *UI
    공통 모듈*. provider 호출 책임은 본 라이브러리에 그대로.

- **결과 (긍정)**:
  - 마커 코드 단일 source. 카테고리/notice 변경 시 매핑 drift 0.
  - 모노레포 PR에서 매핑/컴포넌트를 동기 변경 → 학습·재사용 비용 절감.

- **결과 (부정)**:
  - npm workspace 운영 부담 (Vite 라이브러리 모드 빌드, d.ts 생성).
  - 본 라이브러리 PR에서 두 언어(Python + TypeScript) 변경 → 리뷰 부담 약간
    증가. `tests/unit/test_category_maki_consistency.py` drift gate로 완화.
  - MIT vs GPL 분리는 의도적이지만 운영자가 라이선스 정책을 두 종류로 관리
    해야 함.

- **후속**:
  - `packages/map-marker-react/` 디렉토리 생성 — `package.json` skeleton +
    README + `.gitignore` + `vite.config.ts` (T-017 실행 시).
  - `docs/architecture/debug-ui-package.md` §14 — `categoryMaki.ts`를 `@kor-travel-map/map-marker-react`
    에서 import하도록 명기.
  - `docs/architecture/category.md` §4.4 — maki icon 매핑이 본 UI 공통 reference임 명기
    (ADR-025 후속의 잔존 항목).
  - `tests/unit/test_category_maki_consistency.py` — Python ↔ TS 매핑 1:1
    검증 통합 테스트 (코드 작성 단계).
