"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import {
  CheckIcon,
  MapIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useDeferredValue,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";

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
import { featureStateLabel } from "@/api/features";
import { AdminShell } from "@/components/admin-shell";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { EntityLink } from "@/components/entity-link";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { JsonViewer } from "@/components/json-viewer";
import { CursorPager } from "@/components/pagination-bar";
import { SectionCard } from "@/components/section-card";
import { LevelBadge, StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import {
  DataTable,
  DataTableClampCell,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { FormField, FormTextArea } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { KOREA_COORD_MESSAGE, isKoreaCoordinate } from "@/lib/form-validation";
import { statusLabel } from "@/lib/status-label";

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
const BBOX_FORMAT_HINT = "형식: minLon,minLat,maxLon,maxLat";

function optionLabel(value: string): string {
  return value === "all" ? "전체" : statusLabel(value);
}

function buildActionBody(
  action: AdminIssueAction,
  patch: Partial<AdminIssuePatchRequest> = {},
): AdminIssuePatchRequest {
  return {
    action,
    reason: `admin-ui ${action}`,
    ...patch,
  };
}

function linkedFeatureLabel(issue: AdminIssueRecord): string {
  return issue.feature_id ? shortId(issue.feature_id, 18) : NULL_GLYPH;
}

function parseBbox(value: string) {
  const parts = value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
  if (parts.length !== 4) return {};
  const [min_lon, min_lat, max_lon, max_lat] = parts;
  return { min_lon, min_lat, max_lon, max_lat };
}

function positiveInteger(value: string): number | undefined {
  const parsed = Number(value.trim());
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
}

type IssueActionRunner = (
  actionName: AdminIssueAction,
  patch?: Partial<AdminIssuePatchRequest>,
) => void;

/** issue 상세의 "수동 보정" 폼 — 입력 state·검증·focus 이동을 자체 소유한다.
 *
 * 조치 mutation만은 상단 조치 버튼과 공유해야 하므로(동시 실행 방지 +
 * 실패 alert 단일 표면) 부모에서 받는다.
 */
function IssueManualOverridePanel({
  action,
  runAction,
}: {
  action: ReturnType<typeof useAdminIssueActionMutation>;
  runAction: IssueActionRunner;
}) {
  const [manualAddress, setManualAddress] = useState("");
  const [manualLon, setManualLon] = useState("");
  const [manualLat, setManualLat] = useState("");
  const [manualReason, setManualReason] = useState("");
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualErrorField, setManualErrorField] = useState<
    "address" | "lon" | null
  >(null);
  const manualAddressRef = useRef<HTMLTextAreaElement>(null);
  const manualLonRef = useRef<HTMLInputElement>(null);

  const failManualOverride = (field: "address" | "lon", message: string) => {
    setManualError(message);
    setManualErrorField(field);
    if (field === "address") {
      manualAddressRef.current?.focus();
    } else {
      manualLonRef.current?.focus();
    }
  };

  const submitManualOverride = () => {
    setManualError(null);
    setManualErrorField(null);
    let address: Record<string, unknown> | undefined;
    if (manualAddress.trim().length > 0) {
      try {
        address = JSON.parse(manualAddress) as Record<string, unknown>;
      } catch {
        failManualOverride(
          "address",
          "주소 보정값을 JSON 형식으로 입력하세요.",
        );
        return;
      }
    }
    const lon = manualLon.trim().length > 0 ? Number(manualLon) : undefined;
    const lat = manualLat.trim().length > 0 ? Number(manualLat) : undefined;
    if (
      (lon !== undefined && !Number.isFinite(lon)) ||
      (lat !== undefined && !Number.isFinite(lat))
    ) {
      failManualOverride("lon", "좌표는 숫자로 입력하세요.");
      return;
    }
    if ((lon === undefined) !== (lat === undefined)) {
      failManualOverride("lon", "경도와 위도는 함께 입력하세요.");
      return;
    }
    if (
      lon !== undefined &&
      lat !== undefined &&
      !isKoreaCoordinate(lon, lat)
    ) {
      failManualOverride("lon", KOREA_COORD_MESSAGE);
      return;
    }
    if (address === undefined && lon === undefined) {
      failManualOverride("address", "주소 또는 좌표 중 하나를 입력하세요.");
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

  const isOverriding =
    action.isPending && action.variables?.body.action === "manual_override";

  return (
    <SectionCard
      description="주소 또는 좌표 중 하나만 입력해도 됩니다."
      headingLevel={3}
      title="수동 보정"
    >
      {action.isError ? (
        <Alert variant="destructive">
          <AlertTitle>issue 조치 실패</AlertTitle>
          <AlertDescription>{action.error.message}</AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-col gap-1">
        <FormTextArea
          className="font-mono"
          error={manualErrorField === "address" ? manualError : undefined}
          hint="도로명/지번 주소를 JSON으로 입력합니다."
          label="주소 보정값"
          placeholder='{"road": "...", "jibun": "..."}'
          ref={manualAddressRef}
          value={manualAddress}
          onChange={(event) => setManualAddress(event.target.value)}
        />
        <div className="grid grid-cols-2 gap-x-3">
          <FormField
            error={manualErrorField === "lon" ? manualError : undefined}
            inputMode="decimal"
            label="경도"
            ref={manualLonRef}
            value={manualLon}
            onChange={(event) => setManualLon(event.target.value)}
          />
          <FormField
            error={manualErrorField === "lon" ? manualError : undefined}
            inputMode="decimal"
            label="위도"
            value={manualLat}
            onChange={(event) => setManualLat(event.target.value)}
          />
        </div>
        <FormField
          hint="비워 두면 admin-ui manual override 로 기록됩니다."
          label="보정 사유"
          value={manualReason}
          onChange={(event) => setManualReason(event.target.value)}
        />
        <div className="flex items-center justify-end border-t border-border pt-4">
          <Button
            disabled={action.isPending}
            disabledReason="다른 조치를 처리하는 중입니다"
            loading={isOverriding}
            type="button"
            onClick={submitManualOverride}
          >
            수동 보정 적용
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      <div className="flex gap-1.5">
        <Skeleton className="h-6 w-16" />
        <Skeleton className="h-6 w-14" />
      </div>
      <Skeleton className="h-4 w-5/6" />
      {["a", "b", "c", "d"].map((key) => (
        <div className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3" key={key}>
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ))}
    </div>
  );
}

function IssueDetailPanel({ issueId }: { issueId: string | null }) {
  const detail = useAdminIssueDetail(issueId);
  const action = useAdminIssueActionMutation();

  if (!issueId) {
    return (
      <SectionCard title="상세">
        <EmptyState
          title="선택된 이슈가 없습니다"
          description="table에서 issue를 선택하면 상세 payload와 조치 버튼을 확인할 수 있습니다."
        />
      </SectionCard>
    );
  }

  const issue = detail.data?.data.issue;
  const feature = detail.data?.data.feature;

  const runAction: IssueActionRunner = (actionName, patch = {}) => {
    action.mutate({
      issueId,
      body: buildActionBody(actionName, patch),
    });
  };
  const pendingAction = action.isPending ? action.variables?.body.action : undefined;
  const actionButton = (
    label: string,
    actionName: AdminIssueAction,
    variant: "outline" | "ghost",
    icon?: ReactNode,
  ) => (
    <Button
      disabled={action.isPending}
      disabledReason="다른 조치를 처리하는 중입니다"
      loading={pendingAction === actionName}
      size="sm"
      type="button"
      variant={variant}
      onClick={() => runAction(actionName)}
    >
      {icon}
      {label}
    </Button>
  );

  const items: DetailItem[] | null = issue
    ? [
        { label: "provider", value: issue.provider ?? null },
        { label: "dataset", value: issue.dataset_key ?? null, mono: true },
        {
          label: "provider dataset ID",
          value: issue.provider_dataset_id ?? null,
          numeric: true,
        },
        {
          label: "feature",
          value: issue.feature_id ? (
            <EntityLink id={issue.feature_id} kind="feature" />
          ) : null,
        },
        { label: "source", value: issue.source_record_key ?? null, mono: true },
        { label: "detected", value: formatDateTime(issue.detected_at), numeric: true },
      ]
    : null;

  return (
    <div className="flex flex-col gap-6">
      <SectionCard
        actions={
          issue?.feature_id ? (
            <Link
              className={buttonVariants({ variant: "outline", size: "sm" })}
              href={`/features/${encodeURIComponent(issue.feature_id)}`}
            >
              <MapIcon data-icon="inline-start" />
              Feature 상세
            </Link>
          ) : null
        }
        description={<span className="font-mono break-all">{issueId}</span>}
        title="이슈 상세"
      >
        {detail.isLoading ? <DetailSkeleton /> : null}
        {detail.isError ? (
          <Alert variant="destructive">
            <AlertTitle>issue 상세 조회 실패</AlertTitle>
            <AlertDescription>{detail.error.message}</AlertDescription>
            <AlertActions>
              <Button
                loading={detail.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => void detail.refetch()}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}
        {issue && items ? (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusBadge status={issue.status} />
              <LevelBadge level={issue.severity} />
              <span className="font-mono text-xs text-text-secondary">
                {issue.violation_type}
              </span>
            </div>
            <p className="text-sm text-text-primary">{issue.message}</p>
            <DetailList items={items} layout="inline" />
            <div className="flex flex-col gap-2 border-t border-border pt-4">
              <span className="text-2xs font-medium text-text-secondary">조치</span>
              <div className="flex flex-wrap gap-1.5">
                {actionButton("해결", "resolve", "outline", <CheckIcon data-icon="inline-start" />)}
                {actionButton("무시", "ignore", "ghost", <XIcon data-icon="inline-start" />)}
                {actionButton(
                  "다시 열기",
                  "reopen",
                  "ghost",
                  <RotateCcwIcon data-icon="inline-start" />,
                )}
              </div>
              <span className="mt-1 text-2xs font-medium text-text-secondary">주소·좌표</span>
              <div className="flex flex-wrap gap-1.5">
                {actionButton("주소로 좌표 재검색", "retry_geocode", "ghost")}
                {actionButton("좌표로 주소 재검색", "retry_reverse_geocode", "ghost")}
                {actionButton("추천 주소 적용", "apply_kor_travel_geo_address", "ghost")}
              </div>
            </div>

            {feature ? (
              <details className="group/details border-t border-border pt-4" open>
                <summary className="cursor-pointer text-sm font-medium text-text-primary select-none">
                  Feature 스냅샷
                </summary>
                <div className="mt-3 flex flex-col gap-3">
                  <DetailList
                    items={[
                      {
                        label: "상태 축",
                        value: `${featureStateLabel("lifecycle", feature.lifecycle_state)} · ${featureStateLabel(
                          "publication",
                          feature.publication_state,
                        )} · ${featureStateLabel("quality", feature.quality_state)}`,
                      },
                      {
                        label: "coord",
                        value:
                          typeof feature.lon === "number" &&
                          typeof feature.lat === "number"
                            ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
                            : "없음",
                        mono: true,
                      },
                      { label: "sigungu", value: feature.sigungu_code ?? null, mono: true },
                    ]}
                    layout="inline"
                  />
                  <JsonViewer aria-label="feature address" maxHeight="sm" value={feature.address} />
                </div>
              </details>
            ) : null}

            <details className="border-t border-border pt-4">
              <summary className="cursor-pointer text-sm font-medium text-text-primary select-none">
                payload
              </summary>
              <div className="mt-3">
                <JsonViewer aria-label="issue payload" copyable value={issue.payload} />
              </div>
            </details>
          </>
        ) : null}
      </SectionCard>

      <IssueManualOverridePanel action={action} runAction={runAction} />
    </div>
  );
}

function parseInitialStatus(
  value: string | undefined,
): AdminIssueStatus | "all" {
  return value && (ISSUE_STATUSES as string[]).includes(value)
    ? (value as AdminIssueStatus | "all")
    : "open";
}

interface AdminIssueFilters {
  q: string;
  status: AdminIssueStatus | "all";
  severity: AdminIssueSeverity | "all";
  issueType: string;
  providerDatasetId: string;
  featureId: string;
  bbox: string;
  pageSize: (typeof PAGE_SIZE_OPTIONS)[number];
}

interface AdminIssuesState extends AdminIssueFilters {
  cursor: string | null;
  selectedIssueId: string | null;
}

type AdminIssuesAction =
  | { type: "change-filters"; patch: Partial<AdminIssueFilters> }
  | { type: "reset-filters" }
  | { type: "set-cursor"; cursor: string | null }
  | { type: "select-issue"; issueId: string | null };

function initialAdminIssuesState({
  initialFeatureId,
  initialProviderDatasetId,
  initialStatus,
}: {
  initialFeatureId?: string;
  initialProviderDatasetId?: string;
  initialStatus?: string;
}): AdminIssuesState {
  return {
    q: "",
    status: parseInitialStatus(initialStatus),
    severity: "all",
    issueType: "",
    providerDatasetId: initialProviderDatasetId ?? "",
    featureId: initialFeatureId ?? "",
    bbox: "",
    pageSize: 100,
    cursor: null,
    selectedIssueId: null,
  };
}

function adminIssuesReducer(
  state: AdminIssuesState,
  action: AdminIssuesAction,
): AdminIssuesState {
  switch (action.type) {
    case "change-filters":
      return { ...state, ...action.patch, cursor: null };
    case "reset-filters":
      return {
        ...state,
        q: "",
        status: "open",
        severity: "all",
        issueType: "",
        providerDatasetId: "",
        featureId: "",
        bbox: "",
        cursor: null,
      };
    case "set-cursor":
      return { ...state, cursor: action.cursor };
    case "select-issue":
      return { ...state, selectedIssueId: action.issueId };
  }
}

function useAdminIssuesClientController({
  initialFeatureId,
  initialProviderDatasetId,
  initialStatus,
}: {
  initialFeatureId?: string;
  initialProviderDatasetId?: string;
  initialStatus?: string;
} = {}) {
  const [state, dispatch] = useReducer(
    adminIssuesReducer,
    {
      initialFeatureId,
      initialProviderDatasetId,
      initialStatus,
    },
    initialAdminIssuesState,
  );
  const {
    bbox,
    cursor,
    featureId,
    issueType,
    pageSize,
    providerDatasetId,
    q,
    selectedIssueId,
    severity,
    status,
  } = state;
  const deferredQ = useDeferredValue(q.trim());
  const action = useAdminIssueActionMutation();

  const params = useMemo(
    () => ({
      status: status === "all" ? undefined : status,
      severity: severity === "all" ? undefined : severity,
      issue_type: issueType.trim().length > 0 ? issueType.trim() : undefined,
      provider_dataset_id: positiveInteger(providerDatasetId),
      feature_id: featureId.trim().length > 0 ? featureId.trim() : undefined,
      ...(bbox.trim().length > 0 ? parseBbox(bbox) : {}),
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: pageSize,
      cursor: cursor ?? undefined,
    }),
    [
      bbox,
      cursor,
      deferredQ,
      featureId,
      issueType,
      pageSize,
      providerDatasetId,
      severity,
      status,
    ],
  );
  const issues = useAdminIssues(params);
  const items = issues.data?.data.items ?? [];
  const nextCursor = issues.data?.meta.page?.next_cursor ?? null;

  const changeFilters = (patch: Partial<AdminIssueFilters>) => {
    dispatch({ type: "change-filters", patch });
  };
  const resetFilters = () => {
    dispatch({ type: "reset-filters" });
  };
  const goFirstPage = () => {
    dispatch({ type: "set-cursor", cursor: null });
  };
  const goNextPage = () => {
    if (nextCursor) {
      dispatch({ type: "set-cursor", cursor: nextCursor });
    }
  };
  const selectIssue = (issueId: string | null) => {
    dispatch({ type: "select-issue", issueId });
  };
  const quickAction = useCallback(
    (issueId: string, actionName: AdminIssueAction) => {
      action.mutate({
        issueId,
        body: buildActionBody(actionName),
      });
    },
    [action],
  );
  const actionPending = action.isPending;
  const pendingIssueId = actionPending ? (action.variables?.issueId ?? null) : null;
  const pendingActionKind = actionPending ? (action.variables?.body.action ?? null) : null;

  const columns = useMemo<ColumnDef<AdminIssueRecord, unknown>[]>(
    () => [
      {
        id: "issue",
        header: "이슈",
        enableSorting: false,
        cell: ({ row }) => {
          const issue = row.original;
          return (
            <>
              <div className="font-mono text-xs">{shortId(issue.issue_id)}</div>
              <div className="mt-1 text-xs text-text-secondary">
                {issue.violation_type}
              </div>
            </>
          );
        },
      },
      {
        accessorKey: "severity",
        header: "심각도",
        // keyset cursor 목록 — 서버가 정렬을 소유하고 severity accessor로 정렬하지 않으므로
        // client 정렬은 현재 페이지만 재배열해 오해를 준다(#502). 정렬 비활성화.
        enableSorting: false,
        cell: ({ row }) => <LevelBadge level={row.original.severity} />,
      },
      {
        accessorKey: "status",
        header: "상태",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "provider",
        header: "provider",
        enableSorting: false,
        cell: ({ row }) => {
          const issue = row.original;
          return (
            <>
              <div>{issue.provider ?? NULL_GLYPH}</div>
              <div className="text-xs text-text-secondary">
                {issue.dataset_key ?? NULL_GLYPH}
              </div>
            </>
          );
        },
      },
      {
        id: "message",
        header: "메시지",
        enableSorting: false,
        meta: { wrap: true } satisfies DataTableColumnMeta,
        cell: ({ row }) => {
          const issue = row.original;
          return (
            <div className="max-w-96">
              <DataTableClampCell lines={2}>{issue.message}</DataTableClampCell>
              <div className="mt-1 font-mono text-xs break-all text-text-secondary">
                {issue.source_record_key ?? NULL_GLYPH}
              </div>
            </div>
          );
        },
      },
      {
        id: "feature",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.feature_id ? (
            <EntityLink
              className="font-mono text-xs"
              id={row.original.feature_id}
              kind="feature"
            >
              {linkedFeatureLabel(row.original)}
            </EntityLink>
          ) : (
            <span className="font-mono text-xs">{NULL_GLYPH}</span>
          ),
      },
      {
        accessorKey: "detected_at",
        header: "감지",
        // keyset cursor 목록 — 서버 정렬을 신뢰(현재 페이지만 client 정렬하지 않음, #502).
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.detected_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const issue = row.original;
          const busy = pendingIssueId === issue.issue_id;
          const reason =
            actionPending && !busy ? "다른 조치를 처리하는 중입니다" : undefined;
          return (
            <div className="flex flex-wrap gap-1">
              <Button
                disabled={actionPending}
                disabledReason={reason}
                loading={busy && pendingActionKind === "resolve"}
                size="sm"
                type="button"
                variant="outline"
                onClick={(event) => {
                  event.stopPropagation();
                  quickAction(issue.issue_id, "resolve");
                }}
              >
                <CheckIcon data-icon="inline-start" />
                resolve
              </Button>
              <Button
                disabled={actionPending}
                disabledReason={reason}
                loading={busy && pendingActionKind === "ignore"}
                size="sm"
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  quickAction(issue.issue_id, "ignore");
                }}
              >
                ignore
              </Button>
            </div>
          );
        },
      },
    ],
    [actionPending, pendingActionKind, pendingIssueId, quickAction],
  );

  return {
    action,
    bbox,
    changeFilters,
    columns,
    cursor,
    featureId,
    goFirstPage,
    goNextPage,
    issueType,
    issues,
    items,
    nextCursor,
    pageSize,
    providerDatasetId,
    q,
    resetFilters,
    selectIssue,
    selectedIssueId,
    severity,
    status,
  };
}

function AdminIssuesClientView({
  action,
  bbox,
  changeFilters,
  columns,
  cursor,
  featureId,
  goFirstPage,
  goNextPage,
  issueType,
  issues,
  items,
  nextCursor,
  pageSize,
  providerDatasetId,
  q,
  resetFilters,
  selectIssue,
  selectedIssueId,
  severity,
  status,
}: ReturnType<typeof useAdminIssuesClientController>) {
  const bboxInvalid =
    bbox.trim().length > 0 && Object.keys(parseBbox(bbox)).length === 0;
  const errorLines = [
    issues.error ? `목록: ${issues.error.message}` : null,
    action.error ? `조치: ${action.error.message}` : null,
  ].filter((line): line is string => line !== null);
  return (
    <AdminShell
      actions={
        <Button
          loading={issues.isFetching}
          type="button"
          variant="outline"
          onClick={() => void issues.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="주소·정합성 이슈를 확인하고 처리합니다."
      title="이슈"
    >
      <div className="flex flex-col gap-6">
        {errorLines.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>admin issue 처리 실패</AlertTitle>
            <AlertDescription>
              {errorLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
              <p>잠시 후 다시 시도하세요.</p>
            </AlertDescription>
            <AlertActions>
              <Button
                loading={issues.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => {
                  action.reset();
                  void issues.refetch();
                }}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}

        <FilterBar>
          <FilterField className="w-72" label="검색">
            <Input
              aria-label="이슈 검색"
              placeholder="message, feature_id, source_record_key"
              value={q}
              onChange={(event) => changeFilters({ q: event.target.value })}
            />
          </FilterField>
          <FilterField label="상태">
            <NativeSelect
              aria-label="이슈 상태 필터"
              value={status}
              onChange={(event) =>
                changeFilters({
                  status: event.target.value as AdminIssueStatus | "all",
                })
              }
            >
              {ISSUE_STATUSES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {optionLabel(item)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField label="심각도">
            <NativeSelect
              aria-label="이슈 심각도 필터"
              value={severity}
              onChange={(event) =>
                changeFilters({
                  severity: event.target.value as AdminIssueSeverity | "all",
                })
              }
            >
              {ISSUE_SEVERITIES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {optionLabel(item)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField className="w-40" label="issue type">
            <Input
              aria-label="issue type"
              className="font-mono"
              placeholder="missing_address"
              value={issueType}
              onChange={(event) =>
                changeFilters({ issueType: event.target.value })
              }
            />
          </FilterField>
          <FilterField className="w-40" label="provider dataset ID">
            <Input
              aria-label="issue provider dataset ID"
              inputMode="numeric"
              min="1"
              type="number"
              value={providerDatasetId}
              onChange={(event) =>
                changeFilters({ providerDatasetId: event.target.value })
              }
            />
          </FilterField>
          <FilterField className="w-56" label="feature ID">
            <Input
              aria-label="issue feature id"
              className="font-mono"
              value={featureId}
              onChange={(event) =>
                changeFilters({ featureId: event.target.value })
              }
            />
          </FilterField>
          <FilterField className="w-72" hint={BBOX_FORMAT_HINT} label="bbox">
            <Input
              aria-invalid={bboxInvalid}
              aria-label="bbox"
              className="font-mono"
              placeholder="126.9,37.5,127.1,37.6"
              value={bbox}
              onChange={(event) => changeFilters({ bbox: event.target.value })}
            />
          </FilterField>
          <FilterField label="페이지 크기">
            <NativeSelect
              aria-label="issue page size"
              value={String(pageSize)}
              onChange={(event) =>
                changeFilters({
                  pageSize: Number(event.target.value) as typeof pageSize,
                })
              }
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterActions>
            <Button type="button" variant="outline" onClick={resetFilters}>
              초기화
            </Button>
          </FilterActions>
        </FilterBar>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
          <SectionCard
            description="행을 선택하면 우측에 상세와 조치가 열립니다."
            title="Issue table"
          >
            <DataTable
              columns={columns}
              containerClassName="overflow-auto"
              data={items}
              emptyState={{
                title: "issue가 없습니다.",
                description: "상태 필터를 전체로 바꾸거나 검색어·bbox를 비워 보세요.",
              }}
              getRowId={(row) => row.issue_id}
              isLoading={issues.isLoading}
              isRowActive={(issue) => selectedIssueId === issue.issue_id}
              onRowClick={(issue) => selectIssue(issue.issue_id)}
            />
            <CursorPager
              hasNext={Boolean(nextCursor)}
              isFetching={issues.isFetching}
              isFirst={cursor === null}
              summary={`이 페이지 ${formatCount(issues.data ? items.length : null)}건`}
              onFirst={goFirstPage}
              onNext={goNextPage}
            />
          </SectionCard>

          <IssueDetailPanel issueId={selectedIssueId} />
        </div>
      </div>
    </AdminShell>
  );
}

export function AdminIssuesClient({
  initialFeatureId,
  initialProviderDatasetId,
  initialStatus,
}: {
  initialFeatureId?: string;
  initialProviderDatasetId?: string;
  initialStatus?: string;
} = {}) {
  const controller = useAdminIssuesClientController({
    initialFeatureId,
    initialProviderDatasetId,
    initialStatus,
  });
  return <AdminIssuesClientView {...controller} />;
}
