"use client";

import {
  createMarkerElement,
  resolveMarkerColor,
} from "@kor-travel-map/map-marker-react";
import maplibregl, {
  type Map as MapLibreMap,
  type Marker as MapLibreMarker,
  type Popup as MapLibrePopup,
} from "maplibre-gl";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import {
  buildVWorldStyle,
  getVWorldMaxZoom,
  redactVWorldUrl,
  type VWorldLayerType,
} from "@/lib/vworld-style";

const VWorldMapContext = createContext<MapLibreMap | null>(null);

const CLUSTER_SOURCE_ID = "kor-feature-clusters";
const GEOMETRY_SOURCE_ID = "kor-feature-geometries";
const AREA_FILL_LAYER_ID = `${GEOMETRY_SOURCE_ID}-area-fill`;
const AREA_OUTLINE_LAYER_ID = `${GEOMETRY_SOURCE_ID}-area-outline`;
const ROUTE_LINE_LAYER_ID = `${GEOMETRY_SOURCE_ID}-route-line`;

interface VWorldMapViewProps {
  apiKey: string | undefined;
  center: [number, number];
  zoom: number;
  layerType?: VWorldLayerType;
  maxZoom?: number;
  minZoom?: number;
  navigation?: boolean;
  scale?: boolean;
  className?: string;
  style?: CSSProperties;
  testId?: string;
  children?: ReactNode;
  onContextMenu?: (event: maplibregl.MapMouseEvent) => void;
  onLongPress?: (event: {
    lngLat: maplibregl.LngLat;
    originalEvent: PointerEvent;
  }) => void;
  onLoad?: (map: MapLibreMap) => void;
  onMoveEnd?: (map: MapLibreMap) => void;
  onError?: (event: maplibregl.ErrorEvent) => void;
}

export function VWorldMapView({
  apiKey,
  center,
  zoom,
  layerType = "Base",
  maxZoom = 22,
  minZoom = 6,
  navigation = false,
  scale = false,
  className,
  style,
  testId,
  children,
  onContextMenu,
  onLongPress,
  onLoad,
  onMoveEnd,
  onError,
}: VWorldMapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const appliedStyleRef = useRef({ apiKey, layerType });
  const onContextMenuRef = useRef(onContextMenu);
  const onLongPressRef = useRef(onLongPress);
  const onLoadRef = useRef(onLoad);
  const onMoveEndRef = useRef(onMoveEnd);
  const onErrorRef = useRef(onError);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [loaded, setLoaded] = useState(false);

  useLayoutEffect(() => {
    onContextMenuRef.current = onContextMenu;
    onLongPressRef.current = onLongPress;
    onLoadRef.current = onLoad;
    onMoveEndRef.current = onMoveEnd;
    onErrorRef.current = onError;
  });

  useEffect(() => {
    if (containerRef.current === null) return;

    const nextMap = new maplibregl.Map({
      container: containerRef.current,
      style: buildVWorldStyle(apiKey, layerType),
      center,
      zoom,
      minZoom,
      maxZoom: Math.min(maxZoom, getVWorldMaxZoom(layerType)),
      attributionControl: { compact: true },
    });
    mapRef.current = nextMap;
    appliedStyleRef.current = { apiKey, layerType };
    setMap(nextMap);

    // e2e 훅: 컨테이너 DOM 노드에 map 인스턴스를 매달아 Playwright가
    // page.evaluate로 getLayer/querySourceFeatures 같은 GL 렌더 상태를 단언할 수
    // 있게 한다(전역 오염 없이 testId로 스코프됨). teardown 시 해제.
    const containerNode = containerRef.current as
      | (HTMLDivElement & { _maplibreMap?: MapLibreMap })
      | null;
    if (containerNode) containerNode._maplibreMap = nextMap;

    let didNotifyLoad = false;
    let loadFrame = 0;
    const notifyLoad = () => {
      if (didNotifyLoad) return;
      didNotifyLoad = true;
      setLoaded(true);
      onLoadRef.current?.(nextMap);
    };
    const handleLoad = () => {
      notifyLoad();
    };
    const handleMoveEnd = () => {
      onMoveEndRef.current?.(nextMap);
    };
    const handleContextMenu = (event: maplibregl.MapMouseEvent) => {
      onContextMenuRef.current?.(event);
    };
    const handleError = (event: maplibregl.ErrorEvent) => {
      if (onErrorRef.current) {
        onErrorRef.current(event);
        return;
      }
      const error = event.error as { message?: string; url?: string } | undefined;
      const url =
        error?.url ?? (event as { url?: string | undefined }).url;
      console.warn(
        "[VWorldMapView]",
        error?.message ?? "unknown map error",
        redactVWorldUrl(url) ?? "",
      );
    };

    nextMap.on("load", handleLoad);
    nextMap.on("idle", handleLoad);
    nextMap.on("contextmenu", handleContextMenu);
    nextMap.on("moveend", handleMoveEnd);
    nextMap.on("error", handleError);
    loadFrame = requestAnimationFrame(() => {
      notifyLoad();
    });

    let resizeFrame = 0;
    let longPressTimer = 0;
    let longPressPointer:
      | { id: number; startX: number; startY: number; currentEvent: PointerEvent }
      | null = null;
    const clearLongPress = () => {
      if (longPressTimer !== 0) {
        window.clearTimeout(longPressTimer);
        longPressTimer = 0;
      }
      longPressPointer = null;
    };
    const handlePointerDown = (event: PointerEvent) => {
      if (event.pointerType === "mouse" || !onLongPressRef.current) return;
      clearLongPress();
      longPressPointer = {
        id: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        currentEvent: event,
      };
      longPressTimer = window.setTimeout(() => {
        const pointer = longPressPointer;
        const node = containerRef.current;
        if (!pointer || !node || pointer.id !== event.pointerId) return;
        const rect = node.getBoundingClientRect();
        const lngLat = nextMap.unproject([
          pointer.currentEvent.clientX - rect.left,
          pointer.currentEvent.clientY - rect.top,
        ]);
        onLongPressRef.current?.({
          lngLat,
          originalEvent: pointer.currentEvent,
        });
        clearLongPress();
      }, 600);
    };
    const handlePointerMove = (event: PointerEvent) => {
      if (!longPressPointer || event.pointerId !== longPressPointer.id) return;
      const moveX = Math.abs(event.clientX - longPressPointer.startX);
      const moveY = Math.abs(event.clientY - longPressPointer.startY);
      if (moveX > 12 || moveY > 12) {
        clearLongPress();
        return;
      }
      longPressPointer.currentEvent = event;
    };
    const handlePointerEnd = (event: PointerEvent) => {
      if (longPressPointer && event.pointerId === longPressPointer.id) {
        clearLongPress();
      }
    };
    containerNode?.addEventListener("pointerdown", handlePointerDown);
    containerNode?.addEventListener("pointermove", handlePointerMove);
    containerNode?.addEventListener("pointerup", handlePointerEnd);
    containerNode?.addEventListener("pointercancel", handlePointerEnd);
    containerNode?.addEventListener("pointerleave", handlePointerEnd);
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            if (resizeFrame !== 0) return;
            resizeFrame = requestAnimationFrame(() => {
              resizeFrame = 0;
              nextMap.resize();
            });
          });
    if (resizeObserver && containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    const controls: Array<maplibregl.IControl> = [];
    if (navigation) {
      const control = new maplibregl.NavigationControl({
        showCompass: false,
      });
      nextMap.addControl(control, "top-right");
      controls.push(control);
    }
    if (scale) {
      const control = new maplibregl.ScaleControl({
        maxWidth: 150,
        unit: "metric",
      });
      nextMap.addControl(control, "bottom-right");
      controls.push(control);
    }

    return () => {
      if (loadFrame !== 0) cancelAnimationFrame(loadFrame);
      if (resizeFrame !== 0) cancelAnimationFrame(resizeFrame);
      clearLongPress();
      containerNode?.removeEventListener("pointerdown", handlePointerDown);
      containerNode?.removeEventListener("pointermove", handlePointerMove);
      containerNode?.removeEventListener("pointerup", handlePointerEnd);
      containerNode?.removeEventListener("pointercancel", handlePointerEnd);
      containerNode?.removeEventListener("pointerleave", handlePointerEnd);
      resizeObserver?.disconnect();
      nextMap.off("load", handleLoad);
      nextMap.off("idle", handleLoad);
      nextMap.off("contextmenu", handleContextMenu);
      nextMap.off("moveend", handleMoveEnd);
      nextMap.off("error", handleError);
      for (const control of controls) {
        try {
          nextMap.removeControl(control);
        } catch {
          // MapLibre may already be tearing down the control while removing the map.
        }
      }
      if (containerNode) delete containerNode._maplibreMap;
      nextMap.remove();
      mapRef.current = null;
      setLoaded(false);
      setMap(null);
    };
    // 지도 인스턴스는 mount 1회만 만들고, 이후 camera는 사용자 조작 결과를 store에 동기화한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const currentMap = mapRef.current;
    if (currentMap === null) return;
    if (
      appliedStyleRef.current.apiKey === apiKey &&
      appliedStyleRef.current.layerType === layerType
    ) {
      return;
    }
    currentMap.setStyle(buildVWorldStyle(apiKey, layerType));
    appliedStyleRef.current = { apiKey, layerType };
  }, [apiKey, layerType]);

  return (
    <VWorldMapContext.Provider value={map}>
      <div
        ref={containerRef}
        className={className}
        data-testid={testId}
        style={{
          ...style,
          touchAction: onLongPress ? "none" : style?.touchAction,
        }}
      />
      {loaded ? children : null}
    </VWorldMapContext.Provider>
  );
}

