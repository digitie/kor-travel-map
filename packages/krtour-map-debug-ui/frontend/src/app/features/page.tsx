"use client";

/**
 * `/features` — feature 지도 화면 (ADR-025/043, PR#95+).
 *
 * maplibre-gl 캔버스 + Zustand viewport + react-query로 backend `/features`
 * bbox API를 호출해 marker 렌더. VWorld 타일은 `NEXT_PUBLIC_VWORLD_API_KEY`가
 * 설정돼 있으면 사용, 없으면 회색 배경으로 fallback(캔버스/마커 동작은 유지).
 *
 * 단순 maplibre Marker로 시작 — 카테고리 maki 아이콘(@krtour/map-marker-react)
 * 통합은 후속.
 */

import maplibregl, { LngLatBounds, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";

import { useFeaturesInBbox, type FeatureSummary } from "@/api/features";
import { useMapStore } from "@/state/map";

const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

function buildStyle(): StyleSpecification {
  if (VWORLD_KEY && VWORLD_KEY !== "CHANGE_ME") {
    return {
      version: 8,
      sources: {
        vworld: {
          type: "raster",
          tiles: [
            `https://api.vworld.kr/req/wmts/1.0.0/${VWORLD_KEY}/Base/{z}/{y}/{x}.png`,
          ],
          tileSize: 256,
          attribution: "© VWorld",
        },
      },
      layers: [{ id: "vworld-base", type: "raster", source: "vworld" }],
    };
  }
  // VWorld 키 없으면 회색 배경으로 fallback — 캔버스/마커는 정상 동작.
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: "bg",
        type: "background",
        paint: { "background-color": "#e8eaed" },
      },
    ],
  };
}

interface Bbox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
}

function boundsToBbox(b: LngLatBounds): Bbox {
  return {
    min_lon: b.getWest(),
    min_lat: b.getSouth(),
    max_lon: b.getEast(),
    max_lat: b.getNorth(),
  };
}

export default function FeaturesPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerLayerRef = useRef<maplibregl.Marker[]>([]);

  const viewport = useMapStore((s) => s.viewport);
  const setViewport = useMapStore((s) => s.setViewport);
  const setSelectedFeatureId = useMapStore((s) => s.setSelectedFeatureId);

  const [bbox, setBbox] = useState<Bbox | null>(null);

  const featuresQuery = useFeaturesInBbox(
    bbox ?? { min_lon: 0, min_lat: 0, max_lon: 0, max_lat: 0 },
    { enabled: bbox !== null },
  );

  // maplibre Map 초기화 (mount 1회).
  useEffect(() => {
    if (containerRef.current === null) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: [viewport.lon, viewport.lat],
      zoom: viewport.zoom,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    const updateBbox = () => {
      const center = map.getCenter();
      setViewport({
        lon: center.lng,
        lat: center.lat,
        zoom: map.getZoom(),
      });
      setBbox(boundsToBbox(map.getBounds()));
    };
    map.on("load", updateBbox);
    map.on("moveend", updateBbox);

    return () => {
      for (const m of markerLayerRef.current) m.remove();
      markerLayerRef.current = [];
      map.remove();
      mapRef.current = null;
    };
    // viewport는 초기값으로만 사용 — 이후엔 map이 source of truth.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 응답이 갱신될 때 marker 재배치.
  useEffect(() => {
    if (mapRef.current === null) return;
    const data: FeatureSummary[] = featuresQuery.data?.items ?? [];
    for (const m of markerLayerRef.current) m.remove();
    markerLayerRef.current = [];
    for (const f of data) {
      if (f.lon === null || f.lat === null) continue;
      const el = document.createElement("div");
      el.style.width = "12px";
      el.style.height = "12px";
      el.style.borderRadius = "50%";
      el.style.background = f.marker_color ?? "#3b82f6";
      el.style.border = "2px solid white";
      el.style.boxShadow = "0 1px 4px rgba(0,0,0,0.3)";
      el.style.cursor = "pointer";
      el.title = `${f.name} (${f.kind})`;
      el.addEventListener("click", () => setSelectedFeatureId(f.feature_id));
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([f.lon, f.lat])
        .addTo(mapRef.current!);
      markerLayerRef.current.push(marker);
    }
  }, [featuresQuery.data, setSelectedFeatureId]);

  const status = useMemo(() => {
    if (!bbox) return "지도 로딩 중…";
    if (featuresQuery.isLoading) return "feature 로딩 중…";
    if (featuresQuery.isError) {
      return `feature 호출 실패: ${featuresQuery.error.message}`;
    }
    return `${featuresQuery.data?.count ?? 0}건 표시 (DB 적재 분)`;
  }, [bbox, featuresQuery]);

  return (
    <main
      style={{
        fontFamily: "sans-serif",
        padding: 0,
        margin: 0,
        height: "100vh",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <header
        style={{
          padding: "12px 24px",
          borderBottom: "1px solid #e5e7eb",
          display: "flex",
          alignItems: "baseline",
          gap: 16,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 18 }}>Feature 지도</h1>
        <span style={{ color: "#6b7280", fontSize: 14 }}>{status}</span>
        <a href="/" style={{ marginLeft: "auto", fontSize: 14 }}>
          ← 홈
        </a>
      </header>
      <div
        ref={containerRef}
        data-testid="map-canvas-container"
        style={{ flex: 1, minHeight: 0, width: "100%" }}
      />
      {!VWORLD_KEY || VWORLD_KEY === "CHANGE_ME" ? (
        <footer
          style={{
            padding: "6px 24px",
            background: "#fef3c7",
            fontSize: 12,
            color: "#92400e",
            borderTop: "1px solid #f59e0b",
          }}
        >
          NEXT_PUBLIC_VWORLD_API_KEY 미설정 — 타일 미표시(회색 배경). 마커는 정상 동작.
        </footer>
      ) : null}
    </main>
  );
}
