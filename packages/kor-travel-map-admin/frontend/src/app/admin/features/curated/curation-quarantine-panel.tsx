"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (list) · design-system: design.md · designed-as-app

import {
  ArchiveRestoreIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useState } from "react";

import { ApiClientError } from "@/api/client";
import {
  useAdminCurationCollections,
  useAdminCurationQuarantineCollections,
  useAdminCurationQuarantineItems,
  useReclassifyCurationQuarantineMutation,
  type CurationQuarantineConflictKind,
  type CurationQuarantineSource,
  type CurationQuarantineTheme,
} from "@/api/curations";
import { useConfirm } from "@/components/confirm-dialog";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { SectionCard } from "@/components/section-card";
import {
  SelectableRow,
  SelectableRowDescription,
  SelectableRowGroup,
  SelectableRowTitle,
} from "@/components/selectable-row";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { NULL_GLYPH, formatCount, shortId } from "@/lib/format";
import { type StatusTone } from "@/lib/status-label";

interface StandaloneFormState {
  collectionKey: string;
  title: string;
}

const INITIAL_STANDALONE_FORM: StandaloneFormState = {
  collectionKey: "",
  title: "",
};

const CONFLICT_KIND_LABELS: Record<CurationQuarantineConflictKind, string> = {
  movable: "이동 가능",
  component_identity_conflict: "구성요소 identity 충돌",
  active_source_feature_conflict: "active source-feature 충돌",
  no_target: "target 미지정",
  target_missing: "target 없음",
};

function conflictKindLabel(kind: string): string {
  return kind in CONFLICT_KIND_LABELS
    ? CONFLICT_KIND_LABELS[kind as CurationQuarantineConflictKind]
    : kind;
}

/** conflict preview 톤 — 이동 가능=success · target 미지정=warning · 충돌/없음=destructive (톤 테이블 어휘). */
function conflictTone(kind: CurationQuarantineConflictKind): StatusTone {
  if (kind === "movable") return "success";
  if (kind === "no_target") return "warning";
  return "destructive";
}

interface QuarantineMoveConflict {
  curation_item_id: string;
  conflict_kind: string;
  conflict_item_id: string;
}

/** 409 `CURATION_QUARANTINE_MOVE_CONFLICT` problem details에서 충돌 목록을 꺼낸다. */
function quarantineMoveConflicts(
  error: Error | null,
): QuarantineMoveConflict[] {
  if (
    !(error instanceof ApiClientError) ||
    error.status !== 409 ||
    error.problem?.code !== "CURATION_QUARANTINE_MOVE_CONFLICT"
  ) {
    return [];
  }
  const details = error.problem.details;
  if (typeof details !== "object" || details === null) return [];
  const conflicts = (details as Record<string, unknown>).conflicts;
  if (!Array.isArray(conflicts)) return [];
  const parsed: QuarantineMoveConflict[] = [];
  for (const entry of conflicts) {
    if (typeof entry !== "object" || entry === null) continue;
    const record = entry as Record<string, unknown>;
    if (
      typeof record.curation_item_id !== "string" ||
      typeof record.conflict_kind !== "string" ||
      typeof record.conflict_item_id !== "string"
    ) {
      continue;
    }
    parsed.push({
      curation_item_id: record.curation_item_id,
      conflict_kind: record.conflict_kind,
      conflict_item_id: record.conflict_item_id,
    });
  }
  return parsed;
}

function quarantineErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useCurationQuarantineController() {
  const confirm = useConfirm();
  const quarantineQuery = useAdminCurationQuarantineCollections();
  const targetOptionsQuery = useAdminCurationCollections({ page_size: 500 });
  const reclassify = useReclassifyCurationQuarantineMutation();

  const [selectedQuarantineId, setSelectedQuarantineId] = useState<
    string | null
  >(null);
  const [targetOverrideId, setTargetOverrideId] = useState<string | null>(null);
  const [itemSelection, setItemSelection] = useState<Record<string, boolean>>(
    {},
  );
  const [standaloneForm, setStandaloneForm] = useState<StandaloneFormState>(
    INITIAL_STANDALONE_FORM,
  );
  const [message, setMessage] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const quarantineCollections = quarantineQuery.data?.data.items ?? [];
  const activeQuarantineId =
    selectedQuarantineId ?? quarantineCollections[0]?.collection_id ?? null;
  const activeQuarantine =
    quarantineCollections.find(
      (collection) => collection.collection_id === activeQuarantineId,
    ) ?? null;
  const itemsQuery = useAdminCurationQuarantineItems(
    activeQuarantineId,
    targetOverrideId,
  );
  const preview = itemsQuery.data?.data ?? null;
  const targetOptions = (targetOptionsQuery.data?.data.items ?? []).filter(
    (collection) => collection.collection_id !== activeQuarantineId,
  );
  const selectedItemIds: string[] = [];
  for (const item of preview?.items ?? []) {
    if (itemSelection[item.curation_item_id]) {
      selectedItemIds.push(item.curation_item_id);
    }
  }
  const moveConflicts = quarantineMoveConflicts(reclassify.error);
  const mutationError = reclassify.error;

  const reloadAfterStaleRevision = async (error: unknown) => {
    if (!(error instanceof ApiClientError) || error.status !== 412) return;
    await Promise.all([
      quarantineQuery.refetch(),
      itemsQuery.refetch(),
      targetOptionsQuery.refetch(),
    ]);
    setItemSelection({});
    setLocalError(
      "다른 변경이 먼저 반영되어 격리 목록·대상·충돌 미리보기를 다시 불러왔습니다. 내용을 확인한 뒤 다시 실행하세요.",
    );
    reclassify.reset();
  };

  const selectQuarantine = (collectionId: string) => {
    setSelectedQuarantineId(collectionId);
    setTargetOverrideId(null);
    setItemSelection({});
    setMessage(null);
    setLocalError(null);
    reclassify.reset();
  };

  const selectTarget = (collectionId: string) => {
    setTargetOverrideId(collectionId || null);
    setItemSelection({});
    setMessage(null);
    setLocalError(null);
    reclassify.reset();
  };

  const toggleItem = (curationItemId: string, checked: boolean) => {
    setItemSelection((current) => ({ ...current, [curationItemId]: checked }));
  };

  const moveItems = async () => {
    if (!activeQuarantineId || !activeQuarantine || !preview) return;
    setMessage(null);
    if (preview.target_collection_id === null || preview.target_missing) {
      setLocalError(
        "이동할 target collection이 없습니다. 다른 collection을 선택하거나 별도 collection으로 확정하세요.",
      );
      return;
    }
    setLocalError(null);
    const movingAll = selectedItemIds.length === 0;
    const moveCount = movingAll ? preview.items.length : selectedItemIds.length;
    const confirmed = await confirm({
      title: "격리 항목 이동",
      description: movingAll
        ? `격리 항목 전체 ${moveCount}개를 target collection으로 이동할까요? 충돌이 하나라도 있으면 전체가 거부됩니다.`
        : `선택한 격리 항목 ${moveCount}개를 target collection으로 이동할까요? 충돌이 하나라도 있으면 전체가 거부됩니다.`,
      confirmLabel: "이동",
    });
    if (!confirmed) return;
    try {
      const response = await reclassify.mutateAsync({
        collectionId: activeQuarantineId,
        commandEtag: activeQuarantine.command_etag,
        body: {
          action: "move",
          target_collection_id: preview.target_collection_id,
          target_collection_revision: preview.target_collection_revision,
          item_ids: movingAll ? null : selectedItemIds,
        },
      });
      setItemSelection({});
      const movedCount = response.data.moved_item_ids?.length ?? 0;
      setMessage(
        response.data.quarantine_collection_deleted
          ? `${movedCount}개 항목을 이동했고, 빈 격리 collection을 삭제했습니다.`
          : `${movedCount}개 항목을 이동했습니다.`,
      );
      if (response.data.quarantine_collection_deleted) {
        setSelectedQuarantineId(null);
        setTargetOverrideId(null);
      }
    } catch (error) {
      await reloadAfterStaleRevision(error);
    }
  };

  const confirmStandalone = async () => {
    if (!activeQuarantineId || !activeQuarantine) return;
    setMessage(null);
    const collectionKey = standaloneForm.collectionKey.trim();
    const title = standaloneForm.title.trim();
    if (!collectionKey || !title) {
      setLocalError(
        "별도 collection 확정에는 collection key와 제목이 모두 필요합니다.",
      );
      return;
    }
    setLocalError(null);
    const confirmed = await confirm({
      title: "별도 collection 확정",
      description: `이 격리 collection을 “${collectionKey}” 별도 collection으로 확정할까요? 0065 격리 marker가 제거됩니다.`,
      confirmLabel: "확정",
    });
    if (!confirmed) return;
    try {
      const response = await reclassify.mutateAsync({
        collectionId: activeQuarantineId,
        commandEtag: activeQuarantine.command_etag,
        body: {
          action: "confirm_standalone",
          collection_key: collectionKey,
          title,
        },
      });
      setStandaloneForm(INITIAL_STANDALONE_FORM);
      setMessage(
        `“${response.data.collection_key ?? collectionKey}” 별도 collection으로 확정했습니다.`,
      );
      setSelectedQuarantineId(null);
      setTargetOverrideId(null);
      setItemSelection({});
    } catch (error) {
      await reloadAfterStaleRevision(error);
    }
  };

  return {
    activeQuarantine,
    activeQuarantineId,
    confirmStandalone,
    itemSelection,
    itemsQuery,
    localError,
    message,
    moveConflicts,
    moveItems,
    mutationError,
    preview,
    quarantineCollections,
    quarantineQuery,
    reclassify,
    selectQuarantine,
    selectTarget,
    selectedItemIds,
    setStandaloneForm,
    standaloneForm,
    targetOptions,
    targetOptionsQuery,
    targetOverrideId,
    toggleItem,
  };
}

