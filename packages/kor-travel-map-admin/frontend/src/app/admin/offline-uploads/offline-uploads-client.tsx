"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  CheckCircle2Icon,
  Columns3Icon,
  FileUpIcon,
  PlayIcon,
  RefreshCwIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  type OfflineUploadColumnMapping,
  type OfflineUploadRecord,
  type OfflineUploadStatus,
  useCreateOfflineUploadMutation,
  useDeleteOfflineUploadMutation,
  useLaunchOfflineUploadLoadMutation,
  useOfflineUpload,
  useOfflineUploadPreview,
  useOfflineUploads,
  useOfflineUploadValidation,
  useValidateOfflineUploadMutation,
} from "@/api/offlineUploads";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime, shortId } from "@/lib/format";

const statuses: Array<OfflineUploadStatus | "all"> = [
  "uploaded",
  "validating",
  "validated",
  "validation_failed",
  "loading",
  "loaded",
  "load_failed",
  "cancelled",
  "all",
];

const loadableStates = new Set(["uploaded", "validated", "loaded", "load_failed"]);
const inProgressStates = new Set(["validating", "loading"]);
const tabularFormats = new Set(["csv", "tsv"]);
const byteFormatter = new Intl.NumberFormat("ko-KR");

const defaultColumnMapping: OfflineUploadColumnMapping = {
  name: "name",
  lon: "lon",
  lat: "lat",
  address: "address",
  source_id: "source_id",
  bjd_code: "bjd_code",
  category: "category",
  default_category: "02020101",
  default_marker_icon: "marker",
  default_marker_color: "P-01",
  default_place_kind: "offline_upload",
};

const requiredMappingFields: Array<keyof OfflineUploadColumnMapping> = [
  "name",
  "lon",
  "lat",
];

