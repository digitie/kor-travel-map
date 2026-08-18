"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import {
  FileIcon,
  FolderIcon,
  RefreshCwIcon,
  ScanSearchIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import {
  type ManagedFile,
  type ManagedFileLink,
  type ManagedFileSortField,
  useManagedFile,
  useManagedFiles,
  useManagedFileSummary,
  usePurgeManagedFileMutation,
  useRescanManagedFilesMutation,
} from "@/api/adminFiles";
import { AdminShell } from "@/components/admin-shell";
import { useConfirm } from "@/components/confirm-dialog";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { FilterBar, FilterField } from "@/components/filter-bar";
import { HelpTip } from "@/components/help-tip";
import { JsonViewer } from "@/components/json-viewer";
import { OffsetPager } from "@/components/pagination-bar";
import { SectionCard } from "@/components/section-card";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertAction,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";
import { cn } from "@/lib/utils";

// ── 라벨 사전 (값 drift는 core/managed_file_states.py가 정본) ──────────────
const KIND_LABELS: Record<string, string> = {
  provider_download: "Provider 다운로드",
  backup: "백업",
  upload: "오프라인 업로드",
  feature_file: "Feature 파일",
  report: "리포트",
  temp: "임시 파일",
  other: "기타",
};

const LOCATION_LABELS: Record<string, string> = {
  backup_root: "백업 저장소",
  mois_source: "MOIS 원본",
  object_store: "오브젝트 스토리지",
  offline_uploads: "오프라인 업로드",
};

const EVENT_LABELS: Record<string, string> = {
  registered: "등록",
  downloaded: "다운로드",
  validated: "검증",
  loaded: "적재",
  restored: "복원",
  marked_orphan: "고아 판정",
  marked_missing: "유실 판정",
  reappeared: "재확인",
  deleted: "삭제",
  delete_failed: "삭제 실패",
  purged: "영구 정리",
};

const ORPHAN_REASON_LABELS: Record<string, string> = {
  zombie_object: "소유 레코드 없는 잔존 오브젝트",
  owner_row_deleted: "소유 레코드 삭제됨",
  manifest_missing: "manifest 유실",
  e2e_backup_expired: "E2E 백업 TTL 만료",
  scan_unregistered: "스캔 미등록 파일",
  temp_expired: "임시 파일 TTL 만료",
};

const KIND_OPTIONS = Object.keys(KIND_LABELS);
// 상태 라벨은 status-label 톤 테이블을 그대로 읽는다(StatusBadge와 같은 어휘).
const STATUS_OPTIONS = ["active", "orphan", "missing", "deleted"];
const LOCATION_OPTIONS = Object.keys(LOCATION_LABELS);
const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "downloaded_at", label: "다운로드 최신순" },
  { value: "last_loaded_at", label: "마지막 로드순" },
  { value: "last_seen_at", label: "마지막 확인순" },
  { value: "byte_size", label: "크기순" },
  { value: "updated_at", label: "갱신순" },
];

// purge 가능한 orphan_reason — 서버 게이트와 동일(사용자 기대 정합).
const PURGEABLE_REASONS = new Set(["zombie_object", "owner_row_deleted"]);

const PAGE_SIZE = 50;
const byteFormatter = new Intl.NumberFormat("ko-KR");

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return NULL_GLYPH;
  if (value < 1024) return `${byteFormatter.format(value)} B`;
  if (value < 1024 * 1024)
    return `${byteFormatter.format(Math.round(value / 1024))} KB`;
  if (value < 1024 * 1024 * 1024)
    return `${byteFormatter.format(Math.round(value / 1024 / 1024))} MB`;
  return `${byteFormatter.format(Math.round(value / 1024 / 1024 / 1024))} GB`;
}

