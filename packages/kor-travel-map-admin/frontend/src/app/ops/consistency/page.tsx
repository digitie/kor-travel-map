import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { ConsistencyClient } from "./consistency-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/ops/consistency", "정합성 점검"),
};

export default function ConsistencyPage() {
  return <ConsistencyClient />;
}
