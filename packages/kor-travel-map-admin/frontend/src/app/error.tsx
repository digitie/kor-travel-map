"use client";

import { AppErrorPanel } from "@/components/app-error-panel";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <AppErrorPanel error={error} reset={reset} />;
}
