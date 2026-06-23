"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { PlayIcon, RefreshCwIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import {
  type FeatureUpdateStatus,
  useCancelFeatureUpdateRequestMutation,
  useCreateFeatureUpdateRequestMutation,
  useFeatureUpdateRequests,
  useRunFeatureUpdateRequestNowMutation,
} from "@/api/updateRequests";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatDateTime, shortId } from "@/lib/format";
import {
  combine,
  numberInRange,
  required,
  validateForm,
} from "@/lib/form-validation";

const statuses: Array<FeatureUpdateStatus | "all"> = [
  "queued",
  "running",
  "done",
  "failed",
  "cancelled",
  "all",
];

function commaSeparatedValues(value: string): string[] {
  return value.split(",").flatMap((item) => {
    const trimmed = item.trim();
    return trimmed ? [trimmed] : [];
  });
}

export function FeatureUpdateRequestsClient() {
  const [status, setStatus] = useState<FeatureUpdateStatus | "all">("queued");
  const [lon, setLon] = useState("126.9780");
  const [lat, setLat] = useState("37.5665");
  const [radiusKm, setRadiusKm] = useState("5");
  const [providers, setProviders] = useState("");
  const [datasets, setDatasets] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [runMode, setRunMode] = useState<"queued" | "now">("queued");
  const [errors, setErrors] = useState<
    Partial<Record<"lon" | "lat" | "radiusKm", string>>
  >({});
  const lonRef = useRef<HTMLInputElement>(null);
  const latRef = useRef<HTMLInputElement>(null);
  const radiusKmRef = useRef<HTMLInputElement>(null);

  const requests = useFeatureUpdateRequests({
    status: status === "all" ? undefined : status,
    page_size: 100,
  });
  const createRequest = useCreateFeatureUpdateRequestMutation();
  const cancelRequest = useCancelFeatureUpdateRequestMutation();
  const runNow = useRunFeatureUpdateRequestNowMutation();

  const items = requests.data?.data.items ?? [];
  type RequestRow = NonNullable<typeof requests.data>["data"]["items"][number];
  const columns = useMemo<ColumnDef<RequestRow, unknown>[]>(
    () => [
      {
        id: "request",
        header: "request",
        enableSorting: false,
        cell: ({ row }) => {
          const id = row.original.request_id;
          return (
            <span className="font-mono text-xs">
              {id ? (
                <Link
                  className="underline underline-offset-2"
                  href={`/admin/feature-update-requests/${id}`}
                >
                  {shortId(id)}
                </Link>
              ) : (
                shortId(id)
              )}
            </span>
          );
        },
      },
      { accessorKey: "scope_type", header: "scope" },
      {
        accessorKey: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      { accessorKey: "run_mode", header: "mode" },
      {
        id: "providers",
        header: "providers",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-56 truncate">
            {row.original.providers.join(", ") || "-"}
          </span>
        ),
      },
      {
        id: "job",
        header: "job",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">{shortId(row.original.job_id)}</span>
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
          if (!request.request_id) {
            return <span className="text-sm text-muted-foreground">dry-run</span>;
          }
          const requestId = request.request_id;
          return (
            <div className="flex flex-wrap gap-1">
              {["queued", "running"].includes(request.status) ? (
                <Button
                  disabled={cancelRequest.isPending}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() =>
                    cancelRequest.mutate({
                      requestId,
                      body: { error_message: "cancelled from admin ui" },
                    })
                  }
                >
                  <XIcon data-icon="inline-start" />
                  cancel
                </Button>
              ) : null}
              {request.status !== "running" ? (
                <Button
                  disabled={runNow.isPending}
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    runNow.mutate({
                      requestId,
                      body: { reason: "run-now from admin ui" },
                    })
                  }
                >
                  run-now
                </Button>
              ) : null}
            </div>
          );
        },
      },
    ],
    [cancelRequest, runNow],
  );

  const submit = () => {
    const values = {
      lon: lonRef.current?.value ?? lon,
      lat: latRef.current?.value ?? lat,
      radiusKm: radiusKmRef.current?.value ?? radiusKm,
    };
    const result = validateForm(values, [
      {
        field: "lon",
        validate: combine(
          required("경도(lon)는 필수입니다."),
          numberInRange({ min: 124, max: 132, message: "경도는 124~132 범위여야 합니다." }),
        ),
      },
      {
        field: "lat",
        validate: combine(
          required("위도(lat)는 필수입니다."),
          numberInRange({ min: 33, max: 43, message: "위도는 33~43 범위여야 합니다." }),
        ),
      },
      {
        field: "radiusKm",
        validate: combine(
          required("반경(radius_km)은 필수입니다."),
          numberInRange({ min: 0.1, message: "반경은 0.1 이상이어야 합니다." }),
        ),
      },
    ]);
    setErrors(result.errors);
    if (!result.isValid) {
      const refByField = { lon: lonRef, lat: latRef, radiusKm: radiusKmRef };
      if (result.firstErrorField) {
        refByField[result.firstErrorField].current?.focus();
      }
      return;
    }
    setLon(values.lon);
    setLat(values.lat);
    setRadiusKm(values.radiusKm);
    createRequest.mutate({
      scope: {
        type: "center_radius",
        center: {
          lon: Number(values.lon),
          lat: Number(values.lat),
        },
        radius_km: Number(values.radiusKm),
      },
      providers: commaSeparatedValues(providers),
      dataset_keys: commaSeparatedValues(datasets),
      dry_run: dryRun,
      run_mode: runMode,
      operator: "local-admin",
      reason: dryRun ? "admin ui dry-run" : "admin ui request",
    });
  };

  return (
    <AdminShell
      actions={
        <Button
          disabled={requests.isFetching}
          type="button"
          variant="outline"
          onClick={() => void requests.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="좌표/반경/provider 기준 targeted feature update request를 생성하고 상태를 추적합니다."
      section="Admin"
      title="Feature update requests"
    >
      <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
        <div className="rounded-lg border bg-background p-4">
          <div className="mb-4">
            <div className="font-medium">새 요청</div>
            <div className="text-sm text-muted-foreground">
              center_radius scope payload
            </div>
          </div>
          <div className="flex flex-col gap-3">
            <FormField
              error={errors.lon}
              label="lon"
              ref={lonRef}
              required
              value={lon}
              onChange={(e) => setLon(e.target.value)}
            />
            <FormField
              error={errors.lat}
              label="lat"
              ref={latRef}
              required
              value={lat}
              onChange={(e) => setLat(e.target.value)}
            />
            <FormField
              error={errors.radiusKm}
              label="radius km"
              ref={radiusKmRef}
              required
              value={radiusKm}
              onChange={(e) => setRadiusKm(e.target.value)}
            />
            <FormField
              label="providers"
              placeholder="providers comma separated"
              value={providers}
              onChange={(e) => setProviders(e.target.value)}
            />
            <FormField
              label="dataset keys"
              placeholder="dataset_keys comma separated"
              value={datasets}
              onChange={(e) => setDatasets(e.target.value)}
            />
            <FormSelect
              label="run mode"
              value={runMode}
              onChange={(event) => setRunMode(event.target.value as "queued" | "now")}
            >
              <NativeSelectOption value="queued">queued</NativeSelectOption>
              <NativeSelectOption value="now">now</NativeSelectOption>
            </FormSelect>
            <label className="flex items-center gap-2 text-sm">
              <input
                checked={dryRun}
                type="checkbox"
                onChange={(event) => setDryRun(event.target.checked)}
              />
              dry-run
            </label>
            <Button
              disabled={createRequest.isPending}
              type="button"
              onClick={submit}
            >
              <PlayIcon data-icon="inline-start" />
              요청 생성
            </Button>
            {createRequest.data ? (
              <Alert>
                <AlertTitle>요청 처리 완료</AlertTitle>
                <AlertDescription>
                  {createRequest.data.data.request_id ?? "dry-run"} ·{" "}
                  {createRequest.data.data.status}
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
        </div>

        <div className="flex flex-col gap-4">
          {(requests.isError || cancelRequest.isError || runNow.isError) && (
            <Alert variant="destructive">
              <AlertTitle>request 처리 실패</AlertTitle>
              <AlertDescription>
                {requests.error?.message ??
                  cancelRequest.error?.message ??
                  runNow.error?.message}
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect
              aria-label="request status"
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as FeatureUpdateStatus | "all")
              }
            >
              {statuses.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Badge variant="outline">
              {requests.data?.data.items.length ?? 0} rows
            </Badge>
          </div>
          <DataTable
            columns={columns}
            data={items}
            getRowId={(row) => row.request_id ?? JSON.stringify(row.scope)}
            isLoading={requests.isLoading}
            emptyMessage="요청이 없습니다."
            manualSorting={false}
            containerClassName="rounded-lg border bg-background"
          />
        </div>
      </div>
    </AdminShell>
  );
}
