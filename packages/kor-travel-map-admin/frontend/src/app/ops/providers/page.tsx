import type { Metadata } from "next";

import { ProvidersFreshnessClient } from "./providers-client";

export const metadata: Metadata = {
  title: "Providers | kor-travel-map admin",
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ProvidersPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  return (
    <ProvidersFreshnessClient
      initialDatasetKey={firstParam(params.dataset_key)}
      initialProvider={firstParam(params.provider)}
      initialSyncScope={firstParam(params.sync_scope)}
    />
  );
}
