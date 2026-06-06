import type { Metadata } from "next";

import { BackupsClient } from "./backups-client";

export const metadata: Metadata = {
  title: "Backups | krtour-map admin",
};

export default function BackupsPage() {
  return <BackupsClient />;
}
