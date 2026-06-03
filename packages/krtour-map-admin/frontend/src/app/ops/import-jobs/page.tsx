import type { Metadata } from "next";

import { ImportJobsClient } from "./import-jobs-client";

export const metadata: Metadata = {
  title: "Import jobs | krtour-map admin",
};

export default function ImportJobsPage() {
  return <ImportJobsClient />;
}
