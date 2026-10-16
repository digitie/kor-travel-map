import type { Metadata } from "next";

import { GeoReleasesClient } from "./geo-releases-client";

export const metadata: Metadata = {
  title: "geo 릴리스 | kor-travel-map admin",
};

export default function GeoReleasesPage() {
  return <GeoReleasesClient />;
}
