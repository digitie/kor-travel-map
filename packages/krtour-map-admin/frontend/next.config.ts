import type { NextConfig } from "next";
import path from "node:path";

const workspaceRoot = path.resolve(process.cwd(), "../../..");

/**
 * Next.js config for krtour-map-admin-frontend.
 *
 * ADR 참조:
 * - ADR-025: Next.js + maplibre-vworld
 * - ADR-029 → ADR-043: @krtour/map-marker-react는 workspace 내부 share (private:true).
 * - ADR-035: 운영 시 Cloudflare Tunnel/SSO 뒤에 둠 (코드에 인증 X).
 *
 * 운영 옵션 A (standalone): 8610 포트로 직접 listen. backend(8087) 별도.
 * 운영 옵션 B (FastAPI proxy): basePath를 `/ui`로 두고 FastAPI가 reverse proxy.
 *   현재는 옵션 A 기본 — basePath 미설정.
 */
const config: NextConfig = {
  reactStrictMode: true,

  // Next.js 16 production build uses Turbopack by default. In this npm
  // workspace, set the repo root explicitly so Turbopack can resolve the
  // hoisted `next` package from root node_modules.
  turbopack: {
    root: workspaceRoot,
  },

  // monorepo workspace의 @krtour/map-marker-react (ADR-029, ADR-043 — private:
  // true, registry 게시 X)를 transpile.
  transpilePackages: ["@krtour/map-marker-react"],

  // 디버그 UI는 내부망 전용 (ADR-005 + ADR-020 + ADR-035 admin 확장) — telemetry
  // 무의미.
  productionBrowserSourceMaps: false,
  poweredByHeader: false,
};

export default config;
