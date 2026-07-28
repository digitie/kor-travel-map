import type { Metadata } from "next";
import { Suspense } from "react";

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
  const initialQuery = new URLSearchParams();
  for (const [key, rawValue] of Object.entries(params)) {
    const value = firstParam(rawValue);
    if (value !== undefined) {
      initialQuery.set(key, value);
    }
  }
  return (
    <Suspense fallback={<div className="p-6">파이프라인 불러오는 중...</div>}>
      <PipelineClient initialQuery={initialQuery.toString()} />
    </Suspense>
  );
}
