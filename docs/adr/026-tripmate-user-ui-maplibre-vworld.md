# ADR-026: TripMate 사용자 UI도 `maplibre-vworld` 채택 (SPEC V8 v8_3 supersede)

- **상태**: accepted
- **날짜**: 2026-05-25
- **결정자**: 사용자
- **컨텍스트**: ADR-025로 본 라이브러리의 **디버그 UI** frontend는
  `maplibre-vworld` 채택. 그러나 상위 app TripMate의 **사용자 가시 지도 UI**
  (SPEC V8 v8_3 spec)는 Kakao Maps JS SDK를 사용하도록 명시되어 있었다.
  두 개의 다른 지도 stack을 유지하면:
  - frontend 운영 비용 2배 (Kakao + VWorld 양쪽 학습/디버깅).
  - category maki icon 매핑 코드가 두 곳에 산재.
  - 좌표 변환·proj4·KAKAO_ID vs VWorld coord 정합 부담.
  - Kakao JS key 호출 한도와 모니터링 분리.

  사용자가 "둘 다 바꿈"으로 지시 — TripMate 사용자 UI도 `maplibre-vworld`
  통일.

- **결정**:
  - **TripMate `apps/web` 사용자 가시 지도 UI도 `maplibre-vworld` 채택**.
  - SPEC V8 v8_3의 "Kakao Maps JS SDK" 섹션은 **superseded** — TripMate 측
    spec에 본 ADR 링크 박음.
  - 두 UI(본 라이브러리 디버그 UI + TripMate 사용자 UI)는 동일 frontend
    stack (React + Vite + TS + `maplibre-vworld` + `maplibre-gl` + `zod`).
  - 마커 / category maki icon 매핑 로직은 npm 패키지로 추출 후보
    (`@kor-travel-map/map-marker-react`, 추후 ADR로 결정) — 두 UI에서 import.
  - VWorld API key는 TripMate 사용자 UI도 동일하게 `KOR_TRAVEL_GEO_VWORLD_API_KEY`
    공유 (또는 TripMate 사용자 환경의 동일 출처 키). 운영자 키와 사용자
    프런트 키는 referrer 제한으로 분리 권장.
  - Kakao Maps JS SDK 의존 / `NEXT_PUBLIC_KAKAO_JS_KEY` 등 관련 변수 일괄
    제거 (TripMate 측 후속 PR).

- **근거**:
  - **단일 stack 운영**: 한 frontend stack(React + Vite + TS +
    maplibre-vworld)으로 디버그 UI와 사용자 UI 양쪽 운영 — 학습/디버깅 비용
    절감.
  - **VWorld 일관성**: 본 라이브러리·`kor-travel-geo`·디버그 UI·TripMate
    UI 모두 VWorld 단일 source — 좌표·행정구역·도로명주소 시각화 정합.
  - **호출 한도 일원화**: Kakao JS SDK 일 호출 한도 모니터링 불필요. VWorld
    referrer 제한만 관리.
  - **maki icon 단일 매핑**: `kortravelmap.category` Tier 1~4 → maki icon
    매핑 1회로 두 UI 공통 (추후 npm 패키지 추출).
  - **WebGL 성능**: 10만+ feature 렌더링은 디버그 UI뿐 아니라 사용자 UI에서도
    이점 (예: "주변 100km 내 모든 옵셈 주유소" 같은 시나리오).
  - **사용자 직접 지시 + 본 사용자가 maplibre-vworld-js를 직접 관리** — 결정
    번복 리스크 낮음.

- **결과 (긍정)**:
  - frontend stack 일원화 (React + Vite + TS + maplibre-vworld).
  - category maki icon 매핑 단일화 가능.
  - VWorld key 일원화 (Kakao key 발급/회전/모니터링 제거).
  - 본 라이브러리의 디버그 UI 학습이 TripMate 운영 학습으로 직결.

- **결과 (부정)**:
  - TripMate `apps/web`의 기존 Kakao Maps 코드 제거/대체 PR 필요 (TripMate
    저장소 측 작업, 본 저장소 외).
  - SPEC V8 v8_3의 Kakao Maps 의존 섹션 supersede 표기/링크 필요.
  - 본 라이브러리는 wrapper 도입하지 않음(ADR-006) — TripMate 측이 본 라이브러리
    debug-ui frontend의 컴포넌트를 직접 import할 수 없으므로, 공통 마커 패키지를
    별도 npm 패키지로 추출하는 ADR이 추가 필요 (후속).

- **후속**:
  - TripMate 저장소에 본 ADR 링크하는 supersede 표기 PR (TripMate 측 작업).
  - SPEC V8 v8_3 문서에 "superseded by kor-travel-map ADR-026" 추가
    (SPEC 저장소 측 작업).
  - `docs/tripmate-integration.md` 갱신 — 사용자 UI도 maplibre-vworld
    사용 명기, Kakao 의존 제거.
  - 공통 마커/카테고리 매핑 npm 패키지 추출 ADR (후속, ADR-028~ 후보).
  - `docs/external-apis.md` §8 비용 관리에서 Kakao Maps JS SDK 항목 제거
    또는 "TripMate UI 통일 이후 미사용"으로 표기.
  - `docs/architecture/category.md` §4 maki icon 매핑은 두 UI 공통 reference 명기.
