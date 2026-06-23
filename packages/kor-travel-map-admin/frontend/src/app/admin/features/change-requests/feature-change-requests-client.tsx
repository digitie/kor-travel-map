"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  CheckIcon,
  ClipboardListIcon,
  PlusIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useMemo, useState, type FormEvent } from "react";

import {
  type AdminFeatureChangeAction,
  type AdminFeatureChangeRecord,
  type AdminFeatureChangeStatus,
  type AdminFeatureCreateRequest,
  type AdminFeaturePatchRequest,
  useAdminFeatureChangeRequests,
  useApproveAdminFeatureChangeMutation,
  useCreateAdminFeatureMutation,
  useDeleteAdminFeatureMutation,
  usePatchAdminFeatureMutation,
  useRejectAdminFeatureChangeMutation,
} from "@/api/features";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

const CHANGE_STATUSES: Array<AdminFeatureChangeStatus | "all"> = [
  "pending",
  "applied",
  "rejected",
  "all",
];
const CHANGE_ACTIONS: Array<AdminFeatureChangeAction | "all"> = [
  "all",
  "add",
  "update",
  "delete",
];
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;
const MUTATION_STATUSES = ["draft", "active", "inactive", "hidden"] as const;
const MUTATION_KINDS = ["place", "event"] as const;

type FeatureMutationStatus = (typeof MUTATION_STATUSES)[number];
type FeatureMutationKind = (typeof MUTATION_KINDS)[number];

interface FeatureChangeFormState {
  action: AdminFeatureChangeAction;
  addressJson: string;
  category: string;
  detailJson: string;
  featureId: string;
  idempotencyKey: string;
  kind: FeatureMutationKind;
  lat: string;
  lon: string;
  markerColor: string;
  markerIcon: string;
  name: string;
  operator: string;
  reason: string;
  sigunguCode: string;
  status: FeatureMutationStatus;
  urlsJson: string;
}

const EMPTY_JSON = "";

function initialForm(): FeatureChangeFormState {
  return {
    action: "add",
    addressJson: EMPTY_JSON,
    category: "01070300",
    detailJson: EMPTY_JSON,
    featureId: "",
    idempotencyKey: "",
    kind: "place",
    lat: "",
    lon: "",
    markerColor: "P-01",
    markerIcon: "marker",
    name: "",
    operator: "local-admin",
    reason: "",
    sigunguCode: "",
    status: "active",
    urlsJson: EMPTY_JSON,
  };
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function parseOptionalJsonObject(
  label: string,
  value: string,
): Record<string, unknown> | undefined {
  if (value.trim().length === 0) {
    return undefined;
  }
  const parsed = JSON.parse(value) as unknown;
  if (
    parsed === null ||
    Array.isArray(parsed) ||
    typeof parsed !== "object"
  ) {
    throw new Error(`${label}는 JSON object여야 합니다.`);
  }
  return parsed as Record<string, unknown>;
}

function parseOptionalCoord(
  lonValue: string,
  latValue: string,
): { lon: number; lat: number } | undefined {
  const hasLon = lonValue.trim().length > 0;
  const hasLat = latValue.trim().length > 0;
  if (!hasLon && !hasLat) {
    return undefined;
  }
  if (!hasLon || !hasLat) {
    throw new Error("lon과 lat은 함께 입력해야 합니다.");
  }
  const lon = Number(lonValue);
  const lat = Number(latValue);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    throw new Error("lon과 lat은 숫자여야 합니다.");
  }
  return { lon, lat };
}

