import type { Metadata } from "next";

import { DagsterAdminClient } from "./dagster-client";

export const metadata: Metadata = {
  title: "작업 자동화 | kor-travel-map admin",
};

export default function DagsterAdminPage() {
  return <DagsterAdminClient />;
}
