import type { Metadata } from "next";

import { AdminShell } from "@/components/admin-shell";

import { ManualProviderDedupClient } from "./manual-provider-dedup-client";

export const metadata: Metadata = {
  title: "수동/provider 중복 판정 | kor-travel-map admin",
};

export default function ManualProviderDedupPage() {
  return (
    <AdminShell
      description="탐지기가 올린 수동/provider 중복 후보를 판정합니다. 자동으로 병합되지 않습니다."
      title="수동/provider 중복 판정"
    >
      <ManualProviderDedupClient />
    </AdminShell>
  );
}
