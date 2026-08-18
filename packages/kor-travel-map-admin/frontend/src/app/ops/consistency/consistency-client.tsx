"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (dashboard) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { RefreshCwIcon } from "lucide-react";
import { useState } from "react";

import {
  type IntegrityIssueStatus,
  type OpsConsistencyReportRecord,
  type OpsIntegrityIssueRecord,
  useConsistencyReports,
  useIntegrityIssues,
  useOpsMetrics,
} from "@/api/ops";
import { AdminShell } from "@/components/admin-shell";
import { EntityLink } from "@/components/entity-link";
import { FilterField } from "@/components/filter-bar";
import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { LevelBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DataTable,
  DataTableClampCell,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { statusLabel, toneFor } from "@/lib/status-label";

const issueStatuses: Array<IntegrityIssueStatus | "all"> = [
  "open",
  "acknowledged",
  "resolved",
  "ignored",
  "all",
];

/**
 * consistency 계열 severity(`OK` · `WARN` · `ERROR` · `critical` …)를 tone 테이블 키로 정규화한다
 * — `WARN`은 사전에 없어 raw로 렌더되던 값이라 `warning`으로 접는다(M28: enum raw 렌더 금지).
 */
function severityStatus(value: string | null | undefined): string | null {
  if (value == null) return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === "warn") return "warning";
  return normalized;
}

const reportColumns: ColumnDef<OpsConsistencyReportRecord, unknown>[] = [
  {
    id: "report",
    header: "리포트",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs slashed-zero">
        {shortId(row.original.report_id)}
      </span>
    ),
  },
  {
    id: "batch",
    header: "배치",
    enableSorting: false,
    cell: ({ row }) => (
      <EntityLink className="text-xs" id={row.original.batch_id} kind="loadBatch">
        {shortId(row.original.batch_id)}
      </EntityLink>
    ),
  },
  {
    accessorKey: "severity_max",
    header: "심각도",
    cell: ({ row }) => (
      <LevelBadge level={severityStatus(row.original.severity_max)} />
    ),
  },
  {
    accessorKey: "finished_at",
    header: "완료",
    cell: ({ row }) => (
      <span className="text-text-secondary">
        {formatDateTime(row.original.finished_at)}
      </span>
    ),
  },
];

const issueColumns: ColumnDef<OpsIntegrityIssueRecord, unknown>[] = [
  {
    id: "issue",
    header: "이슈",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs slashed-zero">
        {shortId(row.original.issue_id)}
      </span>
    ),
  },
  {
    accessorKey: "severity",
    header: "심각도",
    cell: ({ row }) => <LevelBadge level={severityStatus(row.original.severity)} />,
  },
  {
    id: "provider_dataset",
    header: "provider dataset",
    cell: ({ row }) =>
      row.original.provider_dataset_id ? (
        <EntityLink
          id=""
          kind="issue"
          params={{
            provider_dataset_id: String(row.original.provider_dataset_id),
          }}
        >
          {row.original.provider
            ? `${row.original.provider} · #${row.original.provider_dataset_id}`
            : `#${row.original.provider_dataset_id}`}
        </EntityLink>
      ) : (
        <span className="text-text-tertiary">{NULL_GLYPH}</span>
      ),
  },
  {
    accessorKey: "message",
    header: "메시지",
    enableSorting: false,
    meta: { wrap: true } satisfies DataTableColumnMeta,
    cell: ({ row }) => (
      <DataTableClampCell lines={2}>{row.original.message}</DataTableClampCell>
    ),
  },
  {
    accessorKey: "detected_at",
    header: "감지",
    cell: ({ row }) => (
      <span className="text-text-secondary">
        {formatDateTime(row.original.detected_at)}
      </span>
    ),
  },
];

/**
 * e2e/consistency-drilldown.spec.ts는 카드를 `div.rounded-lg` + 제목 텍스트로 scope한다
 * (data-testid 없음). `rounded-lg`는 Foundation에서 `--radius-panel`로 접혀 `rounded-panel`과 같은
 * 8px이라 시각 차이는 없다 — spec이 testid로 옮겨 가면 이 클래스는 지운다.
 */
const E2E_CARD_HOOK = "rounded-lg";

