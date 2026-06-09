"use client";

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
import { StatusBadge } from "@/components/status-badge";
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
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
        {result.data.operation} / {result.data.status}
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
      section="Admin"
      title="Backups"
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
              {backups.isLoading ? <Skeleton className="h-64" /> : null}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>backup</TableHead>
                    <TableHead>created</TableHead>
                    <TableHead>status</TableHead>
                    <TableHead>size</TableHead>
                    <TableHead>action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((backup) => (
                    <TableRow
                      className="cursor-pointer"
                      key={backup.backup_id}
                      onClick={() => setSelectedId(backup.backup_id)}
                    >
                      <TableCell className="font-mono text-xs">
                        {shortId(backup.backup_id, 20)}
                      </TableCell>
                      <TableCell>{formatDateTime(backup.created_at_utc)}</TableCell>
                      <TableCell>
                        <StatusBadge status={backup.manifest_status} />
                      </TableCell>
                      <TableCell>{formatBytes(backup.byte_size)}</TableCell>
                      <TableCell>
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
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
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
