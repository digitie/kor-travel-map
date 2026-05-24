// Vite library mode config for @krtour/map-marker-react (ADR-029).
// 코드 작성 단계 진입 시 본 skeleton을 기반으로 src/ 구현.

import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      name: "KrtourMapMarkerReact",
      formats: ["es", "cjs"],
      fileName: (format) => `index.${format}.js`,
    },
    rollupOptions: {
      // peer deps은 번들 제외 — 호스트(debug UI / TripMate)가 제공
      external: ["react", "react-dom", "maplibre-gl", "maplibre-vworld"],
      output: {
        globals: {
          react: "React",
          "react-dom": "ReactDOM",
          "maplibre-gl": "maplibregl",
          "maplibre-vworld": "MaplibreVworld",
        },
      },
    },
    sourcemap: true,
  },
});
