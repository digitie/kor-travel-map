import type { Metadata } from "next";

import { ManualProviderDedupClient } from "./manual-provider-dedup-client";

export const metadata: Metadata = {
  title: "수동/provider 중복 판정 | kor-travel-map admin",
};

export default function ManualProviderDedupPage() {
  return <ManualProviderDedupClient />;
}
