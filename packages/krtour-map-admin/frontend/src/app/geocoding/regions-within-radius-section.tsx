"use client";

import { useReducer } from "react";

import {
  fetchRegionsWithinRadius,
  fetchRegionsWithinRadiusRaw,
  type RegionLevel,
  type RegionsWithinRadiusParams,
} from "@/api/geocoding";

const REGION_LEVELS: readonly RegionLevel[] = ["sido", "sigungu", "emd"];

interface RegionState {
  lon: string;
  lat: string;
  radiusKm: string;
  levels: RegionLevel[];
  raw: boolean;
  pending: boolean;
  error: string | null;
  data: Record<string, unknown> | null;
}

type RegionAction =
  | { type: "setLon"; value: string }
  | { type: "setLat"; value: string }
  | { type: "setRadiusKm"; value: string }
  | { type: "toggleLevel"; value: RegionLevel }
  | { type: "setRaw"; value: boolean }
  | { type: "request" }
  | { type: "success"; value: Record<string, unknown> }
  | { type: "failure"; value: string };

const INITIAL_STATE: RegionState = {
  lon: "126.978",
  lat: "37.5665",
  radiusKm: "3",
  levels: ["sigungu", "emd"],
  raw: false,
  pending: false,
  error: null,
  data: null,
};

function reducer(state: RegionState, action: RegionAction): RegionState {
  switch (action.type) {
    case "setLon":
      return { ...state, lon: action.value };
    case "setLat":
      return { ...state, lat: action.value };
    case "setRadiusKm":
      return { ...state, radiusKm: action.value };
    case "toggleLevel":
      return {
        ...state,
        levels: state.levels.includes(action.value)
          ? state.levels.filter((x) => x !== action.value)
          : [...state.levels, action.value],
      };
    case "setRaw":
      return { ...state, raw: action.value };
    case "request":
      return { ...state, pending: true, error: null };
    case "success":
      return { ...state, pending: false, data: action.value };
    case "failure":
      return { ...state, pending: false, error: action.value };
  }
}

export function RegionsWithinRadiusSection({ disabled }: { disabled: boolean }) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  const run = async () => {
    const params: RegionsWithinRadiusParams = {
      lon: Number(state.lon),
      lat: Number(state.lat),
      radius_km: Number(state.radiusKm),
      levels: state.levels,
    };
    dispatch({ type: "request" });
    try {
      const result = state.raw
        ? await fetchRegionsWithinRadiusRaw(params)
        : await fetchRegionsWithinRadius(params);
      dispatch({
        type: "success",
        value: result as unknown as Record<string, unknown>,
      });
    } catch (exc) {
      dispatch({
        type: "failure",
        value: exc instanceof Error ? exc.message : String(exc),
      });
    }
  };

  return (
    <section data-testid="regions-form" style={{ marginTop: 24 }}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>
        3) Regions within radius: POI 반경 행정구역
      </h2>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <label>
          lon
          <input
            type="text"
            value={state.lon}
            onChange={(e) =>
              dispatch({ type: "setLon", value: e.target.value })
            }
            style={{ display: "block", padding: "4px 6px", width: 110 }}
          />
        </label>
        <label>
          lat
          <input
            type="text"
            value={state.lat}
            onChange={(e) =>
              dispatch({ type: "setLat", value: e.target.value })
            }
            style={{ display: "block", padding: "4px 6px", width: 110 }}
          />
        </label>
        <label>
          radius_km
          <input
            type="number"
            min={0.1}
            max={100}
            step={0.1}
            value={state.radiusKm}
            onChange={(e) =>
              dispatch({ type: "setRadiusKm", value: e.target.value })
            }
            style={{ display: "block", padding: "4px 6px", width: 110 }}
          />
        </label>
        <fieldset
          style={{
            display: "flex",
            gap: 8,
            border: "1px solid #d1d5db",
            padding: "4px 8px",
            margin: 0,
          }}
        >
          <legend style={{ fontSize: 12, color: "#6b7280" }}>level</legend>
          {REGION_LEVELS.map((level) => (
            <label key={level} style={{ fontSize: 13 }}>
              <input
                type="checkbox"
                checked={state.levels.includes(level)}
                onChange={() => dispatch({ type: "toggleLevel", value: level })}
              />{" "}
              {level}
            </label>
          ))}
        </fieldset>
        <label style={{ fontSize: 13 }}>
          <input
            type="checkbox"
            checked={state.raw}
            onChange={(e) =>
              dispatch({ type: "setRaw", value: e.target.checked })
            }
          />{" "}
          raw
        </label>
        <button
          type="button"
          disabled={
            disabled ||
            state.pending ||
            !state.radiusKm ||
            state.levels.length === 0
          }
          onClick={() => void run()}
          style={{ padding: "6px 14px" }}
        >
          {state.pending ? "조회 중..." : "Regions 실행"}
        </button>
      </div>
      {state.error && (
        <p style={{ color: "crimson", fontSize: 13 }}>오류: {state.error}</p>
      )}
      {state.data && (
        <pre
          data-testid="regions-result"
          style={{
            background: "#f5f5f5",
            padding: 12,
            marginTop: 12,
            maxHeight: 400,
            overflow: "auto",
          }}
        >
          {JSON.stringify(state.data, null, 2)}
        </pre>
      )}
    </section>
  );
}
