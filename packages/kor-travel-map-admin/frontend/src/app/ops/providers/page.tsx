import type { Metadata } from "next";

import { ProvidersFreshnessClient } from "./providers-client";

export const metadata: Metadata = {
  title: "Providers | kor-travel-map admin",
};

export default function ProvidersPage() {
  return <ProvidersFreshnessClient />;
}
