import type { Metadata } from "next";

import { LogsClient } from "./logs-client";

export const metadata: Metadata = {
  title: "Logs | kor-travel-map",
  description: "system log와 API call log 조회 화면",
};

export default function LogsPage() {
  return <LogsClient />;
}
