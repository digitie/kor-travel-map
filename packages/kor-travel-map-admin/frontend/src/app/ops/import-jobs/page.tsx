import type { Metadata } from "next";

import { ImportJobsClient } from "./import-jobs-client";

export const metadata: Metadata = {
  title: "Import jobs | kor-travel-map admin",
};

type ImportJobsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ImportJobsPage({
  searchParams,
}: ImportJobsPageProps) {
  const params = await searchParams;
  return (
    <ImportJobsClient
      initialFilters={{
        status: firstParam(params.status),
        kind: firstParam(params.kind),
        loadBatchId: firstParam(params.load_batch_id),
        parentJobId: firstParam(params.parent_job_id),
      }}
    />
  );
}
