import type { Metadata } from "next";

import {
  FeatureChangeRequestsClient,
  type FeatureChangeRequestPrefill,
} from "./feature-change-requests-client";

export const metadata: Metadata = {
  title: "Feature 변경 | kor-travel-map",
  description: "운영자용 feature 추가·수정·삭제 요청 작성",
};

function firstParam(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

export default async function FeatureChangeRequestsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  const action = firstParam(params.action);
  const featureId = firstParam(params.feature_id);
  const reason = firstParam(params.reason);
  const hasPrefill = action || featureId || reason;
  const prefill: FeatureChangeRequestPrefill | undefined = hasPrefill
    ? {
        action,
        featureId,
        key: JSON.stringify({ action, feature_id: featureId, reason }),
        reason,
      }
    : undefined;
  return <FeatureChangeRequestsClient prefill={prefill} view="request" />;
}
