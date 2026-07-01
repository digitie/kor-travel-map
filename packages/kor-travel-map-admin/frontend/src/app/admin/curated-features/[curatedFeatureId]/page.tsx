import { redirect } from "next/navigation";

type CuratedFeatureDetailPageProps = {
  params: Promise<{ curatedFeatureId: string }>;
};

export default async function LegacyCuratedFeatureDetailPage({
  params,
}: CuratedFeatureDetailPageProps) {
  const { curatedFeatureId } = await params;
  redirect(`/admin/features/curated/${encodeURIComponent(curatedFeatureId)}`);
}
