import type { StyleSpecification } from "maplibre-gl";

const VWORLD_ATTRIBUTION = "공간정보 오픈플랫폼 브이월드";
const VWORLD_IMAGERY_LAYERS = new Set<VWorldLayerType>(["Hybrid", "Satellite"]);

export type VWorldLayerType =
  | "Base"
  | "gray"
  | "midnight"
  | "Hybrid"
  | "Satellite";

export function isVWorldApiKeyConfigured(
  apiKey: string | undefined,
): apiKey is string {
  return apiKey !== undefined && apiKey.length > 0 && apiKey !== "CHANGE_ME";
}

export function buildVWorldStyle(
  apiKey: string | undefined,
  layerType: VWorldLayerType = "Base",
): StyleSpecification {
  if (isVWorldApiKeyConfigured(apiKey)) {
    return getClientVWorldStyle(apiKey, layerType);
  }
  return {
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

function getVWorldTileUrl(apiKey: string, layerType: VWorldLayerType): string {
  const extension = layerType === "Satellite" ? "jpeg" : "png";
  const layerName = layerType === "gray" ? "white" : layerType;
  return `https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(
    apiKey.trim(),
  )}/${layerName}/{z}/{y}/{x}.${extension}`;
}

function getVWorldMaxZoom(layerType: VWorldLayerType): number {
  return VWORLD_IMAGERY_LAYERS.has(layerType) ? 18 : 19;
}

function getClientVWorldStyle(
  apiKey: string,
  layerType: VWorldLayerType,
): StyleSpecification {
  const maxzoom = getVWorldMaxZoom(layerType);
  const sources: StyleSpecification["sources"] = {};
  const layers: StyleSpecification["layers"] = [];

  const appendRasterLayer = (
    sourceId: string,
    layerId: string,
    sourceLayerType: VWorldLayerType,
  ) => {
    sources[sourceId] = {
      type: "raster",
      tiles: [getVWorldTileUrl(apiKey, sourceLayerType)],
      tileSize: 256,
      attribution: VWORLD_ATTRIBUTION,
      maxzoom,
    };
    layers.push({
      id: layerId,
      type: "raster",
      source: sourceId,
      minzoom: 0,
    });
  };

  if (layerType === "Hybrid") {
    appendRasterLayer(
      "vworld-satellite",
      "vworld-satellite-layer",
      "Satellite",
    );
  }
  appendRasterLayer(`vworld-${layerType}`, `vworld-${layerType}-layer`, layerType);

  return {
    version: 8,
    sources,
    layers,
  };
}
