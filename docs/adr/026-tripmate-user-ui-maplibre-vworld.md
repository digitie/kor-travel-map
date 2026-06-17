# ADR-026: 본 레포 debug/admin UI를 `maplibre-vworld`로 통일 + category→maki 단일 매핑

- **상태**: accepted
- **날짜**: 2026-05-25
- **결정자**: 사용자
- **컨텍스트**: ADR-025로 본 라이브러리의 **debug/admin UI** frontend는
  `maplibre-vworld` 채택. 본 레포의 지도 시각화 stack을 단일화해 다음 부담을
  제거한다:
  - frontend 운영 비용 (지도 stack 이중 학습/디버깅).
  - category maki icon 매핑 코드 산재.
  - 좌표 변환·proj4·VWorld coord 정합 부담.

- **결정**:
  - **본 레포 debug/admin 지도 UI는 `maplibre-vworld`로 통일**
    (React + Vite + TS + `maplibre-vworld` + `maplibre-gl` + `zod`).
  - 마커 / category maki icon 매핑 로직은 npm 패키지로 추출 후보
    (`@kor-travel-map/map-marker-react`, 추후 ADR로 결정).
  - VWorld API key는 `KOR_TRAVEL_GEO_VWORLD_API_KEY`를 공유한다. 키는
    referrer 제한으로 분리 권장.
  - 외부 소비자의 지도 stack 채택·Kakao 제거 여부는 본 ADR 범위 밖(외부
    경계는 OpenAPI).

- **근거**:
  - **단일 stack 운영**: 한 frontend stack(React + Vite + TS +
    maplibre-vworld)으로 본 레포 UI 운영 — 학습/디버깅 비용 절감.
  - **VWorld 일관성**: 본 라이브러리·`kor-travel-geo`·debug/admin UI 모두
    VWorld 단일 source — 좌표·행정구역·도로명주소 시각화 정합.
  - **maki icon 단일 매핑**: `kortravelmap.category` Tier 1~4 → maki icon
    매핑 1회 (추후 npm 패키지 추출).
  - **WebGL 성능**: 10만+ feature 렌더링 이점 (예: "주변 100km 내 모든 옵셈
    주유소" 같은 시나리오).
  - **사용자 직접 지시 + 본 사용자가 maplibre-vworld-js를 직접 관리** — 결정
    번복 리스크 낮음.

- **결과 (긍정)**:
  - frontend stack 일원화 (React + Vite + TS + maplibre-vworld).
  - category maki icon 매핑 단일화 가능.
  - VWorld key 일원화.

- **결과 (부정)**:
  - 본 라이브러리는 wrapper 도입하지 않음(ADR-006) — debug/admin frontend의
    컴포넌트를 외부에서 직접 import할 수 없으므로, 공통 마커 패키지를 별도 npm
    패키지로 추출하는 ADR이 추가 필요 (후속).

- **후속**:
  - 공통 마커/카테고리 매핑 npm 패키지 추출 ADR (후속, ADR-028~ 후보).
  - `docs/architecture/category.md` §4 maki icon 매핑은 본 레포 UI reference 명기.
