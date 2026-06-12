import type { Metadata } from "next";

import { PoiCacheTargetsClient } from "./poi-cache-targets-client";

export const metadata: Metadata = {
  title: "POI cache targets | kor-travel-map admin",
};

export default function PoiCacheTargetsPage() {
  return <PoiCacheTargetsClient />;
}
