import type { Metadata } from "next";

import { FeatureChangeRequestsClient } from "../change-requests/feature-change-requests-client";

export const metadata: Metadata = {
  title: "Feature 검수 | kor-travel-map",
  description: "운영자용 feature 변경 요청 검수",
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function FeatureChangeReviewsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  return (
    <FeatureChangeRequestsClient
      highlightRequestId={firstParam(params.request_id) ?? null}
      view="review"
    />
  );
}
