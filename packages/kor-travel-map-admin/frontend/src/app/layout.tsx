// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
/**
 * Next.js 16 App Router root layout.
 *
 * - QueryClientProvider 박음 (ADR-037 TanStack Query)
 * - 카테고리/마커 자원은 `@kor-travel-map/map-marker-react`에서 import (ADR-029/043)
 * - 인증 layer 없음 (ADR-005 + ADR-035)
 * - 관리자 셸(`AdminShellFrame`)은 여기 한 번만 둔다 — 페이지 이동 사이에 셸이 다시 마운트되지
 *   않아야 drawer 이동 뒤 본문 포커스가 유지된다. 페이지는 `AdminShell`로 제목·동작만 채운다.
 * - 서체(design.md §Typography): 본문/UI = Pretendard Variable(common tokens/font.css → `pretendard` dynamic
 *   subset CSS, 한글 글리프 커버) · mono = Geist Mono(next/font, `--font-geist-mono`).
 *   Geist Sans는 제거했다 — `--font-sans` 스택은 globals.css `@theme`가 정본.
 */

import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { AdminShellFrame } from "@/components/admin-shell";
import { ConfirmDialogProvider } from "@/components/confirm-dialog";
import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
import { AppQueryClientProvider } from "@/providers/query-client-provider";

import "@kor-travel/tokens/font.css";
import "./globals.css";

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  title: "kor-travel-map admin",
  description:
    "Debug + admin + ops UI for kor-travel-map. Intranet-only (ADR-005/035).",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="ko" className={cn("font-sans", geistMono.variable)}>
      <body>
        <AppQueryClientProvider>
          <ConfirmDialogProvider>
            <AdminShellFrame>{children}</AdminShellFrame>
          </ConfirmDialogProvider>
          <Toaster position="top-right" />
        </AppQueryClientProvider>
      </body>
    </html>
  );
}