interface VWorldMarkerProps {
  lngLat: [number, number];
  markerIcon?: string | null;
  markerColor?: string | null;
  selected?: boolean;
  size?: number;
  title?: string;
  onClick?: () => void;
}

export function VWorldMarker({
  lngLat,
  markerIcon,
  markerColor,
  selected = false,
  size = 24,
  title,
  onClick,
}: VWorldMarkerProps) {
  const map = useContext(VWorldMapContext);
  const markerRef = useRef<MapLibreMarker | null>(null);
  const elementRef = useRef<ReturnType<typeof createMarkerElement> | null>(null);
  const onClickRef = useRef(onClick);
  const clickable = onClick !== undefined;
  const [lng, lat] = lngLat;

  useLayoutEffect(() => {
    onClickRef.current = onClick;
  });

  // 마커 DOM은 map 또는 시각 속성(icon/color/size/title)이 바뀔 때만 재생성한다.
  // lngLat(매 렌더 새 배열)·selected는 deps에서 빼고 아래 효과로 갱신해, 패닝/줌/선택마다
  // 전체 마커가 teardown+recreate되던 churn(#469 리뷰)을 막는다.
  useEffect(() => {
    if (map === null) return;

    const element = createMarkerElement({
      markerIcon,
      markerColor,
      size,
      title,
      onClick: clickable ? () => onClickRef.current?.() : undefined,
    });
    if (clickable) {
      element.setAttribute("aria-label", title ?? "Feature marker");
      element.setAttribute("role", "button");
    }
    elementRef.current = element;

    const marker = new maplibregl.Marker({ element })
      .setLngLat([lng, lat])
      .addTo(map);
    markerRef.current = marker;

    return () => {
      marker.remove();
      markerRef.current = null;
      elementRef.current = null;
    };
    // lng/lat·selected는 별도 효과로 갱신하므로 deps에서 의도적으로 제외한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clickable, map, markerIcon, markerColor, size, title]);

  // 위치 이동은 마커 재생성 없이 setLngLat로만 반영.
  useEffect(() => {
    markerRef.current?.setLngLat([lng, lat]);
  }, [lng, lat]);

  // 선택 상태는 기존 element에 outline만 토글(전체 재생성 없이).
  useEffect(() => {
    const element = elementRef.current;
    if (element === null) return;
    if (selected) {
      element.style.outline = "3px solid hsl(var(--primary))";
      element.style.outlineOffset = "2px";
    } else {
      element.style.outline = "";
      element.style.outlineOffset = "";
    }
  }, [selected]);

  return null;
}

/** 선택 강조: 기존 element에 outline만 토글(마커 재생성 없이). VWorldMarker와 동일 룩. */
function setSelectedOutline(element: HTMLElement, selected: boolean): void {
  if (selected) {
    element.style.outline = "3px solid hsl(var(--primary))";
    element.style.outlineOffset = "2px";
  } else {
    element.style.outline = "";
    element.style.outlineOffset = "";
  }
}

function createClusterElement(pointCount: number, label: string): HTMLDivElement {
  const el = document.createElement("div");
  const size = pointCount < 100 ? 36 : pointCount < 1000 ? 46 : 58;
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  el.style.display = "flex";
  el.style.alignItems = "center";
  el.style.justifyContent = "center";
  el.style.borderRadius = "9999px";
  el.style.background = "#2f765f";
  el.style.color = "#ffffff";
  el.style.fontWeight = "600";
  el.style.fontSize = pointCount < 1000 ? "12px" : "11px";
  el.style.lineHeight = "1";
  el.style.cursor = "pointer";
  el.style.border = "2px solid #ffffff";
  el.style.boxShadow = "0 1px 4px rgba(0,0,0,0.35)";
  el.style.userSelect = "none";
  el.textContent = label;
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", `feature 클러스터 ${pointCount}건`);
  return el;
}

export interface ClusterFeatureInput {
  feature_id: string;
  name: string;
  kind: string;
  category?: string | null;
  lon: number | null;
  lat: number | null;
  marker_icon?: string | null;
  marker_color?: string | null;
  geometry?: unknown;
  area_square_meters?: number | null;
  price_summary?: readonly ClusterPriceSummaryPoint[] | null;
  weather_summary?: ClusterWeatherSummaryPoint | null;
}

interface ClusterPriceSummaryPoint {
  product_key: string;
  product_name?: string | null;
  value_number: number;
  unit: string;
  observed_at: string;
}

interface ClusterWeatherSummaryPoint {
  metric_key: string;
  metric_name?: string | null;
  value_number?: number | null;
  value_text?: string | null;
  unit?: string | null;
  observed_at?: string | null;
  valid_at?: string | null;
  issued_at?: string | null;
}

type GeometryFeatureKind = "route" | "area";
type FeatureMapGeometry =
  | GeoJSON.LineString
  | GeoJSON.MultiLineString
  | GeoJSON.Polygon
  | GeoJSON.MultiPolygon;
type FeatureGeometryProperties = {
  feature_id: string;
  name: string;
  kind: GeometryFeatureKind;
  category: string;
  color: string;
  marker_color: string | null;
  label: string;
  label_lon: number | null;
  label_lat: number | null;
  area_square_meters: number | null;
};
type FeatureGeometryFeature = GeoJSON.Feature<
  FeatureMapGeometry,
  FeatureGeometryProperties
>;

function isFeatureMapGeometry(value: unknown): value is FeatureMapGeometry {
  if (typeof value !== "object" || value === null) return false;
  const type = (value as { type?: unknown }).type;
  return (
    type === "LineString" ||
    type === "MultiLineString" ||
    type === "Polygon" ||
    type === "MultiPolygon"
  );
}

function hasRenderableGeometry(feature: ClusterFeatureInput): boolean {
  return (
    (feature.kind === "route" || feature.kind === "area") &&
    isFeatureMapGeometry(feature.geometry)
  );
}

function shouldClusterAsPoint(feature: ClusterFeatureInput): boolean {
  return feature.kind !== "route";
}

function markerIconForFeature(feature: ClusterFeatureInput): string | null {
  return feature.marker_icon ?? null;
}

const priceFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 0,
});
const temperatureFormatter = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 1,
});

