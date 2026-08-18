"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import {
  CheckCircle2Icon,
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
import {
  type OpsDatasetGridRow,
  useOpsDatasetCatalog,
} from "@/api/datasets";
import { AdminShell } from "@/components/admin-shell";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { EntityLink } from "@/components/entity-link";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { SectionCard } from "@/components/section-card";
import { LevelBadge, StatusBadge } from "@/components/status-badge";
import { statusLabel } from "@/lib/status-label";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { FormField, FormSelect } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

const statuses: Array<OfflineUploadStatus | "all"> = [
  "uploading",
  "uploaded",
  "validating",
  "validated",
  "validation_failed",
  "loading",
  "loaded",
  "load_failed",
  "deleting",
  "cancelled",
  "all",
];

const loadableStates = new Set(["uploaded", "validated", "loaded", "load_failed"]);
const inProgressStates = new Set([
  "uploading",
  "validating",
  "loading",
  "deleting",
]);
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

const LOAD_BLOCKED_REASON = "CSV/TSV는 validation 완료 후 load 가능";
const DELETE_BLOCKED_REASON = "validation/load 진행 중에는 삭제 불가";
const MAPPING_INCOMPLETE_REASON = "필수 매핑(name · lon · lat)을 채우면 활성화됩니다.";

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${byteFormatter.format(value)} B`;
  }
  if (value < 1024 * 1024) {
    return `${byteFormatter.format(Math.round(value / 1024))} KB`;
  }
  return `${byteFormatter.format(Math.round(value / 1024 / 1024))} MB`;
}

function positiveInteger(value: string): number | undefined {
  const parsed = Number(value.trim());
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : undefined;
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

function statusOptionLabel(value: OfflineUploadStatus | "all"): string {
  return value === "all" ? "전체" : statusLabel(value);
}

function UploadDetail({ upload }: { upload: OfflineUploadRecord | null }) {
  if (upload === null) {
    return (
      <SectionCard headingLevel={2} title="상세">
        <EmptyState
          title="선택된 업로드가 없습니다"
          description="목록에서 업로드를 선택하면 저장 key, checksum, validation/load job 상태를 확인할 수 있습니다."
        />
      </SectionCard>
    );
  }
  const items: DetailItem[] = [
    { label: "provider dataset ID", value: upload.provider_dataset_id, numeric: true },
    { label: "스코프", value: upload.sync_scope, mono: true },
    {
      label: "storage",
      value: `${upload.storage_backend}:${upload.storage_key}`,
      mono: true,
      copyable: true,
    },
    { label: "size", value: formatBytes(upload.byte_size), numeric: true },
    { label: "sha256", value: upload.checksum_sha256, mono: true, copyable: true },
    { label: "형식", value: upload.detected_format ?? null, mono: true },
    {
      label: "validation job",
      value: upload.validation_job_id ? (
        <EntityLink id={upload.validation_job_id} kind="importJob" />
      ) : null,
    },
    {
      label: "load job",
      value: upload.load_job_id ? (
        <EntityLink id={upload.load_job_id} kind="importJob" />
      ) : null,
    },
    { label: "updated", value: formatDateTime(upload.updated_at), numeric: true },
  ];
  return (
    <SectionCard
      actions={<StatusBadge status={upload.status} />}
      description={<span className="font-mono">{shortId(upload.upload_id, 18)}</span>}
      headingLevel={2}
      title={<span className="truncate">{upload.original_filename}</span>}
    >
      <DetailList items={items} layout="inline" />
    </SectionCard>
  );
}

function MappingInput({
  label,
  mapping,
  field,
  setMapping,
  headers,
}: {
  label: string;
  mapping: OfflineUploadColumnMapping;
  field: keyof OfflineUploadColumnMapping;
  setMapping: (mapping: OfflineUploadColumnMapping) => void;
  /** CSV 컬럼 매핑 필드용 — preview meta.headers가 있으면 select 어시스트(§4). */
  headers?: string[];
}) {
  const value = (mapping[field] as string | null | undefined) ?? "";
  if (headers && headers.length > 0) {
    return (
      <FormSelect
        aria-label={`mapping ${label}`}
        className="font-mono"
        label={label}
        reserveMessage={false}
        size="sm"
        value={headers.includes(value) ? value : ""}
        onChange={(event) =>
          setMapping({ ...mapping, [field]: event.target.value })
        }
      >
        <NativeSelectOption value="">컬럼 선택</NativeSelectOption>
        {headers.map((header) => (
          <NativeSelectOption key={header} value={header}>
            {header}
          </NativeSelectOption>
        ))}
      </FormSelect>
    );
  }
  return (
    <FormField
      aria-label={`mapping ${label}`}
      className="font-mono"
      label={label}
      reserveMessage={false}
      size="sm"
      value={value}
      onChange={(event) =>
        setMapping({ ...mapping, [field]: event.target.value })
      }
    />
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
          <span className="font-mono text-2xs whitespace-nowrap">{header}</span>
        ),
        cell: ({ row }) => {
          const value = row.original[header] ?? "";
          return (
            <span
              className="block max-w-56 truncate text-xs whitespace-nowrap"
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
      <EmptyState
        description="파일 첫 줄에서 header를 읽지 못했습니다."
        size="sm"
        title="preview 행이 없습니다."
      />
    );
  }

  return (
    <DataTable
      columns={columns}
      containerClassName="max-h-80 overflow-auto"
      data={rows}
      emptyState={{ title: "preview 행이 없습니다." }}
      getRowId={(row) =>
        headers.map((header) => row[header] ?? "").join("")
      }
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
    header: "심각도",
    cell: ({ row }) => <LevelBadge level={row.original.severity} />,
  },
  {
    accessorKey: "row_number",
    header: "행",
    meta: { align: "right" } satisfies DataTableColumnMeta,
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.row_number ?? NULL_GLYPH}</span>
    ),
  },
  {
    accessorKey: "column",
    header: "컬럼",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.column ?? NULL_GLYPH}</span>
    ),
  },
  {
    accessorKey: "code",
    header: "코드",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.code}</span>
    ),
  },
  {
    accessorKey: "message",
    header: "메시지",
    enableSorting: false,
    meta: { wrap: true } satisfies DataTableColumnMeta,
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
      <SectionCard headingLevel={2} title="CSV/TSV validation">
        <EmptyState
          title="선택된 업로드가 없습니다"
          description="CSV/TSV 업로드를 선택하면 column mapping과 validation 결과를 확인할 수 있습니다."
        />
      </SectionCard>
    );
  }

  if (!isTabular) {
    return (
      <SectionCard
        description={`이 업로드는 ${uploadFormat(selected).toUpperCase() || "unknown"} 형식이라 JSON/JSONL FeatureBundle load gate를 따릅니다.`}
        headingLevel={2}
        title="CSV/TSV validation"
      >
        <p className="text-xs text-text-secondary">
          column mapping 없이 목록의 load 버튼으로 바로 적재할 수 있습니다.
        </p>
      </SectionCard>
    );
  }

  const mappingReady = mappingComplete(mapping);
  const validationErrorLines = [
    preview.error ? `preview: ${preview.error.message}` : null,
    validation.error ? `validation 조회: ${validation.error.message}` : null,
    validateUpload.error ? `검증 실행: ${validateUpload.error.message}` : null,
  ].filter((line): line is string => line !== null);
  const previewMeta = preview.data?.meta;

  return (
    <SectionCard
      actions={
        validationResult ? (
          <span
            className={cn(
              "text-xs font-medium tabular-nums",
              validationResult.meta.error_rows > 0 ? "text-destructive" : "text-success",
            )}
          >
            {validationResult.meta.valid_rows} valid / {validationResult.meta.error_rows} error
          </span>
        ) : (
          <span className="text-xs text-text-tertiary">검증 전</span>
        )
      }
      description={
        <span className="tabular-nums">
          {uploadFormat(selected).toUpperCase()} · 총{" "}
          {formatCount(previewMeta?.rows_total ?? null, { loading: preview.isLoading })}행
        </span>
      }
      headingLevel={2}
      title="CSV/TSV validation"
    >
      <div className="flex flex-col gap-3">
        <span className="text-2xs font-medium text-text-secondary">필수 매핑</span>
        <div className="grid gap-3 md:grid-cols-3">
          {requiredMappingFields.map((field) => (
            <MappingInput
              field={field}
              headers={previewMeta?.headers ?? []}
              key={field}
              label={field}
              mapping={mapping}
              setMapping={setMapping}
            />
          ))}
        </div>
        <span className="text-2xs font-medium text-text-secondary">선택 매핑 · 기본값</span>
        <div className="grid gap-3 md:grid-cols-4">
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
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <Button
          data-testid="offline-upload-validate"
          disabled={!mappingReady}
          disabledReason={MAPPING_INCOMPLETE_REASON}
          loading={validateUpload.isPending}
          type="button"
          onClick={() =>
            validateUpload.mutate({
              uploadId: selected.upload_id,
              columnMapping: mappingPayload(mapping),
              sampleSize: 1000,
            })
          }
        >
          <CheckCircle2Icon data-icon="inline-start" />
          검증 실행
        </Button>
        {!mappingReady ? (
          <span className="text-2xs text-text-secondary">{MAPPING_INCOMPLETE_REASON}</span>
        ) : null}
        {selected.validation_job_id ? (
          <span className="text-xs text-text-secondary">
            job{" "}
            <EntityLink id={selected.validation_job_id} kind="importJob">
              {shortId(selected.validation_job_id)}
            </EntityLink>
          </span>
        ) : null}
      </div>

      {validationErrorLines.length > 0 ? (
        <Alert variant="destructive">
          <AlertTitle>validation 처리 실패</AlertTitle>
          <AlertDescription>
            {validationErrorLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </AlertDescription>
          <AlertActions>
            <Button
              loading={preview.isFetching || validation.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={() => {
                validateUpload.reset();
                void preview.refetch();
                void validation.refetch();
              }}
            >
              다시 시도
            </Button>
          </AlertActions>
        </Alert>
      ) : null}

      {preview.isLoading ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : null}
      {previewMeta ? (
        <div className="flex flex-col gap-2 border-t border-border pt-4">
          <p className="text-2xs text-text-secondary tabular-nums">
            <span className="font-medium">미리보기</span> · {previewMeta.headers.length} columns ·{" "}
            {previewMeta.rows_sampled} sampled · sha256{" "}
            <span className="font-mono">
              {shortId(previewMeta.checksum_sha256_actual, 12)}
            </span>
          </p>
          <PreviewTable
            headers={previewMeta.headers}
            rows={previewMeta.sample_rows}
          />
        </div>
      ) : null}

      {validationResult ? (
        <div className="flex flex-col gap-2 border-t border-border pt-4">
          <p className="text-2xs text-text-secondary tabular-nums">
            <span className="font-medium">검증 결과</span> · {validationResult.meta.valid_rows} valid ·{" "}
            <span className={validationResult.meta.error_rows > 0 ? "text-destructive" : undefined}>
              {validationResult.meta.error_rows} error
            </span>{" "}
            · <span>{issues.length} issues</span>
          </p>
          <DataTable
            columns={validationIssueColumns}
            containerClassName="max-h-72 overflow-auto"
            data={issues}
            emptyState={{
              title: "validation issue가 없습니다.",
              description: "표본 행이 모두 통과했습니다.",
            }}
            getRowId={(issue, index) =>
              `${issue.code}-${issue.row_number ?? index}`
            }
            manualSorting={false}
          />
        </div>
      ) : null}
    </SectionCard>
  );
}

function UploadFormPanel({
  onCreated,
}: {
  onCreated: (uploadId: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [providerDatasetId, setProviderDatasetId] = useState("");
  // canonical scope만 서버가 받는다. `"default"`는 canonical이 아니라 422다
  // (예전 기본값이었고, 그 상태로 올리면 operation 해석이 실패해 500이 났다).
  // 빈 값은 "고른 dataset의 canonical scope를 따른다"는 뜻이다 — 아래
  // `effectiveSyncScope` 참조. 고정 기본값을 박으면 canonical scope가
  // `target_grids`/`external_system:*`인 dataset에서 그대로 422가 난다.
  const [syncScope, setSyncScope] = useState("");
  const createUpload = useCreateOfflineUploadMutation();
  const datasetsQuery = useOpsDatasetCatalog();
  const providerDatasetOptions = useMemo(() => {
    const rowsById = new Map<number, OpsDatasetGridRow>();
    for (const row of datasetsQuery.data?.data.items ?? []) {
      rowsById.set(row.provider_dataset_id, row);
    }
    return [...rowsById.values()].sort(
      (left, right) => left.provider_dataset_id - right.provider_dataset_id,
    );
  }, [datasetsQuery.data?.data.items]);
  const parsedProviderDatasetId = positiveInteger(providerDatasetId);
  // 고른 dataset이 실제로 갖고 있는 canonical scope들. grid 행은 membership마다
  // 하나이므로 여기서 그 dataset의 scope 집합이 그대로 나온다.
  const scopeOptions = useMemo(() => {
    const scopes = new Set<string>();
    for (const row of datasetsQuery.data?.data.items ?? []) {
      if (row.provider_dataset_id === parsedProviderDatasetId) {
        scopes.add(row.sync_scope);
      }
    }
    return [...scopes].sort();
  }, [datasetsQuery.data?.data.items, parsedProviderDatasetId]);
  // scope가 **유일할 때만** 자동으로 정한다. 둘 이상이면 운영자가 고른다 —
  // 정렬 첫 값을 집으면 canonical write 대상이 사전순으로 결정된다. 그건 앞 판의
  // 고정 기본값(즉시 422)보다 나쁘다: 조용히 다른 membership에 적재된다.
  const effectiveSyncScope =
    syncScope.trim() || (scopeOptions.length === 1 ? scopeOptions[0] : "");
  const uploadMissingFields = [
    file === null ? "파일" : null,
    parsedProviderDatasetId === undefined ? "provider dataset ID" : null,
    effectiveSyncScope.length === 0
      ? scopeOptions.length > 1
        ? `sync scope(이 dataset은 ${scopeOptions.join(", ")} 중 하나를 골라야 합니다)`
        : "sync scope"
      : null,
  ].filter((item): item is string => item !== null);
  const missingReason =
    uploadMissingFields.length > 0 ? `입력 필요: ${uploadMissingFields.join(", ")}` : null;

  const submitUpload = () => {
    if (file === null || parsedProviderDatasetId === undefined) return;
    createUpload.mutate(
      {
        file,
        providerDatasetId: parsedProviderDatasetId,
        syncScope: effectiveSyncScope,
      },
      { onSuccess: (data) => onCreated(data.data.upload_id) },
    );
  };

  return (
    <SectionCard
      description="JSON/JSONL FeatureBundle, CSV/TSV tabular 원본"
      headingLevel={2}
      title="파일 업로드"
    >
      <div className="flex flex-col gap-1">
        <FormField
          data-testid="offline-upload-file-input"
          label="파일"
          type="file"
          accept=".json,.jsonl,.ndjson,.csv,.tsv,application/json,application/x-ndjson,text/csv,text/tab-separated-values"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <FormField
          label="provider dataset ID"
          list="offline-upload-provider-dataset-options"
          min="1"
          placeholder="401"
          type="number"
          value={providerDatasetId}
          onChange={(event) => setProviderDatasetId(event.target.value)}
        />
        <datalist id="offline-upload-provider-dataset-options">
          {providerDatasetOptions.map((item) => (
            <option
              key={item.provider_dataset_id}
              label={`${item.provider}/${item.dataset_key}`}
              value={item.provider_dataset_id}
            />
          ))}
        </datalist>
        <FormField
          hint={
            scopeOptions.length > 1
              ? `이 dataset은 canonical scope가 여러 개입니다 — 직접 고르세요: ${scopeOptions.join(", ")}`
              : scopeOptions.length === 1
                ? `이 dataset의 canonical scope: ${scopeOptions[0]}`
                : "provider dataset을 먼저 고르면 canonical scope가 채워집니다."
          }
          label="sync scope"
          list="offline-upload-sync-scope-options"
          placeholder={effectiveSyncScope || "default"}
          value={syncScope}
          onChange={(event) => setSyncScope(event.target.value)}
        />
        <datalist id="offline-upload-sync-scope-options">
          {scopeOptions.map((scope) => (
            <option key={scope} value={scope} />
          ))}
        </datalist>
        <div className="flex flex-col items-start gap-1 border-t border-border pt-4">
          <Button
            data-testid="offline-upload-submit"
            disabled={missingReason !== null}
            disabledReason={missingReason ?? undefined}
            loading={createUpload.isPending}
            type="button"
            onClick={submitUpload}
          >
            <UploadCloudIcon data-icon="inline-start" />
            업로드
          </Button>
          {missingReason ? (
            <span className="text-2xs text-text-secondary">{missingReason}</span>
          ) : null}
        </div>
        {createUpload.data ? (
          <p
            aria-live="polite"
            className="text-xs text-text-secondary tabular-nums"
            role="status"
          >
            업로드 완료 ·{" "}
            <span className="font-mono">{shortId(createUpload.data.data.upload_id, 18)}</span> ·{" "}
            {statusLabel(createUpload.data.data.status)} ·{" "}
            {formatBytes(createUpload.data.data.byte_size)}
          </p>
        ) : null}
        {createUpload.isError ? (
          <Alert variant="destructive">
            <AlertTitle>업로드 실패</AlertTitle>
            <AlertDescription>{createUpload.error.message}</AlertDescription>
          </Alert>
        ) : null}
      </div>
    </SectionCard>
  );
}

function useOfflineUploadListController() {
  const [status, setStatus] = useState<OfflineUploadStatus | "all">("uploaded");
  const [providerDatasetIdFilter, setProviderDatasetIdFilter] = useState("");
  const [selectedUploadId, setSelectedUploadId] = useState<string | null>(null);
  const [mapping, setMapping] =
    useState<OfflineUploadColumnMapping>(defaultColumnMapping);

  const uploadsParams = useMemo(
    () => ({
      status: status === "all" ? undefined : status,
      provider_dataset_id: positiveInteger(providerDatasetIdFilter),
      page_size: 100,
    }),
    [providerDatasetIdFilter, status],
  );
  const uploads = useOfflineUploads(uploadsParams);
  const selectedUpload = useOfflineUpload(selectedUploadId);
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
        header: "업로드",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.upload_id)}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "상태",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "format",
        header: "형식",
        accessorFn: (row) => uploadFormat(row),
        cell: ({ row }) => (
          <span className="font-mono text-xs">{uploadFormat(row.original) || NULL_GLYPH}</span>
        ),
      },
      {
        id: "provider_dataset",
        header: "provider dataset",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="max-w-64 truncate font-mono tabular-nums">
              #{row.original.provider_dataset_id}
            </div>
            <div className="max-w-64 truncate text-xs text-text-secondary">
              {row.original.sync_scope}
            </div>
          </>
        ),
      },
      {
        id: "file",
        header: "파일",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex max-w-72 items-center gap-2 truncate">
            <FileUpIcon className="size-4 shrink-0 text-text-secondary" />
            <span className="truncate">{row.original.original_filename}</span>
          </div>
        ),
      },
      {
        accessorKey: "byte_size",
        header: "크기",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatBytes(row.original.byte_size),
      },
      {
        accessorKey: "updated_at",
        header: "수정",
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.updated_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const upload = row.original;
          const loadEnabled = canLoad(upload);
          const inProgress = inProgressStates.has(upload.status);
          const loading = launchLoad.isPending && launchLoad.variables === upload.upload_id;
          const deleting =
            deleteUpload.isPending && deleteUpload.variables === upload.upload_id;
          return (
            <div className="flex items-center gap-1">
              <Button
                data-testid="offline-upload-load"
                disabled={launchLoad.isPending || !loadEnabled}
                disabledReason={
                  launchLoad.isPending ? "다른 load를 실행하는 중입니다" : LOAD_BLOCKED_REASON
                }
                loading={loading}
                size="sm"
                type="button"
                variant="outline"
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
                disabled={deleteUpload.isPending || inProgress}
                disabledReason={
                  inProgress ? DELETE_BLOCKED_REASON : "다른 업로드를 삭제하는 중입니다"
                }
                loading={deleting}
                size="sm"
                title="업로드 row + 저장 객체 삭제"
                type="button"
                variant="destructive"
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

  return {
    deleteUpload,
    launchLoad,
    mapping,
    providerDatasetIdFilter,
    selected,
    selectedUpload,
    selectedUploadId,
    setMapping,
    setProviderDatasetIdFilter,
    setSelectedUploadId,
    setStatus,
    status,
    uploadColumns,
    uploadItems,
    uploads,
  };
}

export function OfflineUploadsClient() {
  const {
    deleteUpload,
    launchLoad,
    mapping,
    providerDatasetIdFilter,
    selected,
    selectedUpload,
    selectedUploadId,
    setMapping,
    setProviderDatasetIdFilter,
    setSelectedUploadId,
    setStatus,
    status,
    uploadColumns,
    uploadItems,
    uploads,
  } = useOfflineUploadListController();
  const errorLines = [
    uploads.error ? `목록: ${uploads.error.message}` : null,
    launchLoad.error ? `load: ${launchLoad.error.message}` : null,
    deleteUpload.error ? `삭제: ${deleteUpload.error.message}` : null,
    selectedUpload.error ? `상세: ${selectedUpload.error.message}` : null,
  ].filter((line): line is string => line !== null);
  return (
    <AdminShell
      actions={
        <Button
          loading={uploads.isFetching}
          type="button"
          variant="outline"
          onClick={() => void uploads.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="저장된 FeatureBundle·CSV 원본을 검증하고 적재합니다."
      title="오프라인 업로드"
    >
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
        <div className="flex flex-col gap-6">
          {errorLines.length > 0 ? (
            <Alert variant="destructive">
              <AlertTitle>offline upload 처리 실패</AlertTitle>
              <AlertDescription>
                {errorLines.map((line) => (
                  <p key={line}>{line}</p>
                ))}
                <p>잠시 후 다시 시도하세요.</p>
              </AlertDescription>
              <AlertActions>
                <Button
                  loading={uploads.isFetching}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => {
                    launchLoad.reset();
                    deleteUpload.reset();
                    void uploads.refetch();
                  }}
                >
                  다시 시도
                </Button>
              </AlertActions>
            </Alert>
          ) : null}

          <FilterBar>
            <FilterField label="상태">
              <NativeSelect
                aria-label="offline upload status"
                value={status}
                onChange={(event) =>
                  setStatus(event.target.value as OfflineUploadStatus | "all")
                }
              >
                {statuses.map((item) => (
                  <NativeSelectOption key={item} value={item}>
                    {statusOptionLabel(item)}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </FilterField>
            <FilterField className="w-56" label="provider dataset ID">
              <Input
                aria-label="provider dataset ID filter"
                inputMode="numeric"
                min="1"
                placeholder="401"
                type="number"
                value={providerDatasetIdFilter}
                onChange={(event) => setProviderDatasetIdFilter(event.target.value)}
              />
            </FilterField>
          </FilterBar>

          {deleteUpload.data ? (
            <p aria-live="polite" className="text-xs text-text-secondary" role="status">
              업로드 삭제됨 ·{" "}
              <span className="font-mono">{shortId(deleteUpload.data.data.upload_id, 18)}</span> ·{" "}
              {deleteUpload.data.data.original_filename}
            </p>
          ) : null}
          {launchLoad.data ? (
            <p aria-live="polite" className="text-xs text-text-secondary" role="status">
              Dagster load 실행됨 ·{" "}
              <span className="font-mono">{shortId(launchLoad.data.meta.dagster_run_id, 18)}</span> ·{" "}
              {statusLabel(launchLoad.data.meta.dagster_status)}
            </p>
          ) : null}

          <SectionCard
            description={
              <span className="tabular-nums">
                {formatCount(uploads.data ? uploadItems.length : null, {
                  loading: uploads.isLoading,
                })}{" "}
                rows
              </span>
            }
            title="업로드 목록"
          >
            <DataTable
              columns={uploadColumns}
              data={uploadItems}
              emptyState={{
                title: "offline upload가 없습니다.",
                description: "상태 필터를 전체로 바꾸거나 우측 폼에서 파일을 올려 보세요.",
              }}
              getRowId={(row) => row.upload_id}
              isLoading={uploads.isLoading}
              isRowActive={(upload) => upload.upload_id === selectedUploadId}
              manualSorting={false}
              onRowClick={(upload) => setSelectedUploadId(upload.upload_id)}
              rowTestId={() => "offline-upload-row"}
            />
          </SectionCard>

          <ValidationPanel
            mapping={mapping}
            selected={selected}
            setMapping={setMapping}
          />
        </div>

        <div className="flex flex-col gap-6">
          <UploadFormPanel onCreated={setSelectedUploadId} />
          <UploadDetail upload={selected} />
        </div>
      </div>
    </AdminShell>
  );
}
