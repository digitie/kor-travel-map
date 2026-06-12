import type { Metadata } from "next";

import { BackupsClient } from "./backups-client";

export const metadata: Metadata = {
  title: "Backups | kor-travel-map admin",
};

export default function BackupsPage() {
  return <BackupsClient />;
}
