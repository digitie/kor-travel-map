/**
 * Marker color palette (ADR-029/043).
 *
 * Feature.marker_color는 "P-01"~"P-16" 16색 팔레트 코드를 사용한다. 본 모듈은
 * 그 코드를 실제 hex color로 풀어준다. 팔레트 자체는 향후 디자인 가이드와 함께
 * 조정할 수 있는 단순 lookup table.
 *
 * 디버그 UI(maplibre marker)와 TripMate user UI에서 동일 매핑을 공유해
 * 카테고리별 색 일관성을 보장한다.
 */

export type PaletteCode =
  | "P-01"
  | "P-02"
  | "P-03"
  | "P-04"
  | "P-05"
  | "P-06"
  | "P-07"
  | "P-08"
  | "P-09"
  | "P-10"
  | "P-11"
  | "P-12"
  | "P-13"
  | "P-14"
  | "P-15"
  | "P-16";

/** 디폴트 hex(`marker_color`가 없거나 미지의 코드일 때). */
export const DEFAULT_MARKER_COLOR = "#3b82f6";

/**
 * 16색 팔레트 hex 매핑. (Tableau 10 + 보강색 — 색약 친화 우선.) 본 lookup은
 * 디자인 가이드 확정 시 supersede 대상. 코드값은 안정.
 */
export const PALETTE: Readonly<Record<PaletteCode, string>> = Object.freeze({
  "P-01": "#1f77b4", // blue
  "P-02": "#ff7f0e", // orange
  "P-03": "#2ca02c", // green
  "P-04": "#d62728", // red
  "P-05": "#9467bd", // purple
  "P-06": "#8c564b", // brown
  "P-07": "#e377c2", // pink
  "P-08": "#7f7f7f", // gray
  "P-09": "#bcbd22", // olive
  "P-10": "#17becf", // cyan
  "P-11": "#f59e0b", // amber
  "P-12": "#10b981", // emerald
  "P-13": "#6366f1", // indigo
  "P-14": "#ec4899", // rose
  "P-15": "#14b8a6", // teal
  "P-16": "#a855f7", // violet
});

/**
 * marker_color 문자열 → hex. 알 수 없는 코드면 `DEFAULT_MARKER_COLOR`.
 * "P-07" 같은 코드 외에 이미 hex(`#rrggbb`)이면 그대로 신뢰.
 */
export function resolveMarkerColor(markerColor: string | null | undefined): string {
  if (!markerColor) return DEFAULT_MARKER_COLOR;
  if (markerColor.startsWith("#")) return markerColor;
  return (PALETTE as Record<string, string>)[markerColor] ?? DEFAULT_MARKER_COLOR;
}