function optionalString(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function buildCreatePayload(
  form: FeatureChangeFormState,
): AdminFeatureCreateRequest {
  if (form.name.trim().length === 0) {
    throw new Error("name은 필수입니다.");
  }
  if (form.category.trim().length === 0) {
    throw new Error("category는 필수입니다.");
  }
  if (form.reason.trim().length === 0) {
    throw new Error("reason은 필수입니다.");
  }
  return {
    kind: form.kind,
    name: form.name.trim(),
    category: form.category.trim(),
    coord: parseOptionalCoord(form.lon, form.lat),
    marker_icon: form.markerIcon.trim(),
    marker_color: form.markerColor.trim(),
    status: form.status,
    reason: form.reason.trim(),
    operator: optionalString(form.operator),
    feature_id: optionalString(form.featureId),
    idempotency_key: optionalString(form.idempotencyKey),
    sigungu_code: optionalString(form.sigunguCode),
    address: parseOptionalJsonObject("address", form.addressJson),
    detail: parseOptionalJsonObject("detail", form.detailJson),
    urls: parseOptionalJsonObject("urls", form.urlsJson),
  };
}

function buildPatchPayload(
  form: FeatureChangeFormState,
): AdminFeaturePatchRequest {
  if (form.featureId.trim().length === 0) {
    throw new Error("update에는 feature_id가 필요합니다.");
  }
  if (form.reason.trim().length === 0) {
    throw new Error("reason은 필수입니다.");
  }
  const coord = parseOptionalCoord(form.lon, form.lat);
  return {
    reason: form.reason.trim(),
    operator: optionalString(form.operator),
    name: optionalString(form.name),
    category: optionalString(form.category),
    coord,
    marker_icon: optionalString(form.markerIcon),
    marker_color: optionalString(form.markerColor),
    sigungu_code: optionalString(form.sigunguCode),
    address: parseOptionalJsonObject("address", form.addressJson),
    detail: parseOptionalJsonObject("detail", form.detailJson),
    urls: parseOptionalJsonObject("urls", form.urlsJson),
  };
}

function ChangeRequestDetail({
  request,
}: {
  request: AdminFeatureChangeRecord | null;
}) {
  if (!request) {
    return (
      <div className="rounded-lg border bg-background p-5 text-sm text-muted-foreground">
        요청 행을 선택하면 payload와 처리 시각을 확인할 수 있습니다.
      </div>
    );
  }

  return (
    <aside className="flex min-w-0 flex-col gap-4 rounded-lg border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-medium">Request detail</div>
          <div className="break-all font-mono text-xs text-muted-foreground">
            {request.request_id}
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge variant="outline">{request.action}</Badge>
          <StatusBadge status={request.status} />
        </div>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
        <dt className="text-muted-foreground">feature</dt>
        <dd className="break-all font-mono">{request.feature_id}</dd>
        <dt className="text-muted-foreground">mode</dt>
        <dd>{request.review_mode}</dd>
        <dt className="text-muted-foreground">requested</dt>
        <dd>{request.requested_by ?? "-"}</dd>
        <dt className="text-muted-foreground">reviewed</dt>
        <dd>{request.reviewed_by ?? "-"}</dd>
        <dt className="text-muted-foreground">created</dt>
        <dd>{formatDateTime(request.created_at)}</dd>
        <dt className="text-muted-foreground">applied</dt>
        <dd>{formatDateTime(request.applied_at)}</dd>
      </dl>
      <div>
        <div className="mb-2 text-sm font-medium">reason</div>
        <p className="text-sm text-muted-foreground">{request.reason ?? "-"}</p>
      </div>
      <div>
        <div className="mb-2 text-sm font-medium">payload</div>
        <JsonBlock value={request.payload} />
      </div>
    </aside>
  );
}

export function FeatureChangeRequestsClient() {
  const [status, setStatus] = useState<AdminFeatureChangeStatus | "all">("pending");
  const [action, setAction] = useState<AdminFeatureChangeAction | "all">("all");
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(100);
  const [q, setQ] = useState("");
  const deferredQ = useDeferredValue(q.trim());
  const [selectedRequest, setSelectedRequest] =
    useState<AdminFeatureChangeRecord | null>(null);
  const [form, setForm] = useState<FeatureChangeFormState>(() => initialForm());
  const [formError, setFormError] = useState<string | null>(null);

  const params = useMemo(
    () => ({
      status: status === "all" ? undefined : [status],
      action: action === "all" ? undefined : [action],
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: pageSize,
    }),
    [action, deferredQ, pageSize, status],
  );
  const changes = useAdminFeatureChangeRequests(params);
  const createFeature = useCreateAdminFeatureMutation();
  const patchFeature = usePatchAdminFeatureMutation();
  const deleteFeature = useDeleteAdminFeatureMutation();
  const approveChange = useApproveAdminFeatureChangeMutation();
  const rejectChange = useRejectAdminFeatureChangeMutation();
  const items = changes.data?.data.items ?? [];
  const reviewMode = changes.data?.data.review_mode ?? "unknown";
  const anyMutationPending =
    createFeature.isPending ||
    patchFeature.isPending ||
    deleteFeature.isPending ||
    approveChange.isPending ||
    rejectChange.isPending;
  const mutationError =
    createFeature.error ??
    patchFeature.error ??
    deleteFeature.error ??
    approveChange.error ??
    rejectChange.error;

  const updateForm = <K extends keyof FeatureChangeFormState>(
    key: K,
    value: FeatureChangeFormState[K],
  ) => setForm((current) => ({ ...current, [key]: value }));

  const resetForm = () => {
    setForm(initialForm());
    setFormError(null);
  };

  const submitChange = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    try {
      if (form.action === "add") {
        const response = await createFeature.mutateAsync(buildCreatePayload(form));
        setSelectedRequest(response.data.request);
      } else if (form.action === "update") {
        const featureId = form.featureId.trim();
        const response = await patchFeature.mutateAsync({
          featureId,
          body: buildPatchPayload(form),
        });
        setSelectedRequest(response.data.request);
      } else {
        const featureId = form.featureId.trim();
        if (featureId.length === 0) {
          throw new Error("delete에는 feature_id가 필요합니다.");
        }
        if (form.reason.trim().length === 0) {
          throw new Error("reason은 필수입니다.");
        }
        const response = await deleteFeature.mutateAsync({
          featureId,
          body: {
            operator: optionalString(form.operator),
            reason: form.reason.trim(),
          },
        });
        setSelectedRequest(response.data.request);
      }
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
    }
  };

  const approve = (request: AdminFeatureChangeRecord) => {
    approveChange.mutate(
      {
        requestId: request.request_id,
        body: { operator: "local-admin", reason: "admin-ui approve" },
      },
      { onSuccess: (data) => setSelectedRequest(data.data.request) },
    );
  };

  const reject = (request: AdminFeatureChangeRecord) => {
    rejectChange.mutate(
      {
        requestId: request.request_id,
        body: { operator: "local-admin", reason: "admin-ui reject" },
      },
      { onSuccess: (data) => setSelectedRequest(data.data.request) },
    );
  };

  const columns = useMemo<ColumnDef<AdminFeatureChangeRecord, unknown>[]>(
    () => [
      {
        id: "request",
        header: "request",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <>
              <div className="font-mono text-xs">
                {shortId(request.request_id, 18)}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {request.requested_by ?? "-"}
              </div>
            </>
          );
        },
      },
      {
        id: "action_status",
        header: "action/status",
        accessorFn: (request) => request.status,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <div className="flex flex-wrap gap-1">
              <Badge variant="outline">{request.action}</Badge>
              <StatusBadge status={request.status} />
            </div>
          );
        },
      },
      {
        id: "feature",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <div className="max-w-64">
              <div className="break-all font-mono text-xs">
                {shortId(request.feature_id, 28)}
              </div>
              {typeof request.payload.name === "string" ? (
                <div className="mt-1 truncate text-sm">
                  {request.payload.name}
                </div>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "review",
        header: "review",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          return (
            <>
              <div>{request.review_mode}</div>
              <div className="text-xs text-muted-foreground">
                {request.reviewed_by ?? "-"}
              </div>
            </>
          );
        },
      },
      {
        id: "reason",
        header: "reason",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-56 truncate">
            {row.original.reason ?? "-"}
          </span>
        ),
      },
      {
        accessorKey: "created_at",
        header: "created",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "actions",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
          if (request.status === "pending") {
            return (
              <div className="flex flex-wrap gap-1">
                <Button
                  disabled={anyMutationPending}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={(event) => {
                    event.stopPropagation();
                    approve(request);
                  }}
                >
                  <CheckIcon data-icon="inline-start" />
                  approve
                </Button>
                <Button
                  disabled={anyMutationPending}
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={(event) => {
                    event.stopPropagation();
                    reject(request);
                  }}
                >
                  <XIcon data-icon="inline-start" />
                  reject
                </Button>
              </div>
            );
          }
          if (request.action === "delete") {
            return (
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Trash2Icon className="size-3.5" />
                완료
              </div>
            );
          }
          return <span className="text-sm text-muted-foreground">완료</span>;
        },
      },
    ],
    [anyMutationPending, approve, reject],
  );

  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features"
          >
            <ClipboardListIcon data-icon="inline-start" />
            목록
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/new"
          >
            <PlusIcon data-icon="inline-start" />
            새 작성
          </Link>
          <Button
            disabled={changes.isFetching}
            type="button"
            variant="outline"
            onClick={() => void changes.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
      }
      description="Feature 추가·수정·삭제 요청을 한 큐에서 만들고 검토합니다."
      section="Admin"
      title="Feature change requests"
    >
      <div className="flex flex-col gap-4">
        {(changes.isError || mutationError || formError) && (
          <Alert variant="destructive">
            <AlertTitle>feature change 처리 실패</AlertTitle>
            <AlertDescription>
              {formError ?? changes.error?.message ?? mutationError?.message}
            </AlertDescription>
          </Alert>
        )}

        <section className="grid gap-3 md:grid-cols-4">
          <div className="rounded-lg border bg-background p-4">
            <div className="text-sm text-muted-foreground">review mode</div>
            <div className="mt-1 flex items-center gap-2">
              <StatusBadge status={reviewMode} />
            </div>
          </div>
          <div className="rounded-lg border bg-background p-4">
            <div className="text-sm text-muted-foreground">rows</div>
            <div className="mt-1 text-xl font-semibold">
              {formatCount(items.length)}
            </div>
          </div>
          <div className="rounded-lg border bg-background p-4">
            <div className="text-sm text-muted-foreground">limit</div>
            <div className="mt-1 text-xl font-semibold">
              {changes.data?.meta.page?.page_size ?? pageSize}
            </div>
          </div>
          <div className="rounded-lg border bg-background p-4">
            <div className="text-sm text-muted-foreground">duration</div>
            <div className="mt-1 text-xl font-semibold">
              {changes.data?.meta.duration_ms ?? 0}ms
            </div>
          </div>
        </section>

        <form
          className="rounded-lg border bg-background p-4"
          onSubmit={submitChange}
        >
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-medium">Change request form</div>
              <div className="text-sm text-muted-foreground">
                정본 admin feature mutation endpoint만 호출합니다.
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={resetForm}
              >
                <RotateCcwIcon data-icon="inline-start" />
                초기화
              </Button>
              <Button disabled={anyMutationPending} size="sm" type="submit">
                <PlusIcon data-icon="inline-start" />
                요청 생성
              </Button>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-4">
            <label
              className="flex flex-col gap-1 text-sm"
              htmlFor="change-action"
            >
              action
              <NativeSelect
                aria-label="change action"
                id="change-action"
                value={form.action}
                onChange={(event) =>
                  updateForm(
                    "action",
                    event.target.value as AdminFeatureChangeAction,
                  )
                }
              >
                <NativeSelectOption value="add">add</NativeSelectOption>
                <NativeSelectOption value="update">update</NativeSelectOption>
                <NativeSelectOption value="delete">delete</NativeSelectOption>
              </NativeSelect>
            </label>
            <label
              className="flex flex-col gap-1 text-sm"
              htmlFor="change-feature-id"
            >
              feature_id
              <Input
                aria-label="change feature id"
                id="change-feature-id"
                placeholder={
                  form.action === "add" ? "optional existing/new id" : "required"
                }
                value={form.featureId}
                onChange={(event) => updateForm("featureId", event.target.value)}
              />
            </label>
            <label
              className="flex flex-col gap-1 text-sm"
              htmlFor="change-reason"
            >
              reason
              <Input
                aria-label="change reason"
                id="change-reason"
                placeholder="운영 변경 사유"
                value={form.reason}
                onChange={(event) => updateForm("reason", event.target.value)}
              />
            </label>
            <label
              className="flex flex-col gap-1 text-sm"
              htmlFor="change-operator"
            >
              operator
              <Input
                aria-label="change operator"
                id="change-operator"
                value={form.operator}
                onChange={(event) => updateForm("operator", event.target.value)}
              />
            </label>
          </div>

          {form.action !== "delete" ? (
            <>
              <div className="mt-3 grid gap-3 lg:grid-cols-4">
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-kind"
                >
                  kind
                  <NativeSelect
                    aria-label="change kind"
                    id="change-kind"
                    value={form.kind}
                    onChange={(event) =>
                      updateForm("kind", event.target.value as FeatureMutationKind)
                    }
                  >
                    {MUTATION_KINDS.map((item) => (
                      <NativeSelectOption key={item} value={item}>
                        {item}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-status"
                >
                  status
                  <NativeSelect
                    aria-label="change feature status"
                    id="change-status"
                    value={form.status}
                    onChange={(event) =>
                      updateForm(
                        "status",
                        event.target.value as FeatureMutationStatus,
                      )
                    }
                  >
                    {MUTATION_STATUSES.map((item) => (
                      <NativeSelectOption key={item} value={item}>
                        {item}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-name"
                >
                  name
                  <Input
                    aria-label="change name"
                    id="change-name"
                    value={form.name}
                    onChange={(event) => updateForm("name", event.target.value)}
                  />
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-category"
                >
                  category
                  <Input
                    aria-label="change category"
                    id="change-category"
                    value={form.category}
                    onChange={(event) => updateForm("category", event.target.value)}
                  />
                </label>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-5">
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-lon"
                >
                  lon
                  <Input
                    aria-label="change lon"
                    id="change-lon"
                    inputMode="decimal"
                    value={form.lon}
                    onChange={(event) => updateForm("lon", event.target.value)}
                  />
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-lat"
                >
                  lat
                  <Input
                    aria-label="change lat"
                    id="change-lat"
                    inputMode="decimal"
                    value={form.lat}
                    onChange={(event) => updateForm("lat", event.target.value)}
                  />
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-marker-icon"
                >
                  marker_icon
                  <Input
                    aria-label="change marker icon"
                    id="change-marker-icon"
                    value={form.markerIcon}
                    onChange={(event) =>
                      updateForm("markerIcon", event.target.value)
                    }
                  />
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-marker-color"
                >
                  marker_color
                  <Input
                    aria-label="change marker color"
                    id="change-marker-color"
                    value={form.markerColor}
                    onChange={(event) =>
                      updateForm("markerColor", event.target.value)
                    }
                  />
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-sigungu-code"
                >
                  sigungu_code
                  <Input
                    aria-label="change sigungu code"
                    id="change-sigungu-code"
                    value={form.sigunguCode}
                    onChange={(event) =>
                      updateForm("sigunguCode", event.target.value)
                    }
                  />
                </label>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-4">
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-idempotency-key"
                >
                  idempotency_key
                  <Input
                    aria-label="change idempotency key"
                    id="change-idempotency-key"
                    value={form.idempotencyKey}
                    onChange={(event) =>
                      updateForm("idempotencyKey", event.target.value)
                    }
                  />
                </label>
                <label
                  className="flex flex-col gap-1 text-sm lg:col-span-3"
                  htmlFor="change-detail-json"
                >
                  detail JSON
                  <textarea
                    aria-label="change detail JSON"
                    className="min-h-24 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    id="change-detail-json"
                    value={form.detailJson}
                    onChange={(event) =>
                      updateForm("detailJson", event.target.value)
                    }
                  />
                </label>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-urls-json"
                >
                  urls JSON
                  <textarea
                    aria-label="change urls JSON"
                    className="min-h-24 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    id="change-urls-json"
                    value={form.urlsJson}
                    onChange={(event) => updateForm("urlsJson", event.target.value)}
                  />
                </label>
                <label
                  className="flex flex-col gap-1 text-sm"
                  htmlFor="change-address-json"
                >
                  address JSON
                  <textarea
                    aria-label="change address JSON"
                    className="min-h-24 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    id="change-address-json"
                    value={form.addressJson}
                    onChange={(event) =>
                      updateForm("addressJson", event.target.value)
                    }
                  />
                </label>
              </div>
            </>
          ) : null}
        </form>

        <section className="rounded-lg border bg-background p-4">
          <div className="grid gap-3 md:grid-cols-[minmax(12rem,1fr)_auto_auto_auto]">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="change search"
                className="pl-8"
                placeholder="feature_id, request_id, reason"
                value={q}
                onChange={(event) => setQ(event.target.value)}
              />
            </div>
            <NativeSelect
              aria-label="change status"
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as AdminFeatureChangeStatus | "all")
              }
            >
              {CHANGE_STATUSES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="change action filter"
              value={action}
              onChange={(event) =>
                setAction(event.target.value as AdminFeatureChangeAction | "all")
              }
            >
              {CHANGE_ACTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="change page size"
              value={String(pageSize)}
              onChange={(event) =>
                setPageSize(Number(event.target.value) as typeof pageSize)
              }
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        </section>

        <section className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_30rem]">
          <DataTable
            columns={columns}
            data={items}
            getRowId={(row) => row.request_id}
            isLoading={changes.isLoading}
            emptyMessage="feature change request가 없습니다."
            manualSorting={false}
            containerClassName="min-w-0 overflow-auto rounded-lg border bg-background"
            onRowClick={(row) => setSelectedRequest(row)}
            isRowActive={(row) =>
              selectedRequest?.request_id === row.request_id
            }
          />

          <ChangeRequestDetail request={selectedRequest} />
        </section>
      </div>
    </AdminShell>
  );
}
