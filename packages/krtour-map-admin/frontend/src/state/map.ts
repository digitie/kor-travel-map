/**
 * Map viewport Zustand store (ADR-037).
 *
 * map viewport (center / zoom) + 카테고리 filter / 선택된 feature 등 UI 상태.
 * server 상태(features API 응답)는 TanStack Query에서 관리하고 여기서는 UI 만.
 *
 * 한국 본토 중심 기본값 (대전 부근) — 도메인 정합 (ADR-012 좌표 정책).
 */

import { create } from "zustand";

export interface MapViewport {
  lon: number;
  lat: number;
  zoom: number;
}

export type FeatureViewMode = "map" | "table";

interface MapStoreState {
  viewport: MapViewport;
  featureViewMode: FeatureViewMode;
  selectedFeatureId: string | null;
  /** 활성 feature kind. 빈 set이면 전체 표시. */
  activeFeatureKinds: ReadonlySet<string>;
  /** 활성 카테고리 8자리 코드 (PlaceCategoryCode). 빈 set이면 전체 표시. */
  activeCategoryCodes: ReadonlySet<string>;
}

interface MapStoreActions {
  setViewport: (next: Partial<MapViewport>) => void;
  resetViewport: () => void;
  setFeatureViewMode: (mode: FeatureViewMode) => void;
  setSelectedFeatureId: (id: string | null) => void;
  toggleFeatureKind: (kind: string) => void;
  clearFeatureKinds: () => void;
  toggleCategory: (code: string) => void;
  clearCategories: () => void;
}

const DEFAULT_VIEWPORT: MapViewport = {
  // 한국 본토 대략 중심 (대전 근처). ADR-012 좌표 정책에 따라 한국 본토 범위
  // [124, 132] × [33, 39.5] 안에 있는 값.
  lon: 127.5,
  lat: 36.5,
  zoom: 6.5,
};

export const useMapStore = create<MapStoreState & MapStoreActions>((set) => ({
  viewport: DEFAULT_VIEWPORT,
  featureViewMode: "map",
  selectedFeatureId: null,
  activeFeatureKinds: new Set<string>(),
  activeCategoryCodes: new Set<string>(),

  setViewport: (next) =>
    set((state) => ({
      viewport: { ...state.viewport, ...next },
    })),

  resetViewport: () => set({ viewport: DEFAULT_VIEWPORT }),

  setFeatureViewMode: (mode) => set({ featureViewMode: mode }),

  setSelectedFeatureId: (id) => set({ selectedFeatureId: id }),

  toggleFeatureKind: (kind) =>
    set((state) => {
      const next = new Set(state.activeFeatureKinds);
      if (next.has(kind)) {
        next.delete(kind);
      } else {
        next.add(kind);
      }
      return { activeFeatureKinds: next };
    }),

  clearFeatureKinds: () => set({ activeFeatureKinds: new Set<string>() }),

  toggleCategory: (code) =>
    set((state) => {
      const next = new Set(state.activeCategoryCodes);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return { activeCategoryCodes: next };
    }),

  clearCategories: () => set({ activeCategoryCodes: new Set<string>() }),
}));

export { DEFAULT_VIEWPORT };
