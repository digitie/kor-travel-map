"use client";

/**
 * /etl — ETL preview 화면 (PR#44).
 *
 * provider/dataset 선택 → "Preview" 버튼 → backend `/debug/etl/*/preview`
 * 호출 → 변환 결과 JSON 표시. 적재(DB write) 없음.
 *
 * 실제 provider client 호출(`source=live`)은 후속 PR — 본 페이지는 fixture
 * 모드만 동작 (live 선택 시 backend 501 응답).
 */

import { useState } from "react";

import { useEtlPreviewMutation, useProviders } from "@/api/etl";

export default function EtlPreviewPage() {
  const providersQuery = useProviders();
  const previewMutation = useEtlPreviewMutation();

  const [provider, setProvider] = useState<string>("");
  const [dataset, setDataset] = useState<string>("");
  const [source, setSource] = useState<"fixture" | "live">("fixture");

  const datasets =
    providersQuery.data?.providers.find((p) => p.provider === provider)
      ?.datasets ?? [];

  const handleRun = () => {
    if (!provider || !dataset) return;
    previewMutation.mutate({ provider, dataset, source });
  };

  return (
    <main style={{ fontFamily: "sans-serif", padding: 24, lineHeight: 1.5 }}>
      <h1>ETL preview</h1>
      <p>
        provider 변환 함수의 출력을 fixture로 미리 본다 (적재 없음, DB write
        없음). live source는 후속 PR.
      </p>

      <section style={{ marginTop: 24 }}>
        <h2>1) provider / dataset 선택</h2>
        {providersQuery.isLoading && <p>loading providers…</p>}
        {providersQuery.isError && (
          <p style={{ color: "crimson" }}>
            providers 호출 실패: {providersQuery.error.message}
          </p>
        )}
        {providersQuery.data && (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <label>
              provider
              <select
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value);
                  setDataset("");
                }}
                style={{ marginLeft: 8 }}
              >
                <option value="">— 선택 —</option>
                {providersQuery.data.providers.map((p) => (
                  <option key={p.provider} value={p.provider}>
                    {p.provider} ({p.datasets.length} dataset)
                  </option>
                ))}
              </select>
            </label>

            <label>
              dataset
              <select
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
                disabled={!provider}
                style={{ marginLeft: 8 }}
              >
                <option value="">— 선택 —</option>
                {datasets.map((d) => (
                  <option key={d.dataset} value={d.dataset}>
                    {d.dataset} [{d.variant}]
                  </option>
                ))}
              </select>
            </label>

            <label>
              source
              <select
                value={source}
                onChange={(e) =>
                  setSource(e.target.value as "fixture" | "live")
                }
                style={{ marginLeft: 8 }}
              >
                <option value="fixture">fixture (offline demo)</option>
                <option value="live">live (provider client, 미구현)</option>
              </select>
            </label>

            <button
              type="button"
              onClick={handleRun}
              disabled={!provider || !dataset || previewMutation.isPending}
            >
              Preview 실행
            </button>
          </div>
        )}
      </section>

      <section style={{ marginTop: 24 }}>
        <h2>2) 변환 결과</h2>
        {previewMutation.isPending && <p>running…</p>}
        {previewMutation.isError && (
          <p style={{ color: "crimson" }}>
            preview 실패: {previewMutation.error.message}
          </p>
        )}
        {previewMutation.data && (
          <div>
            <p>
              <strong>{previewMutation.data.provider}</strong> /{" "}
              {previewMutation.data.dataset} — variant{" "}
              <code>{previewMutation.data.variant}</code>, source{" "}
              <code>{previewMutation.data.source}</code>, count{" "}
              {previewMutation.data.count}
            </p>
            <pre
              style={{
                background: "#f5f5f5",
                padding: 12,
                maxHeight: 600,
                overflow: "auto",
              }}
            >
              {JSON.stringify(previewMutation.data.items, null, 2)}
            </pre>
          </div>
        )}
      </section>
    </main>
  );
}
