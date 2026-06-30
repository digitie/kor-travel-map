"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  ExternalLinkIcon,
  PanelRightOpenIcon,
  PlayIcon,
  RefreshCwIcon,
  SaveIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  type OpsProviderDatasetDetail,
  type OpsProviderDatasetSummary,
  useOpsProvider,
  useOpsProviders,
} from "@/api/providers";
import {
  type ProviderRefreshPolicyRecord,
  type ProviderRefreshPolicyUpsertRequest,
  useUpsertProviderRefreshPolicyMutation,
} from "@/api/providerRefreshPolicies";
import { useCreateFeatureUpdateRequestMutation } from "@/api/updateRequests";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge, statusLabel } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button-variants";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { FormField, FormSelect, FormTextArea } from "@/components/ui/form-field";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCount, formatDateTime, shortId } from "@/lib/format";

const STALE_AFTER_HOURS = 48;

const sourceKinds = ["openapi", "filedata", "manual", "system"] as const;
const targetedPolicies = [
  "follow_system",
  "allow_targeted",
  "disabled",
] as const;

type ProviderSelection = {
  provider: string;
  datasetKey: string;
  syncScope: string;
};

type PolicyDraft = {
  source_kind: ProviderRefreshPolicyUpsertRequest["source_kind"];
  targeted_policy: ProviderRefreshPolicyUpsertRequest["targeted_policy"];
  system_interval_seconds: string;
  optimal_interval_seconds: string;
  min_interval_seconds: string;
  max_requests_per_minute: string;
  max_requests_per_hour: string;
  max_requests_per_day: string;
  max_concurrent: string;
  burst_size: string;
  rate_limit_source: string;
  config_source: string;
  enabled: boolean;
};

function itemKey(item: OpsProviderDatasetSummary): string {
  return `${item.provider}\u0000${item.dataset_key}\u0000${item.sync_scope}`;
}

function selectionFromItem(item: OpsProviderDatasetSummary): ProviderSelection {
  return {
    provider: item.provider,
    datasetKey: item.dataset_key,
    syncScope: item.sync_scope,
  };
}

function sameDataset(item: OpsProviderDatasetSummary, selection: ProviderSelection) {
  return (
    item.provider === selection.provider &&
    item.dataset_key === selection.datasetKey &&
    item.sync_scope === selection.syncScope
  );
}

function isNeverRun(item: OpsProviderDatasetSummary): boolean {
  return item.status === "never_run";
}

function isStale(item: OpsProviderDatasetSummary): boolean {
  // never-run dataset은 "한 번도 안 돈" 별도 상태 — stale(오래됨)로 세지 않는다.
  if (isNeverRun(item)) {
    return false;
  }
  if (!item.last_success_at) {
    return true;
  }
  const ageMs = Date.now() - new Date(item.last_success_at).getTime();
  return ageMs > STALE_AFTER_HOURS * 60 * 60 * 1000;
}

function numberText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function sourceKindValue(
  value: string | null | undefined,
): ProviderRefreshPolicyUpsertRequest["source_kind"] {
  return sourceKinds.includes(
    value as ProviderRefreshPolicyUpsertRequest["source_kind"],
  )
    ? (value as ProviderRefreshPolicyUpsertRequest["source_kind"])
    : "openapi";
}

function targetedPolicyValue(
  value: string | null | undefined,
): ProviderRefreshPolicyUpsertRequest["targeted_policy"] {
  return targetedPolicies.includes(
    value as ProviderRefreshPolicyUpsertRequest["targeted_policy"],
  )
    ? (value as ProviderRefreshPolicyUpsertRequest["targeted_policy"])
    : "follow_system";
}

// rate-limit·주기 기본값 — 신규 정책에서 운영자가 일일이 채우지 않도록 보수적 값을
// 미리 채운다. 기존 정책에 값이 있으면 그대로 유지하고, 비어 있을 때만 기본값을 쓴다.
const POLICY_DEFAULTS = {
  system_interval_seconds: 86400,
  optimal_interval_seconds: 86400,
  min_interval_seconds: 3600,
  max_requests_per_minute: 60,
  max_requests_per_hour: 1000,
  max_requests_per_day: 10000,
  max_concurrent: 1,
  burst_size: 10,
} as const;