const optionalMappingFields: Array<keyof OfflineUploadColumnMapping> = [
  "address",
  "source_id",
  "bjd_code",
  "category",
  "default_category",
  "default_marker_icon",
  "default_marker_color",
  "default_place_kind",
];

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${byteFormatter.format(value)} B`;
  }
  if (value < 1024 * 1024) {
    return `${byteFormatter.format(Math.round(value / 1024))} KB`;
  }
  return `${byteFormatter.format(Math.round(value / 1024 / 1024))} MB`;
}

function uploadFormat(upload: OfflineUploadRecord): string {
  const detected = upload.detected_format?.toLowerCase();
  if (detected) {
    return detected;
  }
  const suffix = upload.original_filename.split(".").pop()?.toLowerCase();
  return suffix ?? "";
}

function isTabularUpload(upload: OfflineUploadRecord | null): boolean {
  return upload !== null && tabularFormats.has(uploadFormat(upload));
}

function canLoad(upload: OfflineUploadRecord): boolean {
  if (!loadableStates.has(upload.status)) {
    return false;
  }
  if (!isTabularUpload(upload)) {
    return true;
  }
  return (
    upload.validation_job_id !== null &&
    ["validated", "loaded", "load_failed"].includes(upload.status)
  );
}

function mappingPayload(
  mapping: OfflineUploadColumnMapping,
): OfflineUploadColumnMapping {
  const optional = Object.fromEntries(
    optionalMappingFields.map((field) => {
      const value = mapping[field];
      return [field, typeof value === "string" && value.trim() ? value.trim() : null];
    }),
  );
  return {
    ...optional,
    name: mapping.name.trim(),
    lon: mapping.lon.trim(),
    lat: mapping.lat.trim(),
    default_category: mapping.default_category?.trim() || "02020101",
    default_marker_icon: mapping.default_marker_icon?.trim() || "marker",
    default_marker_color: mapping.default_marker_color?.trim() || "P-01",
    default_place_kind: mapping.default_place_kind?.trim() || "offline_upload",
  };
}

function mappingComplete(mapping: OfflineUploadColumnMapping): boolean {
  return requiredMappingFields.every((field) => {
    const value = mapping[field];
    return typeof value === "string" && value.trim().length > 0;
  });
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 text-sm sm:grid-cols-[8rem_1fr]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-all font-mono text-xs">{value}</dd>
    </div>
  );
}

function UploadDetail({ upload }: { upload: OfflineUploadRecord | null }) {
  if (upload === null) {
    return (
      <div className="rounded-lg border border-dashed bg-background p-5 text-sm text-muted-foreground">
        목록에서 업로드를 선택하면 저장 key, checksum, validation/load job 상태를
        확인할 수 있습니다.
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-medium">{upload.original_filename}</div>
          <div className="font-mono text-xs text-muted-foreground">
            {shortId(upload.upload_id, 18)}
          </div>
        </div>
        <StatusBadge status={upload.status} />
      </div>
      <dl className="flex flex-col gap-3">
        <DetailRow label="provider" value={upload.provider} />
        <DetailRow label="dataset" value={upload.dataset_key} />
        <DetailRow label="scope" value={upload.sync_scope} />
        <DetailRow label="storage" value={`${upload.storage_backend}:${upload.storage_key}`} />
        <DetailRow label="size" value={formatBytes(upload.byte_size)} />
        <DetailRow label="sha256" value={upload.checksum_sha256} />
        <DetailRow label="format" value={upload.detected_format ?? "-"} />
        <DetailRow label="validation job" value={upload.validation_job_id ?? "-"} />
        <DetailRow label="load job" value={upload.load_job_id ?? "-"} />
        <DetailRow label="updated" value={formatDateTime(upload.updated_at)} />
      </dl>
    </div>
  );
}

function MappingInput({
  label,
  mapping,
  field,
  setMapping,
}: {
  label: string;
  mapping: OfflineUploadColumnMapping;
  field: keyof OfflineUploadColumnMapping;
  setMapping: (mapping: OfflineUploadColumnMapping) => void;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <Input
        aria-label={`mapping ${label}`}
        className="font-mono text-xs"
        value={(mapping[field] as string | null | undefined) ?? ""}
        onChange={(event) =>
          setMapping({ ...mapping, [field]: event.target.value })
        }
      />
    </label>
  );
}

type PreviewRow = Record<string, string>;

function PreviewTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: Array<PreviewRow>;
}) {
  // 컬럼이 동적(파싱된 header 배열)이므로 headers로부터 ColumnDef를 생성한다.
  // preview는 정렬/선택 불필요 — enableSorting 전부 false. 기존 header/cell의
  // font-mono/truncate/title 스타일은 렌더러로 그대로 옮긴다.
  const columns = useMemo<ColumnDef<PreviewRow, unknown>[]>(
    () =>
      headers.map((header) => ({
        id: header,
        accessorFn: (row) => row[header] ?? "",
        enableSorting: false,
        header: () => (
          <span className="whitespace-nowrap font-mono text-xs">{header}</span>
        ),
        cell: ({ row }) => {
          const value = row.original[header] ?? "";
          return (
            <span
              className="block max-w-56 truncate whitespace-nowrap text-xs"
              title={value}
            >
              {value}
            </span>
          );
        },
      })),
    [headers],
  );

  if (headers.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        preview 행이 없습니다.
      </div>
    );
  }

  return (
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(row) =>
        headers.map((header) => row[header] ?? "").join("")
      }
      emptyMessage="preview 행이 없습니다."
      containerClassName="max-h-80 overflow-auto rounded-md border"
    />
  );
}

type ValidationIssueRow = {
  severity: string;
  row_number?: number | null;
  column?: string | null;
  code: string;
  message: string;
};

const validationIssueColumns: ColumnDef<ValidationIssueRow, unknown>[] = [
  {
    accessorKey: "severity",
    header: "severity",
    cell: ({ row }) => <StatusBadge status={row.original.severity} />,
  },
  {
    accessorKey: "row_number",
    header: "row",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.row_number ?? "-"}</span>
    ),
  },
  {
    accessorKey: "column",
    header: "column",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.column ?? "-"}</span>
    ),
  },
  {
    accessorKey: "code",
    header: "code",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.code}</span>
    ),
  },
  {
    accessorKey: "message",
    header: "message",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="block max-w-xl">{row.original.message}</span>
    ),
  },
];

function ValidationPanel({
  selected,
  mapping,
  setMapping,
}: {
  selected: OfflineUploadRecord | null;
  mapping: OfflineUploadColumnMapping;
  setMapping: (mapping: OfflineUploadColumnMapping) => void;
}) {
  const isTabular = isTabularUpload(selected);
  const preview = useOfflineUploadPreview(selected?.upload_id ?? null, 20, isTabular);
  const validation = useOfflineUploadValidation(
    selected?.upload_id ?? null,
    isTabular && selected?.validation_job_id !== null,
  );
  const validateUpload = useValidateOfflineUploadMutation();
  const validationResult =
    validateUpload.data?.data.upload_id === selected?.upload_id
      ? validateUpload.data
      : validation.data;
  const issues = validationResult?.meta.issues ?? [];

  if (selected === null) {
    return (
      <div className="rounded-lg border border-dashed bg-background p-5 text-sm text-muted-foreground">
        CSV/TSV 업로드를 선택하면 column mapping과 validation 결과를 확인할 수 있습니다.
      </div>
    );
  }

  if (!isTabular) {
    return (
      <div className="rounded-lg border bg-background p-4">
        <div className="mb-1 flex items-center gap-2 font-medium">
          <Columns3Icon className="size-4 text-muted-foreground" />
          CSV/TSV validation
        </div>
        <p className="text-sm text-muted-foreground">
          이 업로드는 {uploadFormat(selected).toUpperCase() || "unknown"} 형식이라
          JSON/JSONL FeatureBundle load gate를 따릅니다.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-medium">
            <Columns3Icon className="size-4 text-muted-foreground" />
            CSV/TSV validation
          </div>
          <div className="text-sm text-muted-foreground">
            {uploadFormat(selected).toUpperCase()} ·{" "}
            {preview.data?.meta.rows_total ?? "-"} rows
          </div>
        </div>
        {validationResult ? (
          <Badge variant={validationResult.meta.error_rows > 0 ? "destructive" : "outline"}>
            {validationResult.meta.valid_rows} valid / {validationResult.meta.error_rows} error
          </Badge>
        ) : (
          <Badge variant="outline">not validated</Badge>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {requiredMappingFields.map((field) => (
          <MappingInput
            field={field}
            key={field}
            label={field}
            mapping={mapping}
            setMapping={setMapping}
          />
        ))}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        {optionalMappingFields.map((field) => (
          <MappingInput
            field={field}
            key={field}
            label={field}
            mapping={mapping}
            setMapping={setMapping}
          />
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          data-testid="offline-upload-validate"
          disabled={validateUpload.isPending || !mappingComplete(mapping)}
          type="button"
          onClick={() =>
            validateUpload.mutate({
              uploadId: selected.upload_id,
              columnMapping: mappingPayload(mapping),
              operator: "local-admin",
              sampleSize: 1000,
            })
          }
        >
          <CheckCircle2Icon data-icon="inline-start" />
          검증 실행
        </Button>
        {selected.validation_job_id ? (
          <Badge variant="outline">job {shortId(selected.validation_job_id)}</Badge>
        ) : null}
      </div>

      {(preview.isError || validation.isError || validateUpload.isError) && (
        <Alert className="mt-4" variant="destructive">
          <AlertTitle>validation 처리 실패</AlertTitle>
          <AlertDescription>
            {preview.error?.message ??
              validation.error?.message ??
              validateUpload.error?.message}
          </AlertDescription>
        </Alert>
      )}

      {preview.isLoading ? <Skeleton className="mt-4 h-44" /> : null}
      {preview.data ? (
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{preview.data.meta.headers.length} columns</Badge>
            <Badge variant="outline">{preview.data.meta.rows_sampled} sampled</Badge>
            <Badge variant="outline">
              sha256 {shortId(preview.data.meta.checksum_sha256_actual, 12)}
            </Badge>
          </div>
          <PreviewTable
            headers={preview.data.meta.headers}
            rows={preview.data.meta.sample_rows}
          />
        </div>
      ) : null}

      {validationResult ? (
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{validationResult.meta.valid_rows} valid</Badge>
            <Badge variant={validationResult.meta.error_rows > 0 ? "destructive" : "outline"}>
              {validationResult.meta.error_rows} error
            </Badge>
            <Badge variant="outline">{issues.length} issues</Badge>
          </div>
          <DataTable
            columns={validationIssueColumns}
            data={issues}
            getRowId={(issue, index) =>
              `${issue.code}-${issue.row_number ?? index}`
            }
            emptyMessage="validation issue가 없습니다."
            containerClassName="max-h-72 overflow-auto rounded-md border"
          />
        </div>
      ) : null}
    </div>
  );
}

export function OfflineUploadsClient() {
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("offline-test-provider");
  const [datasetKey, setDatasetKey] = useState("offline_csv");
  const [syncScope, setSyncScope] = useState("default");
  const [createdBy, setCreatedBy] = useState("local-admin");
  const [status, setStatus] = useState<OfflineUploadStatus | "all">("uploaded");
  const [providerFilter, setProviderFilter] = useState("");
  const [datasetFilter, setDatasetFilter] = useState("");
  const [selectedUploadId, setSelectedUploadId] = useState<string | null>(null);
  const [mapping, setMapping] =
    useState<OfflineUploadColumnMapping>(defaultColumnMapping);

  const uploadsParams = useMemo(
    () => ({
      status: status === "all" ? undefined : status,
      provider: providerFilter.trim() || undefined,
      dataset_key: datasetFilter.trim() || undefined,
      page_size: 100,
    }),
    [datasetFilter, providerFilter, status],
  );
  const uploads = useOfflineUploads(uploadsParams);
  const selectedUpload = useOfflineUpload(selectedUploadId);
  const createUpload = useCreateOfflineUploadMutation();
  const launchLoad = useLaunchOfflineUploadLoadMutation();
  const deleteUpload = useDeleteOfflineUploadMutation();

  const selected =
    selectedUpload.data?.data ??
    uploads.data?.data.items.find((item) => item.upload_id === selectedUploadId) ??
    null;

  const uploadItems = uploads.data?.data.items ?? [];

  // 셀 내부 mutation pending(.isPending)에 의존하는 disabled를 반영하기 위해
  // launchLoad/deleteUpload pending과 selectedUploadId를 deps로 메모이즈한다.
  const uploadColumns = useMemo<ColumnDef<OfflineUploadRecord, unknown>[]>(
    () => [
      {
        id: "upload",
        header: "upload",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.upload_id)}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "format",
        header: "format",
        accessorFn: (row) => uploadFormat(row),
        cell: ({ row }) => (
          <Badge variant="outline">{uploadFormat(row.original) || "-"}</Badge>
        ),
      },
      {
        id: "provider/dataset",
        header: "provider/dataset",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="max-w-64 truncate">{row.original.provider}</div>
            <div className="max-w-64 truncate text-xs text-muted-foreground">
              {row.original.dataset_key}/{row.original.sync_scope}
            </div>
          </>
        ),
      },
      {
        id: "file",
        header: "file",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex max-w-72 items-center gap-2 truncate">
            <FileUpIcon className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{row.original.original_filename}</span>
          </div>
        ),
      },
      {
        accessorKey: "byte_size",
        header: "size",
        cell: ({ row }) => formatBytes(row.original.byte_size),
      },
      {
        accessorKey: "updated_at",
        header: "updated",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.updated_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "actions",
        enableSorting: false,
        cell: ({ row }) => {
          const upload = row.original;
          const loadEnabled = canLoad(upload);
          return (
            <div className="flex items-center gap-1">
              <Button
                data-testid="offline-upload-load"
                disabled={launchLoad.isPending || !loadEnabled}
                size="sm"
                title={
                  loadEnabled
                    ? "load"
                    : "CSV/TSV는 validation 완료 후 load 가능"
                }
                type="button"
                variant={loadEnabled ? "outline" : "ghost"}
                onClick={(event) => {
                  event.stopPropagation();
                  setSelectedUploadId(upload.upload_id);
                  launchLoad.mutate(upload.upload_id);
                }}
              >
                <PlayIcon data-icon="inline-start" />
                load
              </Button>
              <Button
                data-testid="offline-upload-delete"
                disabled={
                  deleteUpload.isPending ||
                  inProgressStates.has(upload.status)
                }
                size="sm"
                title={
                  inProgressStates.has(upload.status)
                    ? "validation/load 진행 중에는 삭제 불가"
                    : "업로드 row + 저장 객체 삭제"
                }
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  deleteUpload.mutate(upload.upload_id, {
                    onSuccess: () => {
                      if (selectedUploadId === upload.upload_id) {
                        setSelectedUploadId(null);
                      }
                    },
                  });
                }}
              >
                <Trash2Icon data-icon="inline-start" />
                삭제
              </Button>
            </div>
          );
        },
      },
    ],
    [launchLoad, deleteUpload, selectedUploadId],
  );

  const submitUpload = () => {
    if (file === null) {
      return;
    }
    createUpload.mutate(
      {
        file,
        provider,
        datasetKey,
        syncScope,
        createdBy: createdBy.trim() || undefined,
      },
      {
        onSuccess: (data) => {
          setSelectedUploadId(data.data.upload_id);
        },
      },
    );
  };

  return (
    <AdminShell
      actions={
        <Button
          disabled={uploads.isFetching}
          type="button"
          variant="outline"
          onClick={() => void uploads.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="RustFS에 보존한 JSON/JSONL FeatureBundle 또는 CSV/TSV 원본을 검증하고 Dagster offline_upload_load job으로 적재합니다."
      section="Admin"
      title="Offline uploads"
    >
      <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border bg-background p-4">
            <div className="mb-4">
              <div className="font-medium">파일 업로드</div>
              <div className="text-sm text-muted-foreground">
                JSON/JSONL FeatureBundle, CSV/TSV tabular 원본
              </div>
            </div>
            <div className="flex flex-col gap-3">
              <FormField
                data-testid="offline-upload-file-input"
                label="file"
                type="file"
                accept=".json,.jsonl,.ndjson,.csv,.tsv,application/json,application/x-ndjson,text/csv,text/tab-separated-values"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <FormField
                label="provider"
                placeholder="provider"
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
              />
              <FormField
                label="dataset key"
                placeholder="dataset_key"
                value={datasetKey}
                onChange={(event) => setDatasetKey(event.target.value)}
              />
              <FormField
                label="sync scope"
                placeholder="sync_scope"
                value={syncScope}
                onChange={(event) => setSyncScope(event.target.value)}
              />
              <FormField
                label="created by"
                placeholder="created_by"
                value={createdBy}
                onChange={(event) => setCreatedBy(event.target.value)}
              />
              <Button
                data-testid="offline-upload-submit"
                disabled={
                  createUpload.isPending ||
                  file === null ||
                  provider.trim().length === 0 ||
                  datasetKey.trim().length === 0 ||
                  syncScope.trim().length === 0
                }
                type="button"
                onClick={submitUpload}
              >
                <UploadCloudIcon data-icon="inline-start" />
                업로드
              </Button>
              {createUpload.data ? (
                <Alert>
                  <AlertTitle>업로드 완료</AlertTitle>
                  <AlertDescription>
                    {shortId(createUpload.data.data.upload_id, 18)} ·{" "}
                    {createUpload.data.data.status} ·{" "}
                    {formatBytes(createUpload.data.data.byte_size)}
                  </AlertDescription>
                </Alert>
              ) : null}
              {createUpload.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>업로드 실패</AlertTitle>
                  <AlertDescription>{createUpload.error.message}</AlertDescription>
                </Alert>
              ) : null}
            </div>
          </div>

          <UploadDetail upload={selected} />
        </div>

        <div className="flex flex-col gap-4">
          {(uploads.isError ||
            launchLoad.isError ||
            deleteUpload.isError ||
            selectedUpload.isError) && (
            <Alert variant="destructive">
              <AlertTitle>offline upload 처리 실패</AlertTitle>
              <AlertDescription>
                {uploads.error?.message ??
                  launchLoad.error?.message ??
                  deleteUpload.error?.message ??
                  selectedUpload.error?.message}
              </AlertDescription>
            </Alert>
          )}
          {deleteUpload.data ? (
            <Alert>
              <AlertTitle>업로드 삭제됨</AlertTitle>
              <AlertDescription>
                {shortId(deleteUpload.data.data.upload_id, 18)} ·{" "}
                {deleteUpload.data.data.original_filename}
              </AlertDescription>
            </Alert>
          ) : null}
          {launchLoad.data ? (
            <Alert>
              <AlertTitle>Dagster load 실행됨</AlertTitle>
              <AlertDescription>
                {shortId(launchLoad.data.meta.dagster_run_id, 18)} ·{" "}
                {launchLoad.data.meta.dagster_status}
              </AlertDescription>
            </Alert>
          ) : null}

          <ValidationPanel
            mapping={mapping}
            selected={selected}
            setMapping={setMapping}
          />

          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect
              aria-label="offline upload status"
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as OfflineUploadStatus | "all")
              }
            >
              {statuses.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Input
              className="w-56"
              aria-label="provider filter"
              placeholder="provider filter"
              value={providerFilter}
              onChange={(event) => setProviderFilter(event.target.value)}
            />
            <Input
              className="w-56"
              aria-label="dataset filter"
              placeholder="dataset_key filter"
              value={datasetFilter}
              onChange={(event) => setDatasetFilter(event.target.value)}
            />
            <Badge variant="outline">
              {uploads.data?.data.items.length ?? 0} rows
            </Badge>
          </div>

          <DataTable
            columns={uploadColumns}
            data={uploadItems}
            getRowId={(row) => row.upload_id}
            isLoading={uploads.isLoading}
            emptyMessage="offline upload가 없습니다."
            onRowClick={(upload) => setSelectedUploadId(upload.upload_id)}
            isRowActive={(upload) => upload.upload_id === selectedUploadId}
            containerClassName="overflow-auto rounded-lg border bg-background"
          />
        </div>
      </div>
    </AdminShell>
  );
}
