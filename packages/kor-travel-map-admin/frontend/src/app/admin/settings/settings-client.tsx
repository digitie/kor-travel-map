"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import { RefreshCwIcon, Trash2Icon } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import {
  useAdminAuthEvents,
  useCreatePublicApiKeyMutation,
  usePublicApiKeys,
  useRevokePublicApiKeyMutation,
  type AdminAuthEventRecord,
  type PublicApiKeyRecord,
} from "@/api/adminSettings";
import { AdminShell } from "@/components/admin-shell";
import { useConfirm } from "@/components/confirm-dialog";
import { CopyButton } from "@/components/copy-button";
import { SectionCard } from "@/components/section-card";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { FormField } from "@/components/ui/form-field";
import { NULL_GLYPH, formatDateTime, shortId } from "@/lib/format";

// 로그인 감사 이벤트 종류 — enum을 raw로 렌더하지 않는다(design.md §Copy).
const AUTH_EVENT_LABELS: Record<AdminAuthEventRecord["event_type"], string> = {
  login: "로그인",
  logout: "로그아웃",
};

// 로그인 감사 컬럼 — 상태/핸들러 의존이 없어 모듈 상수로 둔다(컴포넌트 크기 분리).
const AUTH_EVENT_COLUMNS: ColumnDef<AdminAuthEventRecord, unknown>[] = [
  {
    accessorKey: "created_at",
    header: "시각",
    cell: ({ row }) => (
      <span className="text-text-secondary">
        {formatDateTime(row.original.created_at)}
      </span>
    ),
  },
  {
    accessorKey: "event_type",
    header: "이벤트",
    cell: ({ row }) =>
      AUTH_EVENT_LABELS[row.original.event_type] ?? row.original.event_type,
  },
  {
    accessorKey: "outcome",
    header: "결과",
    cell: ({ row }) => <StatusBadge status={row.original.outcome} />,
  },
  {
    accessorKey: "attempted_username",
    header: "사용자명",
    cell: ({ row }) => row.original.attempted_username ?? NULL_GLYPH,
  },
  {
    accessorKey: "reason",
    header: "사유",
    meta: { wrap: true } satisfies DataTableColumnMeta,
    cell: ({ row }) => row.original.reason ?? NULL_GLYPH,
  },
  {
    id: "client",
    header: "클라이언트",
    enableSorting: false,
    cell: ({ row }) => (
      <span
        className="block max-w-72 truncate text-xs text-text-secondary"
        title={`${row.original.client_ip ?? NULL_GLYPH} · ${row.original.user_agent ?? NULL_GLYPH}`}
      >
        {row.original.client_ip ?? NULL_GLYPH} · {row.original.user_agent ?? NULL_GLYPH}
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
];

export function AdminSettingsClient() {
  const [label, setLabel] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const apiKeys = usePublicApiKeys();
  const authEvents = useAdminAuthEvents();
  const createKey = useCreatePublicApiKeyMutation();
  const revokeKey = useRevokePublicApiKeyMutation();
  const confirm = useConfirm();
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
            <div className="font-mono text-xs text-text-secondary">
              {shortId(row.original.public_api_key_id)}
            </div>
          </>
        ),
      },
      {
        accessorKey: "key_hint",
        header: "힌트",
        cell: ({ row }) => (
          <span className="font-mono text-xs">…{row.original.key_hint}</span>
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
          <span className="text-text-secondary">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "revoked",
        header: "폐기",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.revoked_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) =>
          row.original.state === "active" ? (
            <Button
              disabled={revokeKey.isPending}
              disabledReason="다른 키를 폐기하는 중입니다"
              loading={
                revokeKey.isPending &&
                revokeKey.variables === row.original.public_api_key_id
              }
              size="sm"
              type="button"
              variant="destructive"
              onClick={() => {
                void (async () => {
                  const ok = await confirm({
                    title: "이 공개 API 키를 폐기할까요?",
                    description:
                      "폐기 즉시 해당 키의 요청이 거부되며 되돌릴 수 없습니다.",
                    confirmLabel: "폐기",
                    destructive: true,
                  });
                  if (!ok) return;
                  revokeKey.mutate(row.original.public_api_key_id);
                })();
              }}
            >
              <Trash2Icon data-icon="inline-start" />
              폐기
            </Button>
          ) : null,
      },
    ],
    [confirm, revokeKey],
  );

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (createKey.isPending) return;
    try {
      const result = await createKey.mutateAsync({
        label: label.trim() || null,
      });
      setCreatedKey(result.data.key);
      setLabel("");
    } catch {
      // createKey.error가 아래 Alert로 표시된다.
    }
  };

  const refresh = () => {
    void apiKeys.refetch();
    void authEvents.refetch();
  };
  const refreshing = apiKeys.isFetching || authEvents.isFetching;
  const keyMutationErrors = [
    createKey.error ? `키 생성: ${createKey.error.message}` : null,
    revokeKey.error ? `키 폐기: ${revokeKey.error.message}` : null,
  ].filter((item): item is string => item !== null);

  return (
    <AdminShell
      title="설정"
      description="관리자 로그인 감사 기록과 VWorld 호환 public API key를 관리합니다."
      actions={
        <Button loading={refreshing} type="button" variant="outline" onClick={refresh}>
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        <SectionCard
          description="키는 생성 직후 한 번만 표시됩니다. 폐기한 키는 즉시 거부됩니다."
          title="공개 API 키"
        >
          <form
            className="flex flex-wrap items-start gap-x-3 gap-y-2"
            onSubmit={(event) => void submit(event)}
          >
            <FormField
              className="w-full max-w-sm"
              hint="비워 두면 라벨 없이 생성됩니다."
              label="라벨"
              placeholder="예: production-service"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
            {/* 라벨 높이만큼 비운 자리 — 버튼을 입력 컨트롤과 같은 baseline에 맞춘다. */}
            <div className="flex flex-col gap-1.5">
              <span aria-hidden="true" className="invisible text-xs leading-snug font-medium">
                &nbsp;
              </span>
              <Button loading={createKey.isPending} type="submit">
                키 생성
              </Button>
            </div>
          </form>

          {createdKey ? (
            <div
              aria-live="polite"
              className="rounded-control border border-border bg-surface-subtle px-3 py-2"
              role="status"
            >
              <p className="text-xs font-medium text-text-secondary">
                새 API 키 — 지금만 표시됩니다. 복사해 안전한 곳에 보관하세요.
              </p>
              <div className="mt-1 flex items-start gap-2">
                <code className="min-w-0 flex-1 font-mono text-xs break-all text-text-primary slashed-zero">
                  {createdKey}
                </code>
                <CopyButton label="API 키" value={createdKey} />
              </div>
            </div>
          ) : null}

          {keyMutationErrors.length > 0 ? (
            <Alert variant="destructive">
              <AlertTitle>API 키 작업을 완료하지 못했습니다</AlertTitle>
              <AlertDescription>
                {keyMutationErrors.map((message) => (
                  <p key={message}>{message}</p>
                ))}
              </AlertDescription>
              <AlertActions>
                <Button
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => {
                    createKey.reset();
                    revokeKey.reset();
                  }}
                >
                  닫기
                </Button>
              </AlertActions>
            </Alert>
          ) : null}

          <DataTable
            columns={keyColumns}
            data={keyItems}
            emptyState={{
              title: "저장된 API 키가 없습니다.",
              description: "위에서 라벨을 입력하고 키를 생성하면 목록에 나타납니다.",
            }}
            error={apiKeys.error}
            errorTitle="API 키 목록을 불러오지 못했습니다"
            getRowId={(row) => row.public_api_key_id}
            isError={apiKeys.isError}
            isLoading={apiKeys.isLoading}
            onRetry={() => apiKeys.refetch()}
          />
        </SectionCard>

        <SectionCard
          description="최근 로그인·로그아웃 시도와 결과입니다."
          title="로그인 감사"
        >
          <DataTable
            columns={AUTH_EVENT_COLUMNS}
            data={eventItems}
            emptyState={{
              title: "로그인 기록이 없습니다.",
              description: "관리자 로그인 시도가 발생하면 여기에 쌓입니다.",
            }}
            error={authEvents.error}
            errorTitle="로그인 기록을 불러오지 못했습니다"
            getRowId={(row) => row.auth_event_id}
            isError={authEvents.isError}
            isLoading={authEvents.isLoading}
            onRetry={() => authEvents.refetch()}
          />
        </SectionCard>
      </div>
    </AdminShell>
  );
}
