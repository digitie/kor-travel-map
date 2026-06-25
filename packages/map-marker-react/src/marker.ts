/**
 * `createMarkerElement` — maplibre `Marker`에 넘길 HTMLElement 팩토리.
 *
 * maplibre의 `new maplibregl.Marker({ element })`는 임의 DOM 요소를 받으므로,
 * React 컴포넌트가 아닌 **DOM factory**가 가장 가볍고 이식성 좋다 (debug UI
 * Next.js + PinVi 어느 쪽에서도 동일하게 사용). 향후 React 컴포넌트 wrapper
 * 가 필요해지면 본 함수를 감싼다.
 */

import { resolveMarkerLabel } from "./maki";
import { DEFAULT_MARKER_COLOR, resolveMarkerColor } from "./palette";

export interface CreateMarkerElementOptions {
  /** Feature.marker_icon (maki name). 미지의 name이면 첫 글자가 라벨로 표시. */
  markerIcon?: string | null;
  /** Feature.marker_color ("P-01"~"P-16" 코드 또는 hex `#rrggbb`). */
  markerColor?: string | null;
  /** 마커 지름(px). 기본 24. */
  size?: number;
  /** `:hover`/`:click` 처리. maplibre marker는 내부에서 popup 등 다른 layer를 띄울 때
   * 클릭 이벤트를 별도로 다뤄야 하므로, 본 factory는 onClick 만 직접 wire한다. */
  onClick?: (event: MouseEvent) => void;
  /** title 속성 (hover tooltip). 보통 feature.name. */
  title?: string;
  /** 추가 CSS class — 호스트가 글로벌 스타일과 통합할 때 유용. */
  className?: string;
}

/**
 * maplibre.Marker용 HTMLElement 생성. 동그란 색상 배지에 maki 글리프(또는 첫
 * 글자) 라벨이 들어간다.
 *
 *     const el = createMarkerElement({ markerIcon: "park", markerColor: "P-03" });
 *     new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map);
 */
export function createMarkerElement(
  options: CreateMarkerElementOptions = {},
): HTMLDivElement {
  const size = options.size ?? 24;
  const color = resolveMarkerColor(options.markerColor) || DEFAULT_MARKER_COLOR;
  const label = resolveMarkerLabel(options.markerIcon);

  const el = document.createElement("div");
  el.setAttribute("role", "img");
  if (options.title) el.title = options.title;
  if (options.className) el.className = options.className;
  Object.assign(el.style, {
    width: `${size}px`,
    height: `${size}px`,
    borderRadius: "50%",
    background: color,
    border: "2px solid white",
    boxShadow: "0 1px 4px rgba(0,0,0,0.3)",
    color: "white",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: `${Math.max(10, Math.round(size * 0.5))}px`,
    fontFamily:
      "Apple Color Emoji, Segoe UI Emoji, Noto Color Emoji, Twemoji Mozilla, sans-serif",
    lineHeight: "1",
    userSelect: "none",
    cursor: options.onClick ? "pointer" : "default",
  } satisfies Partial<CSSStyleDeclaration>);
  el.textContent = label;

  if (options.onClick) {
    el.addEventListener("click", options.onClick);
  }

  return el;
}
