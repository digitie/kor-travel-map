"use client";

/**
 * TanStack Query 전역 Provider (ADR-037).
 *
 * Next.js 16 App Router에서는 client component로 박는다 (`"use client"`).
 * QueryClient instance를 component 인스턴스 라이프사이클 안에서 생성해 HMR
 * 충돌 회피.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

export function AppQueryClientProvider({ children }: Props) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 디버그 UI는 read-mostly + 내부망 전용 → focus refetch off.
            refetchOnWindowFocus: false,
            // 네트워크 에러 retry는 1회만 — 운영자가 즉시 알아채야 함.
            retry: 1,
            // staleTime은 라우터별 override (`useHealth`/`useVersion` 등).
            staleTime: 0,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
