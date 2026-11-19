import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { PoiCacheTargetsClient } from "./poi-cache-targets-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/poi-cache-targets", "POI 캐시 대상"),
};

export default function PoiCacheTargetsPage() {
  return <PoiCacheTargetsClient />;
}
