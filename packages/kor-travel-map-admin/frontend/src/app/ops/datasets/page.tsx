import type { Metadata } from "next";

import { DatasetsClient } from "./datasets-client";

export const metadata: Metadata = {
  title: "데이터셋 | kor-travel-map admin",
};

function firstParam(value: string | string[] | undefined): string | null {
  return (Array.isArray(value) ? value[0] : value) ?? null;
}

/**
 * `/ops/datasets` — 페이지 ② (ADR-064 T-ADM-C4).
 *
 * 딥링크: `?provider=&dataset=&sync_scope=&panel=policy|preview|history` —
 * searchParams는 초기 선택/탭 상태로만 쓴다(뒤로가기 URL 동기화 없음).
 */
export default async function OpsDatasetsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  return (
    <DatasetsClient
      initialDataset={firstParam(params.dataset)}
      initialPanel={firstParam(params.panel)}
      initialProvider={firstParam(params.provider)}
      initialSyncScope={firstParam(params.sync_scope)}
    />
  );
}
