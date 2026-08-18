"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app

import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  ExternalLinkIcon,
  LockIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";

import { useAdminCuratedFeature } from "@/api/curated";
import { AdminShell } from "@/components/admin-shell";
import { CopyButton } from "@/components/copy-button";
import { DetailList } from "@/components/detail-list";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { statusLabel } from "@/lib/status-label";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  CuratedFeatureDetailPreview,
  CuratedFeatureLocationPanel,
} from "../curated-features-client";
import { CuratedLifecycleStrip } from "../curated-lifecycle";

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

/**
 * legacy 큐레이션 상세(읽기 전용) — detail 변형(design.md): 식별 밴드(flush) → 본문 2단
 * (위치·스냅샷 SectionCard · 우측 rail 안내). 복사는 CopyButton(silent success, M15).
 */
export function CuratedFeatureDetailClient({
  curatedFeatureId,
}: {
  curatedFeatureId: string;
}) {
  const feature = useAdminCuratedFeature(curatedFeatureId);
  const item = feature.data?.data ?? null;
  const pageTitle = item
    ? `${item.display_title ?? item.feature_name} · ${statusLabel(item.curation_status)}`
    : "큐레이션";

  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/curated"
          >
            <ArrowLeftIcon data-icon="inline-start" />
            목록
          </Link>
          {item ? (
            <Link
              className={cn(buttonVariants({ variant: "outline" }))}
              href={featureHref(item.feature_id)}
            >
              <ExternalLinkIcon data-icon="inline-start" />
              feature
            </Link>
          ) : null}
          <Button
            loading={feature.isFetching}
            type="button"
            variant="outline"
            onClick={() => void feature.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
      }
      breadcrumbs={[
        { label: "Feature 관리" },
        { label: "큐레이션 관리", href: "/admin/features/curated" },
        { label: curatedFeatureId },
      ]}
      section="Feature 관리"
      title={pageTitle}
    >
      <div className="flex flex-col gap-6">
        {feature.isLoading ? (
          <div aria-busy="true" className="flex flex-col gap-6">
            <div className="flex flex-col gap-3 border-b border-border pb-5">
              <div className="flex gap-1">
                <Skeleton className="h-6 w-20" />
                <Skeleton className="h-6 w-16" />
                <Skeleton className="h-6 w-20" />
              </div>
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-4 w-80" />
            </div>
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
              <Skeleton className="h-96 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          </div>
        ) : null}
        {feature.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>큐레이션 상세 조회 실패</AlertTitle>
            <AlertDescription>
              {feature.error.message} — ID를 확인하거나 잠시 후 다시 시도하세요.
            </AlertDescription>
            <AlertActions>
              <Button
                loading={feature.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => void feature.refetch()}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}
        {item ? (
          <>
            {/* 식별 밴드 — 프레임 없이 hairline만(M7/M31): 배지 → 이름(h2) → ID(mono + 복사) → 라이프사이클. */}
            <header className="flex flex-col gap-4 border-b border-border pb-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex min-w-0 flex-col gap-2">
                  <div className="flex flex-wrap gap-1">
                    <StatusBadge status={item.curation_status} />
                    <Badge variant="neutral">{item.feature_kind}</Badge>
                    <Badge variant="outline">{item.theme_name}</Badge>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <h2 className="text-lg leading-tight font-semibold break-keep text-text-primary">
                      {item.feature_name}
                    </h2>
                    {item.display_title ? (
                      <p className="text-sm text-text-secondary">{item.display_title}</p>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-1 font-mono text-xs break-all text-text-secondary slashed-zero">
                    <span>{shortId(item.curated_feature_id, 32)}</span>
                    <CopyButton label="ID" value={item.curated_feature_id} />
                  </div>
                </div>
                <DetailList
                  className="min-w-64"
                  items={[
                    { label: "채택 시각", value: formatDateTime(item.selected_at) },
                    { label: "수정 시각", value: formatDateTime(item.updated_at) },
                    { label: "순위", value: item.rank_score.toFixed(2), numeric: true },
                  ]}
                  layout="inline"
                />
              </div>
              <CuratedLifecycleStrip
                activeStatus={item.curation_status}
                compact
              />
            </header>

            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
              <div className="flex min-w-0 flex-col gap-6">
                <CuratedFeatureLocationPanel feature={item} />
                <CuratedFeatureDetailPreview feature={item} />
              </div>
              <aside className="flex min-w-0 flex-col gap-4">
                <Alert variant="info">
                  <LockIcon data-icon="inline-start" />
                  <AlertTitle>legacy 큐레이션 쓰기 봉인 (T-VN-40A)</AlertTitle>
                  <AlertDescription>
                    이 화면은 읽기 전용입니다. 채택·해제·보관·편집은 canonical 컬렉션
                    관리에서 합니다. legacy 표는 T-VN-40C에서 삭제됩니다.
                  </AlertDescription>
                  <AlertActions>
                    <Link
                      className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                      href="/admin/features/curated"
                    >
                      컬렉션 관리로
                    </Link>
                  </AlertActions>
                </Alert>
              </aside>
            </div>
          </>
        ) : null}
      </div>
    </AdminShell>
  );
}
