import type { Metadata } from "next";

import { PipelineClient } from "./pipeline-client";

export const metadata: Metadata = {
  title: "파이프라인 | kor-travel-map admin",
  description:
    "실행 타임라인·스케줄·갱신 요청을 한 화면에서 관측/조작하는 파이프라인 운영 화면 (ADR-064).",
};

type SearchParams = Record<string, string | string[] | undefined>;

function firstParam(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

export default async function OpsPipelinePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  return (
    <PipelineClient
      initialExecution={firstParam(params.execution)}
      initialFilters={{
        kind: firstParam(params.kind),
        status: firstParam(params.status),
        provider: firstParam(params.provider),
        datasetKey: firstParam(params.dataset_key),
        createdFrom: firstParam(params.created_from),
        createdTo: firstParam(params.created_to),
        loadBatchId: firstParam(params.load_batch_id),
        parentJobId: firstParam(params.parent_job_id),
      }}
      initialSchedule={firstParam(params.schedule)}
      initialTab={firstParam(params.tab)}
    />
  );
}
