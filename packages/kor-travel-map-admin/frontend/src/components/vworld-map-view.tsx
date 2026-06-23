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
  lon: number | null;
  lat: number | null;
  marker_icon?: string | null;
  marker_color?: string | null;
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
  clusterRadius = 60,
  clusterMaxZoom = 14,
}: {
  features: ReadonlyArray<ClusterFeatureInput>;
  onSelectFeature?: (featureId: string) => void;
  clusterRadius?: number;
  clusterMaxZoom?: number;
}) {
  const map = useContext(VWorldMapContext);
  const onSelectRef = useRef(onSelectFeature);
  useLayoutEffect(() => {
    onSelectRef.current = onSelectFeature;
  });

  const data = useMemo<GeoJSON.FeatureCollection<GeoJSON.Point>>(
    () => ({
      type: "FeatureCollection",
      features: features.flatMap((f) =>
        typeof f.lon === "number" && typeof f.lat === "number"
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
                  marker_icon: f.marker_icon ?? null,
                  marker_color: f.marker_color ?? null,
                },
              },
            ]
          : [],
      ),
    }),
    [features],
  );

  // source data 갱신 (features prop 변경 시).
  useEffect(() => {
    if (map === null) return;
    const source = map.getSource(CLUSTER_SOURCE_ID) as
      | maplibregl.GeoJSONSource
      | undefined;
    source?.setData(data);
  }, [map, data]);

  // source/layer + 마커 풀 생애주기 (map 1회).
  useEffect(() => {
    if (map === null) return;
    const SRC = CLUSTER_SOURCE_ID;
    const markers = new Map<string, MapLibreMarker>();
    let onScreen = new Set<string>();
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

    const updateMarkers = () => {
      if (!map.getSource(SRC) || !map.isStyleLoaded()) return;
      const next = new Set<string>();
      const seen = new Set<string>();
      const rendered = map.querySourceFeatures(SRC);
      for (const feat of rendered) {
        if (feat.geometry.type !== "Point") continue;
        const coords = feat.geometry.coordinates as [number, number];
        const props = feat.properties ?? {};
        if (props.cluster) {
          const id = `cluster-${String(props.cluster_id)}`;
          if (seen.has(id)) continue;
          seen.add(id);
          let marker = markers.get(id);
          if (marker === undefined) {
            const count = Number(props.point_count) || 0;
            const label = String(props.point_count_abbreviated ?? count);
            const element = createClusterElement(count, label);
            const clusterId = props.cluster_id as number;
            element.addEventListener("click", () => {
              const source = map.getSource(SRC) as maplibregl.GeoJSONSource;
              void source
                .getClusterExpansionZoom(clusterId)
                .then((zoom) => {
                  map.easeTo({ center: coords, zoom });
                })
                .catch(() => {
                  /* 클러스터가 사라졌으면 무시 */
                });
            });
            marker = new maplibregl.Marker({ element }).setLngLat(coords);
            markers.set(id, marker);
          }
          next.add(id);
          if (!onScreen.has(id)) marker.addTo(map);
        } else {
          const featureId = String(props.feature_id);
          const id = `pt-${featureId}`;
          if (seen.has(id)) continue;
          seen.add(id);
          let marker = markers.get(id);
          if (marker === undefined) {
            const element = createMarkerElement({
              markerIcon: (props.marker_icon as string | null) ?? undefined,
              markerColor: (props.marker_color as string | null) ?? undefined,
              size: 24,
              title: `${String(props.name)} (${String(props.kind)})`,
              onClick: () => onSelectRef.current?.(featureId),
            });
            element.setAttribute("role", "button");
            element.setAttribute(
              "aria-label",
              `${String(props.name)} (${String(props.kind)})`,
            );
            marker = new maplibregl.Marker({ element }).setLngLat(coords);
            markers.set(id, marker);
          }
          next.add(id);
          if (!onScreen.has(id)) marker.addTo(map);
        }
      }
      for (const id of onScreen) {
        if (!next.has(id)) markers.get(id)?.remove();
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
    map.on("render", scheduleUpdate);
    map.on("styledata", handleStyleData);

    return () => {
      if (raf !== 0) cancelAnimationFrame(raf);
      map.off("render", scheduleUpdate);
      map.off("styledata", handleStyleData);
      for (const marker of markers.values()) marker.remove();
      markers.clear();
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

  return null;
}
