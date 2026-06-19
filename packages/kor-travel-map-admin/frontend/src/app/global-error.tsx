"use client";

import { AppErrorPanel } from "@/components/app-error-panel";

import "./globals.css";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="ko">
      <body className="font-sans">
        <AppErrorPanel error={error} reset={reset} standalone />
      </body>
    </html>
  );
}
