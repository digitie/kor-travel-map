/**
 * Next.js config for krtour-map-debug-ui frontend (ADR-025 + 사용자 보강 2026-05-25).
 * 코드 작성 단계 진입 시 본 skeleton을 기반으로 확장.
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  // React 19 strict 모드
  reactStrictMode: true,

  // 운영 옵션 (CHANGEME: 운영 정책 결정 후 활성화)
  //   - output: 'standalone' — FastAPI와 별도 포트 운영 (default)
  //   - output: 'export'     — static build → FastAPI static mount
  //   - basePath: '/ui'      — FastAPI reverse proxy 시
  // output: 'standalone',

  // backend(FastAPI) reverse proxy를 통해 same-origin 호출하려면 활성화:
  // async rewrites() {
  //   return [
  //     {
  //       source: '/api/:path*',
  //       destination: `${process.env.NEXT_PUBLIC_KRTOUR_MAP_DEBUG_UI_API}/:path*`,
  //     },
  //   ];
  // },

  // monorepo workspace의 @krtour/map-marker-react (ADR-029)를 transpile
  transpilePackages: ['@krtour/map-marker-react'],

  // 디버그 UI는 내부망 전용 (ADR-005 + ADR-020) — telemetry 무의미
  productionBrowserSourceMaps: false,
};

module.exports = nextConfig;
