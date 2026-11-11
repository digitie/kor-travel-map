import type { StyleSpecification } from "maplibre-gl";
import { getVWorldStyle, type VWorldLayerType } from "vworld-map-web";
export {
  getVWorldTileUrl,
  getVWorldMaxZoom,
  redactVWorldUrl,
} from "vworld-map-web";
export type { VWorldLayerType } from "vworld-map-web";

export function isVWorldApiKeyConfigured(
  apiKey: string | undefined,
): apiKey is string {
  return Boolean(apiKey?.trim() && apiKey.trim() !== "CHANGE_ME");
}

/** 개발용 키 누락 표면만 유지하고 URL·스타일 규칙은 upstream에 위임한다. */
export function buildVWorldStyle(
  apiKey: string | undefined,
  layerType: VWorldLayerType = "Base",
): StyleSpecification {
  return isVWorldApiKeyConfigured(apiKey)
    ? getVWorldStyle(apiKey, layerType)
    : {
        version: 8,
        sources: {},
        layers: [
          {
            id: "bg",
            type: "background",
            paint: { "background-color": "#edf1f5" },
          },
        ],
      };
}
