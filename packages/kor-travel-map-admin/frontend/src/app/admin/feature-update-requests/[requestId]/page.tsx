import { redirect } from "next/navigation";

type FeatureUpdateRequestDetailPageProps = {
  params: Promise<{ requestId: string }>;
};

export default async function LegacyFeatureUpdateRequestDetailPage({
  params,
}: FeatureUpdateRequestDetailPageProps) {
  const { requestId } = await params;
  redirect(`/admin/features/update-requests/${encodeURIComponent(requestId)}`);
}