const FUEL_PRICE_ORDER = ["gasoline", "diesel", "premium_gasoline"] as const;

function fuelPriceOrder(productKey: string): number {
  const index = FUEL_PRICE_ORDER.indexOf(
    productKey as (typeof FUEL_PRICE_ORDER)[number],
  );
  return index === -1 ? 99 : index;
}

function fuelShortLabel(productKey: string, productName: string | null | undefined) {
  if (productKey === "gasoline") return "휘";
  if (productKey === "diesel") return "경";
  if (productKey === "premium_gasoline") return "고";
  return productName ?? productKey;
}

function priceMarkerLabel(
  summary: readonly ClusterPriceSummaryPoint[] | null | undefined,
): string | null {
  const points = (summary ?? [])
    .filter((point) => FUEL_PRICE_ORDER.includes(
      point.product_key as (typeof FUEL_PRICE_ORDER)[number],
    ))
    .sort((a, b) => fuelPriceOrder(a.product_key) - fuelPriceOrder(b.product_key));
  if (points.length === 0) return null;
  return points
    .map(
      (point) =>
        `${fuelShortLabel(point.product_key, point.product_name)} ${priceFormatter.format(
          point.value_number,
        )}`,
    )
    .join("\n");
}

function weatherMarkerLabel(
  summary: ClusterWeatherSummaryPoint | null | undefined,
): string | null {
  if (!summary) return null;
  if (typeof summary.value_number === "number") {
    const unit = summary.unit ?? "";
    const normalizedUnit = unit.toLowerCase();
    if (
      normalizedUnit === "deg_c" ||
      normalizedUnit.includes("celsius") ||
      unit.includes("C") ||
      unit.includes("℃")
    ) {
      return `${temperatureFormatter.format(summary.value_number)}℃`;
    }
    if (unit.length > 0) {
      return `${temperatureFormatter.format(summary.value_number)} ${unit}`;
    }
    return `${temperatureFormatter.format(summary.value_number)}°`;
  }
  return summary.value_text ?? null;
}

type CoincidentEntry = {
  feature_id: string;
  name: string;
  kind: string;
  lon: number;
  lat: number;
};

const FEATURE_KIND_LABELS: Record<string, string> = {
  place: "장소",
  event: "행사",
  notice: "공지",
  price: "가격",
  weather: "날씨",
  route: "경로",
  area: "구역",
};