function policyToDraft(
  policy: ProviderRefreshPolicyRecord | null | undefined,
): PolicyDraft {
  return {
    source_kind: sourceKindValue(policy?.source_kind),
    targeted_policy: targetedPolicyValue(policy?.targeted_policy),
    system_interval_seconds: numberText(
      policy?.system_interval_seconds ?? POLICY_DEFAULTS.system_interval_seconds,
    ),
    optimal_interval_seconds: numberText(
      policy?.optimal_interval_seconds ?? POLICY_DEFAULTS.optimal_interval_seconds,
    ),
    min_interval_seconds: numberText(
      policy?.min_interval_seconds ?? POLICY_DEFAULTS.min_interval_seconds,
    ),
    max_requests_per_minute: numberText(
      policy?.max_requests_per_minute ?? POLICY_DEFAULTS.max_requests_per_minute,
    ),
    max_requests_per_hour: numberText(
      policy?.max_requests_per_hour ?? POLICY_DEFAULTS.max_requests_per_hour,
    ),
    max_requests_per_day: numberText(
      policy?.max_requests_per_day ?? POLICY_DEFAULTS.max_requests_per_day,
    ),
    max_concurrent: numberText(policy?.max_concurrent ?? POLICY_DEFAULTS.max_concurrent),
    burst_size: numberText(policy?.burst_size ?? POLICY_DEFAULTS.burst_size),
    rate_limit_source: JSON.stringify(policy?.rate_limit_source ?? {}, null, 2),
    config_source: policy?.config_source ?? "db",
    enabled: policy?.enabled ?? true,
  };
}

