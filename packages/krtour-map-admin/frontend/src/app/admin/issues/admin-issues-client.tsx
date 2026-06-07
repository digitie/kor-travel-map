"use client";

import {
  AlertTriangleIcon,
  CheckIcon,
  MapIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import {
  useAdminIssueActionMutation,
  useAdminIssueDetail,
  useAdminIssues,
  type AdminIssueAction,
  type AdminIssuePatchRequest,
  type AdminIssueRecord,
  type AdminIssueSeverity,
  type AdminIssueStatus,
} from "@/api/issues";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

const ISSUE_STATUSES: Array<AdminIssueStatus | "all"> = [
  "open",
  "acknowledged",
  "resolved",
  "ignored",
  "all",
];
const ISSUE_SEVERITIES: Array<AdminIssueSeverity | "all"> = [
  "critical",
  "error",
  "warning",
  "info",
  "all",
];
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function buildActionBody(
  action: AdminIssueAction,
  patch: Partial<AdminIssuePatchRequest> = {},
): AdminIssuePatchRequest {
  return {
    action,
    operator: "local-admin",
    prevent_provider_reactivation: true,
    reason: `admin-ui ${action}`,
    ...patch,
  };
}

function linkedFeatureLabel(issue: AdminIssueRecord): string {
  return issue.feature_id ? shortId(issue.feature_id, 18) : "-";
}

function IssueDetailPanel({ violationKey }: { violationKey: string | null }) {
  const detail = useAdminIssueDetail(violationKey);
  const action = useAdminIssueActionMutation();
  const [manualAddress, setManualAddress] = useState("");
  const [manualLon, setManualLon] = useState("");
  const [manualLat, setManualLat] = useState("");
  const [manualReason, setManualReason] = useState("");
  const [manualError, setManualError] = useState<string | null>(null);

  if (!violationKey) {
    return (
      <div className="rounded-lg border bg-background p-5 text-sm text-muted-foreground">
        table에서 issue를 선택하면 상세 payload와 조치 버튼을 확인할 수 있습니다.
      </div>
    );
  }

  const issue = detail.data?.data.issue;
  const feature = detail.data?.data.feature;

  const runAction = (
    actionName: AdminIssueAction,
    patch: Partial<AdminIssuePatchRequest> = {},
  ) => {
    action.mutate({
      violationKey,
      body: buildActionBody(actionName, patch),
    });
  };

  const submitManualOverride = () => {
    setManualError(null);
    let address: Record<string, unknown> | undefined;
    if (manualAddress.trim().length > 0) {
      try {
        address = JSON.parse(manualAddress) as Record<string, unknown>;
      } catch {
        setManualError("address JSON을 파싱할 수 없습니다.");
        return;
      }
    }
    const lon = manualLon.trim().length > 0 ? Number(manualLon) : undefined;
    const lat = manualLat.trim().length > 0 ? Number(manualLat) : undefined;
    if (
      (lon !== undefined && !Number.isFinite(lon)) ||
      (lat !== undefined && !Number.isFinite(lat))
    ) {
      setManualError("lon/lat은 숫자여야 합니다.");
      return;
    }
    if ((lon === undefined) !== (lat === undefined)) {
      setManualError("coord override는 lon/lat을 함께 입력해야 합니다.");
      return;
    }
    if (address === undefined && lon === undefined) {
      setManualError("address JSON 또는 lon/lat 중 하나는 필요합니다.");
      return;
    }
    runAction("manual_override", {
      address,
      coord: lon !== undefined && lat !== undefined ? { lon, lat } : undefined,
      reason:
        manualReason.trim().length > 0
          ? manualReason.trim()
          : "admin-ui manual override",
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border bg-background">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0">
            <div className="font-medium">Issue detail</div>
            <div className="break-all font-mono text-xs text-muted-foreground">
              {violationKey}
            </div>
          </div>
          {issue?.feature_id ? (
            <Link
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
              href="/features"
            >
              <MapIcon data-icon="inline-start" />
              지도
            </Link>
          ) : null}
        </div>
        {detail.isLoading ? <Skeleton className="m-4 h-64" /> : null}
        {detail.isError ? (
          <Alert className="m-4" variant="destructive">
            <AlertTitle>issue 상세 조회 실패</AlertTitle>
            <AlertDescription>{detail.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {issue ? (
          <div className="flex flex-col gap-4 p-4">
            <div className="flex flex-wrap gap-2">
              <StatusBadge status={issue.status} />
              <StatusBadge status={issue.severity} />
              <Badge variant="outline">{issue.violation_type}</Badge>
            </div>
            <p className="text-sm">{issue.message}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">provider</dt>
              <dd>{issue.provider ?? "-"}</dd>
              <dt className="text-muted-foreground">dataset</dt>
              <dd>{issue.dataset_key ?? "-"}</dd>
              <dt className="text-muted-foreground">feature</dt>
              <dd className="break-all font-mono">
                {issue.feature_id ?? "-"}
              </dd>
              <dt className="text-muted-foreground">source</dt>
              <dd className="break-all font-mono">
                {issue.source_record_key ?? "-"}
              </dd>
              <dt className="text-muted-foreground">detected</dt>
              <dd>{formatDateTime(issue.detected_at)}</dd>
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={action.isPending}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => runAction("resolve")}
              >
                <CheckIcon data-icon="inline-start" />
                resolve
              </Button>
              <Button
                disabled={action.isPending}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => runAction("ignore")}
              >
                <XIcon data-icon="inline-start" />
                ignore
              </Button>
              <Button
                disabled={action.isPending}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => runAction("reopen")}
              >
                <RotateCcwIcon data-icon="inline-start" />
                reopen
              </Button>
              <Button
                disabled={action.isPending}
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => runAction("retry_geocode")}
              >
                retry geocode
              </Button>
              <Button
                disabled={action.isPending}
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => runAction("retry_reverse_geocode")}
              >
                retry reverse
              </Button>
              <Button
                disabled={action.isPending}
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => runAction("apply_kraddr_geo_address")}
              >
                apply kraddr
              </Button>
            </div>

            {feature ? (
              <details open>
                <summary className="cursor-pointer text-sm font-medium">
                  feature snapshot
                </summary>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
                  <dt className="text-muted-foreground">status</dt>
                  <dd>{feature.status}</dd>
                  <dt className="text-muted-foreground">coord</dt>
                  <dd className="font-mono">
                    {typeof feature.lon === "number" &&
                    typeof feature.lat === "number"
                      ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
                      : "없음"}
                  </dd>
                  <dt className="text-muted-foreground">sigungu</dt>
                  <dd>{feature.sigungu_code ?? "-"}</dd>
                </dl>
                <div className="mt-3">
                  <JsonBlock value={feature.address} />
                </div>
              </details>
            ) : null}

            <details>
              <summary className="cursor-pointer text-sm font-medium">payload</summary>
              <JsonBlock value={issue.payload} />
            </details>
          </div>
        ) : null}
      </div>

      <div className="rounded-lg border bg-background p-4">
        <div className="mb-3 flex items-center gap-2 font-medium">
          <WrenchIcon className="size-4 text-muted-foreground" />
          Manual override
        </div>
        {manualError ? (
          <Alert className="mb-3" variant="destructive">
            <AlertTitle>manual override 입력 오류</AlertTitle>
            <AlertDescription>{manualError}</AlertDescription>
          </Alert>
        ) : null}
        {action.isError ? (
          <Alert className="mb-3" variant="destructive">
            <AlertTitle>issue 조치 실패</AlertTitle>
            <AlertDescription>{action.error.message}</AlertDescription>
          </Alert>
        ) : null}
        <div className="grid gap-3">
          <textarea
            aria-label="address JSON"
            className="min-h-28 rounded-lg border border-input bg-background p-3 font-mono text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            placeholder='{"road": "...", "jibun": "..."}'
            value={manualAddress}
            onChange={(event) => setManualAddress(event.target.value)}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <Input
              aria-label="manual lon"
              placeholder="lon"
              value={manualLon}
              onChange={(event) => setManualLon(event.target.value)}
            />
            <Input
              aria-label="manual lat"
              placeholder="lat"
              value={manualLat}
              onChange={(event) => setManualLat(event.target.value)}
            />
            <Input
              aria-label="manual reason"
              placeholder="reason"
              value={manualReason}
              onChange={(event) => setManualReason(event.target.value)}
            />
          </div>
          <Button
            disabled={action.isPending || !violationKey}
            type="button"
            onClick={submitManualOverride}
          >
            manual override
          </Button>
        </div>
      </div>
    </div>
  );
}

