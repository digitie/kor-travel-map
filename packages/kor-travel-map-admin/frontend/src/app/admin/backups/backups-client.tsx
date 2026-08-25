"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import {
  ArchiveIcon,
  RefreshCwIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useId, useMemo, useState, type ReactNode } from "react";

import {
  type BackupOperationResponse,
  type BackupRecord,
  useBackups,
  useCreateBackupMutation,
} from "@/api/backups";
import { AdminShell } from "@/components/admin-shell";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { JsonViewer } from "@/components/json-viewer";
import { SectionCard } from "@/components/section-card";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertAction,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { FormField } from "@/components/ui/form-field";
import { NULL_GLYPH, formatCount, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";

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

function commandLine(command: BackupOperationResponse["data"]["command"]): string {
  if (!command) {
    return NULL_GLYPH;
  }
  const env = Object.entries(command.env)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return `${env} ${command.command.join(" ")}`;
}

/**
 * 실행 옵션 토글 — ui/Checkbox + 형제 `<label htmlFor>`. Base UI Checkbox 기본 root는
 * `<span role=checkbox>` + 숨은 `<input>` 쌍이라 `<label>`로 감싸면 접근성 라벨이 두 요소에
 * 붙는다(e2e getByLabel strict 충돌). `nativeButton` + `render={<button/>}`로 root를 labelable
 * `<button>`으로 바꾸면 `id`가 root에 붙어 형제 label 하나만 checkbox를 가리킨다 — 텍스트 클릭
 * 토글은 native label 연결이 맡는다(정적 요소 onClick 없음).
 */
function OptionToggle({
  checked,
  label,
  hint,
  onCheckedChange,
}: {
  checked: boolean;
  label: string;
  hint?: ReactNode;
  onCheckedChange: (checked: boolean) => void;
}) {
  const checkboxId = useId();
  const labelId = useId();
  const hintId = useId();
  return (
    <div className="flex items-start gap-2 py-1">
      <Checkbox
        aria-describedby={hint ? hintId : undefined}
        aria-labelledby={labelId}
        checked={checked}
        className="mt-0.5"
        id={checkboxId}
        nativeButton
        render={<button type="button" />}
        onCheckedChange={(next) => onCheckedChange(next === true)}
      />
      <div className="flex min-w-0 flex-col gap-0.5">
        <label
          className="cursor-pointer text-sm text-text-primary select-none"
          htmlFor={checkboxId}
          id={labelId}
        >
          {label}
        </label>
        {hint ? (
          <span className="text-2xs text-text-secondary" id={hintId}>
            {hint}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function BackupDetail({ backup }: { backup: BackupRecord | null }) {
  if (!backup) {
    return (
      <SectionCard
        description="백업 행을 선택하면 manifest와 보존 범위를 확인합니다."
        headingLevel={2}
        title="선택 없음"
      >
        <p className="text-xs text-text-tertiary">
          목록에서 행을 클릭하거나 Enter로 선택합니다.
        </p>
      </SectionCard>
    );
  }
  const items: DetailItem[] = [
    { label: "생성", value: formatDateTime(backup.created_at_utc), numeric: true },
    { label: "모드", value: backup.mode ?? null },
    { label: "크기", value: formatBytes(backup.byte_size), numeric: true },
    { label: "체크섬", value: `${formatCount(backup.checksum_count)}개`, numeric: true },
    { label: "경로", value: backup.path, mono: true, copyable: true },
  ];
  return (
    <SectionCard
      actions={<StatusBadge status={backup.manifest_status} />}
      description={<span className="font-mono">{backup.backup_id}</span>}
      headingLevel={2}
      title="백업 상세"
    >
      <DetailList items={items} layout="inline" />
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-2xs font-medium text-text-secondary">데이터베이스</span>
          <JsonViewer aria-label="backup databases" maxHeight="sm" value={backup.databases} />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-2xs font-medium text-text-secondary">구성 요소</span>
          <JsonViewer aria-label="backup components" maxHeight="sm" value={backup.components} />
        </div>
      </div>
    </SectionCard>
  );
}

function OperationResult({
  result,
  onDismiss,
}: {
  result: BackupOperationResponse | null;
  onDismiss: () => void;
}) {
  if (!result) {
    return null;
  }
  return (
    <Alert>
      <AlertTitle>
        {result.data.operation} / {statusLabel(result.data.status)}
      </AlertTitle>
      <AlertDescription>
        <p>{result.data.message}</p>
        {result.data.command ? (
          <JsonViewer
            aria-label="backup command"
            className="mt-2"
            copyable
            maxHeight="sm"
            value={commandLine(result.data.command)}
          />
        ) : null}
      </AlertDescription>
      <AlertActions>
        <Link
          className={buttonVariants({ size: "sm", variant: "outline" })}
          href="/ops/logs?tab=system"
        >
          운영 로그에서 실행 확인
        </Link>
      </AlertActions>
      <AlertAction>
        <Button
          aria-label="결과 닫기"
          size="icon-sm"
          type="button"
          variant="ghost"
          onClick={onDismiss}
        >
          <XIcon />
        </Button>
      </AlertAction>
    </Alert>
  );
}

type BackupExecutionOptions = {
  backupId: string;
  executeBackup: boolean;
};

const DEFAULT_EXECUTION_OPTIONS: BackupExecutionOptions = {
  backupId: "",
  executeBackup: false,
};

function ExecutionOptionsPanel({
  options,
  onChange,
}: {
  options: BackupExecutionOptions;
  onChange: (patch: Partial<BackupExecutionOptions>) => void;
}) {
  return (
    <SectionCard
      description="기본은 command plan만 생성합니다. restore와 hot swap은 300 recovery 형식이 정의될 때까지 지원하지 않습니다."
      headingLevel={2}
      title="실행 옵션"
    >
      <FormField
        hint="비워 두면 시각 기반 ID로 자동 생성됩니다."
        id="backup-id-input"
        label="backup id"
        value={options.backupId}
        onChange={(event) => onChange({ backupId: event.target.value })}
      />
      <div className="flex flex-col divide-y divide-border">
        <OptionToggle
          checked={options.executeBackup}
          label="백업 command 실행"
          onCheckedChange={(checked) => onChange({ executeBackup: checked })}
        />
      </div>
    </SectionCard>
  );
}

function useBackupColumns(): ColumnDef<BackupRecord, unknown>[] {
  return useMemo<ColumnDef<BackupRecord, unknown>[]>(
    () => [
      {
        accessorKey: "backup_id",
        header: "백업 ID",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.backup_id, 20)}
          </span>
        ),
      },
      {
        accessorKey: "created_at_utc",
        header: "생성",
        enableSorting: true,
        cell: ({ row }) => formatDateTime(row.original.created_at_utc),
      },
      {
        accessorKey: "manifest_status",
        header: "상태",
        enableSorting: true,
        cell: ({ row }) => <StatusBadge status={row.original.manifest_status} />,
      },
      {
        accessorKey: "byte_size",
        header: "크기",
        enableSorting: true,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => formatBytes(row.original.byte_size),
      },
    ],
    [],
  );
}

export function BackupsClient() {
  const backups = useBackups();
  const createBackup = useCreateBackupMutation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [options, setOptions] = useState<BackupExecutionOptions>(DEFAULT_EXECUTION_OPTIONS);
  const { backupId, executeBackup } = options;
  const updateOptions = useCallback((patch: Partial<BackupExecutionOptions>) => {
    setOptions((prev) => ({ ...prev, ...patch }));
  }, []);
  const [lastResult, setLastResult] = useState<BackupOperationResponse | null>(null);

  const items = useMemo(() => backups.data?.data.items ?? [], [backups.data]);
  const selected = useMemo(
    () => items.find((item) => item.backup_id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );

  const refresh = () => {
    void backups.refetch();
  };

  const columns = useBackupColumns();

  const submitBackup = () => {
    createBackup.mutate(
      {
        backup_id: backupId.trim() || null,
        allow_running: false,
        execute: executeBackup,
      },
      { onSuccess: setLastResult },
    );
  };

  const errorLines = [
    backups.error ? `목록: ${backups.error.message}` : null,
    createBackup.error ? `백업: ${createBackup.error.message}` : null,
  ].filter((line): line is string => line !== null);
  const commandEnabled = backups.data?.data.command_enabled;

  return (
    <AdminShell
      actions={
        <>
          <Button loading={backups.isFetching} type="button" variant="outline" onClick={refresh}>
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <Button loading={createBackup.isPending} type="button" onClick={submitBackup}>
            <ArchiveIcon data-icon="inline-start" />
            백업
          </Button>
        </>
      }
      description="cold backup artifact를 확인하고 필요한 백업 command를 실행합니다."
      meta={
        backups.data ? (
          <>
            저장소 <span className="font-mono">{backups.data.data.backup_root}</span>
          </>
        ) : undefined
      }
      title="백업"
    >
      <div className="flex flex-col gap-6">
        {errorLines.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>백업 요청 실패</AlertTitle>
            <AlertDescription>
              {errorLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
              <p>서버 응답을 확인한 뒤 다시 시도하세요.</p>
            </AlertDescription>
            <AlertActions>
              <Button
                loading={backups.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={refresh}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}
        <OperationResult result={lastResult} onDismiss={() => setLastResult(null)} />

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
          <SectionCard
            actions={
              commandEnabled === undefined ? null : (
                <Badge variant={commandEnabled ? "success" : "neutral"}>
                  {commandEnabled ? "execute enabled" : "plan only"}
                </Badge>
              )
            }
            description={
              backups.data
                ? `${formatCount(backups.data.data.items.length)} artifacts`
                : NULL_GLYPH
            }
            title="백업 목록"
          >
            <DataTable
              columns={columns}
              data={items}
              emptyState={{
                title: "백업이 없습니다.",
                description: "상단 백업 버튼으로 첫 artifact를 만들 수 있습니다.",
              }}
              getRowId={(row) => row.backup_id}
              isLoading={backups.isLoading}
              isRowActive={(row) => selected?.backup_id === row.backup_id}
              manualSorting={false}
              onRowClick={(row) => setSelectedId(row.backup_id)}
            />
          </SectionCard>

          <div className="flex flex-col gap-6">
            <ExecutionOptionsPanel options={options} onChange={updateOptions} />
            <BackupDetail backup={selected} />
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
