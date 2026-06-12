import type { Metadata } from "next";

import { ImportJobDetailClient } from "./import-job-detail-client";

type ImportJobDetailPageProps = {
  params: Promise<{ jobId: string }>;
};

export async function generateMetadata({
  params,
}: ImportJobDetailPageProps): Promise<Metadata> {
  const { jobId } = await params;
  return {
    title: `${jobId} | Import job`,
  };
}

export default async function ImportJobDetailPage({
  params,
}: ImportJobDetailPageProps) {
  const { jobId } = await params;
  return <ImportJobDetailClient jobId={jobId} />;
}
