/**
 * Next.js 16 App Router root layout.
 *
 * - QueryClientProvider 박음 (ADR-037 TanStack Query)
 * - 카테고리/마커 자원은 `@krtour/map-marker-react`에서 import (ADR-029/043)
 * - 인증 layer 없음 (ADR-005 + ADR-035)
 */

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppQueryClientProvider } from "@/providers/query-client-provider";

export const metadata: Metadata = {
  title: "krtour-map debug UI",
  description:
    "Debug + admin + ops UI for python-krtour-map. Intranet-only (ADR-005/035).",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="ko">
      <body>
        <AppQueryClientProvider>{children}</AppQueryClientProvider>
      </body>
    </html>
  );
}