function optionalPositiveInt(value: string, label: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} 값은 양의 정수여야 합니다.`);
  }
  return parsed;
}

function buildPolicyBody(draft: PolicyDraft): ProviderRefreshPolicyUpsertRequest {
  let rateLimitSource: Record<string, unknown>;
  try {
    const parsed = JSON.parse(draft.rate_limit_source || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("rate_limit_source 값은 JSON object여야 합니다.");
    }
    rateLimitSource = parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error("rate_limit_source JSON을 읽을 수 없습니다.");
  }
  return {
    source_kind: draft.source_kind,
    targeted_policy: draft.targeted_policy,
    system_interval_seconds: optionalPositiveInt(
      draft.system_interval_seconds,
      "system interval",
    ),
    optimal_interval_seconds: optionalPositiveInt(
      draft.optimal_interval_seconds,
      "optimal interval",
    ),
    min_interval_seconds: optionalPositiveInt(
      draft.min_interval_seconds,
      "min interval",
    ),
    max_requests_per_minute: optionalPositiveInt(
      draft.max_requests_per_minute,
      "requests/min",
    ),
    max_requests_per_hour: optionalPositiveInt(
      draft.max_requests_per_hour,
      "requests/hour",
    ),
    max_requests_per_day: optionalPositiveInt(
      draft.max_requests_per_day,
      "requests/day",
    ),
    max_concurrent: optionalPositiveInt(draft.max_concurrent, "max concurrent") ?? 1,
    burst_size: optionalPositiveInt(draft.burst_size, "burst size"),
    rate_limit_source: rateLimitSource,
    config_source: draft.config_source.trim() || "db",
    enabled: draft.enabled,
  };
}

function PolicyEditor({
  provider,
  datasetKey,
  policy,
}: {
  provider: string;
  datasetKey: string;
  policy: ProviderRefreshPolicyRecord | null | undefined;
}) {
  const [draft, setDraft] = useState<PolicyDraft>(() => policyToDraft(policy));
  const [error, setError] = useState<string | null>(null);
  const upsertPolicy = useUpsertProviderRefreshPolicyMutation();

  const setField = (field: keyof PolicyDraft, value: string | boolean) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  const submit = () => {
    setError(null);
    let body: ProviderRefreshPolicyUpsertRequest;
    try {
      body = buildPolicyBody(draft);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "policy payload를 만들 수 없습니다.",
      );
      return;
    }
    upsertPolicy.mutate({ provider, datasetKey, body });
  };

  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium">갱신 정책</div>
          <div className="font-mono text-xs text-muted-foreground">
            {provider}/{datasetKey}
          </div>
        </div>
        <Badge variant={draft.enabled ? "outline" : "destructive"}>
          {draft.enabled ? "활성" : "비활성"}
        </Badge>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <FormField
          readOnly
          label="소스 종류"
          hint="제공자·데이터셋에 따라 고정되는 값이라 자동 설정됩니다(수정 불가)."
          value={draft.source_kind}
        />
        <FormSelect
          label="타깃 갱신 정책"
          hint="개별 지점 타깃 갱신을 허용/차단하거나 시스템 정책을 따를지 정합니다."
          value={draft.targeted_policy}
          onChange={(event) =>
            setField(
              "targeted_policy",
              event.target.value as PolicyDraft["targeted_policy"],
            )
          }
        >
          {targetedPolicies.map((value) => (
            <NativeSelectOption key={value} value={value}>
              {value}
            </NativeSelectOption>
          ))}
        </FormSelect>
        <FormField
          inputMode="numeric"
          label="시스템 주기(초)"
          hint="시스템 자동 갱신이 도는 기본 간격(초)입니다."
          value={draft.system_interval_seconds}
          onChange={(event) =>
            setField("system_interval_seconds", event.target.value)
          }
        />
        <FormField
          inputMode="numeric"
          label="최적 주기(초)"
          hint="데이터 신선도상 권장되는 갱신 간격(초)입니다."
          value={draft.optimal_interval_seconds}
          onChange={(event) =>
            setField("optimal_interval_seconds", event.target.value)
          }
        />
        <FormField
          inputMode="numeric"
          label="최소 주기(초)"
          hint="이 간격보다 더 자주는 갱신하지 않습니다(과도 호출 방지)."
          value={draft.min_interval_seconds}
          onChange={(event) => setField("min_interval_seconds", event.target.value)}
        />
        <FormField
          inputMode="numeric"
          label="분당 요청 수"
          hint="provider API에 1분 동안 보낼 수 있는 최대 요청 수입니다."
          value={draft.max_requests_per_minute}
          onChange={(event) =>
            setField("max_requests_per_minute", event.target.value)
          }
        />
        <FormField
          inputMode="numeric"
          label="시간당 요청 수"
          hint="1시간 동안 보낼 수 있는 최대 요청 수입니다."
          value={draft.max_requests_per_hour}
          onChange={(event) =>
            setField("max_requests_per_hour", event.target.value)
          }
        />
        <FormField
          inputMode="numeric"
          label="일일 요청 수"
          hint="하루 동안 보낼 수 있는 최대 요청 수(무료키 일일 쿼터 보호)입니다."
          value={draft.max_requests_per_day}
          onChange={(event) =>
            setField("max_requests_per_day", event.target.value)
          }
        />
        <FormField
          inputMode="numeric"
          label="최대 동시 실행"
          hint="동시에 실행할 수 있는 최대 요청 수입니다."
          value={draft.max_concurrent}
          onChange={(event) => setField("max_concurrent", event.target.value)}
        />
        <FormField
          inputMode="numeric"
          label="버스트 크기"
          hint="순간적으로 허용되는 추가 요청 수(토큰 버킷 버스트)입니다."
          value={draft.burst_size}
          onChange={(event) => setField("burst_size", event.target.value)}
        />
        <FormField
          label="설정 출처"
          hint="이 정책 값의 출처 식별자입니다(기본 db)."
          value={draft.config_source}
          onChange={(event) => setField("config_source", event.target.value)}
        />
        <label className="flex items-center gap-2 self-end text-sm">
          <input
            checked={draft.enabled}
            type="checkbox"
            onChange={(event) => setField("enabled", event.target.checked)}
          />
          활성화
        </label>
        <FormTextArea
          className="lg:col-span-2"
          label="rate limit 출처(JSON)"
          hint="provider가 내려준 원본 rate-limit 정보를 JSON으로 보관합니다."
          value={draft.rate_limit_source}
          onChange={(event) => setField("rate_limit_source", event.target.value)}
        />
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          disabled={upsertPolicy.isPending}
          type="button"
          onClick={submit}
        >
          <SaveIcon data-icon="inline-start" />
          저장
        </Button>
        {upsertPolicy.data ? (
          <Badge variant="outline">
            저장됨 {formatDateTime(upsertPolicy.data.data.updated_at)}
          </Badge>
        ) : null}
      </div>
      {error || upsertPolicy.isError ? (
        <Alert className="mt-3" variant="destructive">
          <AlertTitle>정책 저장 실패</AlertTitle>
          <AlertDescription>
            {error ?? upsertPolicy.error?.message}
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

type SyncStateRow = OpsProviderDatasetDetail["sync_states"][number];
type RecentRequestRow =
  OpsProviderDatasetDetail["recent_update_requests"][number];

const syncStateColumns: ColumnDef<SyncStateRow, unknown>[] = [
  {
    accessorKey: "sync_scope",
    header: "범위",
    enableSorting: false,
    cell: ({ row }) => row.original.sync_scope,
  },
  {
    accessorKey: "status",
    header: "상태",
    enableSorting: true,
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  },
  {
    accessorKey: "last_success_at",
    header: "마지막 성공",
    enableSorting: true,
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {formatDateTime(row.original.last_success_at)}
      </span>
    ),
  },
  {
    accessorKey: "next_run_after",
    header: "다음 실행",
    enableSorting: true,
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {formatDateTime(row.original.next_run_after)}
      </span>
    ),
  },
  {
    accessorKey: "consecutive_failures",
    header: "실패 횟수",
    enableSorting: false,
    cell: ({ row }) => formatCount(row.original.consecutive_failures),
  },
];

const recentRequestColumns: ColumnDef<RecentRequestRow, unknown>[] = [
  {
    id: "request",
    header: "요청",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs">{shortId(row.original.request_id)}</span>
    ),
  },
  {
    accessorKey: "status",
    header: "상태",
    enableSorting: true,
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  },
  {
    id: "job",
    header: "잡",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs">
        {row.original.job_id ? (
          <Link
            className="underline underline-offset-2"
            href={`/ops/import-jobs/${row.original.job_id}`}
          >
            {shortId(row.original.job_id)}
          </Link>
        ) : (
          "-"
        )}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "생성",
    enableSorting: true,
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {formatDateTime(row.original.created_at)}
      </span>
    ),
  },
  {
    id: "link",
    header: "링크",
    enableSorting: false,
    cell: ({ row }) => (
      <Link
        className={buttonVariants({ size: "sm", variant: "ghost" })}
        href={`/admin/feature-update-requests/${row.original.request_id}`}
      >
        <ExternalLinkIcon data-icon="inline-start" />
        상세
      </Link>
    ),
  },
];

function DatasetDetailPanel({
  selection,
  detail,
}: {
  selection: ProviderSelection;
  detail: OpsProviderDatasetDetail | null;
}) {
  const createRequest = useCreateFeatureUpdateRequestMutation();
  const createdRequestId = createRequest.data?.data.request_id ?? null;

  const createProviderDatasetRequest = () => {
    createRequest.mutate({
      scope: {
        type: "provider_dataset",
        provider: selection.provider,
        dataset_key: selection.datasetKey,
        sync_scope:
          selection.syncScope === "default" ? undefined : selection.syncScope,
      },
      providers: [selection.provider],
      dataset_keys: [selection.datasetKey],
      dry_run: false,
      run_mode: "queued",
      priority: 75,
      operator: "local-admin",
      reason: "provider dataset refresh from ops/providers",
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border bg-background p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="font-medium">데이터셋 상세</div>
            <div className="break-all font-mono text-xs text-muted-foreground">
              {selection.provider}/{selection.datasetKey}
            </div>
          </div>
          <Button
            disabled={createRequest.isPending}
            type="button"
            onClick={createProviderDatasetRequest}
          >
            <PlayIcon data-icon="inline-start" />
            요청 생성
          </Button>
        </div>
        {createRequest.data && createdRequestId ? (
          <Alert>
            <AlertTitle>요청 생성 완료</AlertTitle>
            <AlertDescription>
              <Link
                className="underline underline-offset-2"
                href={`/admin/feature-update-requests/${createdRequestId}`}
              >
                {shortId(createdRequestId)}
              </Link>
              {" · "}
              {statusLabel(createRequest.data.data.status)}
            </AlertDescription>
          </Alert>
        ) : null}
        {createRequest.isError ? (
          <Alert variant="destructive">
            <AlertTitle>요청 생성 실패</AlertTitle>
            <AlertDescription>{createRequest.error.message}</AlertDescription>
          </Alert>
        ) : null}
      </div>

      <DataTable
        columns={syncStateColumns}
        data={detail?.sync_states ?? []}
        getRowId={(state) => state.sync_scope}
        emptyMessage="sync state 없음"
        manualSorting={false}
        containerClassName="overflow-auto rounded-lg border bg-background"
      />

      <div className="rounded-lg border bg-background p-4">
        <div className="mb-2 font-medium">커서</div>
        <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(detail?.sync_states[0]?.cursor ?? {}, null, 2)}
        </pre>
      </div>

      <DataTable
        columns={recentRequestColumns}
        data={detail?.recent_update_requests ?? []}
        getRowId={(request) => request.request_id}
        emptyMessage="provider_dataset request 없음"
        manualSorting={false}
        containerClassName="overflow-auto rounded-lg border bg-background"
      />
    </div>
  );
}

export function ProvidersFreshnessClient({
  initialDatasetKey = null,
  initialProvider = null,
  initialSyncScope = null,
}: {
  initialDatasetKey?: string | null;
  initialProvider?: string | null;
  initialSyncScope?: string | null;
}) {
  const providers = useOpsProviders();
  const items = useMemo(() => providers.data?.data.items ?? [], [providers.data]);
  const [selection, setSelection] = useState<ProviderSelection | null>(null);

  const initialSelection = useMemo(() => {
    if (!initialProvider || items.length === 0) {
      return null;
    }
    const requested = items.find(
      (item) =>
        item.provider === initialProvider &&
        (!initialDatasetKey || item.dataset_key === initialDatasetKey) &&
        (!initialSyncScope || item.sync_scope === initialSyncScope),
    ) ?? items.find((item) => item.provider === initialProvider);
    if (!requested) {
      return null;
    }
    return selectionFromItem(requested);
  }, [initialDatasetKey, initialProvider, initialSyncScope, items]);

  const activeSelection =
    selection ?? initialSelection ?? (items[0] ? selectionFromItem(items[0]) : null);
  const detail = useOpsProvider(activeSelection?.provider ?? null);

  const selectedDetail = useMemo(() => {
    if (!activeSelection) {
      return null;
    }
    return (
      detail.data?.data.datasets.find(
        (item) => item.dataset_key === activeSelection.datasetKey,
      ) ?? null
    );
  }, [activeSelection, detail.data]);

  const summary = useMemo(() => {
    const providerNames = new Set(items.map((item) => item.provider));
    const failing = items.filter((item) => item.consecutive_failures > 0);
    const stale = items.filter(
      (item) => item.consecutive_failures === 0 && isStale(item),
    );
    const neverRun = items.filter((item) => isNeverRun(item));
    const policies = items.filter((item) => item.refresh_policy);
    return {
      providers: providerNames.size,
      failing,
      stale,
      neverRun,
      policies: policies.length,
    };
  }, [items]);

  // never-run dataset은 단건 상세(sync/policy row)가 없어 404가 정상 — 이때
  // detail 에러를 목록 상단에 블로킹 alert로 띄우지 않는다.
  const activeIsNeverRun = useMemo(
    () =>
      activeSelection
        ? (items.find((item) => sameDataset(item, activeSelection))?.status ??
            "") === "never_run"
        : false,
    [activeSelection, items],
  );
  const showDetailError = detail.isError && !activeIsNeverRun;

  type ProviderRow = NonNullable<typeof providers.data>["data"]["items"][number];
  const columns = useMemo<ColumnDef<ProviderRow, unknown>[]>(
    () => [
      {
        id: "detail",
        header: "상세",
        enableSorting: false,
        cell: ({ row }) => {
          const item = row.original;
          const active = activeSelection
            ? sameDataset(item, activeSelection)
            : false;
          return (
            <Button
              aria-pressed={active}
              size="icon"
              type="button"
              variant={active ? "secondary" : "ghost"}
              onClick={(event) => {
                event.stopPropagation();
                setSelection(selectionFromItem(item));
              }}
            >
              <PanelRightOpenIcon />
            </Button>
          );
        },
      },
      {
        accessorKey: "provider",
        header: "제공자",
        enableSorting: true,
        cell: ({ row }) => (
          <span className="font-medium">{row.original.provider}</span>
        ),
      },
      {
        accessorKey: "dataset_key",
        header: "데이터셋",
        enableSorting: true,
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.dataset_key}</span>
        ),
      },
      {
        accessorKey: "sync_scope",
        header: "범위",
        enableSorting: true,
        cell: ({ row }) => row.original.sync_scope,
      },
      {
        accessorKey: "status",
        header: "상태",
        enableSorting: true,
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "policy",
        header: "정책",
        accessorFn: (item) => item.refresh_policy?.targeted_policy ?? "",
        enableSorting: true,
        cell: ({ row }) =>
          row.original.refresh_policy ? (
            <Badge variant="outline">
              {row.original.refresh_policy.targeted_policy}
            </Badge>
          ) : (
            <span className="text-muted-foreground">-</span>
          ),
      },
      {
        accessorKey: "last_success_at",
        header: "마지막 성공",
        enableSorting: true,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.last_success_at)}
          </span>
        ),
      },
      {
        accessorKey: "next_run_after",
        header: "다음 실행",
        enableSorting: true,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.next_run_after)}
          </span>
        ),
      },
      {
        accessorKey: "consecutive_failures",
        header: "실패 횟수",
        enableSorting: true,
        cell: ({ row }) =>
          row.original.consecutive_failures > 0 ? (
            <Badge variant="destructive">{row.original.consecutive_failures}</Badge>
          ) : (
            <span className="text-muted-foreground">0</span>
          ),
      },
    ],
    [activeSelection],
  );

  return (
    <AdminShell
      actions={
        <Button
          disabled={providers.isFetching || detail.isFetching}
          type="button"
          variant="outline"
          onClick={() => {
            void providers.refetch();
            void detail.refetch();
          }}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="전 provider×dataset의 동기화 상태, 갱신 요청, 갱신 정책을 추적합니다."
      section="운영"
      title="제공자"
    >
      <div className="flex flex-col gap-4">
        {providers.isError || showDetailError ? (
          <Alert variant="destructive">
            <AlertTitle>provider 조회 실패</AlertTitle>
            <AlertDescription>
              {providers.error?.message ?? detail.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}

        <section className="flex flex-wrap gap-2">
          <Badge variant="outline">
            제공자 {formatCount(summary.providers)}
          </Badge>
          <Badge variant="outline">데이터셋 {formatCount(items.length)}</Badge>
          <Badge variant="outline">정책 {formatCount(summary.policies)}</Badge>
          <Badge variant={summary.failing.length > 0 ? "destructive" : "outline"}>
            실패 {formatCount(summary.failing.length)}
          </Badge>
          <Badge variant="outline">
            오래됨(&gt;{STALE_AFTER_HOURS}h) {formatCount(summary.stale.length)}
          </Badge>
          <Badge variant="outline">
            미실행 {formatCount(summary.neverRun.length)}
          </Badge>
        </section>

        {summary.failing.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>연속 실패 중인 dataset</AlertTitle>
            <AlertDescription>
              {summary.failing
                .map(
                  (item) =>
                    `${item.provider}/${item.dataset_key} (${item.consecutive_failures}회)`,
                )
                .join(", ")}
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(28rem,0.85fr)]">
          <DataTable
            columns={columns}
            data={items}
            getRowId={(row) => itemKey(row)}
            isLoading={providers.isLoading}
            emptyMessage="provider ops row가 없습니다."
            onRowClick={(row) => setSelection(selectionFromItem(row))}
            isRowActive={(row) =>
              activeSelection ? sameDataset(row, activeSelection) : false
            }
            manualSorting={false}
            containerClassName="overflow-auto rounded-lg border bg-background"
          />

          <div className="flex min-w-0 flex-col gap-4">
            {activeSelection ? (
              <>
                {detail.isLoading ? <Skeleton className="h-64" /> : null}
                <DatasetDetailPanel
                  detail={selectedDetail}
                  key={`${activeSelection.provider}/${activeSelection.datasetKey}/${activeSelection.syncScope}`}
                  selection={activeSelection}
                />
                <PolicyEditor
                  datasetKey={activeSelection.datasetKey}
                  key={`${activeSelection.provider}/${activeSelection.datasetKey}`}
                  policy={selectedDetail?.refresh_policy ?? null}
                  provider={activeSelection.provider}
                />
              </>
            ) : (
              <div className="rounded-lg border bg-background p-6 text-sm text-muted-foreground">
                선택된 provider dataset이 없습니다.
              </div>
            )}
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
