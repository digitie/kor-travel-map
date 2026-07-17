"use client";

import { useQueryClient } from "@tanstack/react-query";
import { type CellContext, type ColumnDef } from "@tanstack/react-table";
import {
  ExternalLinkIcon,
  FlaskConicalIcon,
  PanelRightOpenIcon,
  PlayIcon,
  RefreshCwIcon,
  SaveIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiClientError } from "@/api/client";
import {
  type OpsDatasetCatalogInfo,
  type OpsDatasetDetailData,
  type OpsDatasetEventRecord,
  type OpsDatasetFreshness,
  type OpsDatasetGridRow,
  type OpsDatasetLatestExecution,
  type OpsDatasetPreviewData,
  type OpsDatasetScopeState,
  type ProviderRefreshPolicyRecord,
  type ProviderRefreshPolicyUpsertRequest,
  OPS_DATASET_LIVE_TOPICS,
  datasetRefreshConflict,
  filterDatasetRecentRuns,
  invalidateOpsDatasetQueries,
  opsDatasetLiveBadgeLabel,
  resolveDatasetRefreshScope,
  useDatasetRefreshRequestStatus,
  useOpsDataset,
  useOpsDatasetPreviewMutation,
  useOpsDatasetRefreshNowMutation,
  useOpsDatasets,
  useUpsertOpsDatasetRefreshPolicyMutation,
} from "@/api/datasets";
import { useOpsLiveInvalidation, type OpsLiveTopic } from "@/api/live";
import { AdminShell } from "@/components/admin-shell";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { integerString, ordered, validateForm } from "@/lib/form-validation";

import {
  datasetGridOpenIssueCount,
  datasetRowHasOpenIssue,
  datasetRowOpenIssueCount,
} from "./dataset-issues";

const PANELS = ["history", "policy", "preview"] as const;
type DrawerPanel = (typeof PANELS)[number];

function panelValue(value: string | null): DrawerPanel {
  return PANELS.includes(value as DrawerPanel) ? (value as DrawerPanel) : "history";
}

type DatasetSelection = {
  provider: string;
  datasetKey: string;
  syncScope: string;
};

/** text-safe stable tuple key — NUL 문자는 diff를 binary로 만들었다(리뷰 검출). */
function rowKey(row: OpsDatasetGridRow): string {
  return [row.provider, row.dataset_key, row.sync_scope]
    .map(encodeURIComponent)
    .join("|");
}

function selectionFromRow(row: OpsDatasetGridRow): DatasetSelection {
  return {
    provider: row.provider,
    datasetKey: row.dataset_key,
    syncScope: row.sync_scope,
  };
}

function sameRow(row: OpsDatasetGridRow, selection: DatasetSelection): boolean {
  return (
    row.provider === selection.provider &&
    row.dataset_key === selection.datasetKey &&
    row.sync_scope === selection.syncScope
  );
}

type DatasetGridActionContextValue = {
  activeSelection: DatasetSelection | null;
  openSelection: (selection: DatasetSelection) => void;
};

const DatasetGridActionContext =
  createContext<DatasetGridActionContextValue | null>(null);

function DatasetDetailToggleCell({
  row,
}: CellContext<OpsDatasetGridRow, unknown>) {
  const actions = useContext(DatasetGridActionContext);
  if (!actions) {
    throw new Error("DatasetDetailToggleCell requires DatasetGridActionContext");
  }
  const active = actions.activeSelection
    ? sameRow(row.original, actions.activeSelection)
    : false;
  return (
    <Button
      aria-label={`${row.original.provider} ${row.original.dataset_key} ${row.original.sync_scope} 상세 열기`}
      aria-controls={`dataset-detail-region-${rowKey(row.original)}`}
      aria-expanded={active}
      aria-pressed={active}
      id={`dataset-detail-toggle-${rowKey(row.original)}`}
      size="icon"
      type="button"
      variant={active ? "secondary" : "ghost"}
      onClick={(event) => {
        event.stopPropagation();
        actions.openSelection(selectionFromRow(row.original));
      }}
    >
      <PanelRightOpenIcon />
    </Button>
  );
}

function isCanonicalRepresentativeRow(row: OpsDatasetGridRow): boolean {
  return (
    row.catalog_state === "canonical" &&
    row.catalog !== null &&
    row.sync_scope === row.catalog.provider_state_default_scope
  );
}

function isNeverRun(row: OpsDatasetGridRow): boolean {
  return row.status === "never_run";
}

// 서버 계산 freshness 정본(#678/#684) — 브라우저 고정 48h 계산을 제거하고
// state·근거(threshold)를 그대로 렌더링한다.
const FRESHNESS_LABELS: Record<OpsDatasetFreshness["state"], string> = {
  never_run: "미실행",
  fresh: "신선",
  overdue: "오래됨",
  disabled: "비활성",
  unknown: "알 수 없음",
};

function freshnessVariant(
  state: OpsDatasetFreshness["state"],
): "outline" | "warning" | "destructive" | "secondary" {
  if (state === "overdue") return "warning";
  if (state === "disabled") return "secondary";
  if (state === "unknown") return "secondary";
  return "outline";
}

/** freshness 근거 문구 — basis/SLA/초과분을 사람이 읽게 표기. */
function freshnessReason(freshness: OpsDatasetFreshness): string {
  if (freshness.basis === "disabled") {
    return "갱신 정책 비활성";
  }
  if (freshness.basis === "unknown" || freshness.sla_seconds === null) {
    return "SLA(stale_after) 미설정 — 신선도 판단 불가";
  }
  const slaHours = Math.round((freshness.sla_seconds / 3600) * 10) / 10;
  if (freshness.is_overdue) {
    const overdueHours =
      Math.round((freshness.overdue_by_seconds / 3600) * 10) / 10;
    return `SLA ${slaHours}h 초과 +${overdueHours}h (기한 ${
      formatDateTime(freshness.due_at) ?? "-"
    })`;
  }
  return `SLA ${slaHours}h (기한 ${formatDateTime(freshness.due_at) ?? "-"})`;
}

function featuresHref(selection: DatasetSelection): string {
  return (
    `/admin/features?provider=${encodeURIComponent(selection.provider)}` +
    `&dataset_key=${encodeURIComponent(selection.datasetKey)}`
  );
}

/** 페이지 ①(pipeline, T-ADM-C5) 실행 상세 딥링크 — `{kind}:{id}` 형식(ADR-064 §3). */
function pipelineExecutionHref(kind: "update_request" | "import_job", id: string) {
  return `/ops/pipeline?execution=${kind}:${encodeURIComponent(id)}`;
}

// ── 갱신 정책 편집 (PUT /ops/datasets/refresh-policy?provider=&dataset_key=) ──

const sourceKinds = ["openapi", "filedata", "manual", "system"] as const;
const targetedPolicies = ["follow_system", "allow_targeted", "disabled"] as const;

type PolicyDraft = {
  source_kind: ProviderRefreshPolicyUpsertRequest["source_kind"] | "";
  targeted_policy: ProviderRefreshPolicyUpsertRequest["targeted_policy"];
  system_interval_seconds: string;
  optimal_interval_seconds: string;
  min_interval_seconds: string;
  max_requests_per_minute: string;
  max_requests_per_hour: string;
  max_requests_per_day: string;
  max_concurrent: string;
  burst_size: string;
  stale_after_minutes: string;
  enabled: boolean;
};