/** 재스캔 결과의 느슨한 dict 값에서 숫자만 취한다 — 미지 값은 `—`(가짜 0 금지). */
function asCount(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function basename(path: string): string {
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || path;
}

type Filters = {
  q: string;
  kind: string;
  status: string;
  location: string;
  provider: string;
  sort: string;
};

const EMPTY_FILTERS: Filters = {
  q: "",
  kind: "",
  status: "",
  location: "",
  provider: "",
  sort: "downloaded_at",
};

// ── 요약 facet (칩 = 해당 필터 토글, count 는 inline tabular 숫자 — badge 아님) ──────
function SummaryChips({
  title,
  buckets,
  activeKey,
  labels,
  onPick,
}: {
  title: string;
  buckets: { key: string; count: number }[];
  activeKey: string;
  labels: (key: string) => string;
  onPick: (key: string) => void;
}) {
  if (buckets.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label={`${title} 요약`}>
      <span className="text-2xs font-medium text-text-secondary">{title}</span>
      <div className="flex flex-wrap gap-1.5">
        {buckets.map((bucket) => {
          const active = activeKey === bucket.key;
          return (
            <Button
              aria-pressed={active}
              key={bucket.key}
              size="sm"
              type="button"
              variant={active ? "secondary" : "outline"}
              onClick={() => onPick(active ? "" : bucket.key)}
            >
              {labels(bucket.key)}
              <span
                className={cn(
                  "text-2xs tabular-nums",
                  active ? "text-brand" : "text-text-secondary",
                )}
              >
                {formatCount(bucket.count)}
              </span>
            </Button>
          );
        })}
      </div>
    </div>
  );
}

function ProvenanceLinks({ links }: { links: ManagedFileLink[] }) {
  if (links.length === 0) {
    return <span className="text-xs text-text-tertiary">연결된 항목이 없습니다.</span>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {links.map((link) =>
        link.href ? (
          <Link
            key={link.rel}
            className={buttonVariants({ size: "sm", variant: "outline" })}
            href={link.href}
          >
            {link.label}
          </Link>
        ) : (
          <span
            key={link.rel}
            className="inline-flex h-control-sm items-center rounded-control px-2.5 text-xs text-text-secondary"
          >
            {link.label}
          </span>
        ),
      )}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      {["a", "b", "c", "d", "e", "f"].map((key) => (
        <div className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3" key={key}>
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      ))}
    </div>
  );
}

function FileDetailPanel({
  fileId,
  onPurged,
}: {
  fileId: number | null;
  onPurged: () => void;
}) {
  const detail = useManagedFile(fileId);
  const purge = usePurgeManagedFileMutation();
  const confirm = useConfirm();

  if (fileId === null) {
    return (
      <SectionCard description="행을 선택하면 연결·이력을 추적합니다." title="상세">
        <EmptyState
          icon={<FileIcon />}
          title="선택된 파일 없음"
          description="목록에서 파일을 클릭하면 어디에 연결됐는지, 언제 받고 로드됐는지 표시됩니다."
        />
      </SectionCard>
    );
  }
  if (detail.isLoading) {
    return (
      <SectionCard title="상세">
        <DetailSkeleton />
      </SectionCard>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <SectionCard title="상세">
        <Alert variant="destructive">
          <AlertTitle>상세를 불러오지 못했습니다</AlertTitle>
          <AlertDescription>
            {detail.error?.message ?? "해당 파일이 레지스트리에 없습니다."}
          </AlertDescription>
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
      </SectionCard>
    );
  }

  const { file, links, events } = detail.data.data;
  const purgeable =
    file.status === "orphan" &&
    file.storage_backend === "s3" &&
    file.orphan_reason !== null &&
    PURGEABLE_REASONS.has(file.orphan_reason);

  const items: DetailItem[] = [
    { label: "경로", value: file.path, mono: true, copyable: true },
    { label: "위치", value: LOCATION_LABELS[file.location] ?? file.location },
    { label: "종류", value: KIND_LABELS[file.kind] ?? file.kind },
    {
      label: "저장 방식",
      value: file.storage_backend,
      help: "filesystem(호스트 디스크) 또는 s3(오브젝트 스토리지).",
    },
    { label: "Provider", value: file.provider ?? null },
    { label: "Dataset", value: file.dataset_key ?? null, mono: true },
    {
      label: "등록 경로",
      value: file.registered_by,
      help: "hook(생산/소비 시 자동) · scan(주기 스캔) · backfill(DB 회수).",
    },
    { label: "크기", value: formatBytes(file.byte_size), numeric: true },
    {
      label: "체크섬",
      value: file.checksum_sha256 ? shortId(file.checksum_sha256, 16) : null,
      mono: true,
      copyable: file.checksum_sha256 !== null,
    },
    {
      label: "다운로드",
      value: formatDateTime(file.downloaded_at),
      help: "파일이 시스템에 처음 적재된 시각.",
    },
    {
      label: "마지막 로드",
      value: formatDateTime(file.last_loaded_at),
      help: "이 파일이 Feature 적재 등에 마지막으로 사용된 시각.",
    },
    {
      label: "마지막 확인",
      value: formatDateTime(file.last_seen_at),
      help: "스캔이 실체 존재를 마지막으로 확인한 시각.",
    },
  ];
  if (file.orphan_reason) {
    items.push({
      label: "고아 사유",
      value: ORPHAN_REASON_LABELS[file.orphan_reason] ?? file.orphan_reason,
      help: "소유 레코드가 사라졌거나 TTL이 지난 파일의 판정 사유.",
    });
  }

  const runPurge = () => {
    void (async () => {
      const ok = await confirm({
        title: "잔존 오브젝트를 레지스트리에서 정리할까요?",
        description:
          "소유 레코드가 사라진 S3 잔존 오브젝트를 레지스트리에서 제거합니다. 실체 삭제는 스캐너가 뒤이어 처리하며 되돌릴 수 없습니다.",
        confirmLabel: "정리",
        destructive: true,
      });
      if (!ok) return;
      purge.mutate(file.file_id, { onSuccess: onPurged });
    })();
  };

  return (
    <SectionCard
      actions={<StatusBadge status={file.status} />}
      footer={
        purgeable ? (
          <div className="flex w-full flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-1 text-xs text-text-secondary">
              잔존 오브젝트 정리
              <HelpTip label="영구 정리">
                소유 레코드가 사라진 S3 잔존 오브젝트만 레지스트리에서 제거합니다. 실체
                오브젝트 삭제는 스토리지를 소유한 스캐너가 뒤이어 정리합니다. 파괴적
                작업 스위치가 켜져 있어야 동작합니다.
              </HelpTip>
            </span>
            <Button
              loading={purge.isPending}
              size="sm"
              type="button"
              variant="destructive"
              onClick={runPurge}
            >
              <Trash2Icon data-icon="inline-start" />
              레지스트리에서 정리
            </Button>
          </div>
        ) : undefined
      }
      title={
        <span className="flex min-w-0 items-center gap-2">
          {file.is_directory ? (
            <FolderIcon className="size-4 shrink-0 text-text-secondary" />
          ) : (
            <FileIcon className="size-4 shrink-0 text-text-secondary" />
          )}
          <span className="truncate">{basename(file.path)}</span>
        </span>
      }
    >
      <DetailList items={items} layout="inline" />

      <div className="flex flex-col gap-2 border-t border-border pt-4">
        <span className="text-2xs font-medium text-text-secondary">연결된 항목</span>
        <ProvenanceLinks links={links} />
      </div>

      <div className="flex flex-col gap-2 border-t border-border pt-4">
        <span className="text-2xs font-medium text-text-secondary">
          이력 · {formatCount(events.length)}건
        </span>
        {events.length === 0 ? (
          <span className="text-xs text-text-tertiary">기록된 이력이 없습니다.</span>
        ) : (
          <ol className="flex flex-col divide-y divide-border">
            {events.map((event) => (
              <li
                key={event.event_id}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5 text-sm"
              >
                <span className="font-medium">
                  {EVENT_LABELS[event.event_kind] ?? event.event_kind}
                </span>
                <span className="text-xs text-text-secondary tabular-nums">
                  {formatDateTime(event.occurred_at)}
                </span>
                {event.actor ? (
                  <span className="text-xs text-text-secondary">· {event.actor}</span>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>

      {Object.keys(file.meta).length > 0 ? (
        <div className="flex flex-col gap-2 border-t border-border pt-4">
          <span className="text-2xs font-medium text-text-secondary">메타데이터</span>
          <JsonViewer aria-label="file metadata" value={file.meta} />
        </div>
      ) : null}

      {purge.error ? (
        <Alert variant="destructive">
          <AlertTitle>정리를 완료하지 못했습니다</AlertTitle>
          <AlertDescription>{purge.error.message}</AlertDescription>
        </Alert>
      ) : null}
    </SectionCard>
  );
}

function useFilesClientController() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // search-as-you-type: 키 입력마다 refetch하지 않도록 q만 deferred로 넘긴다(m10).
  const deferredQ = useDeferredValue(filters.q);

  const listParams = useMemo(
    () => ({
      q: deferredQ.trim() || null,
      kind: filters.kind ? [filters.kind] : undefined,
      status: filters.status ? [filters.status] : undefined,
      location: filters.location || null,
      provider: filters.provider.trim() || null,
      sort: filters.sort as ManagedFileSortField,
      limit: PAGE_SIZE,
      offset,
    }),
    [deferredQ, filters.kind, filters.location, filters.provider, filters.sort, filters.status, offset],
  );

  const files = useManagedFiles(listParams);
  const summary = useManagedFileSummary();
  const rescan = useRescanManagedFilesMutation();

  const items = useMemo(() => files.data?.data ?? [], [files.data]);
  const total = files.data?.meta.page?.total ?? null;

  const patch = (next: Partial<Filters>) => {
    setFilters((prev) => ({ ...prev, ...next }));
    setOffset(0);
  };

  const columns = useMemo<ColumnDef<ManagedFile, unknown>[]>(
    () => [
      {
        accessorKey: "path",
        header: "파일",
        cell: ({ row }) => (
          <span className="flex items-center gap-1.5 font-mono text-xs">
            {row.original.is_directory ? (
              <FolderIcon className="size-3.5 shrink-0 text-text-secondary" />
            ) : (
              <FileIcon className="size-3.5 shrink-0 text-text-secondary" />
            )}
            {shortId(basename(row.original.path), 28)}
          </span>
        ),
      },
      {
        accessorKey: "kind",
        header: "종류",
        cell: ({ row }) => KIND_LABELS[row.original.kind] ?? row.original.kind,
      },
      {
        accessorKey: "location",
        header: "위치",
        cell: ({ row }) =>
          LOCATION_LABELS[row.original.location] ?? row.original.location,
      },
      {
        accessorKey: "status",
        header: "상태",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "provider",
        header: "Provider",
        cell: ({ row }) => row.original.provider ?? NULL_GLYPH,
      },
      {
        accessorKey: "byte_size",
        header: "크기",
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatBytes(row.original.byte_size),
      },
      {
        accessorKey: "downloaded_at",
        header: "다운로드",
        cell: ({ row }) => formatDateTime(row.original.downloaded_at),
      },
      {
        accessorKey: "last_loaded_at",
        header: "마지막 로드",
        cell: ({ row }) => formatDateTime(row.original.last_loaded_at),
      },
    ],
    [],
  );

  return {
    columns,
    files,
    filters,
    items,
    offset,
    patch,
    rescan,
    selectedId,
    setOffset,
    setSelectedId,
    summary,
    total,
  };
}

function FilesClientView({
  columns,
  files,
  filters,
  items,
  offset,
  patch,
  rescan,
  selectedId,
  setOffset,
  setSelectedId,
  summary,
  total,
}: ReturnType<typeof useFilesClientController>) {
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = total === null ? null : Math.max(1, Math.ceil(total / PAGE_SIZE));
  const refreshAll = () => {
    void files.refetch();
    void summary.refetch();
  };
  return (
    <AdminShell
      actions={
        <>
          <Button
            loading={files.isFetching || summary.isFetching}
            type="button"
            variant="outline"
            onClick={refreshAll}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <Button
            loading={rescan.isPending}
            type="button"
            onClick={() => rescan.mutate(null, { onSuccess: refreshAll })}
          >
            <ScanSearchIcon data-icon="inline-start" />
            재스캔
          </Button>
        </>
      }
      description="Provider 다운로드·백업·업로드 등 시스템 파일이 어디에 연결됐고 언제 쓰였는지 추적합니다."
      title="파일 관리"
    >
      <div className="flex flex-col gap-6">
        {rescan.error ? (
          <Alert variant="destructive">
            <AlertTitle>재스캔을 실행하지 못했습니다</AlertTitle>
            <AlertDescription>{rescan.error.message}</AlertDescription>
            <AlertActions>
              <Button
                loading={rescan.isPending}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => rescan.mutate(null, { onSuccess: refreshAll })}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}

        {rescan.data ? (
          <Alert>
            <AlertTitle>재스캔 완료</AlertTitle>
            <AlertDescription>
              {rescan.data.data.results.length > 0 ? (
                <DetailList
                  items={rescan.data.data.results.map((result) => ({
                    label: String(result.location),
                    value: `등록 ${formatCount(asCount(result.registered))} · 고아 ${formatCount(
                      asCount(result.orphaned),
                    )} · 유실 ${formatCount(asCount(result.missing))}`,
                    numeric: true,
                  }))}
                  layout="inline"
                />
              ) : (
                <p>변경된 파일이 없습니다.</p>
              )}
              {rescan.data.data.note ? <p className="mt-2">{rescan.data.data.note}</p> : null}
            </AlertDescription>
            <AlertAction>
              <Button
                aria-label="재스캔 결과 닫기"
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={() => rescan.reset()}
              >
                <XIcon />
              </Button>
            </AlertAction>
          </Alert>
        ) : null}

        <SectionCard
          description="칩을 누르면 해당 조건으로 목록을 좁힙니다."
          title="레지스트리 요약"
        >
          {summary.isLoading ? (
            <div className="flex flex-col gap-3" aria-busy="true">
              <Skeleton className="h-control-sm w-2/3" />
              <Skeleton className="h-control-sm w-1/2" />
              <Skeleton className="h-control-sm w-3/5" />
            </div>
          ) : summary.error ? (
            <Alert variant="destructive">
              <AlertTitle>요약을 불러오지 못했습니다</AlertTitle>
              <AlertDescription>{summary.error.message}</AlertDescription>
              <AlertActions>
                <Button
                  loading={summary.isFetching}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => void summary.refetch()}
                >
                  다시 시도
                </Button>
              </AlertActions>
            </Alert>
          ) : summary.data ? (
            <div className="flex flex-col gap-4">
              <SummaryChips
                title="종류"
                buckets={summary.data.data.by_kind.map((b) => ({
                  key: b.key,
                  count: b.count,
                }))}
                activeKey={filters.kind}
                labels={(key) => KIND_LABELS[key] ?? key}
                onPick={(key) => patch({ kind: key })}
              />
              <SummaryChips
                title="상태"
                buckets={summary.data.data.by_status.map((b) => ({
                  key: b.key,
                  count: b.count,
                }))}
                activeKey={filters.status}
                labels={(key) => statusLabel(key)}
                onPick={(key) => patch({ status: key })}
              />
              <SummaryChips
                title="위치"
                buckets={summary.data.data.by_location.map((b) => ({
                  key: b.key,
                  count: b.count,
                }))}
                activeKey={filters.location}
                labels={(key) => LOCATION_LABELS[key] ?? key}
                onPick={(key) => patch({ location: key })}
              />
            </div>
          ) : null}
        </SectionCard>

        <FilterBar>
          <FilterField className="w-56" htmlFor="files-q" label="검색">
            <Input
              id="files-q"
              placeholder="경로 · provider · dataset"
              value={filters.q}
              onChange={(event) => patch({ q: event.target.value })}
            />
          </FilterField>
          <FilterField htmlFor="files-kind" label="종류">
            <NativeSelect
              id="files-kind"
              value={filters.kind}
              onChange={(event) => patch({ kind: event.target.value })}
            >
              <NativeSelectOption value="">전체</NativeSelectOption>
              {KIND_OPTIONS.map((kind) => (
                <NativeSelectOption key={kind} value={kind}>
                  {KIND_LABELS[kind]}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField htmlFor="files-status" label="상태">
            <NativeSelect
              id="files-status"
              value={filters.status}
              onChange={(event) => patch({ status: event.target.value })}
            >
              <NativeSelectOption value="">전체</NativeSelectOption>
              {STATUS_OPTIONS.map((status) => (
                <NativeSelectOption key={status} value={status}>
                  {statusLabel(status)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField htmlFor="files-location" label="위치">
            <NativeSelect
              id="files-location"
              value={filters.location}
              onChange={(event) => patch({ location: event.target.value })}
            >
              <NativeSelectOption value="">전체</NativeSelectOption>
              {LOCATION_OPTIONS.map((location) => (
                <NativeSelectOption key={location} value={location}>
                  {LOCATION_LABELS[location]}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
          <FilterField htmlFor="files-sort" label="정렬">
            <NativeSelect
              id="files-sort"
              value={filters.sort}
              onChange={(event) => patch({ sort: event.target.value })}
            >
              {SORT_OPTIONS.map((option) => (
                <NativeSelectOption key={option.value} value={option.value}>
                  {option.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </FilterField>
        </FilterBar>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
          <SectionCard
            description={`${formatCount(total, { loading: files.isLoading })}건`}
            title="파일 목록"
          >
            <DataTable
              columns={columns}
              data={items}
              emptyState={{
                title: "조건에 맞는 파일이 없습니다.",
                description: "필터를 비우거나 재스캔을 실행해 최신 상태를 반영하세요.",
                action: (
                  <Button
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => patch(EMPTY_FILTERS)}
                  >
                    필터 초기화
                  </Button>
                ),
              }}
              error={files.error}
              errorTitle="파일 목록을 불러오지 못했습니다"
              getRowId={(row) => String(row.file_id)}
              isError={files.isError}
              isLoading={files.isLoading}
              isRowActive={(row) => row.file_id === selectedId}
              manualSorting={false}
              onRetry={() => files.refetch()}
              onRowClick={(row) => setSelectedId(row.file_id)}
            />
            <OffsetPager
              ariaPrefix="파일"
              currentCount={items.length}
              hasNextPage={total !== null && offset + PAGE_SIZE < total}
              hasPreviousPage={offset > 0}
              isFetching={files.isFetching}
              page={page}
              totalCount={total}
              totalPages={totalPages}
              onPageChange={(nextPage) => setOffset(Math.max(0, nextPage - 1) * PAGE_SIZE)}
            />
          </SectionCard>

          <FileDetailPanel fileId={selectedId} onPurged={refreshAll} />
        </div>
      </div>
    </AdminShell>
  );
}

export function FilesClient() {
  const controller = useFilesClientController();
  return <FilesClientView {...controller} />;
}
