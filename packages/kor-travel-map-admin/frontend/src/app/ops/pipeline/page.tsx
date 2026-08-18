// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { PipelineClient } from "./pipeline-client";

export const metadata: Metadata = {
  title: "파이프라인 | kor-travel-map admin",
  description:
    "실행 타임라인·스케줄·갱신 요청을 한 화면에서 관측/조작하는 파이프라인 운영 화면 (ADR-064).",
};

/** 라우트 suspense fallback — 텍스트 로더 대신 페이지 형태(제목 · 요약 · 목록)의 skeleton(M19). */
function PipelineFallback() {
  return (
    <div aria-busy="true" className="space-y-4 p-6">
      <span className="sr-only">파이프라인 불러오는 중</span>
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

export default function OpsPipelinePage() {
  return (
    <Suspense fallback={<PipelineFallback />}>
      <PipelineClient />
    </Suspense>
  );
}
