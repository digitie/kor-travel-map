import type { Metadata } from "next";

import { ConsistencyClient } from "./consistency-client";

export const metadata: Metadata = {
  title: "Consistency | kor-travel-map admin",
};

export default function ConsistencyPage() {
  return <ConsistencyClient />;
}