export function ConsistencyClient() {
  const [status, setStatus] = useState<IntegrityIssueStatus | "all">("open");
  const metrics = useOpsMetrics();
  const metricsData = metrics.data?.data;
  const reports = useConsistencyReports({ page_size: 20 });
  const issues = useIntegrityIssues({
    status: status === "all" ? undefined : status,
    page_size: 100,
  });

  const refreshAll = () => {
    void metrics.refetch();
    void reports.refetch();
    void issues.refetch();
  };
  const isRefreshing =
    metrics.isFetching || reports.isFetching || issues.isFetching;

  const reportItems = reports.data?.data.items ?? [];
  const issueItems = issues.data?.data.items ?? [];

  const latestSeverity = severityStatus(
    metricsData?.latest_consistency_report?.severity_max ?? "none",
  );
  const queryError =
    metrics.error?.message ?? reports.error?.message ?? issues.error?.message;

  return (
    <AdminShell
      actions={
        <Button
          loading={isRefreshing}
          type="button"
          variant="outline"
          onClick={refreshAll}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="정합성 리포트와 이슈 큐를 조회합니다."
      title="정합성 점검"
    >
      <div className="flex flex-col gap-6">
        {metrics.isError || reports.isError || issues.isError ? (
          <Alert variant="destructive">
            <AlertTitle>consistency 조회 실패</AlertTitle>
            <AlertDescription>
              {queryError ?? "서버가 응답하지 않았거나 요청이 거부되었습니다."}
            </AlertDescription>
            <AlertActions>
              <Button
                loading={isRefreshing}
                size="sm"
                type="button"
                variant="outline"
                onClick={refreshAll}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}

        <div className={E2E_CARD_HOOK}>
          <StatStrip
            ariaLabel="정합성 요약"
            isLoading={metrics.isLoading}
            items={[
              {
                key: "open-issues",
                label: "Open issues",
                value: metricsData?.data_integrity_issues.open_total,
                unit: "건",
                caption: "열린 정합성 이슈",
              },
              {
                key: "latest-severity",
                label: "Latest severity",
                value: statusLabel(latestSeverity),
                tone: toneFor(latestSeverity),
                caption: "최근 consistency 리포트 기준",
              },
              {
                key: "checked-at",
                label: "Checked at",
                value: (
                  <span className="text-sm font-medium">
                    {formatDateTime(metricsData?.checked_at)}
                  </span>
                ),
                caption: "마지막 점검 시각",
              },
            ]}
          />
        </div>

        <section className="grid gap-6 xl:grid-cols-2">
          <SectionCard
            actions={
              <span className="text-xs text-text-secondary tabular-nums">
                <span>
                  {formatCount(reports.data ? reportItems.length : null, {
                    loading: reports.isLoading,
                  })}
                </span>{" "}
                건
              </span>
            }
            className={E2E_CARD_HOOK}
            description="최근 consistency batch"
            title="Reports"
          >
            <DataTable
              columns={reportColumns}
              data={reportItems}
              getRowId={(row) => row.report_id}
              isLoading={reports.isLoading}
              emptyState={{
                title: "데이터가 없습니다.",
                description:
                  "consistency batch가 끝나면 리포트가 여기에 쌓입니다.",
              }}
              manualSorting={false}
              skeletonRowCount={5}
            />
          </SectionCard>

          <SectionCard
            actions={
              <FilterField label="상태">
                <NativeSelect
                  aria-label="issue status"
                  size="sm"
                  value={status}
                  onChange={(event) =>
                    setStatus(event.target.value as IntegrityIssueStatus | "all")
                  }
                >
                  {issueStatuses.map((item) => (
                    <NativeSelectOption key={item} value={item}>
                      {item === "all" ? "전체" : statusLabel(item)}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </FilterField>
            }
            className={E2E_CARD_HOOK}
            description="상태·provider dataset·유형별 후속 처리 대상"
            title="Integrity issues"
          >
            <DataTable
              columns={issueColumns}
              data={issueItems}
              getRowId={(row) => row.issue_id}
              isLoading={issues.isLoading}
              emptyState={{
                title: "데이터가 없습니다.",
                description:
                  status === "all"
                    ? "기록된 정합성 이슈가 없습니다."
                    : "상태 필터를 전체로 바꾸면 다른 상태의 이슈를 볼 수 있습니다.",
              }}
              manualSorting={false}
              skeletonRowCount={5}
            />
          </SectionCard>
        </section>
      </div>
    </AdminShell>
  );
}
