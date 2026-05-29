"use client";

/**
 * `/features` — feature 지도 화면 (ADR-025/043, PR#95+).
 *
 * maplibre-gl 캔버스 + Zustand viewport + react-query로 backend `/features`
 * bbox API를 호출해 marker 렌더 + kind 필터 + 선택 feature 상세 패널.
 * 카테고리 maki/색 매핑은 `@krtour/map-marker-react`(ADR-029/043).
 *
 * VWorld 타일은 `NEXT_PUBLIC_VWORLD_API_KEY`가 설정돼 있으면 사용, 없으면 회색
 * 배경으로 fallback(캔버스/마커 동작은 유지).
 */

import { createMarkerElement } from "@krtour/map-marker-react";
import maplibregl, { LngLatBounds, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  FEATURE_KINDS,
  useFeatureDetail,
  useFeaturesInBbox,
  type FeatureKind,
  type FeatureSummary,
} from "@/api/features";
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
  const selectedFeatureId = useMapStore((s) => s.selectedFeatureId);
  const setSelectedFeatureId = useMapStore((s) => s.setSelectedFeatureId);

  const [bbox, setBbox] = useState<Bbox | null>(null);
  // kind 필터 — 빈 배열은 "전체 표시"(API에 kind 미지정).
  const [kindFilter, setKindFilter] = useState<FeatureKind[]>([]);

  const featuresQuery = useFeaturesInBbox(
    {
      ...(bbox ?? { min_lon: 0, min_lat: 0, max_lon: 0, max_lat: 0 }),
      kinds: kindFilter.length > 0 ? kindFilter : undefined,
    },
    { enabled: bbox !== null },
  );
  const detailQuery = useFeatureDetail(selectedFeatureId);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 응답이 갱신될 때 marker 재배치 (공통 createMarkerElement 사용).
  useEffect(() => {
    if (mapRef.current === null) return;
    const data: FeatureSummary[] = featuresQuery.data?.items ?? [];
    for (const m of markerLayerRef.current) m.remove();
    markerLayerRef.current = [];
    for (const f of data) {
      if (f.lon === null || f.lat === null) continue;
      const el = createMarkerElement({
        markerIcon: f.marker_icon,
        markerColor: f.marker_color,
        size: 24,
        title: `${f.name} (${f.kind})`,
        onClick: () => setSelectedFeatureId(f.feature_id),
      });
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

  const toggleKind = (k: FeatureKind) => {
    setKindFilter((prev) =>
      prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k],
    );
  };

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
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <h1 style={{ margin: 0, fontSize: 18 }}>Feature 지도</h1>
        <span style={{ color: "#6b7280", fontSize: 14 }}>{status}</span>
        <div
          role="group"
          aria-label="kind 필터"
          data-testid="kind-filter"
          style={{ display: "flex", gap: 6, flexWrap: "wrap" }}
        >
          {FEATURE_KINDS.map((k) => {
            const active = kindFilter.includes(k);
            return (
              <button
                key={k}
                type="button"
                onClick={() => toggleKind(k)}
                aria-pressed={active}
                style={{
                  fontSize: 12,
                  padding: "4px 10px",
                  borderRadius: 999,
                  border: active ? "1px solid #1f77b4" : "1px solid #d1d5db",
                  background: active ? "#dbeafe" : "white",
                  color: active ? "#1e40af" : "#374151",
                  cursor: "pointer",
                }}
              >
                {k}
              </button>
            );
          })}
          {kindFilter.length > 0 && (
            <button
              type="button"
              onClick={() => setKindFilter([])}
              style={{
                fontSize: 12,
                padding: "4px 8px",
                borderRadius: 999,
                border: "1px dashed #9ca3af",
                background: "transparent",
                color: "#6b7280",
                cursor: "pointer",
              }}
            >
              초기화
            </button>
          )}
        </div>
        <a href="/" style={{ marginLeft: "auto", fontSize: 14 }}>
          ← 홈
        </a>
      </header>
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
        <div
          ref={containerRef}
          data-testid="map-canvas-container"
          style={{ position: "absolute", inset: 0 }}
        />
        {selectedFeatureId && (
          <aside
            data-testid="feature-detail-panel"
            style={{
              position: "absolute",
              right: 12,
              top: 12,
              bottom: 12,
              width: 360,
              maxWidth: "40vw",
              background: "white",
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
              overflow: "auto",
              padding: 16,
              fontSize: 13,
            }}
          >
            <header
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 8,
                marginBottom: 8,
              }}
            >
              <strong style={{ fontSize: 14 }}>선택 Feature</strong>
              <span style={{ color: "#6b7280", fontSize: 12 }}>
                {selectedFeatureId}
              </span>
              <button
                type="button"
                aria-label="닫기"
                onClick={() => setSelectedFeatureId(null)}
                style={{
                  marginLeft: "auto",
                  border: "none",
                  background: "transparent",
                  cursor: "pointer",
                  fontSize: 16,
                  color: "#6b7280",
                }}
              >
                ×
              </button>
            </header>
            {detailQuery.isLoading && <p>로딩 중…</p>}
            {detailQuery.isError && (
              <p style={{ color: "crimson" }}>
                상세 호출 실패: {detailQuery.error.message}
              </p>
            )}
            {detailQuery.data && (
              <div>
                <h2 style={{ fontSize: 16, marginTop: 0 }}>
                  {detailQuery.data.name}
                </h2>
                <dl
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr",
                    gap: "4px 12px",
                    margin: 0,
                  }}
                >
                  <dt style={{ color: "#6b7280" }}>kind</dt>
                  <dd style={{ margin: 0 }}>{detailQuery.data.kind}</dd>
                  <dt style={{ color: "#6b7280" }}>category</dt>
                  <dd style={{ margin: 0 }}>{detailQuery.data.category}</dd>
                  <dt style={{ color: "#6b7280" }}>status</dt>
                  <dd style={{ margin: 0 }}>{detailQuery.data.status}</dd>
                  {detailQuery.data.lon !== null && detailQuery.data.lat !== null && (
                    <>
                      <dt style={{ color: "#6b7280" }}>coord</dt>
                      <dd style={{ margin: 0 }}>
                        {detailQuery.data.lon.toFixed(5)}, {detailQuery.data.lat.toFixed(5)}
                      </dd>
                    </>
                  )}
                </dl>
                <details style={{ marginTop: 12 }}>
                  <summary>address</summary>
                  <pre style={{ background: "#f5f5f5", padding: 8 }}>
                    {JSON.stringify(detailQuery.data.address, null, 2)}
                  </pre>
                </details>
                <details>
                  <summary>detail</summary>
                  <pre style={{ background: "#f5f5f5", padding: 8 }}>
                    {JSON.stringify(detailQuery.data.detail, null, 2)}
                  </pre>
                </details>
                <details>
                  <summary>urls</summary>
                  <pre style={{ background: "#f5f5f5", padding: 8 }}>
                    {JSON.stringify(detailQuery.data.urls, null, 2)}
                  </pre>
                </details>
              </div>
            )}
          </aside>
        )}
      </div>
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