function featureKindLabel(kind: string): string {
  return FEATURE_KIND_LABELS[kind] ?? kind;
}

/** 마커 우상단에 겹침 개수 배지를 단다(클릭하면 선택 팝업이 뜬다는 신호). */
function appendCountBadge(el: HTMLElement, count: number, color: string): void {
  if (!el.style.position) el.style.position = "relative";
  const badge = document.createElement("div");
  badge.textContent = String(count);
  badge.setAttribute("aria-hidden", "true");
  badge.style.position = "absolute";
  badge.style.top = "-6px";
  badge.style.right = "-6px";
  badge.style.minWidth = "16px";
  badge.style.height = "16px";
  badge.style.padding = "0 3px";
  badge.style.borderRadius = "8px";
  badge.style.background = color;
  badge.style.color = "#ffffff";
  badge.style.fontSize = "10px";
  badge.style.fontWeight = "700";
  badge.style.lineHeight = "16px";
  badge.style.textAlign = "center";
  badge.style.border = "1.5px solid #ffffff";
  badge.style.boxShadow = "0 1px 3px rgba(0,0,0,0.3)";
  badge.style.pointerEvents = "none";
  badge.style.boxSizing = "border-box";
  el.appendChild(badge);
}

function createFeatureMarkerElement({
  markerIcon,
  markerColor,
  priceLabel,
  weatherLabel,
  title,
  badgeCount,
  onClick,
}: {
  markerIcon?: string | null;
  markerColor?: string | null;
  priceLabel?: string | null;
  weatherLabel?: string | null;
  title: string;
  badgeCount?: number;
  onClick?: (event: MouseEvent) => void;
}): HTMLDivElement {
  const icon = createMarkerElement({
    markerIcon,
    markerColor,
    size: 24,
    title,
  });
  const markerLabel = priceLabel ?? weatherLabel ?? null;
  if (!markerLabel) {
    if (onClick) {
      icon.style.cursor = "pointer";
      icon.addEventListener("click", onClick);
    }
    if (badgeCount && badgeCount > 1) {
      appendCountBadge(icon, badgeCount, resolveMarkerColor(markerColor ?? null));
    }
    return icon;
  }

  const color = resolveMarkerColor(markerColor ?? null);
  const wrapper = document.createElement("div");
  wrapper.title = `${title} ${markerLabel.replace(/\n/g, " ")}`;
  wrapper.style.display = "flex";
  wrapper.style.alignItems = "center";
  wrapper.style.gap = "4px";
  wrapper.style.cursor = onClick ? "pointer" : "default";
  wrapper.style.userSelect = "none";

  const label = document.createElement("div");
  label.textContent = markerLabel;
  label.style.minWidth = priceLabel ? "58px" : "38px";
  label.style.padding = "3px 6px";
  label.style.borderRadius = "6px";
  label.style.background = "rgba(255,255,255,0.96)";
  label.style.border = `1px solid ${color}`;
  label.style.boxShadow = "0 1px 4px rgba(0,0,0,0.24)";
  label.style.color = "#111827";
  label.style.fontSize = "11px";
  label.style.fontWeight = "700";
  label.style.lineHeight = "1.18";
  label.style.whiteSpace = "pre";
  label.style.textAlign = "left";
  label.style.pointerEvents = "none";

  wrapper.append(icon, label);
  if (onClick) wrapper.addEventListener("click", onClick);
  if (badgeCount && badgeCount > 1) {
    appendCountBadge(wrapper, badgeCount, color);
  }
  return wrapper;
}

function areaLabel(areaSquareMeters: number | null | undefined): string | null {
  if (typeof areaSquareMeters !== "number" || !Number.isFinite(areaSquareMeters)) {
    return null;
  }
  if (areaSquareMeters >= 1_000_000) {
    return `${(areaSquareMeters / 1_000_000).toLocaleString("ko-KR", {
      maximumFractionDigits: 1,
    })} km2`;
  }
  return `${Math.round(areaSquareMeters).toLocaleString("ko-KR")} m2`;
}

function geometryLabel(feature: ClusterFeatureInput): string {
  if (feature.kind !== "area") return feature.name;
  const area = areaLabel(feature.area_square_meters);
  return area ? `${feature.name} - ${area}` : feature.name;
}

function geometryFeature(
  feature: ClusterFeatureInput,
  options: { selectedFeatureId: string | null; showAreaGeometry: boolean },
): FeatureGeometryFeature | null {
  if (
    (feature.kind !== "route" && feature.kind !== "area") ||
    !isFeatureMapGeometry(feature.geometry)
  ) {
    return null;
  }
  if (
    feature.kind === "area" &&
    !options.showAreaGeometry &&
    options.selectedFeatureId !== feature.feature_id
  ) {
    return null;
  }
  const markerColor = feature.marker_color ?? null;
  return {
    type: "Feature",
    geometry: feature.geometry,
    properties: {
      feature_id: feature.feature_id,
      name: feature.name,
      kind: feature.kind,
      category: feature.category ?? "",
      color: resolveMarkerColor(markerColor),
      marker_color: markerColor,
      label: geometryLabel(feature),
      label_lon: feature.lon,
      label_lat: feature.lat,
      area_square_meters: feature.area_square_meters ?? null,
    },
  };
}

function createGeometryLabelElement(
  feature: FeatureGeometryFeature,
  onSelectFeature: ((featureId: string) => void) | undefined,
): HTMLDivElement {
  const element = document.createElement("div");
  const color = feature.properties.color;
  element.textContent = feature.properties.label;
  element.title = `${feature.properties.name} (${feature.properties.kind})`;
  element.style.maxWidth = "13rem";
  element.style.padding = "3px 7px";
  element.style.borderRadius = "6px";
  element.style.background = "rgba(255,255,255,0.92)";
  element.style.border = `1px solid ${color}`;
  element.style.boxShadow = "0 1px 4px rgba(0,0,0,0.22)";
  element.style.color = "#111827";
  element.style.fontSize = "11px";
  element.style.fontWeight = "600";
  element.style.lineHeight = "1.2";
  element.style.whiteSpace = "normal";
  element.style.textAlign = "center";
  element.style.pointerEvents = onSelectFeature ? "auto" : "none";
  element.style.cursor = onSelectFeature ? "pointer" : "default";
  element.style.userSelect = "none";
  if (onSelectFeature) {
    element.setAttribute("role", "button");
    element.setAttribute("aria-label", element.title);
    element.addEventListener("click", (event) => {
      event.stopPropagation();
      onSelectFeature(feature.properties.feature_id);
    });
  } else {
    element.setAttribute("role", "img");
    element.setAttribute("aria-label", element.title);
  }
  return element;
}

