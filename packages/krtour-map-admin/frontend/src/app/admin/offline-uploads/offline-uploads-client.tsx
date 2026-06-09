"use client";

import {
  CheckCircle2Icon,
  Columns3Icon,
  FileUpIcon,
  PlayIcon,
  RefreshCwIcon,
  UploadCloudIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  type OfflineUploadColumnMapping,
  type OfflineUploadRecord,
  type OfflineUploadStatus,
  useCreateOfflineUploadMutation,
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

function PreviewTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: Array<Record<string, string>>;
}) {
  if (headers.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        preview 행이 없습니다.
      </div>
    );
  }

  return (
    <div className="max-h-80 overflow-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {headers.map((header) => (
              <TableHead className="whitespace-nowrap font-mono text-xs" key={header}>
                {header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={headers.map((header) => row[header] ?? "").join("\u0001")}>
              {headers.map((header) => (
                <TableCell
                  className="max-w-56 truncate whitespace-nowrap text-xs"
                  key={header}
                  title={row[header] ?? ""}
                >
                  {row[header] ?? ""}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

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
          <div className="max-h-72 overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>severity</TableHead>
                  <TableHead>row</TableHead>
                  <TableHead>column</TableHead>
                  <TableHead>code</TableHead>
                  <TableHead>message</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {issues.map((issue, index) => (
                  <TableRow key={`${issue.code}-${issue.row_number ?? index}`}>
                    <TableCell>
                      <StatusBadge status={issue.severity} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {issue.row_number ?? "-"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {issue.column ?? "-"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{issue.code}</TableCell>
                    <TableCell className="max-w-xl">{issue.message}</TableCell>
                  </TableRow>
                ))}
                {issues.length === 0 ? (
                  <TableRow>
                    <TableCell
                      className="h-20 text-center text-muted-foreground"
                      colSpan={5}
                    >
                      validation issue가 없습니다.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
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

  const selected =
    selectedUpload.data?.data ??
    uploads.data?.data.items.find((item) => item.upload_id === selectedUploadId) ??
    null;

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
              <Input
                data-testid="offline-upload-file-input"
                type="file"
                accept=".json,.jsonl,.ndjson,.csv,.tsv,application/json,application/x-ndjson,text/csv,text/tab-separated-values"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <Input
                aria-label="provider"
                placeholder="provider"
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
              />
              <Input
                aria-label="dataset key"
                placeholder="dataset_key"
                value={datasetKey}
                onChange={(event) => setDatasetKey(event.target.value)}
              />
              <Input
                aria-label="sync scope"
                placeholder="sync_scope"
                value={syncScope}
                onChange={(event) => setSyncScope(event.target.value)}
              />
              <Input
                aria-label="created by"
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
          {(uploads.isError || launchLoad.isError || selectedUpload.isError) && (
            <Alert variant="destructive">
              <AlertTitle>offline upload 처리 실패</AlertTitle>
              <AlertDescription>
                {uploads.error?.message ??
                  launchLoad.error?.message ??
                  selectedUpload.error?.message}
              </AlertDescription>
            </Alert>
          )}
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

          {uploads.isLoading ? <Skeleton className="h-96" /> : null}
          <div className="overflow-auto rounded-lg border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>upload</TableHead>
                  <TableHead>status</TableHead>
                  <TableHead>format</TableHead>
                  <TableHead>provider/dataset</TableHead>
                  <TableHead>file</TableHead>
                  <TableHead>size</TableHead>
                  <TableHead>updated</TableHead>
                  <TableHead>actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(uploads.data?.data.items ?? []).map((upload) => {
                  const loadEnabled = canLoad(upload);
                  return (
                    <TableRow
                      className="cursor-pointer"
                      data-testid="offline-upload-row"
                      key={upload.upload_id}
                      onClick={() => setSelectedUploadId(upload.upload_id)}
                    >
                      <TableCell className="font-mono text-xs">
                        {shortId(upload.upload_id)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={upload.status} />
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{uploadFormat(upload) || "-"}</Badge>
                      </TableCell>
                      <TableCell>
                        <div className="max-w-64 truncate">{upload.provider}</div>
                        <div className="max-w-64 truncate text-xs text-muted-foreground">
                          {upload.dataset_key}/{upload.sync_scope}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex max-w-72 items-center gap-2 truncate">
                          <FileUpIcon className="size-4 shrink-0 text-muted-foreground" />
                          <span className="truncate">{upload.original_filename}</span>
                        </div>
                      </TableCell>
                      <TableCell>{formatBytes(upload.byte_size)}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(upload.updated_at)}
                      </TableCell>
                      <TableCell>
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
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!uploads.isLoading && (uploads.data?.data.items.length ?? 0) === 0 ? (
                  <TableRow>
                    <TableCell
                      className="h-32 text-center text-muted-foreground"
                      colSpan={8}
                    >
                      offline upload가 없습니다.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
