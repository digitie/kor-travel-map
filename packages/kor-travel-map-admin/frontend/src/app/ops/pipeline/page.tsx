import type { Metadata } from "next";
import { Suspense } from "react";

import { PipelineClient } from "./pipeline-client";

export const metadata: Metadata = {
  title: "파이프라인 | kor-travel-map admin",
  description:
    "실행 타임라인·스케줄·갱신 요청을 한 화면에서 관측/조작하는 파이프라인 운영 화면 (ADR-064).",
};

export default function OpsPipelinePage() {
  return (
    <Suspense fallback={<div className="p-6">파이프라인 불러오는 중...</div>}>
      <PipelineClient />
    </Suspense>
  );
}
