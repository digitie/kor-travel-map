import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { HomePageClient } from "./home-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/", "운영 홈"),
  description: "feature 운영과 provider 변환 확인을 위한 내부망 관리 화면",
};

export default function HomePage() {
  return <HomePageClient />;
}
