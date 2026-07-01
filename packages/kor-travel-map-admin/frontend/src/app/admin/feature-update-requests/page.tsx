import { redirect } from "next/navigation";

export default function LegacyFeatureUpdateRequestsPage() {
  redirect("/admin/features/update-requests");
}
