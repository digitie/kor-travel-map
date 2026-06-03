/**
 * Next.js 16 App Router root layout.
 *
 * - QueryClientProvider 박음 (ADR-037 TanStack Query)
 * - 카테고리/마커 자원은 `@krtour/map-marker-react`에서 import (ADR-029/043)
 * - 인증 layer 없음 (ADR-005 + ADR-035)
 */

import type { Metadata } from "next";
import { Geist } from "next/font/google";
import type { ReactNode } from "react";

import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
import { AppQueryClientProvider } from "@/providers/query-client-provider";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "krtour-map admin",
  description:
    "Debug + admin + ops UI for python-krtour-map. Intranet-only (ADR-005/035).",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="ko" className={cn("font-sans", geist.variable)}>
      <body>
        <AppQueryClientProvider>
          {children}
          <Toaster position="top-right" richColors />
        </AppQueryClientProvider>
      </body>
    </html>
  );
}
