import { redirect } from "next/navigation";

export default function LegacyCuratedFeaturesPage() {
  redirect("/admin/features/curated");
}
