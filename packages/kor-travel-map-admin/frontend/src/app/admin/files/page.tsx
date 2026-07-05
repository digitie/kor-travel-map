import type { Metadata } from "next";

import { FilesClient } from "./files-client";

export const metadata: Metadata = {
  title: "파일 관리 | kor-travel-map admin",
};

export default function FilesPage() {
  return <FilesClient />;
}
