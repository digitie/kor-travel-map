import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { GeoReleasesClient } from "./geo-releases-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/ops/geo-releases", "geo 릴리스"),
};

export default function GeoReleasesPage() {
  return <GeoReleasesClient />;
}
