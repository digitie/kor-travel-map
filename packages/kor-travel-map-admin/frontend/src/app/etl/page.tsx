import type { Metadata } from "next";

import { EtlPreviewClient } from "./etl-client";

export const metadata: Metadata = {
  title: "ETL preview | kor-travel-map admin",
  description: "provider fixture/live 변환 출력을 적재 없이 검토하는 화면",
};

export default function EtlPreviewPage() {
  return <EtlPreviewClient />;
}
