import type { Metadata } from "next";

import { Suspense } from "react";

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
 * searchParams는 **첫 렌더 시드**로만 서버에서 읽어 client에 넘기고, 이후 행
 * 선택·탭 상태는 client의 `useSearchParams`가 URL query를 정본으로 동기화한다
 * (뒤로/앞으로 가기로 복원, 닫기 시 빈 상태 — T-ADM-C4R/#684).
 */
export default async function OpsDatasetsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  return (
    <Suspense>
      <DatasetsClient
        initialDataset={firstParam(params.dataset)}
        initialPanel={firstParam(params.panel)}
        initialProvider={firstParam(params.provider)}
        initialSyncScope={firstParam(params.sync_scope)}
      />
    </Suspense>
  );
}
