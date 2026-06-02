import type { Metadata } from "next";

import { DagsterAdminClient } from "./dagster-client";

export const metadata: Metadata = {
  title: "Dagster 운영 | krtour-map admin",
};

export default function DagsterAdminPage() {
  return <DagsterAdminClient />;
}
