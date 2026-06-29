"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  ArchiveIcon,
  DatabaseIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCcwIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  type BackupOperationResponse,
  type BackupRecord,
  useBackups,
  useCreateBackupMutation,
  useRestoreBackupMutation,
  useRestoreSwapMutation,
} from "@/api/backups";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge, statusLabel } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { formatCount, formatDateTime, shortId } from "@/lib/format";

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
    return "-";
  }
  const env = Object.entries(command.env)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
  return `${env} ${command.command.join(" ")}`;
}

function BackupDetail({ backup }: { backup: BackupRecord | null }) {
  if (!backup) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>선택 없음</CardTitle>
          <CardDescription>백업 행을 선택하면 manifest와 restore target을 확인합니다.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{backup.backup_id}</CardTitle>
            <CardDescription>{backup.path}</CardDescription>
          </div>
          <StatusBadge status={backup.manifest_status} />
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 text-sm">
          <div className="grid gap-1 sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">created</dt>
            <dd>{formatDateTime(backup.created_at_utc)}</dd>
          </div>
          <div className="grid gap-1 sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">mode</dt>
            <dd>{backup.mode ?? "-"}</dd>
          </div>
          <div className="grid gap-1 sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">size</dt>
            <dd>{formatBytes(backup.byte_size)}</dd>
          </div>
          <div className="grid gap-1 sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">checksums</dt>
            <dd>{formatCount(backup.checksum_count)}</dd>
          </div>
          <div className="grid gap-1 sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">databases</dt>
            <dd className="break-all font-mono text-xs">
              {JSON.stringify(backup.databases)}
            </dd>
          </div>
          <div className="grid gap-1 sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">components</dt>
            <dd className="break-all font-mono text-xs">
              {JSON.stringify(backup.components)}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function OperationResult({ result }: { result: BackupOperationResponse | null }) {
  if (!result) {
    return null;
  }
  return (
    <Alert>
      <DatabaseIcon data-icon="inline-start" />
      <AlertTitle>
        {result.data.operation} / {statusLabel(result.data.status)}
      </AlertTitle>
      <AlertDescription className="flex flex-col gap-2">
        <span>{result.data.message}</span>
        {result.data.restore_targets ? (
          <span className="font-mono text-xs">
            {result.data.restore_targets.app_db} /{" "}
            {result.data.restore_targets.dagster_db} /{" "}
            {result.data.restore_targets.rustfs_volume}
          </span>
        ) : null}
        {result.data.command ? (
          <code className="block whitespace-pre-wrap break-all rounded-md bg-muted p-2 text-xs">
            {commandLine(result.data.command)}
          </code>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

export function BackupsClient() {
  const backups = useBackups();
  const createBackup = useCreateBackupMutation();
  const restoreBackup = useRestoreBackupMutation();
  const swapRestore = useRestoreSwapMutation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [backupId, setBackupId] = useState("");
  const [executeBackup, setExecuteBackup] = useState(false);
  const [executeRestore, setExecuteRestore] = useState(false);
  const [executeSwap, setExecuteSwap] = useState(false);
  const [applySwap, setApplySwap] = useState(false);
  const [recreateRestore, setRecreateRestore] = useState(false);
  const [lastResult, setLastResult] = useState<BackupOperationResponse | null>(null);

  const items = useMemo(() => backups.data?.data.items ?? [], [backups.data]);
  const selected = useMemo(
    () => items.find((item) => item.backup_id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );

  const refresh = () => {
    void backups.refetch();
  };

  type BackupRow = NonNullable<typeof backups.data>["data"]["items"][number];
  const columns = useMemo<ColumnDef<BackupRow, unknown>[]>(
    () => [
      {
        accessorKey: "backup_id",
        header: "backup",
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.backup_id, 20)}
          </span>
        ),
      },
      {
        accessorKey: "created_at_utc",
        header: "created",
        enableSorting: true,
        cell: ({ row }) => formatDateTime(row.original.created_at_utc),
      },
      {
        accessorKey: "manifest_status",
        header: "status",
        enableSorting: true,
        cell: ({ row }) => <StatusBadge status={row.original.manifest_status} />,
      },
      {
        accessorKey: "byte_size",
        header: "size",
        enableSorting: true,
        cell: ({ row }) => formatBytes(row.original.byte_size),
      },
      {
        id: "action",
        header: "action",
        enableSorting: false,
        cell: ({ row }) => {
          const backup = row.original;
          return (
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={(event) => {
                  event.stopPropagation();
                  submitRestore(backup);
                }}
              >
                <RotateCcwIcon data-icon="inline-start" />
                Restore
              </Button>
              <Button
                size="sm"
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  submitSwap(backup);
                }}
              >
                <PlayIcon data-icon="inline-start" />
                Swap
              </Button>
            </div>
          );
        },
      },
    ],
    // 행의 Restore/Swap 버튼 onClick은 submitRestore/submitSwap을 통해 execute/recreate/
    // apply 체크박스 state를 읽는다. 이 state들이 바뀔 때 컬럼을 재생성하지 않으면 onClick이
    // 최초 렌더의 stale closure를 잡아 항상 execute:false를 보낸다(실행 옵션 무효 버그).
    // 해당 state들을 deps에 넣어 토글 시 onClick이 최신 값을 읽도록 한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [executeRestore, recreateRestore, executeSwap, applySwap],
  );

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

  const submitRestore = (backup: BackupRecord) => {
    restoreBackup.mutate(
      {
        backupId: backup.backup_id,
        body: {
          app_db: null,
          dagster_db: null,
          rustfs_volume: null,
          recreate: recreateRestore,
          skip_checksum: false,
          skip_rustfs: false,
          execute: executeRestore,
        },
      },
      { onSuccess: setLastResult },
    );
  };

  const submitSwap = (backup: BackupRecord) => {
    swapRestore.mutate(
      {
        backupId: backup.backup_id,
        body: {
          app_db: null,
          dagster_db: null,
          rustfs_volume: null,
          env_file: null,
          apply: applySwap,
          execute: executeSwap,
          skip_verify: false,
          operator: null,
          note: null,
        },
      },
      { onSuccess: setLastResult },
    );
  };

  const activeError =
    backups.error ??
    createBackup.error ??
    restoreBackup.error ??
    swapRestore.error;

  return (
    <AdminShell
      actions={
        <>
          <Button type="button" variant="outline" onClick={refresh}>
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <Button
            disabled={createBackup.isPending}
            type="button"
            onClick={submitBackup}
          >
            <ArchiveIcon data-icon="inline-start" />
            백업
          </Button>
        </>
      }
      description="cold backup artifact와 staging restore command를 확인합니다."
      section="관리"
      title="백업"
    >
      <div className="flex flex-col gap-5">
        {activeError ? (
          <Alert variant="destructive">
            <AlertTitle>backup/restore 요청 실패</AlertTitle>
            <AlertDescription>{activeError.message}</AlertDescription>
          </Alert>
        ) : null}
        <OperationResult result={lastResult} />

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>백업 목록</CardTitle>
                  <CardDescription>
                    {backups.data
                      ? `${formatCount(backups.data.data.items.length)} artifacts`
                      : "loading"}
                  </CardDescription>
                </div>
                <Badge
                  variant={
                    backups.data?.data.command_enabled ? "default" : "secondary"
                  }
                >
                  {backups.data?.data.command_enabled
                    ? "execute enabled"
                    : "plan only"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="overflow-auto">
              <DataTable
                columns={columns}
                data={items}
                getRowId={(row) => row.backup_id}
                isLoading={backups.isLoading}
                emptyMessage="백업이 없습니다."
                onRowClick={(row) => setSelectedId(row.backup_id)}
                isRowActive={(row) => selected?.backup_id === row.backup_id}
                manualSorting={false}
              />
            </CardContent>
          </Card>

          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader>
                <CardTitle>실행 옵션</CardTitle>
                <CardDescription>기본은 command plan만 생성합니다.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <label className="flex flex-col gap-1 text-sm" htmlFor="backup-id-input">
                  backup id
                  <Input
                    id="backup-id-input"
                    placeholder="자동 생성"
                    value={backupId}
                    onChange={(event) => setBackupId(event.target.value)}
                  />
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    checked={executeBackup}
                    type="checkbox"
                    onChange={(event) => setExecuteBackup(event.target.checked)}
                  />
                  백업 command 실행
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    checked={executeRestore}
                    type="checkbox"
                    onChange={(event) => setExecuteRestore(event.target.checked)}
                  />
                  restore command 실행
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    checked={recreateRestore}
                    type="checkbox"
                    onChange={(event) => setRecreateRestore(event.target.checked)}
                  />
                  staging 대상 재생성
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    checked={executeSwap}
                    type="checkbox"
                    onChange={(event) => setExecuteSwap(event.target.checked)}
                  />
                  swap command 실행
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    checked={applySwap}
                    type="checkbox"
                    onChange={(event) => setApplySwap(event.target.checked)}
                  />
                  swap 즉시 적용
                </label>
              </CardContent>
            </Card>
            <BackupDetail backup={selected} />
          </div>
        </section>
      </div>
    </AdminShell>
  );
}
