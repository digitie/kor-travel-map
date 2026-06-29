"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  CopyIcon,
  KeyRoundIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  Trash2Icon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import {
  useAdminAuthEvents,
  useCreatePublicApiKeyMutation,
  usePublicApiKeys,
  useRevokePublicApiKeyMutation,
  type AdminAuthEventRecord,
  type PublicApiKeyRecord,
} from "@/api/adminSettings";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { formatDateTime, shortId } from "@/lib/format";

export function AdminSettingsClient() {
  const [label, setLabel] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const apiKeys = usePublicApiKeys();
  const authEvents = useAdminAuthEvents();
  const createKey = useCreatePublicApiKeyMutation();
  const revokeKey = useRevokePublicApiKeyMutation();
  const keyItems = apiKeys.data?.data.items ?? [];
  const eventItems = authEvents.data?.data.items ?? [];

  const keyColumns = useMemo<ColumnDef<PublicApiKeyRecord, unknown>[]>(
    () => [
      {
        id: "label",
        header: "라벨",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.label ?? "이름 없음"}</div>
            <div className="font-mono text-xs text-muted-foreground">
              {shortId(row.original.public_api_key_id)}
            </div>
          </>
        ),
      },
      {
        accessorKey: "key_hint",
        header: "힌트",
        cell: ({ row }) => (
          <span className="font-mono text-xs">...{row.original.key_hint}</span>
        ),
      },
      {
        accessorKey: "state",
        header: "상태",
        cell: ({ row }) => <StatusBadge status={row.original.state} />,
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
        id: "revoked",
        header: "취소",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.revoked_at ? (
            <span className="text-muted-foreground">
              {formatDateTime(row.original.revoked_at)}
            </span>
          ) : (
            "-"
          ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.state === "active" ? (
            <Button
              disabled={revokeKey.isPending}
              size="sm"
              type="button"
              variant="ghost"
              onClick={() => revokeKey.mutate(row.original.public_api_key_id)}
            >
              <Trash2Icon data-icon="inline-start" />
              폐기
            </Button>
          ) : null,
      },
    ],
    [revokeKey],
  );

  const authColumns = useMemo<ColumnDef<AdminAuthEventRecord, unknown>[]>(
    () => [
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
        accessorKey: "event_type",
        header: "이벤트",
        cell: ({ row }) => <Badge variant="outline">{row.original.event_type}</Badge>,
      },
      {
        accessorKey: "outcome",
        header: "결과",
        cell: ({ row }) => <StatusBadge status={row.original.outcome} />,
      },
      { accessorKey: "attempted_username", header: "사용자명" },
      { accessorKey: "reason", header: "사유" },
      {
        id: "client",
        header: "클라이언트",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-72 truncate text-xs text-muted-foreground">
            {row.original.client_ip ?? "-"} / {row.original.user_agent ?? "-"}
          </span>
        ),
      },
      {
        id: "request",
        header: "요청",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">{shortId(row.original.request_id)}</span>
        ),
      },
    ],
    [],
  );

  const submit = async () => {
    const result = await createKey.mutateAsync({
      label: label.trim() || null,
    });
    setCreatedKey(result.data.key);
    setLabel("");
  };

  const copyKey = async () => {
    if (!createdKey) {
      return;
    }
    if (!window.isSecureContext || !navigator.clipboard?.writeText) {
      toast.info("자동 복사를 사용할 수 없습니다. 키를 직접 선택해 복사하세요.");
      return;
    }
    try {
      await navigator.clipboard.writeText(createdKey);
      toast.success("API 키를 클립보드에 복사했습니다.");
    } catch {
      toast.error("클립보드 복사에 실패했습니다. 키를 직접 선택해 복사하세요.");
    }
  };

  const refresh = () => {
    void apiKeys.refetch();
    void authEvents.refetch();
  };

  return (
    <AdminShell
      title="설정"
      description="관리자 로그인 감사 기록과 VWorld 호환 public API key를 관리합니다."
      section="관리"
      actions={
        <Button type="button" variant="outline" onClick={refresh}>
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
    >
      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="space-y-4 rounded-lg border border-surface-muted bg-card p-5">
          <div className="flex items-center gap-2">
            <KeyRoundIcon className="size-4 text-brand" />
            <h2 className="text-[16px] font-semibold">Public API keys</h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <Input
              placeholder="예: production-service"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
            <Button disabled={createKey.isPending} type="button" onClick={submit}>
              <KeyRoundIcon data-icon="inline-start" />
              랜덤 생성
            </Button>
          </div>
          {createdKey ? (
            <Alert>
              <ShieldCheckIcon className="size-4" />
              <AlertTitle>생성된 키</AlertTitle>
              <AlertDescription>
                <div className="mt-2 flex flex-col gap-2">
                  <code className="break-all rounded-md bg-surface-subtle px-2 py-1 font-mono text-xs">
                    {createdKey}
                  </code>
                  <Button size="sm" type="button" variant="outline" onClick={copyKey}>
                    <CopyIcon data-icon="inline-start" />
                    복사
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}
          {apiKeys.isError || createKey.isError || revokeKey.isError ? (
            <Alert variant="destructive">
              <AlertTitle>API key 작업 실패</AlertTitle>
              <AlertDescription>
                {apiKeys.error?.message ??
                  createKey.error?.message ??
                  revokeKey.error?.message}
              </AlertDescription>
            </Alert>
          ) : null}
          <DataTable
            columns={keyColumns}
            data={keyItems}
            emptyMessage="저장된 API 키가 없습니다."
          />
        </section>

        <section className="space-y-4 rounded-lg border border-surface-muted bg-card p-5">
          <div className="flex items-center gap-2">
            <ShieldCheckIcon className="size-4 text-brand" />
            <h2 className="text-[16px] font-semibold">Login audit</h2>
          </div>
          {authEvents.isError ? (
            <Alert variant="destructive">
              <AlertTitle>로그 조회 실패</AlertTitle>
              <AlertDescription>{authEvents.error.message}</AlertDescription>
            </Alert>
          ) : null}
          <DataTable
            columns={authColumns}
            data={eventItems}
            emptyMessage="로그인 기록이 없습니다."
          />
        </section>
      </div>
    </AdminShell>
  );
}