function numberText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/** 서버 정본 source_kind만 신뢰한다 — 없으면 명시 선택을 요구(추측 금지, #684). */
function sourceKindValue(
  value: string | null | undefined,
): ProviderRefreshPolicyUpsertRequest["source_kind"] | "" {
  return sourceKinds.includes(
    value as ProviderRefreshPolicyUpsertRequest["source_kind"],
  )
    ? (value as ProviderRefreshPolicyUpsertRequest["source_kind"])
    : "";
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

// full PUT에서 기존 nullable interval/quota를 임의 기본값으로 바꾸지 않는다
// (#684 — enabled만 바꿔도 기존 null은 null로 남아야 한다). 빈 입력 = null 유지.
function policyToDraft(
  policy: ProviderRefreshPolicyRecord | null | undefined,
): PolicyDraft {
  return {
    source_kind: sourceKindValue(policy?.source_kind),
    targeted_policy: targetedPolicyValue(policy?.targeted_policy),
    system_interval_seconds: numberText(policy?.system_interval_seconds),
    optimal_interval_seconds: numberText(policy?.optimal_interval_seconds),
    min_interval_seconds: numberText(policy?.min_interval_seconds),
    max_requests_per_minute: numberText(policy?.max_requests_per_minute),
    max_requests_per_hour: numberText(policy?.max_requests_per_hour),
    max_requests_per_day: numberText(policy?.max_requests_per_day),
    max_concurrent: numberText(policy?.max_concurrent ?? 1),
    burst_size: numberText(policy?.burst_size),
    stale_after_minutes: numberText(policy?.stale_after_minutes),
    enabled: policy?.enabled ?? true,
  };
}

/** 빈 입력은 **null**로 보낸다 — full PUT에서 기존 null이 임의 기본값으로 덮이지 않게. */
function optionalPositiveInt(value: string, label: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} 값은 양의 정수여야 합니다.`);
  }
  return parsed;
}

function buildPolicyBody(
  draft: PolicyDraft,
  expectedRevision: string | null,
): ProviderRefreshPolicyUpsertRequest {
  if (!draft.source_kind) {
    throw new Error(
      "소스 종류를 선택하세요 — 서버 정본이 없을 때 자동 추측하지 않습니다.",
    );
  }
  // rate_limit_source는 provenance(출처) 필드다 — UI 편집값이 아니라 서버가
  // 기록한다(#684, body에서 보내지 않음). config_source는 UI 저장 = db 출처라
  // 상수 "db"로 고정한다(사용자 편집 불가).
  return {
    expected_revision: expectedRevision,
    config_source: "db",
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
    stale_after_minutes: optionalPositiveInt(
      draft.stale_after_minutes,
      "stale after(분)",
    ),
    enabled: draft.enabled,
  };
}

/** "86400" → "86400초 = 24시간" 같은 사람 친화 표기. 해석 불가면 null. */
function humanizeSeconds(value: string): string | null {
  const parsed = Number(value.trim());
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  if (parsed >= 86_400 && parsed % 86_400 === 0) {
    return `${parsed}초 = ${parsed / 86_400}일`;
  }
  if (parsed >= 3_600 && parsed % 3_600 === 0) {
    return `${parsed}초 = ${parsed / 3_600}시간`;
  }
  if (parsed >= 60 && parsed % 60 === 0) {
    return `${parsed}초 = ${parsed / 60}분`;
  }
  return `${parsed}초`;
}

const POLICY_INT_FIELDS = [
  "system_interval_seconds",
  "optimal_interval_seconds",
  "min_interval_seconds",
  "max_requests_per_minute",
  "max_requests_per_hour",
  "max_requests_per_day",
  "max_concurrent",
  "burst_size",
  "stale_after_minutes",
] as const;

const POLICY_DRAFT_FIELDS = [
  "source_kind",
  "targeted_policy",
  ...POLICY_INT_FIELDS,
  "enabled",
] as const satisfies readonly (keyof PolicyDraft)[];

const POLICY_REPLAY_FIELDS = [
  "targeted_policy",
  ...POLICY_INT_FIELDS,
  "enabled",
] as const satisfies readonly (keyof PolicyDraft)[];

type PolicyRevisionConflict = {
  currentPolicy: ProviderRefreshPolicyRecord | null;
  currentRevision: string | null;
};

function policyDraftsEqual(left: PolicyDraft, right: PolicyDraft): boolean {
  return POLICY_DRAFT_FIELDS.every((field) => left[field] === right[field]);
}

function reconcilePolicyDraft(
  basePolicy: ProviderRefreshPolicyRecord | null,
  localDraft: PolicyDraft,
  latestPolicy: ProviderRefreshPolicyRecord | null,
): { draft: PolicyDraft; conflicts: (keyof PolicyDraft)[] } {
  const baseDraft = policyToDraft(basePolicy);
  const latestDraft = policyToDraft(latestPolicy);
  const draft = { ...latestDraft };
  const conflicts: (keyof PolicyDraft)[] = [];
  // source_kind는 row 생성 뒤 서버 불변 identity다. concurrent create loser의
  // 로컬 선택을 새 row 위에 재적용하지 않는다. 서버 row가 삭제된 경우에는
  // 다음 create에 필요하므로 local source_kind를 보존한다.
  const replayFields =
    latestPolicy === null ? POLICY_DRAFT_FIELDS : POLICY_REPLAY_FIELDS;
  for (const field of replayFields) {
    const localChanged = localDraft[field] !== baseDraft[field];
    if (!localChanged) continue;
    const serverChanged = latestDraft[field] !== baseDraft[field];
    if (serverChanged && latestDraft[field] !== localDraft[field]) {
      conflicts.push(field);
    }
    Object.assign(draft, { [field]: localDraft[field] });
  }
  return { draft, conflicts };
}

function policyRevisionConflict(error: Error): PolicyRevisionConflict | null {
  if (
    !(error instanceof ApiClientError) ||
    ![
      "PROVIDER_REFRESH_POLICY_REVISION_CONFLICT",
      "PROVIDER_REFRESH_POLICY_SOURCE_KIND_IMMUTABLE",
    ].includes(error.problem?.code ?? "")
  ) {
    return null;
  }
  const details = error.problem.details;
  if (typeof details !== "object" || details === null) {
    return null;
  }
  const raw = details as Record<string, unknown>;
  const currentRevision =
    typeof raw.current_revision === "string" ? raw.current_revision : null;
  const currentPolicy =
    typeof raw.current_record === "object" && raw.current_record !== null
      ? (raw.current_record as ProviderRefreshPolicyRecord)
      : null;
  return { currentPolicy, currentRevision };
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
  const [draftBasePolicy, setDraftBasePolicy] =
    useState<ProviderRefreshPolicyRecord | null>(policy ?? null);
  const [draftBaseRevision, setDraftBaseRevision] = useState<string | null>(
    policy?.revision ?? null,
  );
  const [latestObservedPolicy, setLatestObservedPolicy] =
    useState<ProviderRefreshPolicyRecord | null>(policy ?? null);
  const [latestObservedRevision, setLatestObservedRevision] = useState<
    string | null
  >(policy?.revision ?? null);
  const [hasDeferredServerPolicy, setHasDeferredServerPolicy] = useState(false);
  const [revisionConflict, setRevisionConflict] =
    useState<PolicyRevisionConflict | null>(null);
  const [reconcileMessage, setReconcileMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<string, string>>>(
    {},
  );
  const draftDirty = useRef(false);
  const observedPropRevision = useRef<string | null>(policy?.revision ?? null);
  const upsertPolicy = useUpsertOpsDatasetRefreshPolicyMutation();
  const saveBlocked = hasDeferredServerPolicy || revisionConflict !== null;

  const setField = (field: keyof PolicyDraft, value: string | boolean) => {
    draftDirty.current = true;
    setReconcileMessage(null);
    setDraft((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
  };

  const applyServerPolicy = useCallback(
    (nextPolicy: ProviderRefreshPolicyRecord | null | undefined) => {
      setDraft(policyToDraft(nextPolicy));
      setDraftBasePolicy(nextPolicy ?? null);
      setDraftBaseRevision(nextPolicy?.revision ?? null);
      setLatestObservedPolicy(nextPolicy ?? null);
      setLatestObservedRevision(nextPolicy?.revision ?? null);
      setFieldErrors({});
      setError(null);
      draftDirty.current = false;
      setHasDeferredServerPolicy(false);
      setRevisionConflict(null);
      setReconcileMessage(null);
    },
    [],
  );

  // 같은 정책의 background refetch는 작성 중인 draft를 건드리지 않는다. 서버의
  // 단조 revision이 실제로 바뀌었을 때만 동기화하고, 작성 중이면 명시적 선택 전까지
  // 보류해 운영자가 입력한 값을 조용히 덮어쓰지 않는다.
  useEffect(() => {
    const incomingRevision = policy?.revision ?? null;
    if (incomingRevision === observedPropRevision.current) {
      return;
    }
    observedPropRevision.current = incomingRevision;
    // 409 본문의 current record를 이미 반영한 뒤 query refetch가 같은 revision을
    // 전달하면 새 서버 변경으로 오인하지 않는다.
    if (incomingRevision === latestObservedRevision) {
      return;
    }
    setLatestObservedPolicy(policy ?? null);
    setLatestObservedRevision(incomingRevision);
    if (draftDirty.current) {
      setHasDeferredServerPolicy(true);
      return;
    }
    applyServerPolicy(policy);
  }, [applyServerPolicy, latestObservedRevision, policy]);

  const rebaseLocalDraftOnLatest = useCallback(() => {
    const reconciled = reconcilePolicyDraft(
      draftBasePolicy,
      draft,
      latestObservedPolicy,
    );
    const latestDraft = policyToDraft(latestObservedPolicy);
    setDraft(reconciled.draft);
    setDraftBasePolicy(latestObservedPolicy);
    setDraftBaseRevision(latestObservedRevision);
    draftDirty.current = !policyDraftsEqual(reconciled.draft, latestDraft);
    setHasDeferredServerPolicy(false);
    setRevisionConflict(null);
    setError(null);
    setReconcileMessage(
      reconciled.conflicts.length > 0
        ? `서버와 겹친 ${reconciled.conflicts.length}개 필드는 내 입력을 유지했습니다. 최신 revision 기준으로 다시 저장하세요.`
        : "서버 변경과 겹치지 않은 내 입력을 최신 revision 위에 다시 적용했습니다.",
    );
  }, [draft, draftBasePolicy, latestObservedPolicy, latestObservedRevision]);

  const submit = () => {
    if (saveBlocked) {
      return;
    }
    setError(null);
    setRevisionConflict(null);
    setReconcileMessage(null);
    // 빈 필드는 "null 유지" 의미라 검증하지 않는다 — 값이 있을 때만 양의 정수 검증.
    const filledIntFields = POLICY_INT_FIELDS.filter((field) =>
      String(draft[field] ?? "").trim(),
    );
    const orderedTriple = [
      "min_interval_seconds",
      "optimal_interval_seconds",
      "system_interval_seconds",
    ] as const;
    const result = validateForm(draft, [
      ...filledIntFields.map((field) => ({
        field: field as keyof PolicyDraft & string,
        validate: integerString<PolicyDraft>({
          min: 1,
          message: "양의 정수를 입력하세요.",
        }),
      })),
      ...(orderedTriple.every((field) => draft[field].trim())
        ? [
            {
              field: "min_interval_seconds" as keyof PolicyDraft & string,
              validate: ordered<PolicyDraft>(
                [...orderedTriple],
                "최소 ≤ 최적 ≤ 시스템 주기 순서를 지켜야 합니다.",
              ),
            },
          ]
        : []),
    ]);
    if (!result.isValid) {
      setFieldErrors(result.errors);
      return;
    }
    setFieldErrors({});
    let body: ProviderRefreshPolicyUpsertRequest;
    try {
      body = buildPolicyBody(draft, draftBaseRevision);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "policy payload를 만들 수 없습니다.",
      );
      return;
    }
    upsertPolicy.mutate(
      { provider, datasetKey, body },
      {
        onSuccess: (response) => applyServerPolicy(response.data),
        onError: (submitError) => {
          const conflict = policyRevisionConflict(submitError);
          if (conflict === null) return;
          setLatestObservedPolicy(conflict.currentPolicy);
          setLatestObservedRevision(conflict.currentRevision);
          if (conflict.currentPolicy !== null) {
            setDraft((current) => ({
              ...current,
              source_kind: sourceKindValue(conflict.currentPolicy?.source_kind),
            }));
          }
          setHasDeferredServerPolicy(true);
          setRevisionConflict(conflict);
        },
      },
    );
  };

  return (
    <div className="rounded-xl bg-surface-subtle p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium">갱신 정책</div>
          <div className="font-mono text-xs text-text-secondary">
            {provider}/{datasetKey}
          </div>
        </div>
        <Badge variant={draft.enabled ? "outline" : "destructive"}>
          {draft.enabled ? "활성" : "비활성"}
        </Badge>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {latestObservedPolicy?.source_kind ? (
          <FormField
            readOnly
            label="소스 종류"
            help="서버가 기록한 정본 값입니다(수정 불가)."
            value={draft.source_kind}
          />
        ) : (
          <FormSelect
            error={fieldErrors.source_kind}
            label="소스 종류"
            help="정책이 없어 서버 정본이 없습니다 — 자동 추측하지 않으니 명시 선택하세요."
            value={draft.source_kind}
            onChange={(event) =>
              setField(
                "source_kind",
                event.target.value as PolicyDraft["source_kind"],
              )
            }
          >
            <NativeSelectOption value="">선택하세요</NativeSelectOption>
            {sourceKinds.map((value) => (
              <NativeSelectOption key={value} value={value}>
                {value}
              </NativeSelectOption>
            ))}
          </FormSelect>
        )}
        <FormSelect
          label="타깃 갱신 정책"
          help="개별 지점 타깃 갱신을 허용/차단하거나 시스템 정책을 따를지 정합니다."
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
          error={fieldErrors.system_interval_seconds}
          hint={humanizeSeconds(draft.system_interval_seconds) ?? undefined}
          inputMode="numeric"
          label="시스템 주기(초)"
          help="시스템 자동 갱신이 도는 기본 간격(초)입니다."
          value={draft.system_interval_seconds}
          onChange={(event) =>
            setField("system_interval_seconds", event.target.value)
          }
        />
        <FormField
          error={fieldErrors.optimal_interval_seconds}
          hint={humanizeSeconds(draft.optimal_interval_seconds) ?? undefined}
          inputMode="numeric"
          label="최적 주기(초)"
          help="데이터 신선도상 권장되는 갱신 간격(초)입니다."
          value={draft.optimal_interval_seconds}
          onChange={(event) =>
            setField("optimal_interval_seconds", event.target.value)
          }
        />
        <FormField
          error={fieldErrors.min_interval_seconds}
          hint={humanizeSeconds(draft.min_interval_seconds) ?? undefined}
          inputMode="numeric"
          label="최소 주기(초)"
          help="이 간격보다 더 자주는 갱신하지 않습니다(과도 호출 방지)."
          value={draft.min_interval_seconds}
          onChange={(event) => setField("min_interval_seconds", event.target.value)}
        />
        <FormField
          error={fieldErrors.max_requests_per_minute}
          inputMode="numeric"
          label="분당 요청 수"
          value={draft.max_requests_per_minute}
          onChange={(event) =>
            setField("max_requests_per_minute", event.target.value)
          }
        />
        <FormField
          error={fieldErrors.max_requests_per_hour}
          inputMode="numeric"
          label="시간당 요청 수"
          value={draft.max_requests_per_hour}
          onChange={(event) =>
            setField("max_requests_per_hour", event.target.value)
          }
        />
        <FormField
          error={fieldErrors.max_requests_per_day}
          inputMode="numeric"
          label="일일 요청 수"
          help="무료키 일일 쿼터 보호 한도 — 초과 시 이후 요청이 차단됩니다."
          value={draft.max_requests_per_day}
          onChange={(event) =>
            setField("max_requests_per_day", event.target.value)
          }
        />
        <FormField
          error={fieldErrors.max_concurrent}
          inputMode="numeric"
          label="최대 동시 실행"
          value={draft.max_concurrent}
          onChange={(event) => setField("max_concurrent", event.target.value)}
        />
        <FormField
          error={fieldErrors.burst_size}
          inputMode="numeric"
          label="버스트 크기"
          help="순간적으로 허용되는 추가 요청 수(토큰 버킷 버스트)입니다."
          value={draft.burst_size}
          onChange={(event) => setField("burst_size", event.target.value)}
        />
        <FormField
          error={fieldErrors.stale_after_minutes}
          inputMode="numeric"
          label="신선도 SLA(분)"
          help="freshness 판단 기준(stale_after). 비우면 SLA 미설정 → 신선도 unknown."
          value={draft.stale_after_minutes}
          onChange={(event) =>
            setField("stale_after_minutes", event.target.value)
          }
        />
        <label className="flex items-center gap-2 self-end text-sm">
          <input
            checked={draft.enabled}
            type="checkbox"
            onChange={(event) => setField("enabled", event.target.checked)}
          />
          활성화
        </label>
      </div>
      {latestObservedPolicy ? (
        <div className="mt-4 rounded-md bg-card p-3 text-xs text-text-secondary">
          <div className="mb-1 font-medium text-text-primary">
            출처(provenance) — 서버 기록, 편집 불가
          </div>
          <p>
            config_source:{" "}
            <span className="font-mono">
              {latestObservedPolicy.config_source}
            </span>
          </p>
          <p className="mt-1">
            rate_limit_source:{" "}
            <span className="font-mono break-all">
              {JSON.stringify(latestObservedPolicy.rate_limit_source)}
            </span>
          </p>
          <p className="mt-1">
            초안 기준 revision:{" "}
            <span className="font-mono">{draftBaseRevision ?? "신규"}</span>
            {latestObservedRevision !== draftBaseRevision ? (
              <>
                {" "}· 최신 서버 revision:{" "}
                <span className="font-mono">
                  {latestObservedRevision ?? "없음"}
                </span>
              </>
            ) : null}
          </p>
        </div>
      ) : null}
      {revisionConflict ? (
        <Alert className="mt-3" variant="destructive">
          <AlertTitle>정책 저장 충돌</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-2">
            <span>
              입력 중인 초안은 그대로 보존했습니다. 서버 revision이{" "}
              {latestObservedRevision ?? "없음"}으로 바뀌어 저장하지 않았습니다.
            </span>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={rebaseLocalDraftOnLatest}
            >
              서버 기준으로 초안 조정
            </Button>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => applyServerPolicy(latestObservedPolicy)}
            >
              서버 값 다시 불러오기
            </Button>
          </AlertDescription>
        </Alert>
      ) : hasDeferredServerPolicy ? (
        <Alert className="mt-3" variant="destructive">
          <AlertTitle>서버 정책이 변경됨</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-2">
            <span>
              입력 중인 값은 유지했습니다. 저장 전에 최신 서버 revision을 기준으로
              초안을 조정하거나 서버 값을 다시 불러오세요.
            </span>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={rebaseLocalDraftOnLatest}
            >
              서버 기준으로 초안 조정
            </Button>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => applyServerPolicy(latestObservedPolicy)}
            >
              서버 값 다시 불러오기
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}
      {reconcileMessage ? (
        <Alert className="mt-3">
          <AlertTitle>초안 조정 완료</AlertTitle>
          <AlertDescription>{reconcileMessage}</AlertDescription>
        </Alert>
      ) : null}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          disabled={upsertPolicy.isPending || saveBlocked}
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
      {!revisionConflict && (error || upsertPolicy.isError) ? (
        <Alert className="mt-3" variant="destructive">
          <AlertTitle>정책 저장 실패</AlertTitle>
          <AlertDescription>{error ?? upsertPolicy.error?.message}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

// ── ETL 미리보기 (POST /ops/datasets/preview?provider=&dataset_key=) ─────

function PreviewPanel({
  selection,
  catalog,
}: {
  selection: DatasetSelection;
  catalog: OpsDatasetCatalogInfo | null | undefined;
}) {
  const preview = useOpsDatasetPreviewMutation();
  const result: OpsDatasetPreviewData | null = preview.data?.data ?? null;
  // #678 typed preview 계약 — fixture 전용(외부 호출 budget 0), capability로
  // 지원 여부를 fail-closed 판정한다. live 실행 경로는 계약에서 제거됐다.
  const capability = catalog?.preview ?? null;
  const fixtureSupported = Boolean(
    capability?.supported && (capability.sources ?? []).includes("fixture"),
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl bg-surface-subtle p-4">
        <div className="mb-1 font-medium">ETL 미리보기 (dry-run)</div>
        <p className="text-[13px] leading-normal text-text-secondary">
          provider raw → DTO 변환만 실행하고 제한된 typed 결과를 보여줍니다
          (DB 적재 없음, fixture 전용 — 외부 provider 호출 budget 0).
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            disabled={preview.isPending || !fixtureSupported}
            type="button"
            onClick={() =>
              preview.mutate({
                provider: selection.provider,
                datasetKey: selection.datasetKey,
                body: {
                  source: "fixture",
                  max_items: capability?.default_max_items ?? 20,
                },
              })
            }
          >
            <FlaskConicalIcon data-icon="inline-start" />
            fixture 실행
          </Button>
          <Badge variant={fixtureSupported ? "outline" : "secondary"}>
            {fixtureSupported
              ? `fixture 지원 (최대 ${capability?.max_items_limit ?? 100}건)`
              : "미리보기 미지원"}
          </Badge>
        </div>
        {!fixtureSupported ? (
          <p className="mt-2 text-[13px] text-text-tertiary">
            이 데이터셋은 preview capability가 없습니다 — 버튼이 비활성화됩니다
            (fail-closed).
          </p>
        ) : null}
      </div>
      {preview.isError ? (
        <Alert variant="destructive">
          <AlertTitle>미리보기 실패</AlertTitle>
          <AlertDescription>{preview.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {result ? (
        <div className="rounded-xl bg-surface-subtle p-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{result.source}</Badge>
            <Badge variant="outline">{result.variant}</Badge>
            <span className="text-[13px] text-text-secondary">
              {result.description} · {formatCount(result.returned_items)}/
              {formatCount(result.total_items)}건
              {result.truncated ? " (잘림)" : ""}
            </span>
          </div>
          <p className="mb-2 text-xs text-text-tertiary">
            budget: 외부 호출 {result.budget.external_call_budget}회 · 최대{" "}
            {result.budget.max_items}건 · {result.budget.timeout_seconds}s
          </p>
          <pre className="max-h-96 overflow-auto rounded-md bg-card p-3 text-xs">
            {JSON.stringify(result.items, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

// ── "지금 갱신" 인라인 폐루프 ───────────────────────────────────────────

// 백엔드 terminal 어휘 정본 = infra/feature_update_repo._TERMINAL_STATES
// ({"done","failed","cancelled"}) — "succeeded"는 존재하지 않는 상태다(리뷰 검출).
const TERMINAL_REQUEST_STATUSES = ["done", "failed", "cancelled"];
const ACTIVE_EXECUTION_STATUSES = ["queued", "running"];

function RefreshNowSection({
  selection,
  detail,
  latestExecution,
  detailLoading,
  detailError,
}: {
  selection: DatasetSelection;
  detail: OpsDatasetDetailData | null;
  latestExecution: OpsDatasetLatestExecution | null;
  detailLoading: boolean;
  detailError: boolean;
}) {
  const catalog = detail?.catalog ?? null;
  const queryClient = useQueryClient();
  const refreshNow = useOpsDatasetRefreshNowMutation();
  const [requestId, setRequestId] = useState<string | null>(null);
  const statusQuery = useDatasetRefreshRequestStatus(requestId);

  // 생성된 request의 WS topic 구독 — snapshot/update가 오면 live.ts가
  // canonical ["pipeline", "execution", "update_request", id] prefix를
  // 무효화해 statusQuery가 즉시 refetch된다.
  const liveTopics = useMemo<readonly OpsLiveTopic[]>(
    () => (requestId ? [`feature_update_request:${requestId}`] : []),
    [requestId],
  );
  useOpsLiveInvalidation({ topics: liveTopics, enabled: Boolean(requestId) });

  const currentStatus =
    statusQuery.data?.data.execution.status ?? refreshNow.data?.data.status ?? null;
  const localRequestActive = Boolean(
    requestId &&
      (!currentStatus || !TERMINAL_REQUEST_STATUSES.includes(currentStatus)),
  );
  const scopeRefresh = catalog?.scope_refresh ?? null;
  const scopeDecision = resolveDatasetRefreshScope(
    scopeRefresh,
    selection.syncScope,
    catalog?.provider_state_default_scope,
  );
  const activeLatestExecution =
    latestExecution &&
    (ACTIVE_EXECUTION_STATUSES.includes(latestExecution.status) ||
      ACTIVE_EXECUTION_STATUSES.includes(latestExecution.pair_status))
      ? latestExecution
      : null;

  // 완료(terminal) 전이 시 그리드/상세 신선도를 즉시 refetch — 인라인 폐루프.
  const notifiedStatus = useRef<string | null>(null);
  useEffect(() => {
    if (!currentStatus || notifiedStatus.current === currentStatus) {
      return;
    }
    notifiedStatus.current = currentStatus;
    if (TERMINAL_REQUEST_STATUSES.includes(currentStatus)) {
      invalidateOpsDatasetQueries(queryClient);
    }
  }, [currentStatus, queryClient]);

  // action capability는 fail-closed(#684) — 상세 로딩/오류·orphan·비가변·
  // 비-refreshable이면 활성화하지 않고 사유를 보여준다.
  const disabledReason = detailLoading
    ? "상세를 불러오는 중입니다 — 확인 후 활성화됩니다."
    : detailError
      ? "상세 조회에 실패해 조작을 차단했습니다(fail-closed)."
      : !detail
        ? "상세 정보가 없어 조작을 차단했습니다."
        : detail.provider !== selection.provider ||
            detail.dataset_key !== selection.datasetKey
          ? "상세 응답의 provider/dataset이 선택 행과 달라 조작을 차단했습니다."
          : !detail.scopes.some(
                (scope) => scope.sync_scope === selection.syncScope,
              )
            ? "선택한 exact sync scope가 상세 응답에 없어 조작을 차단했습니다."
        : detail.catalog_state === "orphan"
          ? `카탈로그에 없는 잔존 행이라 갱신할 수 없습니다${
              detail.orphan_reason ? ` (${detail.orphan_reason})` : ""
            }.`
          : !detail.mutable
            ? "이 행은 서버가 조작 불가(mutable=false)로 표시했습니다."
            : detail.refresh_policy?.enabled === false
              ? "서버 갱신 정책이 enabled=false라 수동 갱신도 차단됩니다. 정책 탭에서 활성화한 뒤 다시 시도하세요."
              : detail.refresh_policy?.targeted_policy === "disabled"
                ? "서버 갱신 정책이 targeted_policy=disabled라 이 데이터셋 갱신을 차단합니다. 정책 탭에서 허용 정책으로 변경하세요."
            : !catalog
              ? "카탈로그 계약이 없어 갱신 범위를 검증할 수 없습니다."
              : !catalog.is_refreshable
                ? (scopeRefresh?.reason ??
                  "이 데이터셋은 실행 가능한 refresh runner가 없습니다.")
                : !scopeDecision.allowed
                  ? scopeRefresh?.effect === "dataset_wide" &&
                      selection.syncScope !==
                        catalog.provider_state_default_scope
                    ? "dataset 전체 갱신은 provider의 기본 state scope 행에서만 실행할 수 있습니다. 이 행은 잔존 비기본 scope입니다."
                    : selection.syncScope.startsWith("external_system:")
                    ? "현재 활성 POI target에 없는 잔존 external scope라 갱신할 수 없습니다."
                    : scopeDecision.reason
                  : null;
  const existingConflict = datasetRefreshConflict(refreshNow.error);
  const conflict =
    refreshNow.error instanceof ApiClientError && refreshNow.error.status === 409;
  const retryAfterSeconds =
    conflict && refreshNow.error instanceof ApiClientError
      ? (refreshNow.error.retryAfterSeconds ?? null)
      : null;

  const submit = () => {
    // actor(operator)는 서버가 인증 컨텍스트에서 파생한다 — body로 보내지
    // 않는다(#684, 감사 위조 방지). reason만 사용자 입력.
    refreshNow.mutate(
      {
        provider: selection.provider,
        datasetKey: selection.datasetKey,
        syncScope: scopeDecision.allowed ? scopeDecision.syncScope : null,
        priority: 75,
        reason: "dataset refresh from ops/datasets",
      },
      { onSuccess: (data) => setRequestId(data.data.request_id) },
    );
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {activeLatestExecution ? (
          <span
            className="flex flex-wrap items-center gap-2 text-xs"
            data-testid="active-latest-execution"
          >
            <span>이미 진행 중인 canonical 실행</span>
            <StatusBadge status={activeLatestExecution.status} />
            <Badge variant="outline">
              pair {activeLatestExecution.pair_status}
            </Badge>
            <Link
              className="text-primary underline-offset-2 hover:underline"
              data-api-detail-url={activeLatestExecution.detail_url}
              href={pipelineExecutionHref(
                activeLatestExecution.kind,
                activeLatestExecution.id,
              )}
            >
              실행 {shortId(activeLatestExecution.id)} 보기
            </Link>
          </span>
        ) : localRequestActive && requestId ? (
          <span
            className="flex flex-wrap items-center gap-2 text-xs"
            data-testid="active-local-request"
          >
            <span>terminal 확인 전인 갱신 요청</span>
            <StatusBadge
              status={statusQuery.isError ? "unknown" : (currentStatus ?? "unknown")}
            />
            {statusQuery.isError ? (
              <Badge variant="destructive">상태 재확인 필요</Badge>
            ) : null}
            <Link
              className="text-primary underline-offset-2 hover:underline"
              href={pipelineExecutionHref("update_request", requestId)}
            >
              실행 {shortId(requestId)} 보기
            </Link>
          </span>
        ) : (
          <Button
            disabled={refreshNow.isPending || disabledReason !== null}
            type="button"
            onClick={submit}
          >
            <PlayIcon data-icon="inline-start" />
            지금 갱신
          </Button>
        )}
        {refreshNow.data ? (
          <Badge
            data-testid="refresh-create-result"
            variant={refreshNow.data.reused_active_request ? "warning" : "outline"}
          >
            {refreshNow.data.idempotent_replay
              ? "동일 요청 결과 재생(200)"
              : refreshNow.data.reused_active_request
                ? "활성 요청 재사용(200)"
                : "새 요청 생성(201)"}
          </Badge>
        ) : null}
        {requestId && currentStatus && !statusQuery.isError ? (
          <span className="flex items-center gap-2 text-xs">
            <StatusBadge status={currentStatus} />
            <Link
              className="text-primary underline-offset-2 hover:underline"
              href={pipelineExecutionHref("update_request", requestId)}
            >
              자세히
            </Link>
          </span>
        ) : null}
      </div>
      {scopeRefresh ? (
        <p className="text-xs text-text-tertiary">
          범위 계약: {scopeRefresh.selector === "poi_cache_targets"
            ? "활성 POI target"
            : "selector 없음"}
          {" · "}
          효과 {scopeRefresh.effect === "sync_scope" ? "선택 scope" : "dataset 전체"}
          {" · "}
          기본 <span className="font-mono">{scopeRefresh.default_sync_scope}</span>
        </p>
      ) : null}
      {disabledReason ? (
        <p className="text-[13px] leading-normal text-text-tertiary">
          {disabledReason}
        </p>
      ) : null}
      {refreshNow.isError ? (
        <Alert variant="destructive">
          <AlertTitle>
            {conflict ? "동일 범위 갱신이 이미 진행 중" : "갱신 요청 실패"}
          </AlertTitle>
          <AlertDescription>
            {existingConflict ? (
              <span className="flex flex-wrap items-center gap-2">
                <span>다른 실행 계획의 활성 요청이 이 범위를 점유하고 있습니다.</span>
                {existingConflict.status ? (
                  <StatusBadge status={existingConflict.status} />
                ) : null}
                <Link
                  className="text-primary underline-offset-2 hover:underline"
                  data-api-detail-url={existingConflict.detailUrl ?? undefined}
                  href={pipelineExecutionHref(
                    "update_request",
                    existingConflict.requestId,
                  )}
                >
                  기존 요청 {shortId(existingConflict.requestId)} 보기
                </Link>
              </span>
            ) : conflict
              ? retryAfterSeconds !== null
                ? `요청 경합 중입니다. 약 ${retryAfterSeconds}초 후 다시 시도하세요.`
                : "요청 경합 중입니다. 잠시 후 다시 시도하세요."
              : refreshNow.error.message}
          </AlertDescription>
        </Alert>
      ) : null}
      {requestId && statusQuery.isError ? (
        <Alert data-testid="refresh-status-error" variant="destructive">
          <AlertTitle>갱신 상태 확인 실패</AlertTitle>
          <AlertDescription className="space-y-1">
            <p>
              요청 {shortId(requestId)}은 생성됐지만 상태 조회가 실패했습니다 —
              마지막 확인 상태로 고정하지 않습니다.
            </p>
            <p className="break-all">{statusQuery.error.message}</p>
            <span className="flex items-center gap-2">
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={() => void statusQuery.refetch()}
              >
                다시 확인
              </Button>
              <Link
                className="text-primary underline-offset-2 hover:underline"
                href={pipelineExecutionHref("update_request", requestId)}
              >
                파이프라인에서 보기
              </Link>
            </span>
          </AlertDescription>
        </Alert>
      ) : null}
      {requestId && currentStatus === "done" ? (
        <Alert>
          <AlertTitle>갱신 완료</AlertTitle>
          <AlertDescription>
            요청 {shortId(requestId)}이 완료되어 행 신선도를 갱신했습니다.
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

// ── 상태·이력 패널 ──────────────────────────────────────────────────────

const scopeColumns: ColumnDef<OpsDatasetScopeState, unknown>[] = [
  {
    accessorKey: "sync_scope",
    header: "범위",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.sync_scope}</span>
    ),
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
      <span className="text-text-secondary">
        {formatDateTime(row.original.last_success_at)}
      </span>
    ),
  },
  {
    accessorKey: "last_failure_at",
    header: "마지막 실패",
    enableSorting: true,
    cell: ({ row }) => (
      <span className={row.original.last_failure_at ? "text-destructive" : "text-text-secondary"}>
        {formatDateTime(row.original.last_failure_at)}
      </span>
    ),
  },
  {
    id: "freshness",
    header: "신선도(SLA)",
    enableSorting: false,
    cell: ({ row }) => (
      <span
        className="flex flex-wrap items-center gap-1"
        title={freshnessReason(row.original.freshness)}
      >
        <Badge variant={freshnessVariant(row.original.freshness.state)}>
          {FRESHNESS_LABELS[row.original.freshness.state]}
        </Badge>
        <span className="text-xs text-text-tertiary">
          {formatDateTime(row.original.freshness.due_at)}
        </span>
      </span>
    ),
  },
  {
    // rate-limit/backoff상 재호출 가능 시각 — Dagster 스케줄 시각이 아니다(#684).
    accessorKey: "eligible_after",
    header: "재호출 가능(rate-limit)",
    enableSorting: true,
    cell: ({ row }) => (
      <span className="text-text-secondary">
        {formatDateTime(row.original.eligible_after)}
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

const recentRunColumns: ColumnDef<OpsDatasetLatestExecution, unknown>[] = [
  {
    id: "execution",
    header: "실행",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs">
        {row.original.kind === "update_request" ? "요청" : "잡"} {shortId(row.original.id)}
      </span>
    ),
  },
  {
    accessorKey: "status",
    header: "루트 상태",
    enableSorting: true,
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  },
  {
    accessorKey: "pair_status",
    header: "선택 pair",
    enableSorting: true,
    cell: ({ row }) => <StatusBadge status={row.original.pair_status} />,
  },
  {
    accessorKey: "sync_scope",
    header: "범위",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-xs">
        {row.original.sync_scope ?? "dataset 전체"}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "생성",
    enableSorting: true,
    cell: ({ row }) => (
      <span className="text-text-secondary">
        {formatDateTime(row.original.created_at)}
      </span>
    ),
  },
  {
    id: "pipeline",
    header: "파이프라인",
    enableSorting: false,
    cell: ({ row }) => (
      <Link
        className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
        href={pipelineExecutionHref(row.original.kind, row.original.id)}
        onClick={(event) => event.stopPropagation()}
      >
        <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
        실행 상세
      </Link>
    ),
  },
];

function EventRow({ event }: { event: OpsDatasetEventRecord }) {
  return (
    <li className="flex flex-wrap items-center gap-2 border-b border-surface-muted py-2 text-[13px] last:border-b-0">
      <StatusBadge status={event.level} />
      {event.code ? (
        <span className="font-mono text-xs text-text-secondary">{event.code}</span>
      ) : null}
      <span className="min-w-0 flex-1 break-all">{event.message}</span>
      <span className="text-xs text-text-tertiary">
        {formatDateTime(event.occurred_at)}
      </span>
    </li>
  );
}

function HistoryPanel({
  selection,
  detail,
  latestExecution,
}: {
  selection: DatasetSelection;
  detail: OpsDatasetDetailData | null;
  latestExecution: OpsDatasetLatestExecution | null;
}) {
  const selectedScope =
    detail?.scopes.find((scope) => scope.sync_scope === selection.syncScope) ?? null;
  const recentRuns = useMemo(
    () =>
      filterDatasetRecentRuns(
        detail?.recent_runs ?? [],
        selection.syncScope,
        detail?.catalog?.scope_refresh,
        detail?.catalog?.provider_state_default_scope,
      ),
    [detail, selection],
  );
  return (
    <div className="flex flex-col gap-3">
      <DataTable
        ariaLabel="sync scope 상태"
        columns={scopeColumns}
        data={detail?.scopes ?? []}
        getRowId={(scope) => scope.sync_scope}
        emptyMessage="sync scope 상태가 없습니다."
        manualSorting={false}
        containerClassName="overflow-auto rounded-xl bg-surface-subtle"
      />
      {!selectedScope ? (
        <Alert variant="destructive">
          <AlertTitle>선택 범위 상태 확인 불가</AlertTitle>
          <AlertDescription>
            상세 응답에 <span className="font-mono">{selection.syncScope}</span>
            범위가 없어 다른 scope로 대체하지 않았습니다(degrade, fail-closed).
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="rounded-xl bg-surface-subtle p-4">
        <div className="mb-2 font-medium">
          커서{" "}
          <span className="font-mono text-xs text-text-secondary">
            {selectedScope?.sync_scope ?? "-"}
          </span>
        </div>
        <pre className="max-h-64 overflow-auto rounded-md bg-card p-3 text-xs">
          {JSON.stringify(selectedScope?.cursor ?? {}, null, 2)}
        </pre>
      </div>
      <div className="rounded-xl bg-surface-subtle p-4">
        <div className="mb-2 font-medium">선택 범위 최신 실행</div>
        {latestExecution ? (
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <StatusBadge status={latestExecution.status} />
            <Badge variant="outline">pair {latestExecution.pair_status}</Badge>
            <span className="font-mono text-xs">
              {latestExecution.kind}:{shortId(latestExecution.id)}
            </span>
            <span className="text-text-secondary">
              {formatDateTime(latestExecution.created_at)}
            </span>
            <Link
              className="text-primary underline-offset-2 hover:underline"
              data-api-detail-url={latestExecution.detail_url}
              href={pipelineExecutionHref(
                latestExecution.kind,
                latestExecution.id,
              )}
            >
              실행 상세
            </Link>
          </div>
        ) : (
          <p className="text-[13px] text-text-secondary">
            이 범위에 정확히 대응하는 canonical 실행이 없습니다.
          </p>
        )}
      </div>
      <div className="rounded-xl bg-surface-subtle p-4">
        <div className="mb-2 font-medium">최근 실행</div>
        <p className="mb-2 text-xs text-text-tertiary">
          DB에 영속된 canonical operation 중 선택한 scope에 대응하는 실행만
          표시합니다. 다른 external scope 이력은 섞지 않습니다.
        </p>
        <DataTable
          ariaLabel="최근 실행"
          columns={recentRunColumns}
          data={recentRuns}
          getRowId={(run) => `${run.kind}:${run.id}`}
          emptyMessage="최근 실행 기록이 없습니다."
          manualSorting={false}
          containerClassName="overflow-auto rounded-md bg-card"
        />
      </div>
      <div className="rounded-xl bg-surface-subtle p-4">
        <div className="mb-2 font-medium">최근 이벤트</div>
        {detail && detail.recent_events.length > 0 ? (
          <ul>
            {detail.recent_events.map((event) => (
              <EventRow event={event} key={event.event_id} />
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-text-secondary">
            최근 이벤트가 없습니다.
          </p>
        )}
      </div>
    </div>
  );
}

// ── 행 상세 drawer ─────────────────────────────────────────────────────

function severitySummary(counts: Record<string, number>): string {
  const parts = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([severity, count]) => `${severity} ${count}`);
  return parts.length > 0 ? ` (${parts.join(" · ")})` : "";
}

function DatasetDrawer({
  selection,
  detail,
  latestExecution,
  isLoading,
  isError,
  activePanel,
  onPanelChange,
  onClose,
}: {
  selection: DatasetSelection;
  detail: OpsDatasetDetailData | null;
  latestExecution: OpsDatasetLatestExecution | null;
  isLoading: boolean;
  isError: boolean;
  activePanel: DrawerPanel;
  onPanelChange: (panel: DrawerPanel) => void;
  onClose: () => void;
}) {
  const catalog = detail?.catalog ?? null;
  const policyMutationBlockedReason = detail
    ? detail.catalog_state !== "canonical"
      ? `카탈로그 정본이 아닌 잔존 행이라 정책을 변경할 수 없습니다${
          detail.orphan_reason ? ` (${detail.orphan_reason})` : ""
        }.`
      : !detail.mutable
        ? "서버가 mutable=false로 표시한 행이라 정책 변경을 차단했습니다."
        : null
    : "상세 계약을 확인할 수 없어 정책 변경을 차단했습니다.";
  return (
    <div
      aria-label={`${selection.provider}/${selection.datasetKey} 상세`}
      className="rounded-lg border bg-background p-4"
      id={`dataset-detail-region-${[
        selection.provider,
        selection.datasetKey,
        selection.syncScope,
      ]
        .map(encodeURIComponent)
        .join("|")}`}
      role="region"
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium">데이터셋 상세</div>
          <div className="break-all font-mono text-xs text-text-secondary">
            {selection.provider}/{selection.datasetKey}
          </div>
          <div className="mt-1 break-all font-mono text-xs text-text-tertiary">
            sync_scope={selection.syncScope}
          </div>
          {catalog ? (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Badge variant="outline">{catalog.feature_kind}</Badge>
              <span className="text-[13px] text-text-secondary">
                {catalog.label}
              </span>
            </div>
          ) : (
            <p className="mt-1 text-[13px] text-text-tertiary">
              ETL 카탈로그에 없는 잔존 행입니다(상태 가시성만 유지).
            </p>
          )}
          <div className="mt-1 flex flex-wrap gap-3 text-xs">
            <Link
              className="text-primary underline-offset-2 hover:underline"
              href={featuresHref(selection)}
            >
              생성된 Feature 보기
            </Link>
            {detail && detail.dataset_issues.open_count > 0 ? (
              <Link
                className="text-primary underline-offset-2 hover:underline"
                href={
                  `/admin/issues?provider=${encodeURIComponent(selection.provider)}` +
                  `&dataset_key=${encodeURIComponent(selection.datasetKey)}`
                }
              >
                데이터셋 이슈 {formatCount(detail.dataset_issues.open_count)}건
                {severitySummary(detail.dataset_issues.severity_counts)}
              </Link>
            ) : null}
            {detail && detail.provider_issues.open_count > 0 ? (
              <Link
                className="text-primary underline-offset-2 hover:underline"
                href={`/admin/issues?provider=${encodeURIComponent(selection.provider)}`}
              >
                제공자 이슈 {formatCount(detail.provider_issues.open_count)}건
                {severitySummary(detail.provider_issues.severity_counts)}
              </Link>
            ) : null}
          </div>
        </div>
        <Button
          aria-label="데이터셋 상세 닫기"
          size="icon"
          type="button"
          variant="ghost"
          onClick={onClose}
        >
          <XIcon />
        </Button>
      </div>
      {detail && detail.schedule_source_status !== "ok" ? (
        <Alert
          className="mb-3"
          variant="destructive"
        >
          <AlertTitle>Dagster 스케줄 소스 이상</AlertTitle>
          <AlertDescription>
            {(detail.schedule_source_errors ?? []).length > 0
              ? (detail.schedule_source_errors ?? []).join(" / ")
              : "스케줄 상태를 확인할 수 없습니다(degrade)."}
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="mb-4">
        <RefreshNowSection
          detail={detail}
          detailError={isError}
          detailLoading={isLoading}
          latestExecution={latestExecution}
          selection={selection}
        />
      </div>
      {isLoading ? <Skeleton className="h-64" /> : null}
      {/* 상세가 로드된 뒤에만 패널을 mount한다 — PolicyEditor draft가 정책
          prefill 없이 초기화되는 mount-before-data 경쟁 방지. */}
      {detail ? (
        <Tabs
          value={activePanel}
          onValueChange={(value) => onPanelChange(panelValue(String(value)))}
        >
          <TabsList>
            <TabsTrigger value="history">상태·이력</TabsTrigger>
            <TabsTrigger value="policy">갱신 정책</TabsTrigger>
            <TabsTrigger value="preview">ETL 미리보기</TabsTrigger>
          </TabsList>
          <TabsContent value="history">
            <HistoryPanel
              detail={detail}
              latestExecution={latestExecution}
              selection={selection}
            />
          </TabsContent>
          <TabsContent keepMounted value="policy">
            {policyMutationBlockedReason ? (
              <Alert data-testid="policy-readonly-alert" variant="destructive">
                <AlertTitle>정책 변경 불가</AlertTitle>
                <AlertDescription>{policyMutationBlockedReason}</AlertDescription>
              </Alert>
            ) : (
              <PolicyEditor
                datasetKey={selection.datasetKey}
                key={`${selection.provider}/${selection.datasetKey}`}
                policy={detail.refresh_policy ?? null}
                provider={selection.provider}
              />
            )}
          </TabsContent>
          <TabsContent value="preview">
            <PreviewPanel catalog={catalog} selection={selection} />
          </TabsContent>
        </Tabs>
      ) : null}
    </div>
  );
}

// ── 페이지 본체 ────────────────────────────────────────────────────────

type StatusFilter = "" | "failing" | "stale" | "never_run" | "issues";

export function DatasetsClient({
  initialDataset = null,
  initialPanel = null,
  initialProvider = null,
  initialSyncScope = null,
}: {
  initialDataset?: string | null;
  initialPanel?: string | null;
  initialProvider?: string | null;
  initialSyncScope?: string | null;
}) {
  const live = useOpsLiveInvalidation({
    topics: OPS_DATASET_LIVE_TOPICS,
  });
  const pollingFallback = live.mode === "polling";
  const datasets = useOpsDatasets({ pollingFallback });
  const items = useMemo(() => datasets.data?.data.items ?? [], [datasets.data]);

  // 행 선택·panel은 URL query가 정본이다(#684) — 뒤로/앞으로 가기로 복원된다.
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // initial* prop은 **첫 렌더 시드로만** 쓴다 — 마운트 시 1회 URL에 반영한 뒤로는
  // searchParams만 신뢰한다. 영구 fallback으로 쓰면(구현 결함) URL 파라미터를 지운
  // 뒤에도 딥링크 값이 되살아나 닫기/Escape/back이 무력화된다(#684 리뷰 S2).
  const urlProvider = searchParams.get("provider");
  const urlDataset = searchParams.get("dataset");
  const urlSyncScope = searchParams.get("sync_scope");
  const activePanel = panelValue(searchParams.get("panel"));

  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const focusReturnIdRef = useRef<string | null>(null);
  const focusReturnFrameRef = useRef<number | null>(null);

  // 마운트 1회: URL에 선택이 없고 initial* 딥링크 prop이 있으면 URL에 seed한다
  // (replace — history 추가 없이). 이후 선택 상태는 오직 URL query가 정본.
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) {
      return;
    }
    seededRef.current = true;
    if (searchParams.get("provider") || !initialProvider) {
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    params.set("provider", initialProvider);
    if (initialDataset) {
      params.set("dataset", initialDataset);
    }
    if (initialSyncScope) {
      params.set("sync_scope", initialSyncScope);
    }
    if (initialPanel && PANELS.includes(initialPanel as DrawerPanel)) {
      params.set("panel", initialPanel);
    }
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  }, [
    initialDataset,
    initialPanel,
    initialProvider,
    initialSyncScope,
    pathname,
    router,
    searchParams,
  ]);

  const selectionResolution = useMemo(() => {
    const hasSelectionParams = Boolean(
      urlProvider || urlDataset || urlSyncScope,
    );
    if (!urlProvider) {
      return {
        selection: null,
        invalid: Boolean(urlDataset || urlSyncScope),
        canonicalize: false,
      };
    }
    if (items.length === 0) {
      return {
        selection: null,
        invalid: hasSelectionParams && datasets.data !== undefined,
        canonicalize: false,
      };
    }

    const providerRows = items.filter((row) => row.provider === urlProvider);
    if (providerRows.length === 0 || (!urlDataset && urlSyncScope)) {
      return { selection: null, invalid: true, canonicalize: false };
    }
    const datasetRows = urlDataset
      ? providerRows.filter((row) => row.dataset_key === urlDataset)
      : providerRows;
    const requested = urlSyncScope
      ? datasetRows.find((row) => row.sync_scope === urlSyncScope)
      : datasetRows.find(isCanonicalRepresentativeRow);
    if (!requested) {
      // provider/dataset/scope full tuple가 틀리면 같은 provider 첫 행으로
      // 대체하지 않는다. 잘못된 조작 대상이 열리는 것보다 명시 실패가 안전하다.
      return { selection: null, invalid: true, canonicalize: false };
    }
    return {
      selection: selectionFromRow(requested),
      invalid: false,
      // provider-only와 provider+dataset 링크는 catalog의 provider-state 기본
      // scope인 canonical 행으로만 확정한다. orphan/stale external이 목록 앞에
      // 있어도 대표 조작 대상으로 승격하지 않는다.
      canonicalize: !urlDataset || !urlSyncScope,
    };
  }, [datasets.data, items, urlDataset, urlProvider, urlSyncScope]);

  // 선택은 오직 URL query가 정본이다(#684 리뷰 S2) — items[0] 자동 선택
  // fallback을 두지 않는다. 그래야 닫기(X/Escape)·비딥링크 진입이 모두 동일한
  // 빈 상태로 수렴하고 닫기 컨트롤이 무력화되지 않는다.
  const resolvedSelection = selectionResolution.selection;
  const selectionCanonicalizing = Boolean(
    resolvedSelection && selectionResolution.canonicalize,
  );
  // provider-only/provider+dataset 링크는 완전한 tuple URL로 replace된 다음 렌더에서만
  // 조작 대상으로 승격한다. canonicalize effect 전에는 drawer와 mutation hook을
  // 열지 않아 화면 대상과 URL 정본이 잠시 어긋나는 경쟁을 제거한다.
  const activeSelection = selectionCanonicalizing ? null : resolvedSelection;
  const previousSelectionRef = useRef<DatasetSelection | null>(activeSelection);

  useEffect(() => {
    if (!resolvedSelection || !selectionResolution.canonicalize) {
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    params.set("provider", resolvedSelection.provider);
    params.set("dataset", resolvedSelection.datasetKey);
    params.set("sync_scope", resolvedSelection.syncScope);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [
    pathname,
    resolvedSelection,
    router,
    searchParams,
    selectionResolution.canonicalize,
  ]);

  const activeRow = useMemo(
    () =>
      activeSelection
        ? (items.find((row) => sameRow(row, activeSelection)) ?? null)
        : null,
    [activeSelection, items],
  );

  const applySelection = useCallback(
    (next: DatasetSelection | null, panel?: DrawerPanel) => {
      if (next) {
        // 닫기 navigation이 반영되기 전에 다른 행을 열면 이전 행으로 향하던
        // 지연 focus 예약을 폐기한다.
        focusReturnIdRef.current = null;
        if (focusReturnFrameRef.current !== null) {
          cancelAnimationFrame(focusReturnFrameRef.current);
          focusReturnFrameRef.current = null;
        }
      }
      const params = new URLSearchParams(searchParams.toString());
      if (next) {
        params.set("provider", next.provider);
        params.set("dataset", next.datasetKey);
        params.set("sync_scope", next.syncScope);
      } else {
        params.delete("provider");
        params.delete("dataset");
        params.delete("sync_scope");
      }
      if (panel) {
        params.set("panel", panel);
      }
      const query = params.toString();
      const target = query ? `${pathname}?${query}` : pathname;
      // 선택·탭은 이 client 화면의 URL 상태다. router.push를 쓰면 query-only
      // 전환에도 RSC가 다시 내려와 focused grid DOM이 뒤늦게 교체된다.
      // Next가 useSearchParams와 연동하는 native History API로 history만 쌓아
      // 뒤로/앞으로 복원과 DOM identity를 함께 보존한다.
      window.history.pushState(null, "", target);
    },
    [pathname, searchParams],
  );

  const closeDetail = useCallback(() => {
    if (activeSelection) {
      focusReturnIdRef.current = `dataset-detail-toggle-${rowKey({
        provider: activeSelection.provider,
        dataset_key: activeSelection.datasetKey,
        sync_scope: activeSelection.syncScope,
      } as OpsDatasetGridRow)}`;
    }
    applySelection(null);
  }, [activeSelection, applySelection]);

  // X/Escape뿐 아니라 browser Back(popstate)로 drawer가 닫혀도 직전 행을
  // focus 복귀 대상으로 기록한다.
  useEffect(() => {
    const previous = previousSelectionRef.current;
    if (previous && !activeSelection && focusReturnIdRef.current === null) {
      focusReturnIdRef.current = `dataset-detail-toggle-${rowKey({
        provider: previous.provider,
        dataset_key: previous.datasetKey,
        sync_scope: previous.syncScope,
      } as OpsDatasetGridRow)}`;
    }
    previousSelectionRef.current = activeSelection;
  }, [activeSelection]);

  // router.push 직후에는 구 drawer DOM이 남아 있어 즉시 focus하면 URL 전환
  // 재렌더에서 초점이 다시 사라진다. 선택이 실제로 닫힌 렌더에서 복귀시킨다.
  useEffect(() => {
    const targetId = focusReturnIdRef.current;
    if (activeSelection || !targetId || typeof document === "undefined") {
      return;
    }
    const frame = requestAnimationFrame(() => {
      focusReturnFrameRef.current = null;
      if (focusReturnIdRef.current !== targetId) {
        return;
      }
      focusReturnIdRef.current = null;
      const target =
        document.getElementById(targetId) ??
        document.getElementById("datasets-q");
      target?.focus();
    });
    focusReturnFrameRef.current = frame;
    return () => {
      if (focusReturnFrameRef.current === frame) {
        cancelAnimationFrame(frame);
        focusReturnFrameRef.current = null;
      }
    };
  }, [activeSelection]);

  // 상세가 열려 있을 때 Escape로 닫는다 — window 리스너라 drawer focus와 무관하게
  // 동작한다(#684 리뷰 S2 e2e: 닫기 컨트롤 실동작 보장).
  useEffect(() => {
    if (!activeSelection) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeDetail();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeSelection, closeDetail]);

  const detail = useOpsDataset(
    activeSelection
      ? {
          provider: activeSelection.provider,
          datasetKey: activeSelection.datasetKey,
          syncScope: activeSelection.syncScope,
        }
      : null,
    { pollingFallback },
  );

  const filteredItems = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return items.filter((row) => {
      if (
        needle &&
        !`${row.provider} ${row.dataset_key}`.toLowerCase().includes(needle)
      ) {
        return false;
      }
      if (statusFilter === "failing") return row.consecutive_failures > 0;
      if (statusFilter === "stale") return row.freshness.state === "overdue";
      if (statusFilter === "never_run") return isNeverRun(row);
      if (statusFilter === "issues") return datasetRowHasOpenIssue(row);
      return true;
    });
  }, [items, q, statusFilter]);

  const summary = useMemo(() => {
    const providers = new Set(items.map((row) => row.provider));
    const failing = items.filter((row) => row.consecutive_failures > 0).length;
    const stale = items.filter(
      (row) => row.freshness.state === "overdue",
    ).length;
    const neverRun = items.filter((row) => isNeverRun(row)).length;
    const issues = datasetGridOpenIssueCount(items);
    return { providers: providers.size, failing, stale, neverRun, issues };
  }, [items]);

  const columns = useMemo<ColumnDef<OpsDatasetGridRow, unknown>[]>(
    () => [
      {
        id: "detail",
        header: "상세",
        enableSorting: false,
        cell: DatasetDetailToggleCell,
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
        cell: ({ row }) => (
          <span
            className="flex flex-wrap items-center gap-1"
            title={freshnessReason(row.original.freshness)}
          >
            <StatusBadge status={row.original.status} />
            <Badge variant={freshnessVariant(row.original.freshness.state)}>
              {FRESHNESS_LABELS[row.original.freshness.state]}
            </Badge>
          </span>
        ),
      },
      {
        id: "policy",
        header: "정책",
        accessorFn: (row) => row.refresh_policy?.targeted_policy ?? "",
        enableSorting: true,
        cell: ({ row }) =>
          row.original.refresh_policy ? (
            <Badge
              variant={row.original.refresh_policy.enabled ? "outline" : "destructive"}
            >
              {row.original.refresh_policy.targeted_policy}
            </Badge>
          ) : (
            <span className="text-text-secondary">-</span>
          ),
      },
      {
        accessorKey: "last_success_at",
        header: "마지막 성공",
        enableSorting: true,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.last_success_at)}
          </span>
        ),
      },
      {
        accessorKey: "last_failure_at",
        header: "마지막 실패",
        enableSorting: true,
        cell: ({ row }) => (
          <span
            className={
              row.original.last_failure_at
                ? "text-destructive"
                : "text-text-secondary"
            }
          >
            {formatDateTime(row.original.last_failure_at)}
          </span>
        ),
      },
      {
        // Dagster futureTicks 기반 실제 스케줄 시각 — rate-limit eligibility
        // (eligible_after, scope 표)와 다른 개념이라 별도 라벨을 쓴다(#684).
        id: "next_scheduled_at",
        header: "다음 스케줄(Dagster)",
        accessorFn: (row) => row.schedule.next_scheduled_at ?? "",
        enableSorting: true,
        cell: ({ row }) => {
          const schedule = row.original.schedule;
          if (schedule.basis === "unknown") {
            // Dagster GraphQL degrade — "스케줄 없음"(not_scheduled)과 구분한다.
            return (
              <Badge title={schedule.status ?? undefined} variant="secondary">
                확인 불가
              </Badge>
            );
          }
          return (
            <span className="text-text-secondary">
              {schedule.basis === "not_scheduled"
                ? "스케줄 없음"
                : (formatDateTime(schedule.next_scheduled_at) ?? "-")}
            </span>
          );
        },
      },
      {
        accessorKey: "consecutive_failures",
        header: "실패",
        enableSorting: true,
        cell: ({ row }) =>
          row.original.consecutive_failures > 0 ? (
            <Badge variant="destructive">{row.original.consecutive_failures}</Badge>
          ) : (
            <span className="text-text-secondary">0</span>
          ),
      },
      {
        id: "issues",
        header: "이슈",
        accessorFn: (row) => datasetRowOpenIssueCount(row),
        enableSorting: true,
        cell: ({ row }) => (
          <span className="flex flex-wrap items-center gap-1">
            {row.original.dataset_issues.open_count > 0 ? (
              <Badge
                title={`데이터셋 이슈${severitySummary(row.original.dataset_issues.severity_counts)}`}
                variant="destructive"
              >
                {formatCount(row.original.dataset_issues.open_count)}
              </Badge>
            ) : null}
            {row.original.provider_issues.open_count > 0 ? (
              <Badge
                title={`제공자 이슈${severitySummary(row.original.provider_issues.severity_counts)}`}
                variant="warning"
              >
                P{formatCount(row.original.provider_issues.open_count)}
              </Badge>
            ) : null}
            {!datasetRowHasOpenIssue(row.original) ? (
              <span className="text-text-secondary">-</span>
            ) : null}
          </span>
        ),
      },
    ],
    [],
  );

  const gridActions = useMemo<DatasetGridActionContextValue>(
    () => ({
      activeSelection,
      openSelection: (selection) => applySelection(selection),
    }),
    [activeSelection, applySelection],
  );

  return (
    <AdminShell
      actions={
        <Button
          disabled={datasets.isFetching || detail.isFetching}
          type="button"
          variant="outline"
          onClick={() => {
            void datasets.refetch();
            void detail.refetch();
          }}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="provider×dataset×범위의 신선도·갱신 정책·이슈를 한 화면에서 추적하고, 정책 편집·ETL 미리보기·지금 갱신을 실행합니다."
      title="데이터셋"
    >
      <div className="flex flex-col gap-4">
        {datasets.isError ? (
          <Alert variant="destructive">
            <AlertTitle>데이터셋 조회 실패</AlertTitle>
            <AlertDescription>{datasets.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {selectionResolution.invalid ? (
          <Alert data-testid="invalid-dataset-deep-link" variant="destructive">
            <AlertTitle>유효하지 않은 데이터셋 링크</AlertTitle>
            <AlertDescription>
              URL의 provider/dataset/sync_scope 조합과 정확히 일치하는 행이 없어
              상세와 조작을 열지 않았습니다. 목록에서 올바른 행을 선택하세요.
            </AlertDescription>
          </Alert>
        ) : null}

        <section className="flex flex-wrap gap-2">
          <Badge
            data-testid="datasets-live-mode"
            title={live.lastError ?? `ops live: ${live.state}`}
            variant={
              live.mode === "live"
                ? "outline"
                : live.mode === "polling"
                  ? "warning"
                  : live.mode === "standby"
                    ? "secondary"
                    : "destructive"
            }
          >
            {opsDatasetLiveBadgeLabel(live)}
          </Badge>
          <Badge variant="outline">제공자 {formatCount(summary.providers)}</Badge>
          <Badge variant="outline">행 {formatCount(items.length)}</Badge>
          <Badge variant={summary.failing > 0 ? "destructive" : "outline"}>
            실패 {formatCount(summary.failing)}
          </Badge>
          <Badge variant={summary.stale > 0 ? "warning" : "outline"}>
            오래됨(SLA 초과) {formatCount(summary.stale)}
          </Badge>
          <Badge variant="outline">미실행 {formatCount(summary.neverRun)}</Badge>
          <Badge variant={summary.issues > 0 ? "destructive" : "outline"}>
            이슈 {formatCount(summary.issues)}
          </Badge>
        </section>

        {datasets.data && datasets.data.data.schedule_source_status !== "ok" ? (
          <Alert
            data-testid="schedule-degrade-banner"
            variant="destructive"
          >
            <AlertTitle>
              {datasets.data.data.schedule_source_status === "unavailable"
                ? "Dagster 스케줄 소스 연결 불가"
                : "Dagster 스케줄 소스 오류"}
            </AlertTitle>
            <AlertDescription>
              {(datasets.data.data.schedule_source_errors ?? []).length > 0
                ? (datasets.data.data.schedule_source_errors ?? []).join(" / ")
                : "다음 스케줄 시각을 확인할 수 없습니다 — '확인 불가'로 표시됩니다."}
            </AlertDescription>
          </Alert>
        ) : null}

        <FilterBar>
          <FilterField className="w-64" htmlFor="datasets-q" label="검색">
            <Input
              id="datasets-q"
              placeholder="제공자 · 데이터셋"
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
          </FilterField>
          <FilterField htmlFor="datasets-status" label="상태">
            <NativeSelect
              id="datasets-status"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value as StatusFilter)
              }
            >
              <NativeSelectOption value="">전체</NativeSelectOption>
              <NativeSelectOption value="failing">실패</NativeSelectOption>
              <NativeSelectOption value="stale">오래됨</NativeSelectOption>
              <NativeSelectOption value="never_run">미실행</NativeSelectOption>
              <NativeSelectOption value="issues">이슈 있음</NativeSelectOption>
            </NativeSelect>
          </FilterField>
        </FilterBar>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(30rem,0.9fr)]">
          <DatasetGridActionContext.Provider value={gridActions}>
            <DataTable
              ariaLabel="데이터셋 그리드"
              columns={columns}
              data={filteredItems}
              getRowId={(row) => rowKey(row)}
              isLoading={datasets.isLoading}
              emptyMessage="조건에 맞는 데이터셋 행이 없습니다."
              onRowClick={(row) => applySelection(selectionFromRow(row))}
              isRowActive={(row) =>
                activeSelection ? sameRow(row, activeSelection) : false
              }
              manualSorting={false}
              containerClassName="overflow-auto rounded-lg border bg-background"
            />
          </DatasetGridActionContext.Provider>

          <div
            className={`flex min-w-0 flex-col gap-4 ${
              activeSelection ? "order-first xl:order-none" : ""
            }`}
          >
            {activeSelection ? (
              <>
                {detail.isError ? (
                  <Alert variant="destructive">
                    <AlertTitle>데이터셋 상세 조회 실패</AlertTitle>
                    <AlertDescription>{detail.error.message}</AlertDescription>
                  </Alert>
                ) : null}
                <DatasetDrawer
                  activePanel={activePanel}
                  detail={detail.data?.data ?? null}
                  isError={detail.isError}
                  isLoading={detail.isLoading}
                  key={`${activeSelection.provider}/${activeSelection.datasetKey}/${activeSelection.syncScope}`}
                  latestExecution={activeRow?.latest_execution ?? null}
                  onClose={closeDetail}
                  onPanelChange={(panel) => applySelection(activeSelection, panel)}
                  selection={activeSelection}
                />
              </>
            ) : selectionCanonicalizing ? (
              <div
                className="rounded-lg border bg-background p-6 text-sm text-text-secondary"
                data-testid="dataset-selection-canonicalizing"
              >
                데이터셋 링크를 canonical provider/dataset/sync_scope 조합으로
                확정하는 중입니다. 완료 전에는 상세와 조작을 열지 않습니다.
              </div>
            ) : (
              <div className="rounded-lg border bg-background p-6 text-sm text-text-secondary">
                선택된 데이터셋 행이 없습니다.
              </div>
            )}
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
