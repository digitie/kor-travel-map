"use client";

import {
  ArrowLeftIcon,
  DatabaseIcon,
  PencilIcon,
} from "lucide-react";
import Link from "next/link";

import { AdminShell } from "@/components/admin-shell";
import { FeatureDetailView } from "@/components/feature-detail-view";
import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

export function FeatureDetailPageClient({ featureId }: { featureId: string }) {
  return (
    <AdminShell
      actions={
        <>
          <Link className={cn(buttonVariants({ variant: "outline" }))} href="/features">
            <ArrowLeftIcon data-icon="inline-start" />
            지도
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features"
          >
            <DatabaseIcon data-icon="inline-start" />
            Feature 목록
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href={`/admin/features?feature_id=${encodeURIComponent(featureId)}`}
          >
            <PencilIcon data-icon="inline-start" />
            수정
          </Link>
        </>
      }
      breadcrumbs={[
        { label: "Feature 관리" },
        { label: "Feature 목록", href: "/admin/features" },
        { label: featureId },
      ]}
      title="Feature 상세"
    >
      <FeatureDetailView featureId={featureId} />
    </AdminShell>
  );
}
