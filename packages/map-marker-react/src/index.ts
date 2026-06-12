/**
 * `@kor-travel-map/map-marker-react` — kor-travel-map 공통 마커 자원 (ADR-029/043).
 *
 * 디버그 UI(`packages/kor-travel-map-admin/frontend/`)와 TripMate 사용자 UI가
 * 같은 카테고리 색/아이콘 매핑을 공유해 시각 일관성을 보장한다. 본 라이브러리
 * 자체는 maplibre/React에 종속되지 않는 **순수 DOM factory + lookup table** —
 * 후속 PR에서 React 컴포넌트 wrapper / 정식 maki SVG sprite를 같은 API로 swap.
 */

export {
  createMarkerElement,
  type CreateMarkerElementOptions,
} from "./marker";
export {
  resolveMarkerColor,
  PALETTE,
  DEFAULT_MARKER_COLOR,
  type PaletteCode,
} from "./palette";
export { resolveMarkerLabel, getMakiGlyph, KNOWN_MAKI_NAMES } from "./maki";