/**
 * maplibre 네이티브 클러스터링(GeoJSON source `cluster:true`)으로 feature 점을
 * 그루핑하고, 클러스터(원+카운트)·개별(category 아이콘)을 **DOM 마커**로 렌더한다
 * (maplibre 공식 "Display HTML clusters" 패턴). VWorld style에 sprite/glyphs가
 * 없어 GL symbol/text 레이어 대신 DOM을 쓴다. 뷰포트에 보이는 마커만 풀에서
 * 재사용하므로 개별 마커 수백 개를 매 패닝마다 teardown/recreate하던 churn이 없다.
 */
export function VWorldFeatureClusters({
  features,
  onSelectFeature,
  selectedFeatureId = null,
  showAreaGeometry = true,
  clusterRadius = 60,
  clusterMaxZoom = 14,
}: {
  features: ReadonlyArray<ClusterFeatureInput>;
  onSelectFeature?: (featureId: string) => void;
  selectedFeatureId?: string | null;
  showAreaGeometry?: boolean;
  clusterRadius?: number;
  clusterMaxZoom?: number;
}) {
  const map = useContext(VWorldMapContext);
  const onSelectRef = useRef(onSelectFeature);
  const selectedFeatureIdRef = useRef<string | null>(selectedFeatureId);
  const priceSummariesRef = useRef(
    new Map<string, readonly ClusterPriceSummaryPoint[]>(),
  );
  const weatherSummariesRef = useRef(
    new Map<string, ClusterWeatherSummaryPoint>(),
  );
  // 현재 화면에 떠 있는 point/label 마커 element를 feature_id로 추적해, selection 변경
  // 시 마커 풀을 건드리지 않고 outline만 토글한다(#500 (c)).
  const pointElementsRef = useRef(new Map<string, HTMLElement>());
  const labelElementsRef = useRef(new Map<string, HTMLElement>());
  // 겹친 마커 선택: 같은 화면 픽셀 셀에 묶인 point feature 그룹(feature_id → 그룹)과
  // 현재 떠 있는 선택 팝업을 추적한다(동일 좌표 KMA 초단기/단기 등 겹침 분기).
  const coincidentGroupsRef = useRef(new Map<string, CoincidentEntry[]>());
  const popupRef = useRef<MapLibrePopup | null>(null);
  useLayoutEffect(() => {
    onSelectRef.current = onSelectFeature;
    selectedFeatureIdRef.current = selectedFeatureId;
    const summaries = new Map<string, readonly ClusterPriceSummaryPoint[]>();
    const weatherSummaries = new Map<string, ClusterWeatherSummaryPoint>();
    for (const feature of features) {
      if (feature.price_summary && feature.price_summary.length > 0) {
        summaries.set(feature.feature_id, feature.price_summary);
      }
      if (feature.weather_summary) {
        weatherSummaries.set(feature.feature_id, feature.weather_summary);
      }
    }
    priceSummariesRef.current = summaries;
    weatherSummariesRef.current = weatherSummaries;
  });

  const data = useMemo<GeoJSON.FeatureCollection<GeoJSON.Point>>(
    () => ({
      type: "FeatureCollection",
      features: features.flatMap((f) =>
        typeof f.lon === "number" &&
        typeof f.lat === "number" &&
        (!hasRenderableGeometry(f) || shouldClusterAsPoint(f))
          ? [
              {
                type: "Feature" as const,
                geometry: {
                  type: "Point" as const,
                  coordinates: [f.lon, f.lat],
                },
                properties: {
                  feature_id: f.feature_id,
                  name: f.name,
                  kind: f.kind,
                  marker_icon: markerIconForFeature(f),
                  marker_color: f.marker_color ?? null,
                },
              },
            ]
          : [],
      ),
    }),
    [features],
  );
  const geometryData = useMemo<
    GeoJSON.FeatureCollection<FeatureMapGeometry, FeatureGeometryProperties>
  >(
    () => ({
      type: "FeatureCollection",
      features: features.flatMap((feature) => {
        const item = geometryFeature(feature, {
          selectedFeatureId,
          showAreaGeometry,
        });
        return item ? [item] : [];
      }),
    }),
    [features, selectedFeatureId, showAreaGeometry],
  );

  // source data 갱신 (features prop 변경 시).
  useEffect(() => {
    if (map === null) return;
    const source = map.getSource(CLUSTER_SOURCE_ID) as
      | maplibregl.GeoJSONSource
      | undefined;
    source?.setData(data);
  }, [map, data]);

  useEffect(() => {
    if (map === null) return;
    const source = map.getSource(GEOMETRY_SOURCE_ID) as
      | maplibregl.GeoJSONSource
      | undefined;
    source?.setData(geometryData);
  }, [map, geometryData]);

  useEffect(() => {
    if (map === null) return;

    const ensureGeometryLayers = () => {
      if (!map.getSource(GEOMETRY_SOURCE_ID)) {
        map.addSource(GEOMETRY_SOURCE_ID, {
          type: "geojson",
          data: geometryData,
        });
      }
      if (!map.getLayer(AREA_FILL_LAYER_ID)) {
        map.addLayer({
          id: AREA_FILL_LAYER_ID,
          type: "fill",
          source: GEOMETRY_SOURCE_ID,
          filter: ["==", ["get", "kind"], "area"],
          paint: {
            "fill-color": ["get", "color"],
            "fill-opacity": 0.22,
          },
        });
      }
      if (!map.getLayer(AREA_OUTLINE_LAYER_ID)) {
        map.addLayer({
          id: AREA_OUTLINE_LAYER_ID,
          type: "line",
          source: GEOMETRY_SOURCE_ID,
          filter: ["==", ["get", "kind"], "area"],
          paint: {
            "line-color": ["get", "color"],
            "line-opacity": 0.9,
            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],
              8,
              1.2,
              14,
              2.8,
            ],
          },
        });
      }
      if (!map.getLayer(ROUTE_LINE_LAYER_ID)) {
        map.addLayer({
          id: ROUTE_LINE_LAYER_ID,
          type: "line",
          source: GEOMETRY_SOURCE_ID,
          filter: ["==", ["get", "kind"], "route"],
          layout: {
            "line-cap": "round",
            "line-join": "round",
          },
          paint: {
            "line-color": ["get", "color"],
            "line-opacity": 0.92,
            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],
              8,
              2,
              14,
              4.5,
            ],
          },
        });
      }
    };

    const handleGeometryClick = (event: maplibregl.MapLayerMouseEvent) => {
      const featureId = event.features?.[0]?.properties?.feature_id;
      if (typeof featureId === "string") {
        onSelectRef.current?.(featureId);
      }
    };
    const handleMouseEnter = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const handleMouseLeave = () => {
      map.getCanvas().style.cursor = "";
    };
    const handleStyleData = () => {
      ensureGeometryLayers();
    };

    ensureGeometryLayers();
    for (const layerId of [
      AREA_FILL_LAYER_ID,
      AREA_OUTLINE_LAYER_ID,
      ROUTE_LINE_LAYER_ID,
    ]) {
      map.on("click", layerId, handleGeometryClick);
      map.on("mouseenter", layerId, handleMouseEnter);
      map.on("mouseleave", layerId, handleMouseLeave);
    }
    map.on("styledata", handleStyleData);

    return () => {
      map.off("styledata", handleStyleData);
      for (const layerId of [
        AREA_FILL_LAYER_ID,
        AREA_OUTLINE_LAYER_ID,
        ROUTE_LINE_LAYER_ID,
      ]) {
        map.off("click", layerId, handleGeometryClick);
        map.off("mouseenter", layerId, handleMouseEnter);
        map.off("mouseleave", layerId, handleMouseLeave);
      }
      try {
        if (map.getLayer(ROUTE_LINE_LAYER_ID)) map.removeLayer(ROUTE_LINE_LAYER_ID);
        if (map.getLayer(AREA_OUTLINE_LAYER_ID)) {
          map.removeLayer(AREA_OUTLINE_LAYER_ID);
        }
        if (map.getLayer(AREA_FILL_LAYER_ID)) map.removeLayer(AREA_FILL_LAYER_ID);
        if (map.getSource(GEOMETRY_SOURCE_ID)) map.removeSource(GEOMETRY_SOURCE_ID);
      } catch {
        // 지도가 teardown 중일 수 있다.
      }
    };
    // geometryData 변경은 위 setData effect로 반영한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  // geometry LABEL 마커를 feature_id로 풀링한다(#500 (d)). geometryData가 바뀌어도
  // 전체 teardown/recreate 대신 setLngLat로 위치만 갱신하고, 사라진 feature만 remove한다.
  const labelMarkersRef = useRef(new Map<string, MapLibreMarker>());
  useEffect(() => {
    if (map === null) return;
    const pool = labelMarkersRef.current;
    const elements = labelElementsRef.current;
    const next = new Set<string>();

    for (const feature of geometryData.features) {
      const lon = feature.properties.label_lon;
      const lat = feature.properties.label_lat;
      if (typeof lon !== "number" || typeof lat !== "number") continue;
      const id = feature.properties.feature_id;
      next.add(id);
      let marker = pool.get(id);
      if (marker === undefined) {
        const element = createGeometryLabelElement(feature, onSelectRef.current);
        marker = new maplibregl.Marker({ anchor: "center", element })
          .setLngLat([lon, lat])
          .addTo(map);
        pool.set(id, marker);
        elements.set(id, element);
      } else {
        marker.setLngLat([lon, lat]);
      }
      setSelectedOutline(
        elements.get(id) ?? (marker.getElement() as HTMLElement),
        selectedFeatureIdRef.current === id,
      );
    }

    for (const [id, marker] of pool) {
      if (!next.has(id)) {
        marker.remove();
        pool.delete(id);
        elements.delete(id);
      }
    }
  }, [map, geometryData]);

  // map teardown 시 label 마커 풀 정리.
  useEffect(() => {
    if (map === null) return;
    const pool = labelMarkersRef.current;
    const elements = labelElementsRef.current;
    return () => {
      for (const marker of pool.values()) marker.remove();
      pool.clear();
      elements.clear();
    };
  }, [map]);

  // source/layer + 마커 풀 생애주기 (map 1회).
  useEffect(() => {
    if (map === null) return;
    const SRC = CLUSTER_SOURCE_ID;
    const markers = new Map<string, MapLibreMarker>();
    let onScreen = new Set<string>();
    // ref.current를 effect 시작 시 한 번 캡처해 cleanup에서도 같은 Map을 쓴다
    // (react-hooks/exhaustive-deps: cleanup에서 ref.current 직접 읽기 경고 회피).
    const pointElements = pointElementsRef.current;
    let raf = 0;

    const ensureSource = () => {
      if (map.getSource(SRC)) return;
      map.addSource(SRC, {
        type: "geojson",
        data,
        cluster: true,
        clusterRadius,
        clusterMaxZoom,
      });
      // querySourceFeatures가 렌더된 feature를 돌려주도록 투명 circle 레이어를 둔다.
      map.addLayer({
        id: `${SRC}-clusters`,
        type: "circle",
        source: SRC,
        filter: ["has", "point_count"],
        paint: { "circle-radius": 1, "circle-opacity": 0 },
      });
      map.addLayer({
        id: `${SRC}-points`,
        type: "circle",
        source: SRC,
        filter: ["!", ["has", "point_count"]],
        paint: { "circle-radius": 1, "circle-opacity": 0 },
      });
    };

    // 겹친 좌표의 feature들을 나열해 선택하게 하는 팝업. 동일 좌표(KMA 초단기/단기
    // 격자처럼)나 근접해 마커가 겹치는 경우, 마커 클릭이 이 팝업으로 분기한다.
    const showCoincidentPopup = (group: CoincidentEntry[]) => {
      popupRef.current?.remove();
      const container = document.createElement("div");
      container.style.font = "13px/1.4 system-ui, -apple-system, sans-serif";
      container.style.color = "#111827";
      const header = document.createElement("div");
      header.textContent = `겹친 지점 ${group.length}개`;
      header.style.fontSize = "11px";
      header.style.fontWeight = "700";
      header.style.color = "#6b7280";
      header.style.padding = "2px 4px 6px";
      container.appendChild(header);
      const list = document.createElement("div");
      list.style.display = "flex";
      list.style.flexDirection = "column";
      list.style.gap = "2px";
      list.style.maxHeight = "220px";
      list.style.overflowY = "auto";
      for (const f of group) {
        const row = document.createElement("button");
        row.type = "button";
        row.style.display = "flex";
        row.style.alignItems = "center";
        row.style.gap = "6px";
        row.style.width = "100%";
        row.style.padding = "5px 6px";
        row.style.border = "none";
        row.style.borderRadius = "5px";
        row.style.background = "transparent";
        row.style.cursor = "pointer";
        row.style.textAlign = "left";
        row.style.font = "inherit";
        row.style.color = "inherit";
        row.addEventListener("mouseenter", () => {
          row.style.background = "#f3f4f6";
        });
        row.addEventListener("mouseleave", () => {
          row.style.background = "transparent";
        });
        const kindBadge = document.createElement("span");
        kindBadge.textContent = featureKindLabel(f.kind);
        kindBadge.style.flex = "0 0 auto";
        kindBadge.style.fontSize = "10px";
        kindBadge.style.fontWeight = "700";
        kindBadge.style.padding = "1px 5px";
        kindBadge.style.borderRadius = "4px";
        kindBadge.style.background = "#e5e7eb";
        kindBadge.style.color = "#374151";
        const nameSpan = document.createElement("span");
        nameSpan.textContent = f.name;
        nameSpan.style.flex = "1 1 auto";
        nameSpan.style.whiteSpace = "nowrap";
        nameSpan.style.overflow = "hidden";
        nameSpan.style.textOverflow = "ellipsis";
        row.append(kindBadge, nameSpan);
        row.addEventListener("click", () => {
          onSelectRef.current?.(f.feature_id);
          popupRef.current?.remove();
        });
        list.appendChild(row);
      }
      container.appendChild(list);
      popupRef.current = new maplibregl.Popup({
        closeButton: true,
        closeOnClick: true,
        maxWidth: "260px",
      })
        .setLngLat([group[0].lon, group[0].lat])
        .setDOMContent(container)
        .addTo(map);
    };

    const updateMarkers = () => {
      if (!map.getSource(SRC) || !map.isStyleLoaded()) return;
      const next = new Set<string>();
      const seen = new Set<string>();
      const selectedId = selectedFeatureIdRef.current;
      pointElements.clear();
      const rendered = map.querySourceFeatures(SRC);
      // 겹침 그룹 선계산: 화면 픽셀 셀(≈마커 크기)로 point feature를 묶는다. zoom마다
      // 픽셀 위치가 바뀌므로 update마다 다시 계산하고, 클릭 핸들러는 ref로 최신값을 읽는다.
      const OVERLAP_PX = 24;
      const cellGroups = new Map<string, CoincidentEntry[]>();
      for (const feat of rendered) {
        if (feat.geometry.type !== "Point") continue;
        const props = feat.properties ?? {};
        if (props.cluster) continue;
        const c = feat.geometry.coordinates as [number, number];
        const p = map.project(c);
        const cellKey = `${Math.round(p.x / OVERLAP_PX)}:${Math.round(p.y / OVERLAP_PX)}`;
        const entry: CoincidentEntry = {
          feature_id: String(props.feature_id),
          name: String(props.name),
          kind: String(props.kind),
          lon: c[0],
          lat: c[1],
        };
        const arr = cellGroups.get(cellKey);
        if (arr) arr.push(entry);
        else cellGroups.set(cellKey, [entry]);
      }
      const coincident = new Map<string, CoincidentEntry[]>();
      for (const arr of cellGroups.values()) {
        if (arr.length > 1) {
          arr.sort((a, b) =>
            a.kind === b.kind
              ? a.name.localeCompare(b.name, "ko")
              : a.kind.localeCompare(b.kind),
          );
        }
        for (const e of arr) coincident.set(e.feature_id, arr);
      }
      coincidentGroupsRef.current = coincident;
      for (const feat of rendered) {
        if (feat.geometry.type !== "Point") continue;
        const coords = feat.geometry.coordinates as [number, number];
        const props = feat.properties ?? {};
        if (props.cluster) {
          const id = `cluster-${String(props.cluster_id)}`;
          if (seen.has(id)) continue;
          seen.add(id);
          const count = Number(props.point_count) || 0;
          const label = String(props.point_count_abbreviated ?? count);
          const clusterId = props.cluster_id as number;
          let marker = markers.get(id);
          if (marker === undefined) {
            const element = createClusterElement(count, label);
            element.dataset.clusterId = String(clusterId);
            // 클릭 핸들러는 element.dataset에서 *현재* clusterId/coords를 읽어
            // 캐시 HIT 재사용 시 stale closure로 옛 클러스터를 확대하지 않게 한다.
            element.dataset.lon = String(coords[0]);
            element.dataset.lat = String(coords[1]);
            element.addEventListener("click", () => {
              const source = map.getSource(SRC) as maplibregl.GeoJSONSource;
              const currentClusterId = Number(element.dataset.clusterId);
              const currentCoords: [number, number] = [
                Number(element.dataset.lon),
                Number(element.dataset.lat),
              ];
              void source
                .getClusterExpansionZoom(currentClusterId)
                .then((zoom) => {
                  map.easeTo({ center: currentCoords, zoom });
                })
                .catch(() => {
                  /* 클러스터가 사라졌으면 무시 */
                });
            });
            marker = new maplibregl.Marker({ element }).setLngLat(coords);
            markers.set(id, marker);
          } else {
            // 캐시 HIT — 풀 마커를 *실제로* 갱신한다(#500 (a)): 위치 + count/label +
            // dataset(클릭 핸들러가 읽는 현재 id/coords).
            marker.setLngLat(coords);
            const element = marker.getElement();
            element.dataset.clusterId = String(clusterId);
            element.dataset.lon = String(coords[0]);
            element.dataset.lat = String(coords[1]);
            if (element.textContent !== label) element.textContent = label;
            const ariaLabel = `feature 클러스터 ${count}건`;
            if (element.getAttribute("aria-label") !== ariaLabel) {
              element.setAttribute("aria-label", ariaLabel);
            }
          }
          next.add(id);
          if (!onScreen.has(id)) marker.addTo(map);
        } else {
          const featureId = String(props.feature_id);
          const id = `pt-${featureId}`;
          if (seen.has(id)) continue;
          seen.add(id);
          const title = `${String(props.name)} (${String(props.kind)})`;
          const markerIcon = (props.marker_icon as string | null) ?? undefined;
          const markerColor = (props.marker_color as string | null) ?? undefined;
          const priceLabel = priceMarkerLabel(
            priceSummariesRef.current.get(featureId),
          );
          const weatherLabel = weatherMarkerLabel(
            weatherSummariesRef.current.get(featureId),
          );
          const coincidentGroup = coincidentGroupsRef.current.get(featureId);
          const coincidentCount = coincidentGroup ? coincidentGroup.length : 1;
          const renderKey = JSON.stringify({
            markerIcon,
            markerColor,
            priceLabel,
            weatherLabel,
            coincidentCount,
          });
          let marker = markers.get(id);
          const wasOnScreen = onScreen.has(id);
          if (
            marker === undefined ||
            marker.getElement().dataset.renderKey !== renderKey
          ) {
            marker?.remove();
            const element = createFeatureMarkerElement({
              markerIcon,
              markerColor,
              priceLabel,
              weatherLabel,
              title,
              badgeCount: coincidentCount,
              onClick: () => {
                // 겹친 그룹이 2개 이상이면 선택 팝업, 단일이면 바로 선택(ref로 최신값).
                const grp = coincidentGroupsRef.current.get(featureId);
                if (grp && grp.length > 1) showCoincidentPopup(grp);
                else onSelectRef.current?.(featureId);
              },
            });
            element.dataset.renderKey = renderKey;
            element.setAttribute("role", "button");
            element.setAttribute(
              "aria-label",
              priceLabel || weatherLabel
                ? `${title} ${(priceLabel ?? weatherLabel ?? "").replace(/\n/g, " ")}`
                : title,
            );
            marker = new maplibregl.Marker({ element }).setLngLat(coords);
            markers.set(id, marker);
            if (wasOnScreen) marker.addTo(map);
          } else {
            // 캐시 HIT — 위치 갱신 + name/kind 변경 시 title/aria refresh(#500 (a)).
            marker.setLngLat(coords);
            const element = marker.getElement();
            const ariaLabel = priceLabel
              ? `${title} ${priceLabel.replace(/\n/g, " ")}`
              : weatherLabel
                ? `${title} ${weatherLabel.replace(/\n/g, " ")}`
              : title;
            if (element.getAttribute("aria-label") !== ariaLabel) {
              element.title = ariaLabel;
              element.setAttribute("aria-label", ariaLabel);
            }
          }
          // selection outline은 마커 풀을 건드리지 않고 element에만 토글(#500 (c)).
          const element = marker.getElement();
          pointElements.set(featureId, element);
          setSelectedOutline(element, selectedId === featureId);
          next.add(id);
          if (!wasOnScreen) marker.addTo(map);
        }
      }
      for (const id of onScreen) {
        if (!next.has(id)) {
          markers.get(id)?.remove();
          markers.delete(id);
        }
      }
      onScreen = next;
    };

    const scheduleUpdate = () => {
      if (raf !== 0) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        updateMarkers();
      });
    };

    const handleStyleData = () => {
      ensureSource();
    };

    ensureSource();
    map.on("moveend", scheduleUpdate);
    map.on("zoomend", scheduleUpdate);
    map.on("sourcedata", scheduleUpdate);
    map.on("idle", scheduleUpdate);
    map.on("styledata", handleStyleData);
    scheduleUpdate();

    return () => {
      if (raf !== 0) cancelAnimationFrame(raf);
      map.off("moveend", scheduleUpdate);
      map.off("zoomend", scheduleUpdate);
      map.off("sourcedata", scheduleUpdate);
      map.off("idle", scheduleUpdate);
      map.off("styledata", handleStyleData);
      popupRef.current?.remove();
      popupRef.current = null;
      for (const marker of markers.values()) marker.remove();
      markers.clear();
      pointElements.clear();
      onScreen = new Set();
      try {
        if (map.getLayer(`${SRC}-clusters`)) map.removeLayer(`${SRC}-clusters`);
        if (map.getLayer(`${SRC}-points`)) map.removeLayer(`${SRC}-points`);
        if (map.getSource(SRC)) map.removeSource(SRC);
      } catch {
        // 지도가 teardown 중일 수 있다.
      }
    };
    // features 변경은 위 setData effect로 반영하므로 deps는 map 생애만.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  // 선택 변경 시 마커 풀/레이어를 건드리지 않고, 현재 떠 있는 point/label element의
  // outline만 다시 칠한다(#500 (c)). render마다 가벼우므로 deps에 selectedFeatureId만 둔다.
  useEffect(() => {
    for (const [featureId, element] of pointElementsRef.current) {
      setSelectedOutline(element, selectedFeatureId === featureId);
    }
    for (const [featureId, element] of labelElementsRef.current) {
      setSelectedOutline(element, selectedFeatureId === featureId);
    }
  }, [selectedFeatureId]);

  return null;
}
