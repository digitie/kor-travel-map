import type { Metadata } from "next";

import { HomePageClient } from "./home-client";

export const metadata: Metadata = {
  title: "kor-travel-map admin",
  description: "feature 운영과 provider 변환 확인을 위한 내부망 관리 화면",
};

export default function HomePage() {
  return <HomePageClient />;
}
