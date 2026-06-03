"use client";

import {
  FileUpIcon,
  PlayIcon,
  RefreshCwIcon,
  UploadCloudIcon,
} from "lucide-react";
import { useState } from "react";

import {
  type OfflineUploadRecord,
  type OfflineUploadState,
  useCreateOfflineUploadMutation,
  useLaunchOfflineUploadLoadMutation,
  useOfflineUpload,
  useOfflineUploads,
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

const states: Array<OfflineUploadState | "all"> = [
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
const byteFormatter = new Intl.NumberFormat("ko-KR");

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${byteFormatter.format(value)} B`;
  }
  if (value < 1024 * 1024) {
    return `${byteFormatter.format(Math.round(value / 1024))} KB`;
  }
  return `${byteFormatter.format(Math.round(value / 1024 / 1024))} MB`;
}

function canLoad(upload: OfflineUploadRecord): boolean {
  return loadableStates.has(upload.state);
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
        목록에서 업로드를 선택하면 저장 key, checksum, Dagster load 상태를 확인할 수
        있습니다.
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
        <StatusBadge status={upload.state} />
      </div>
      <dl className="flex flex-col gap-3">
        <DetailRow label="provider" value={upload.provider} />
        <DetailRow label="dataset" value={upload.dataset_key} />
        <DetailRow label="scope" value={upload.sync_scope} />
        <DetailRow label="storage" value={`${upload.storage_backend}:${upload.storage_key}`} />
        <DetailRow label="size" value={formatBytes(upload.byte_size)} />
        <DetailRow label="sha256" value={upload.checksum_sha256} />
        <DetailRow label="format" value={upload.detected_format ?? "-"} />
        <DetailRow label="load job" value={upload.load_job_id ?? "-"} />
        <DetailRow label="updated" value={formatDateTime(upload.updated_at)} />
      </dl>
    </div>
  );
}

export function OfflineUploadsClient() {
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("offline-test-provider");
  const [datasetKey, setDatasetKey] = useState("offline_jsonl");
  const [syncScope, setSyncScope] = useState("default");
  const [createdBy, setCreatedBy] = useState("local-admin");
  const [state, setState] = useState<OfflineUploadState | "all">("uploaded");
  const [providerFilter, setProviderFilter] = useState("");
  const [datasetFilter, setDatasetFilter] = useState("");
  const [selectedUploadId, setSelectedUploadId] = useState<string | null>(null);

  const uploads = useOfflineUploads({
    state: state === "all" ? undefined : state,
    provider: providerFilter.trim() || undefined,
    dataset_key: datasetFilter.trim() || undefined,
    page_size: 100,
  });
  const selectedUpload = useOfflineUpload(selectedUploadId);
  const createUpload = useCreateOfflineUploadMutation();
  const launchLoad = useLaunchOfflineUploadLoadMutation();

  const selected =
    selectedUpload.data ??
    uploads.data?.items.find((item) => item.upload_id === selectedUploadId) ??
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
      description="RustFS에 보존한 JSON/JSONL FeatureBundle 원본을 업로드하고 Dagster offline_upload_load job으로 적재합니다."
      section="Admin"
      title="Offline uploads"
    >
      <div className="grid gap-4 xl:grid-cols-[24rem_1fr]">
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border bg-background p-4">
            <div className="mb-4">
              <div className="font-medium">파일 업로드</div>
              <div className="text-sm text-muted-foreground">
                JSON/JSONL FeatureBundle 원본
              </div>
            </div>
            <div className="flex flex-col gap-3">
              <Input
                data-testid="offline-upload-file-input"
                type="file"
                accept=".json,.jsonl,.ndjson,application/json,application/x-ndjson"
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
                    {createUpload.data.data.state} ·{" "}
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

          <div className="flex flex-wrap items-center gap-2">
            <NativeSelect
              aria-label="offline upload state"
              value={state}
              onChange={(event) =>
                setState(event.target.value as OfflineUploadState | "all")
              }
            >
              {states.map((item) => (
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
            <Badge variant="outline">{uploads.data?.count ?? 0} rows</Badge>
          </div>

          {uploads.isLoading ? <Skeleton className="h-96" /> : null}
          <div className="overflow-auto rounded-lg border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>upload</TableHead>
                  <TableHead>state</TableHead>
                  <TableHead>provider/dataset</TableHead>
                  <TableHead>file</TableHead>
                  <TableHead>size</TableHead>
                  <TableHead>updated</TableHead>
                  <TableHead>actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(uploads.data?.items ?? []).map((upload) => (
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
                      <StatusBadge status={upload.state} />
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
                        disabled={launchLoad.isPending || !canLoad(upload)}
                        size="sm"
                        type="button"
                        variant={canLoad(upload) ? "outline" : "ghost"}
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
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