export function AdminIssuesClient() {
  const [q, setQ] = useState("");
  const deferredQ = useDeferredValue(q.trim());
  const [status, setStatus] = useState<AdminIssueStatus | "all">("open");
  const [severity, setSeverity] = useState<AdminIssueSeverity | "all">("all");
  const [issueType, setIssueType] = useState("");
  const [provider, setProvider] = useState("");
  const [datasetKey, setDatasetKey] = useState("");
  const [bbox, setBbox] = useState("");
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(100);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedViolationKey, setSelectedViolationKey] = useState<string | null>(
    null,
  );
  const action = useAdminIssueActionMutation();

  const params = useMemo(
    () => ({
      status: status === "all" ? undefined : status,
      severity: severity === "all" ? undefined : severity,
      issue_type: issueType.trim().length > 0 ? issueType.trim() : undefined,
      provider: provider.trim().length > 0 ? provider.trim() : undefined,
      dataset_key:
        datasetKey.trim().length > 0 ? datasetKey.trim() : undefined,
      bbox: bbox.trim().length > 0 ? bbox.trim() : undefined,
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: pageSize,
      cursor: cursor ?? undefined,
    }),
    [
      bbox,
      cursor,
      datasetKey,
      deferredQ,
      issueType,
      pageSize,
      provider,
      severity,
      status,
    ],
  );
  const issues = useAdminIssues(params);
  const items = issues.data?.data.items ?? [];
  const nextCursor = issues.data?.data.next_cursor ?? null;

  const resetCursor = () => setCursor(null);
  const quickAction = (
    violationKey: string,
    actionName: AdminIssueAction,
  ) => {
    action.mutate({
      violationKey,
      body: buildActionBody(actionName),
    });
  };

  return (
    <AdminShell
      actions={
        <Button
          disabled={issues.isFetching}
          type="button"
          variant="outline"
          onClick={() => void issues.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="주소/정합성 이슈 목록, 상세 payload, resolve/ignore/reopen/manual override를 처리합니다."
      section="Admin"
      title="Admin issues"
    >
      <div className="flex flex-col gap-4">
        {(issues.isError || action.isError) && (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>admin issue 처리 실패</AlertTitle>
            <AlertDescription>
              {issues.error?.message ?? action.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <section className="rounded-lg border bg-background p-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(12rem,1fr)_auto_auto_auto_auto]">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="issue search"
                className="pl-8"
                placeholder="message, feature_id, source_record_key"
                value={q}
                onChange={(event) => {
                  setQ(event.target.value);
                  resetCursor();
                }}
              />
            </div>
            <NativeSelect
              aria-label="issue status"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as AdminIssueStatus | "all");
                resetCursor();
              }}
            >
              {ISSUE_STATUSES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="issue severity"
              value={severity}
              onChange={(event) => {
                setSeverity(event.target.value as AdminIssueSeverity | "all");
                resetCursor();
              }}
            >
              {ISSUE_SEVERITIES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="issue page size"
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number(event.target.value) as typeof pageSize);
                resetCursor();
              }}
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setQ("");
                setStatus("open");
                setSeverity("all");
                setIssueType("");
                setProvider("");
                setDatasetKey("");
                setBbox("");
                resetCursor();
              }}
            >
              초기화
            </Button>
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-4">
            <Input
              aria-label="issue type"
              placeholder="issue_type"
              value={issueType}
              onChange={(event) => {
                setIssueType(event.target.value);
                resetCursor();
              }}
            />
            <Input
              aria-label="issue provider"
              placeholder="provider"
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value);
                resetCursor();
              }}
            />
            <Input
              aria-label="issue dataset"
              placeholder="dataset_key"
              value={datasetKey}
              onChange={(event) => {
                setDatasetKey(event.target.value);
                resetCursor();
              }}
            />
            <Input
              aria-label="bbox"
              placeholder="min_lon,min_lat,max_lon,max_lat"
              value={bbox}
              onChange={(event) => {
                setBbox(event.target.value);
                resetCursor();
              }}
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge variant="outline">
              {formatCount(issues.data?.meta.count)} rows
            </Badge>
            <Badge variant="outline">
              {issues.data?.meta.duration_ms ?? 0}ms
            </Badge>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_30rem]">
          <div className="min-w-0 rounded-lg border bg-background">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="font-medium">Issue table</div>
                <div className="text-sm text-muted-foreground">
                  `/admin/issues` keyset cursor 목록
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={!cursor}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => setCursor(null)}
                >
                  첫 페이지
                </Button>
                <Button
                  disabled={!nextCursor}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => setCursor(nextCursor)}
                >
                  다음
                </Button>
              </div>
            </div>
            {issues.isLoading ? <Skeleton className="m-4 h-96" /> : null}
            <div className="overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>issue</TableHead>
                    <TableHead>severity</TableHead>
                    <TableHead>status</TableHead>
                    <TableHead>provider</TableHead>
                    <TableHead>message</TableHead>
                    <TableHead>feature</TableHead>
                    <TableHead>detected</TableHead>
                    <TableHead>actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((issue) => (
                    <TableRow
                      className="cursor-pointer"
                      key={issue.violation_key}
                      data-state={
                        selectedViolationKey === issue.violation_key
                          ? "selected"
                          : undefined
                      }
                      onClick={() => setSelectedViolationKey(issue.violation_key)}
                    >
                      <TableCell>
                        <div className="font-mono text-xs">
                          {shortId(issue.violation_key)}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {issue.violation_type}
                        </div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={issue.severity} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={issue.status} />
                      </TableCell>
                      <TableCell>
                        <div>{issue.provider ?? "-"}</div>
                        <div className="text-xs text-muted-foreground">
                          {issue.dataset_key ?? "-"}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-96">
                        <div className="line-clamp-2">{issue.message}</div>
                        <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                          {issue.source_record_key ?? "-"}
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {linkedFeatureLabel(issue)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(issue.detected_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          <Button
                            disabled={action.isPending}
                            size="sm"
                            type="button"
                            variant="outline"
                            onClick={(event) => {
                              event.stopPropagation();
                              quickAction(issue.violation_key, "resolve");
                            }}
                          >
                            <CheckIcon data-icon="inline-start" />
                            resolve
                          </Button>
                          <Button
                            disabled={action.isPending}
                            size="sm"
                            type="button"
                            variant="ghost"
                            onClick={(event) => {
                              event.stopPropagation();
                              quickAction(issue.violation_key, "ignore");
                            }}
                          >
                            ignore
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!issues.isLoading && items.length === 0 ? (
                    <TableRow>
                      <TableCell
                        className="h-32 text-center text-muted-foreground"
                        colSpan={8}
                      >
                        issue가 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </div>
          </div>

          <IssueDetailPanel violationKey={selectedViolationKey} />
        </section>
      </div>
    </AdminShell>
  );
}
