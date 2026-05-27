"use client";

/**
 * Landing page — 임시 health/version 표시 + Zustand store demo.
 *
 * 본 페이지는 frontend skeleton의 smoke test 역할. 실제 지도 화면 (`/features`
 * 등)은 후속 PR (`features.py` 라우터 + `infra/feature_repo.py` 진입 후).
 */

import { useHealth, useVersion } from "@/api/queries";
import { useMapStore } from "@/state/map";

export default function HomePage() {
  const health = useHealth();
  const version = useVersion();
  const viewport = useMapStore((state) => state.viewport);
  const resetViewport = useMapStore((state) => state.resetViewport);
  const setViewport = useMapStore((state) => state.setViewport);

  return (
    <main style={{ fontFamily: "sans-serif", padding: 24, lineHeight: 1.5 }}>
      <h1>krtour-map debug UI</h1>
      <p>
        본 페이지는 Sprint 2 §2.5 frontend skeleton의 smoke test다. 실제 지도
        화면은 후속 PR (`/features/*` 라우터 + `infra/feature_repo.py` 진입
        후).
      </p>

      <section style={{ marginTop: 24 }}>
        <h2>Backend health</h2>
        {health.isLoading && <p>loading…</p>}
        {health.isError && (
          <p style={{ color: "crimson" }}>
            health 호출 실패: {health.error.message}
          </p>
        )}
        {health.data && (
          <pre>{JSON.stringify(health.data, null, 2)}</pre>
        )}
      </section>

      <section style={{ marginTop: 24 }}>
        <h2>Versions</h2>
        {version.isLoading && <p>loading…</p>}
        {version.isError && (
          <p style={{ color: "crimson" }}>
            version 호출 실패: {version.error.message}
          </p>
        )}
        {version.data && (
          <ul>
            <li>
              <strong>debug_ui</strong>: {version.data.debug_ui}
            </li>
            <li>
              <strong>krtour_map</strong>: {version.data.krtour_map}
            </li>
          </ul>
        )}
      </section>

      <section style={{ marginTop: 24 }}>
        <h2>Map viewport (Zustand demo)</h2>
        <pre>{JSON.stringify(viewport, null, 2)}</pre>
        <button
          type="button"
          onClick={() =>
            setViewport({ lon: viewport.lon + 0.1, lat: viewport.lat + 0.1 })
          }
        >
          미세 이동 (+0.1, +0.1)
        </button>{" "}
        <button type="button" onClick={() => resetViewport()}>
          기본값으로 초기화
        </button>
      </section>
    </main>
  );
}