function QuarantineStatusMessages({
  localError,
  message,
  moveConflicts,
  mutationError,
}: Pick<ReturnType<typeof useCurationQuarantineController>, "localError" | "message" | "moveConflicts" | "mutationError">) {
  return (
    <>
      {localError || mutationError ? (
        <Alert variant="destructive">
          <AlertTitle>재분류 실패</AlertTitle>
          <AlertDescription>
            {localError ?? quarantineErrorMessage(mutationError)} — 대상과 선택 항목을 확인한 뒤 다시
            시도하세요.
          </AlertDescription>
        </Alert>
      ) : null}
      {moveConflicts.length > 0 ? (
        <Alert data-testid="quarantine-move-conflicts" variant="destructive">
          <AlertTitle>
            이동 충돌 {moveConflicts.length}건 — 전체가 거부되었습니다
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-disc space-y-1 pl-4">
              {moveConflicts.map((conflict) => (
                <li key={conflict.curation_item_id}>
                  <span className="font-mono text-xs">
                    {shortId(conflict.curation_item_id, 20)}
                  </span>
                  {" · "}
                  {conflictKindLabel(conflict.conflict_kind)}
                  {" · 기존 항목 "}
                  <span className="font-mono text-xs">
                    {shortId(conflict.conflict_item_id, 20)}
                  </span>
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      {/* 조용한 결과 줄(role=status) — 축하 배너 대신 한 줄(M15). */}
      <p
        aria-live="polite"
        className="min-h-[1lh] text-xs text-text-secondary"
        role="status"
      >
        {message}
      </p>
    </>
  );
}

function QuarantineCollectionList({
  activeQuarantineId,
  quarantineCollections,
  quarantineQuery,
  selectQuarantine,
}: Pick<ReturnType<typeof useCurationQuarantineController>, "activeQuarantineId" | "quarantineCollections" | "quarantineQuery" | "selectQuarantine">) {
  return (
    <SectionCard
      actions={
        <Button
          aria-label="격리 collection 목록 새로고침"
          disabled={quarantineQuery.isFetching}
          size="icon-sm"
          type="button"
          variant="ghost"
          onClick={() => void quarantineQuery.refetch()}
        >
          <RefreshCwIcon />
        </Button>
      }
      description={`현재 ${formatCount(quarantineCollections.length)}개`}
      headingLevel={3}
      title="격리 collection"
    >
      {quarantineQuery.isError ? (
        <Alert variant="destructive">
          <AlertTitle>격리 목록 조회 실패</AlertTitle>
          <AlertDescription>{quarantineQuery.error.message}</AlertDescription>
        </Alert>
      ) : (
        <SelectableRowGroup
          aria-label="격리 collection"
          className="-mx-3"
          data-testid="quarantine-collection-list"
          divided
        >
          {quarantineCollections.map((collection) => (
            <SelectableRow
              key={collection.collection_id}
              selected={activeQuarantineId === collection.collection_id}
              trailing={<StatusBadge status={collection.status} />}
              onSelect={() => selectQuarantine(collection.collection_id)}
            >
              <SelectableRowTitle>{collection.title}</SelectableRowTitle>
              <SelectableRowDescription className="font-mono">
                {collection.collection_key} · {collection.edition_key || "회차 없음"}
              </SelectableRowDescription>
              <SelectableRowDescription className="tabular-nums">
                {formatCount(collection.item_count)}개 ·{" "}
                {collection.marker_intact ? "marker 정상" : "marker 변조"}
              </SelectableRowDescription>
            </SelectableRow>
          ))}
        </SelectableRowGroup>
      )}
    </SectionCard>
  );
}

function QuarantineThemeSourceColumn({
  source,
  theme,
  title,
}: {
  source: CurationQuarantineSource | null;
  theme: CurationQuarantineTheme | null;
  title: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <h4 className="text-xs font-semibold text-text-primary">{title}</h4>
      <DetailList
        items={[
          {
            label: "테마",
            value: theme
              ? `${theme.theme_name} · ${theme.theme_slug} · ${theme.theme_group}`
              : null,
          },
          {
            label: "출처",
            value: source
              ? `${source.source_name ?? NULL_GLYPH} · ${source.provider ?? NULL_GLYPH}/${source.dataset_key ?? NULL_GLYPH}`
              : null,
          },
        ]}
        layout="inline"
      />
    </div>
  );
}

function QuarantineComparison({
  activeQuarantine,
}: Pick<ReturnType<typeof useCurationQuarantineController>, "activeQuarantine">) {
  if (!activeQuarantine) return null;
  const original = activeQuarantine.original_collection;
  return (
    <div className="space-y-3" data-testid="quarantine-comparison">
      <div className="grid gap-4 md:grid-cols-2 md:[&>*:not(:first-child)]:border-l md:[&>*:not(:first-child)]:border-border md:[&>*:not(:first-child)]:pl-4">
        <QuarantineThemeSourceColumn
          source={activeQuarantine.quarantine_source}
          theme={activeQuarantine.quarantine_theme}
          title="격리 보관 theme/source"
        />
        <QuarantineThemeSourceColumn
          source={original?.source ?? null}
          theme={original?.theme ?? null}
          title={
            original?.exists
              ? `원본 collection 현재 상태 — ${original.title ?? NULL_GLYPH}`
              : "원본 collection 현재 상태"
          }
        />
      </div>
      {!original?.exists ? (
        <Alert variant="destructive">
          <AlertTitle>원본 collection 없음</AlertTitle>
          <AlertDescription>
            0065 marker가 가리키는 원본 collection이 더 이상 존재하지 않습니다.
            다른 target collection을 선택하거나 별도 collection으로 확정하세요.
          </AlertDescription>
        </Alert>
      ) : (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
          <span>원본</span>
          <StatusBadge status={original.status ?? null} />
          <span>· {original.visibility ?? NULL_GLYPH}</span>
          <span className="font-mono slashed-zero">
            · {shortId(original.collection_id, 20)}
          </span>
        </div>
      )}
    </div>
  );
}

function QuarantineTargetPicker({
  preview,
  selectTarget,
  targetOptions,
  targetOverrideId,
}: Pick<ReturnType<typeof useCurationQuarantineController>, "preview" | "selectTarget" | "targetOptions" | "targetOverrideId">) {
  return (
    <div className="space-y-2">
      <FormSelect
        label="이동 target collection"
        value={targetOverrideId ?? ""}
        onChange={(event) => selectTarget(event.target.value)}
      >
        <NativeSelectOption value="">원본 collection (기본)</NativeSelectOption>
        {targetOptions.map((collection) => (
          <NativeSelectOption
            key={collection.collection_id}
            value={collection.collection_id}
          >
            {collection.title} · {collection.collection_key}
          </NativeSelectOption>
        ))}
      </FormSelect>
      {preview?.target_missing ? (
        <Alert variant="destructive">
          <AlertTitle>target collection 없음</AlertTitle>
          <AlertDescription>
            선택한 target collection이 존재하지 않아 이동할 수 없습니다.
          </AlertDescription>
        </Alert>
      ) : null}
      {preview && !preview.target_missing && preview.target_archived ? (
        <Alert variant="destructive">
          <AlertTitle>target collection 보관됨</AlertTitle>
          <AlertDescription>
            target collection이 archive 상태라 move가 거부됩니다.
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

function QuarantineItemsTable({
  itemSelection,
  itemsQuery,
  preview,
  toggleItem,
}: Pick<ReturnType<typeof useCurationQuarantineController>, "itemSelection" | "itemsQuery" | "preview" | "toggleItem">) {
  if (itemsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>격리 item 조회 실패</AlertTitle>
        <AlertDescription>{itemsQuery.error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!preview) {
    return (
      <p aria-busy="true" className="text-xs text-text-secondary">
        격리 item conflict preview를 불러오는 중입니다.
      </p>
    );
  }
  if (preview.items.length === 0) {
    return (
      <EmptyState
        description="이 격리 collection에 남은 항목이 없습니다."
        size="sm"
        title="격리 item이 없습니다"
      />
    );
  }
  return (
    <Table data-testid="quarantine-items-table">
      <TableHeader>
        <TableRow>
          <TableHead>선택</TableHead>
          <TableHead>장소</TableHead>
          <TableHead>출처 항목</TableHead>
          <TableHead>상태</TableHead>
          <TableHead>conflict preview</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {preview.items.map((item) => (
          <TableRow key={item.curation_item_id}>
            <TableCell>
              <Checkbox
                aria-label={`${item.place_name} 이동 선택`}
                checked={itemSelection[item.curation_item_id] ?? false}
                onCheckedChange={(checked) =>
                  toggleItem(item.curation_item_id, checked === true)
                }
              />
            </TableCell>
            <TableCell className="whitespace-normal">
              <div className="flex max-w-64 flex-col gap-0.5">
                <span className="font-medium">{item.place_name}</span>
                <span className="font-mono text-2xs text-text-secondary slashed-zero">
                  {item.feature_id
                    ? shortId(item.feature_id, 20)
                    : "Feature 미연결"}
                </span>
              </div>
            </TableCell>
            <TableCell className="whitespace-normal">
              <div className="flex max-w-64 flex-col gap-1">
                <span className="font-mono text-xs slashed-zero">
                  {item.external_item_id}/{item.external_component_id}
                </span>
                {item.source_present ? null : (
                  <StatusBadge label="원천 누락" status="missing" />
                )}
              </div>
            </TableCell>
            <TableCell>
              <div className="flex flex-col items-start gap-1">
                <StatusBadge status={item.status} />
                {item.archived_at ? (
                  <span className="text-2xs text-text-secondary">보관됨</span>
                ) : null}
              </div>
            </TableCell>
            <TableCell className="whitespace-normal">
              <div className="flex flex-col items-start gap-1">
                <StatusBadge
                  label={conflictKindLabel(item.conflict_kind)}
                  status={item.conflict_kind}
                  tone={conflictTone(item.conflict_kind)}
                />
                {item.conflict_item_id ? (
                  <span className="font-mono text-2xs text-text-secondary slashed-zero">
                    기존 {shortId(item.conflict_item_id, 20)}
                  </span>
                ) : null}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function QuarantineActions({
  confirmStandalone,
  moveItems,
  preview,
  reclassify,
  selectedItemIds,
  setStandaloneForm,
  standaloneForm,
}: Pick<ReturnType<typeof useCurationQuarantineController>, "confirmStandalone" | "moveItems" | "preview" | "reclassify" | "selectedItemIds" | "setStandaloneForm" | "standaloneForm">) {
  const moveDisabled =
    reclassify.isPending ||
    !preview ||
    preview.target_collection_id === null ||
    preview.target_missing ||
    preview.target_archived ||
    preview.items.length === 0;
  // 이동이 잠긴 이유를 버튼 아래 한 줄로 보여 준다(M35).
  const moveDisabledReason = reclassify.isPending
    ? "재분류가 진행 중입니다"
    : !preview
      ? "conflict preview를 불러온 뒤 이동할 수 있습니다"
      : preview.target_collection_id === null
        ? "이동 target collection을 선택하세요"
        : preview.target_missing
          ? "target collection이 존재하지 않습니다"
          : preview.target_archived
            ? "target collection이 archive 상태입니다"
            : preview.items.length === 0
              ? "이동할 격리 item이 없습니다"
              : undefined;
  const isMovePending = reclassify.isPending && reclassify.variables?.body.action === "move";
  const isStandalonePending =
    reclassify.isPending && reclassify.variables?.body.action !== "move";
  return (
    <div className="grid gap-6 border-t border-border pt-4 md:grid-cols-2 md:[&>*:not(:first-child)]:border-l md:[&>*:not(:first-child)]:border-border md:[&>*:not(:first-child)]:pl-6">
      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-semibold text-text-primary">target으로 이동</h4>
        <p className="text-xs text-text-secondary">
          {selectedItemIds.length > 0
            ? `선택한 ${formatCount(selectedItemIds.length)}개 항목만 이동합니다.`
            : "선택한 항목이 없으면 전체를 이동합니다."}
        </p>
        <div>
          <Button
            disabled={moveDisabled}
            disabledReason={moveDisabledReason}
            loading={isMovePending}
            type="button"
            onClick={() => void moveItems()}
          >
            <ArchiveRestoreIcon data-icon="inline-start" />
            이동
          </Button>
        </div>
        <p className="min-h-[1lh] text-2xs text-text-secondary">
          {moveDisabledReason ?? "이동 전 확인 대화상자에서 대상과 건수를 다시 보여 줍니다."}
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-semibold text-text-primary">별도 collection 확정</h4>
        <p className="text-xs text-text-secondary">
          0065 격리 marker를 제거하고 확정된 key/제목의 독립 collection으로
          유지합니다.
        </p>
        <FormField
          label="확정 collection key"
          placeholder="standalone-collection-key"
          size="sm"
          value={standaloneForm.collectionKey}
          onChange={(event) =>
            setStandaloneForm((current) => ({
              ...current,
              collectionKey: event.target.value,
            }))
          }
        />
        <FormField
          label="확정 제목"
          placeholder="독립 collection 제목"
          size="sm"
          value={standaloneForm.title}
          onChange={(event) =>
            setStandaloneForm((current) => ({
              ...current,
              title: event.target.value,
            }))
          }
        />
        <div>
          <Button
            disabled={reclassify.isPending}
            disabledReason="재분류가 진행 중입니다"
            loading={isStandalonePending}
            type="button"
            variant="outline"
            onClick={() => void confirmStandalone()}
          >
            <ShieldCheckIcon data-icon="inline-start" />
            별도 collection 확정
          </Button>
        </div>
      </div>
    </div>
  );
}

function QuarantineWorkspace({
  activeQuarantine,
  confirmStandalone,
  itemSelection,
  itemsQuery,
  moveItems,
  preview,
  reclassify,
  selectTarget,
  selectedItemIds,
  setStandaloneForm,
  standaloneForm,
  targetOptions,
  targetOverrideId,
  toggleItem,
}: Pick<ReturnType<typeof useCurationQuarantineController>, "activeQuarantine" | "confirmStandalone" | "itemSelection" | "itemsQuery" | "moveItems" | "preview" | "reclassify" | "selectTarget" | "selectedItemIds" | "setStandaloneForm" | "standaloneForm" | "targetOptions" | "targetOverrideId" | "toggleItem">) {
  return (
    <SectionCard
      description={
        activeQuarantine
          ? `${activeQuarantine.collection_key} · 생성 ${activeQuarantine.created_by ?? NULL_GLYPH}`
          : "왼쪽에서 격리 collection을 선택하세요."
      }
      headingLevel={3}
      title={activeQuarantine?.title ?? "격리 상세"}
    >
      {activeQuarantine ? (
        <div className="space-y-5" data-testid="quarantine-workspace">
          <QuarantineComparison activeQuarantine={activeQuarantine} />
          <QuarantineTargetPicker
            preview={preview}
            selectTarget={selectTarget}
            targetOptions={targetOptions}
            targetOverrideId={targetOverrideId}
          />
          <QuarantineItemsTable
            itemSelection={itemSelection}
            itemsQuery={itemsQuery}
            preview={preview}
            toggleItem={toggleItem}
          />
          <QuarantineActions
            confirmStandalone={confirmStandalone}
            moveItems={moveItems}
            preview={preview}
            reclassify={reclassify}
            selectedItemIds={selectedItemIds}
            setStandaloneForm={setStandaloneForm}
            standaloneForm={standaloneForm}
          />
        </div>
      ) : (
        <EmptyState title="격리 collection을 선택하세요" />
      )}
    </SectionCard>
  );
}

function CurationQuarantinePanelView({
  activeQuarantine,
  activeQuarantineId,
  confirmStandalone,
  itemSelection,
  itemsQuery,
  localError,
  message,
  moveConflicts,
  moveItems,
  mutationError,
  preview,
  quarantineCollections,
  quarantineQuery,
  reclassify,
  selectQuarantine,
  selectTarget,
  selectedItemIds,
  setStandaloneForm,
  standaloneForm,
  targetOptions,
  targetOverrideId,
  toggleItem,
}: ReturnType<typeof useCurationQuarantineController>) {
  return (
    <section
      aria-labelledby="curation-quarantine-heading"
      className="flex flex-col gap-4 border-t border-border pt-6"
    >
      <div className="flex flex-col gap-1">
        <h2
          className="text-md leading-snug font-semibold text-text-primary"
          id="curation-quarantine-heading"
        >
          격리 collection 재분류
        </h2>
        <p className="text-xs text-text-secondary">
          0065 마이그레이션이 격리한 collection을 원본 이동 또는 별도 collection 확정으로 명시
          재분류합니다.
        </p>
      </div>
      <div className="space-y-4">
        <QuarantineStatusMessages
          localError={localError}
          message={message}
          moveConflicts={moveConflicts}
          mutationError={mutationError}
        />
        {!quarantineQuery.isError &&
        quarantineQuery.data !== undefined &&
        quarantineCollections.length === 0 ? (
          <EmptyState
            description="0065 마이그레이션이 격리한 큐레이션 collection이 없는 정상 상태입니다."
            icon={<ShieldCheckIcon />}
            title="격리된 collection 없음"
          />
        ) : (
          <div className="grid gap-6 xl:grid-cols-[var(--rail)_minmax(0,1fr)]">
            <QuarantineCollectionList
              activeQuarantineId={activeQuarantineId}
              quarantineCollections={quarantineCollections}
              quarantineQuery={quarantineQuery}
              selectQuarantine={selectQuarantine}
            />
            <QuarantineWorkspace
              activeQuarantine={activeQuarantine}
              confirmStandalone={confirmStandalone}
              itemSelection={itemSelection}
              itemsQuery={itemsQuery}
              moveItems={moveItems}
              preview={preview}
              reclassify={reclassify}
              selectTarget={selectTarget}
              selectedItemIds={selectedItemIds}
              setStandaloneForm={setStandaloneForm}
              standaloneForm={standaloneForm}
              targetOptions={targetOptions}
              targetOverrideId={targetOverrideId}
              toggleItem={toggleItem}
            />
          </div>
        )}
      </div>
    </section>
  );
}

export function CurationQuarantinePanel() {
  const controller = useCurationQuarantineController();
  return <CurationQuarantinePanelView {...controller} />;
}
