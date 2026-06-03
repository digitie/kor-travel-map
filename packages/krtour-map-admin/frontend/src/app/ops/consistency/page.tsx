import type { Metadata } from "next";

import { ConsistencyClient } from "./consistency-client";

export const metadata: Metadata = {
  title: "Consistency | krtour-map admin",
};

export default function ConsistencyPage() {
  return <ConsistencyClient />;
}
