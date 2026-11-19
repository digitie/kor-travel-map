import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { CacheTargetStreamsClient } from "./cache-target-streams-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/ops/cache-target-streams", "캐시 전파 스트림"),
};

export default function CacheTargetStreamsPage() {
  return <CacheTargetStreamsClient />;
}
