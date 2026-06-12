"use client";

import {
  ArrowLeftIcon,
  ClipboardListIcon,
  DatabaseIcon,
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
            Admin
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/change-requests"
          >
            <ClipboardListIcon data-icon="inline-start" />
            Changes
          </Link>
        </>
      }
      section="Features"
      title="Feature detail"
    >
      <FeatureDetailView featureId={featureId} />
    </AdminShell>
  );
}
