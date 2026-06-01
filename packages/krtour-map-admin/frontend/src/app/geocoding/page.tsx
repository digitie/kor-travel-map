"use client";

/**
 * `/geocoding` — kraddr-geo 디버그 인터랙티브 페이지 (PR#102).
 *
 * backend `/debug/geocoding/{health,reverse,geocode}` (+/raw)을 form으로 호출해
 * 결과 `Address`/`Coordinate`/raw 응답을 직접 확인. base_url 미설정이면 health
 * 카드에 503 상태가 보이고 호출 버튼 비활성.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import {
  fetchGeocode,
  fetchGeocodeRaw,
  fetchGeocodingHealth,
  fetchReverse,
  fetchReverseRaw,
  type GeocodeParams,
  type GeocodingHealthResponse,
  type ReverseGeocodingParams,
} from "@/api/geocoding";

import { RegionsWithinRadiusSection } from "./regions-within-radius-section";

function HealthCard({ health }: { health: GeocodingHealthResponse | undefined }) {
  if (!health) {
    return <p style={{ color: "#6b7280" }}>upstream health 확인 중…</p>;
  }
  const bg = health.reachable ? "#dcfce7" : "#fee2e2";
  const fg = health.reachable ? "#166534" : "#991b1b";
  return (
    <div
      data-testid="geocoding-health"
      style={{
        background: bg,
        color: fg,
        padding: "6px 10px",
        borderRadius: 6,
        fontSize: 13,
      }}
    >
      <strong>kraddr-geo:</strong>{" "}
      {health.reachable ? "reachable" : "unreachable"}{" "}
      {health.base_url && (
        <code style={{ background: "rgba(0,0,0,0.05)", padding: "0 4px" }}>
          {health.base_url}
        </code>
      )}{" "}
      {health.upstream_status !== null && (
        <span>(upstream HTTP {health.upstream_status})</span>
      )}
      {health.detail && (
        <span style={{ marginLeft: 8 }}>: {health.detail}</span>
      )}
    </div>
  );
}

export default function GeocodingPage() {
  const healthQuery = useQuery({
    queryKey: ["geocoding-health"],
    queryFn: fetchGeocodingHealth,
    refetchInterval: 30_000,
  });

  // ── reverse form ──────────────────────────────────────────────────────
  const [revLon, setRevLon] = useState("126.9779");
  const [revLat, setRevLat] = useState("37.5663");
  const [revType, setRevType] = useState<"both" | "road" | "parcel">("both");
  const [revRadius, setRevRadius] = useState("");
  const [revRaw, setRevRaw] = useState(false);

  const reverseMutation = useMutation({
    mutationFn: async () => {
      const params: ReverseGeocodingParams = {
        lon: Number(revLon),
        lat: Number(revLat),
        type: revType,
        ...(revRadius ? { radius_m: Number(revRadius) } : {}),
      };
      if (revRaw) return fetchReverseRaw(params);
      return fetchReverse(params);
    },
  });

  // ── geocode form ──────────────────────────────────────────────────────
  const [geoAddress, setGeoAddress] = useState("서울특별시 중구 세종대로 110");
  const [geoType, setGeoType] = useState<"road" | "parcel">("road");
  const [geoFallback, setGeoFallback] = useState<"off" | "local_only" | "api">(
    "local_only",
  );
  const [geoRaw, setGeoRaw] = useState(false);

  const geocodeMutation = useMutation({
    mutationFn: async () => {
      const params: GeocodeParams = {
        address: geoAddress,
        type: geoType,
        fallback: geoFallback,
      };
      if (geoRaw) return fetchGeocodeRaw(params);
      return fetchGeocode(params);
    },
  });

  const disabled = !healthQuery.data?.reachable;

  return (
    <main style={{ fontFamily: "sans-serif", padding: 24, lineHeight: 1.5 }}>
      <header style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <h1 style={{ margin: 0, fontSize: 18 }}>kraddr-geo 디버그</h1>
        <Link href="/" style={{ marginLeft: "auto", fontSize: 14 }}>
          ← 홈
        </Link>
      </header>

      <section style={{ marginTop: 12 }}>
        <HealthCard health={healthQuery.data} />
        {healthQuery.isError && (
          <p style={{ color: "crimson", fontSize: 13 }}>
            health 호출 실패: {healthQuery.error.message}
          </p>
        )}
      </section>

      {/* Reverse */}
      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>1) Reverse: 좌표 → 주소</h2>
        <form
          data-testid="reverse-form"
          onSubmit={(e) => {
            e.preventDefault();
            reverseMutation.mutate();
          }}
          style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}
        >
          <label>
            lon
            <input
              type="text"
              value={revLon}
              onChange={(e) => setRevLon(e.target.value)}
              style={{ display: "block", padding: "4px 6px", width: 110 }}
            />
          </label>
          <label>
            lat
            <input
              type="text"
              value={revLat}
              onChange={(e) => setRevLat(e.target.value)}
              style={{ display: "block", padding: "4px 6px", width: 110 }}
            />
          </label>
          <label>
            type
            <select
              value={revType}
              onChange={(e) =>
                setRevType(e.target.value as "both" | "road" | "parcel")
              }
              style={{ display: "block", padding: "4px 6px" }}
            >
              <option value="both">both</option>
              <option value="road">road</option>
              <option value="parcel">parcel</option>
            </select>
          </label>
          <label>
            radius_m
            <input
              type="number"
              min={1}
              max={2000}
              value={revRadius}
              onChange={(e) => setRevRadius(e.target.value)}
              placeholder="default 200"
              style={{ display: "block", padding: "4px 6px", width: 100 }}
            />
          </label>
          <label style={{ fontSize: 13 }}>
            <input
              type="checkbox"
              checked={revRaw}
              onChange={(e) => setRevRaw(e.target.checked)}
            />{" "}
            raw
          </label>
          <button
            type="submit"
            disabled={disabled || reverseMutation.isPending}
            style={{ padding: "6px 14px" }}
          >
            {reverseMutation.isPending ? "조회 중..." : "Reverse 실행"}
          </button>
        </form>
        {reverseMutation.isError && (
          <p style={{ color: "crimson", fontSize: 13 }}>
            오류: {reverseMutation.error.message}
          </p>
        )}
        {reverseMutation.data && (
          <pre
            data-testid="reverse-result"
            style={{
              background: "#f5f5f5",
              padding: 12,
              marginTop: 12,
              maxHeight: 400,
              overflow: "auto",
            }}
          >
            {JSON.stringify(reverseMutation.data, null, 2)}
          </pre>
        )}
      </section>

      {/* Geocode */}
      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>2) Geocode: 주소 → 좌표</h2>
        <form
          data-testid="geocode-form"
          onSubmit={(e) => {
            e.preventDefault();
            geocodeMutation.mutate();
          }}
          style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}
        >
          <label style={{ flex: 1, minWidth: 280 }}>
            address
            <input
              type="text"
              value={geoAddress}
              onChange={(e) => setGeoAddress(e.target.value)}
              style={{ display: "block", padding: "4px 6px", width: "100%" }}
            />
          </label>
          <label>
            type
            <select
              value={geoType}
              onChange={(e) => setGeoType(e.target.value as "road" | "parcel")}
              style={{ display: "block", padding: "4px 6px" }}
            >
              <option value="road">road</option>
              <option value="parcel">parcel</option>
            </select>
          </label>
          <label>
            fallback
            <select
              value={geoFallback}
              onChange={(e) =>
                setGeoFallback(
                  e.target.value as "off" | "local_only" | "api",
                )
              }
              style={{ display: "block", padding: "4px 6px" }}
            >
              <option value="off">off</option>
              <option value="local_only">local_only</option>
              <option value="api">api</option>
            </select>
          </label>
          <label style={{ fontSize: 13 }}>
            <input
              type="checkbox"
              checked={geoRaw}
              onChange={(e) => setGeoRaw(e.target.checked)}
            />{" "}
            raw
          </label>
          <button
            type="submit"
            disabled={disabled || !geoAddress || geocodeMutation.isPending}
            style={{ padding: "6px 14px" }}
          >
            {geocodeMutation.isPending ? "조회 중..." : "Geocode 실행"}
          </button>
        </form>
        {geocodeMutation.isError && (
          <p style={{ color: "crimson", fontSize: 13 }}>
            오류: {geocodeMutation.error.message}
          </p>
        )}
        {geocodeMutation.data && (
          <pre
            data-testid="geocode-result"
            style={{
              background: "#f5f5f5",
              padding: 12,
              marginTop: 12,
              maxHeight: 400,
              overflow: "auto",
            }}
          >
            {JSON.stringify(geocodeMutation.data, null, 2)}
          </pre>
        )}
      </section>

      <RegionsWithinRadiusSection disabled={disabled} />
    </main>
  );
}
