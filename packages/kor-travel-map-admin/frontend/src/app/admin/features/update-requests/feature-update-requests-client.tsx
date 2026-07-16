"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { PlayIcon, RefreshCwIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import {
  type FeatureUpdateRequestPreviewRequest,
  type FeatureUpdateStatus,
  useCancelFeatureUpdateRequestMutation,
  useCreateFeatureUpdateRequestMutation,
  useFeatureUpdateRequests,
  usePreviewFeatureUpdateRequestMutation,
  useRunFeatureUpdateRequestNowMutation,
} from "@/api/updateRequests";
import { useProviders } from "@/api/etl";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge, statusLabel } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { ComboboxMultiple } from "@/components/ui/combobox-multiple";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatDateTime, shortId } from "@/lib/format";
import {
  combine,
  koreaLatitude,
  koreaLongitude,
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

type PreviewProviderDataset = {
  provider: string;
  datasetKey: string;
  featureCount: number;
};

function previewProviderDatasets(
  matchedScope: Record<string, unknown> | undefined,
): PreviewProviderDataset[] {
  const rawGroups =
    matchedScope?.provider_datasets ?? matchedScope?.deduped_provider_scopes;
  if (!Array.isArray(rawGroups)) {
    return [];
  }
  return rawGroups.flatMap((group) => {
    if (
      typeof group !== "object" ||
      group === null ||
      !("provider" in group) ||
      !("dataset_key" in group) ||
      !("feature_count" in group) ||
      typeof group.provider !== "string" ||
      typeof group.dataset_key !== "string" ||
      typeof group.feature_count !== "number"
    ) {
      return [];
    }
    return [
      {
        provider: group.provider,
        datasetKey: group.dataset_key,
        featureCount: group.feature_count,
      },
    ];
  });
}

export function FeatureUpdateRequestsClient() {
  const [status, setStatus] = useState<FeatureUpdateStatus | "all">("queued");
  const [lon, setLon] = useState("126.9780");
  const [lat, setLat] = useState("37.5665");
  const [radiusKm, setRadiusKm] = useState("5");
  const [providers, setProviders] = useState<string[]>([]);
  const [datasets, setDatasets] = useState("");
  const [previewOnly, setPreviewOnly] = useState(true);
  const [runMode, setRunMode] = useState<"queued" | "now">("queued");
  const [selectionError, setSelectionError] = useState<string | null>(null);
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
  const providersQuery = useProviders();
  const createRequest = useCreateFeatureUpdateRequestMutation();
  const previewRequest = usePreviewFeatureUpdateRequestMutation();
  const cancelRequest = useCancelFeatureUpdateRequestMutation();
  const runNow = useRunFeatureUpdateRequestNowMutation();
  const cancellation = cancelRequest.data?.data;
  const items = requests.data?.data.items ?? [];
  const cancelledJob = cancellation?.members.find(
    (member) => member.operation_kind === "feature_update_request",
  );
  const preview = previewRequest.data?.data;
  const previewFeatureCount =
    typeof preview?.matched_scope.feature_count === "number"
      ? preview.matched_scope.feature_count
      : null;
  const previewSigunguCodes = Array.isArray(
    preview?.matched_scope.sigungu_codes,
  )
    ? preview.matched_scope.sigungu_codes.filter(
        (code): code is string => typeof code === "string",
      )
    : [];
  const previewProviderDatasetGroups = previewProviderDatasets(
    preview?.matched_scope,
  );

  const providerOptions = useMemo(() => {
    const catalogOptions =
      providersQuery.data?.data.providers.map((entry) => ({
        value: entry.provider,
        label: entry.provider,
        description: `데이터셋 ${entry.datasets.length}개`,
      })) ?? [];
    const known = new Set(catalogOptions.map((option) => option.value));
    return [
      ...providers
        .filter((provider) => !known.has(provider))
        .map((provider) => ({ value: provider, label: provider })),
      ...catalogOptions,
    ];
  }, [providers, providersQuery.data?.data.providers]);
  type RequestRow = NonNullable<typeof requests.data>["data"]["items"][number];
  const columns = useMemo<ColumnDef<RequestRow, unknown>[]>(
    () => [
      {
        id: "request",
        header: "요청",
        enableSorting: false,
        cell: ({ row }) => {
          const id = row.original.request_id;
          return (
            <span className="font-mono text-xs">
              {id ? (
                <Link
                  className="underline underline-offset-2"
                  href={`/admin/features/update-requests/${id}`}
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
      { accessorKey: "scope_type", header: "범위" },
      {
        accessorKey: "status",
        header: "상태",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      { accessorKey: "run_mode", header: "모드" },
      {
        id: "providers",
        header: "제공자",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-56 truncate">
            {row.original.providers.join(", ") || "-"}
          </span>
        ),
      },
      {
        id: "job",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.job_id)}
          </span>
        ),
      },
      {
        accessorKey: "created_at",
        header: "생성",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "동작",
        enableSorting: false,
        cell: ({ row }) => {
          const request = row.original;
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
                      body: { reason: "cancelled from admin ui" },
                    })
                  }
                >
                  <XIcon data-icon="inline-start" />
                  취소
                </Button>
              ) : null}
              {["queued", "running"].includes(request.status) ? (
                <Button
                  disabled={runNow.isPending}
                  size="sm"
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    runNow.mutate({
                      requestId,
                      body: {},
                    })
                  }
                >
                  <PlayIcon data-icon="inline-start" />
                  즉시 실행
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
        validate: combine(required("경도를 입력하세요."), koreaLongitude()),
      },
      {
        field: "lat",
        validate: combine(required("위도를 입력하세요."), koreaLatitude()),
      },
      {
        field: "radiusKm",
        validate: combine(
          required("반경을 입력하세요."),
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
    const datasetKeys = commaSeparatedValues(datasets);
    if (providers.length === 0 && datasetKeys.length === 0) {
      setSelectionError("제공자 또는 데이터셋 키를 하나 이상 선택하세요.");
      return;
    }
    setSelectionError(null);
    const plan = {
      scope: {
        type: "center_radius",
        center: {
          lon: Number(values.lon),
          lat: Number(values.lat),
        },
        radius_km: Number(values.radiusKm),
      },
      providers,
      dataset_keys: datasetKeys,
      run_mode: runMode,
    } satisfies FeatureUpdateRequestPreviewRequest;
    createRequest.reset();
    previewRequest.reset();
    if (previewOnly) {
      previewRequest.mutate(plan);
      return;
    }
    createRequest.mutate({
      ...plan,
      reason: "admin ui request",
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
      description="좌표·반경·provider 기준 타깃 갱신 요청을 생성하고 상태를 추적합니다."
      section="수집 파이프라인"
      title="갱신 요청"
    >
      <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
        <div className="rounded-lg border bg-background p-4">
          <div className="mb-4">
            <div className="font-medium">새 요청</div>
            <div className="text-sm text-muted-foreground">
              중심점·반경 기준 스코프
            </div>
          </div>
          <div className="flex flex-col gap-3">
            <FormField
              error={errors.lon}
              label="경도"
              ref={lonRef}
              required
              value={lon}
              onChange={(e) => setLon(e.target.value)}
            />
            <FormField
              error={errors.lat}
              label="위도"
              ref={latRef}
              required
              value={lat}
              onChange={(e) => setLat(e.target.value)}
            />
            <FormField
              error={errors.radiusKm}
              label="반경(km)"
              ref={radiusKmRef}
              required
              value={radiusKm}
              onChange={(e) => setRadiusKm(e.target.value)}
            />
            <ComboboxMultiple
              disabled={providersQuery.isLoading}
              emptyMessage="일치하는 제공자가 없습니다."
              error={
                providersQuery.isError
                  ? providersQuery.error.message
                  : undefined
              }
              label="제공자"
              options={providerOptions}
              placeholder={
                providersQuery.isLoading
                  ? "불러오는 중"
                  : "제공자 선택(또는 데이터셋 키 입력)"
              }
              searchPlaceholder="제공자 검색"
              value={providers}
              onChange={(value) => {
                setProviders(value);
                if (value.length > 0) {
                  setSelectionError(null);
                }
              }}
            />
            <FormField
              label="데이터셋 키"
              hint="제공자 또는 dataset_key 중 하나는 필수입니다. 여러 키는 쉼표로 구분합니다."
              placeholder="예: mois_license_features_bulk"
              value={datasets}
              onChange={(event) => {
                setDatasets(event.target.value);
                if (commaSeparatedValues(event.target.value).length > 0) {
                  setSelectionError(null);
                }
              }}
            />
            {selectionError ? (
              <p className="text-sm text-destructive" role="alert">
                {selectionError}
              </p>
            ) : null}
            <FormSelect
              label="실행 모드"
              value={runMode}
              onChange={(event) =>
                setRunMode(event.target.value as "queued" | "now")
              }
            >
              <NativeSelectOption value="queued">
                예약(queued)
              </NativeSelectOption>
              <NativeSelectOption value="now">즉시(now)</NativeSelectOption>
            </FormSelect>
            <label className="flex items-center gap-2 text-sm">
              <input
                checked={previewOnly}
                type="checkbox"
                onChange={(event) => setPreviewOnly(event.target.checked)}
              />
              미리보기(요청을 저장하거나 실행하지 않음)
            </label>
            <Button
              disabled={createRequest.isPending || previewRequest.isPending}
              type="button"
              onClick={submit}
            >
              <PlayIcon data-icon="inline-start" />
              {previewOnly ? "미리보기" : "요청 생성"}
            </Button>
            {createRequest.data || previewRequest.data ? (
              <Alert>
                <AlertTitle>요청 처리 완료</AlertTitle>
                <AlertDescription>
                  {createRequest.data?.data.result_kind === "request" ? (
                    `${createRequest.data.data.request_id} · ${statusLabel(createRequest.data.data.status)}`
                  ) : preview ? (
                    <div className="space-y-1">
                      <div>미리보기 완료</div>
                      <div>
                        대상 Feature{" "}
                        {previewFeatureCount === null
                          ? "확인 불가"
                          : `${previewFeatureCount}개`}
                        {" · "}시군구 {previewSigunguCodes.length}개
                      </div>
                      <div>
                        범위 {preview.scope_type}
                        {" · "}실행 모드 {preview.run_mode}
                      </div>
                      <div>
                        요청 필터 · 제공자{" "}
                        {preview.providers.join(", ") || "전체"}
                        {" · "}데이터셋{" "}
                        {preview.dataset_keys.join(", ") || "전체"}
                      </div>
                      <div>
                        실제 적재 그룹 {previewProviderDatasetGroups.length}개
                      </div>
                      {previewProviderDatasetGroups.length > 0 ? (
                        <ul className="list-disc pl-5">
                          {previewProviderDatasetGroups.map((group) => (
                            <li key={`${group.provider}:${group.datasetKey}`}>
                              {group.provider} / {group.datasetKey}
                              {" · "}Feature {group.featureCount}개
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {previewSigunguCodes.length > 0 ? (
                        <div>시군구 코드 {previewSigunguCodes.join(", ")}</div>
                      ) : null}
                    </div>
                  ) : null}
                </AlertDescription>
              </Alert>
            ) : null}
            {createRequest.isError ? (
              <Alert variant="destructive">
                <AlertTitle>요청 생성 실패</AlertTitle>
                <AlertDescription>
                  {createRequest.error.message}
                </AlertDescription>
              </Alert>
            ) : null}
            {previewRequest.isError ? (
              <Alert variant="destructive">
                <AlertTitle>미리보기 실패</AlertTitle>
                <AlertDescription>
                  {previewRequest.error.message}
                </AlertDescription>
              </Alert>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col gap-4">
          {requests.isError ? (
            <Alert variant="destructive">
              <AlertTitle>요청 목록 조회 실패</AlertTitle>
              <AlertDescription>{requests.error.message}</AlertDescription>
            </Alert>
          ) : null}
          {cancelRequest.isError ? (
            <Alert variant="destructive">
              <AlertTitle>요청 취소 실패</AlertTitle>
              <AlertDescription>{cancelRequest.error.message}</AlertDescription>
            </Alert>
          ) : null}
          {cancellation ? (
            <Alert>
              <AlertTitle>요청 취소 처리 결과</AlertTitle>
              <AlertDescription>
                원 요청{" "}
                <Link
                  className="break-all font-mono underline underline-offset-2"
                  href={`/admin/features/update-requests/${cancellation.root.id}`}
                >
                  {cancellation.root.id}
                </Link>
                {" · "}원 요청 상태{" "}
                {cancelledJob?.terminal_status ??
                  cancelledJob?.result ??
                  "확인 중"}
                {" · "}취소 처리 상태 {cancellation.status}
              </AlertDescription>
            </Alert>
          ) : null}
          {runNow.isError ? (
            <Alert variant="destructive">
              <AlertTitle>즉시 실행 요청 실패</AlertTitle>
              <AlertDescription>{runNow.error.message}</AlertDescription>
            </Alert>
          ) : null}
          {runNow.data ? (
            <Alert>
              <AlertTitle>즉시 실행 요청 완료</AlertTitle>
              <AlertDescription>
                {runNow.data.data.status === "running"
                  ? "요청이 이미 실행 중입니다."
                  : "기존 요청의 즉시 dispatch를 요청했습니다."}{" "}
                <Link
                  className="break-all font-mono underline underline-offset-2"
                  href={`/admin/features/update-requests/${runNow.data.data.request_id}`}
                >
                  {runNow.data.data.request_id}
                </Link>
                상태를 확인하세요.
              </AlertDescription>
            </Alert>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect
              aria-label="요청 상태 필터"
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as FeatureUpdateStatus | "all")
              }
            >
              {statuses.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item === "all" ? "전체" : statusLabel(item)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Badge variant="outline">
              {requests.data?.data.items.length ?? 0}건
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
