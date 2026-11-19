import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { LogsClient } from "./logs-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/ops/logs", "운영 로그"),
  description: "system log와 API call log 조회 화면",
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function LogsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  return (
    <LogsClient
      initialLevel={firstParam(params.level)}
      initialTab={firstParam(params.tab)}
    />
  );
}
