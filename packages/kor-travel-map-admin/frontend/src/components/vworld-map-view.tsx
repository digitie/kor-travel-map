"use client";

import { createMarkerElement } from "@kor-travel-map/map-marker-react";
import maplibregl, {
  type Map as MapLibreMap,
  type Marker as MapLibreMarker,
} from "maplibre-gl";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
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
  onLoad,
  onMoveEnd,
  onError,
}: VWorldMapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const appliedStyleRef = useRef({ apiKey, layerType });
  const onLoadRef = useRef(onLoad);
  const onMoveEndRef = useRef(onMoveEnd);
  const onErrorRef = useRef(onError);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [loaded, setLoaded] = useState(false);

  useLayoutEffect(() => {
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
    nextMap.on("moveend", handleMoveEnd);
    nextMap.on("error", handleError);
    loadFrame = requestAnimationFrame(() => {
      notifyLoad();
    });

    let resizeFrame = 0;
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
      resizeObserver?.disconnect();
      nextMap.off("load", handleLoad);
      nextMap.off("idle", handleLoad);
      nextMap.off("moveend", handleMoveEnd);
      nextMap.off("error", handleError);
      for (const control of controls) {
        try {
          nextMap.removeControl(control);
        } catch {
          // MapLibre may already be tearing down the control while removing the map.
        }
      }
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
        style={style}
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
  const onClickRef = useRef(onClick);
  const clickable = onClick !== undefined;

  useLayoutEffect(() => {
    onClickRef.current = onClick;
  });

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
    if (selected) {
      element.style.outline = "3px solid hsl(var(--primary))";
      element.style.outlineOffset = "2px";
    }

    const marker = new maplibregl.Marker({ element })
      .setLngLat(lngLat)
      .addTo(map);
    markerRef.current = marker;

    return () => {
      marker.remove();
      markerRef.current = null;
    };
  }, [clickable, map, lngLat, markerIcon, markerColor, selected, size, title]);

  return null;
}
