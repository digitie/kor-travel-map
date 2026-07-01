import { redirect } from "next/navigation";

export default function LegacyDedupReviewPage() {
  redirect("/admin/features/dedup-reviews");
}
