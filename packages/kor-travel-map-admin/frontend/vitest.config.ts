import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

// 컴포넌트 테스트(jsdom)는 파일 상단 `// @vitest-environment jsdom` 프래그마로 켠다.
// 순수 함수 테스트는 기본 node 환경을 유지한다. react 플러그인은 TSX 변환,
// tsconfigPaths는 `@/*` alias 해석을 담당한다.
export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    exclude: ["e2e/**", "node_modules/**", "dist/**", ".next/**"],
  },
});
