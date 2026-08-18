"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import {
  CheckIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { ApiClientError } from "@/api/client";
import {
  type ThemeCandidate,
  type ThemeCandidateListParams,
  type ThemeCandidatePromoteRequest,
  type ThemeCandidateTransition,
  usePromoteThemeCandidateMutation,
  useRejectThemeCandidateMutation,
  useThemeCandidate,
  useThemeCandidates,
  useThemeCandidateTransitions,
} from "@/api/curation-candidates";
import {
  useAdminCurationCollection,
  useAdminCurationCollections,
} from "@/api/curations";
import { AdminShell } from "@/components/admin-shell";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { EntityLink } from "@/components/entity-link";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { JsonViewer } from "@/components/json-viewer";
import { CursorPager } from "@/components/pagination-bar";
import { SectionCard } from "@/components/section-card";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable, type DataTableColumnMeta } from "@/components/ui/data-table";
import { FormField, FormSelect, FormTextArea } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { NULL_GLYPH, formatDateTime, shortId } from "@/lib/format";
import { statusLabel } from "@/lib/status-label";

const REVIEW_STATES = ["all", "open", "promoted", "rejected"] as const;
const RELATIONS: ThemeCandidatePromoteRequest["curation_relation"][] = [
  "primary_stop",
  "food_stop",
  "cafe_stop",
  "bookstore_stop",
  "nearby_option",
  "accessibility_support",
  "pet_support",
  "family_support",
  "theme_area_anchor",
];
// enum → 한글 라벨(design.md §Copy — 옵션도 raw enum 금지). 값 정본은 API 스키마.
const RELATION_LABELS: Record<ThemeCandidatePromoteRequest["curation_relation"], string> = {
  primary_stop: "주요 방문지",
  food_stop: "식사",
  cafe_stop: "카페",
  bookstore_stop: "서점",
  nearby_option: "인근 선택지",
  accessibility_support: "접근성 지원",
  pet_support: "반려동물 동반",
  family_support: "가족 동반",
  theme_area_anchor: "테마 구역 앵커",
};

type ReviewStateFilter = (typeof REVIEW_STATES)[number];
type EligibilityFilter = "all" | "present" | "missing";

interface Filters {
  reviewState: ReviewStateFilter;
  eligibility: EligibilityFilter;
  ruleId: string;
  themeId: string;
  sourceId: string;
  featureId: string;
}

interface PromoteForm {
  collectionId: string;
  externalItemId: string;
  externalComponentId: string;
  placeName: string;
  relation: ThemeCandidatePromoteRequest["curation_relation"];
  itemStatus: ThemeCandidatePromoteRequest["item_status"];
  reusePolicy: ThemeCandidatePromoteRequest["reuse_policy"];
  sortOrder: string;
  itemTitle: string;
  itemSummary: string;
  addressHint: string;
  reasonCode: string;
}

const INITIAL_FILTERS: Filters = {
  reviewState: "open",
  eligibility: "present",
  ruleId: "",
  themeId: "",
  sourceId: "",
  featureId: "",
};

const INITIAL_PROMOTE_FORM: PromoteForm = {
  collectionId: "",
  externalItemId: "",
  externalComponentId: "main",
  placeName: "",
  relation: "primary_stop",
  itemStatus: "included",
  reusePolicy: "allowed",
  sortOrder: "0",
  itemTitle: "",
  itemSummary: "",
  addressHint: "",
  reasonCode: "operator_promote",
};

function candidateParams(
  filters: Filters,
  cursor: string | null,
): ThemeCandidateListParams {
  return {
    cursor,
    eligibility_present:
      filters.eligibility === "all"
        ? undefined
        : filters.eligibility === "present",
    feature_id: filters.featureId.trim() || undefined,
    page_size: 50,
    review_state:
      filters.reviewState === "all" ? undefined : filters.reviewState,
    rule_id: filters.ruleId.trim() || undefined,
    source_id: filters.sourceId.trim() || undefined,
    theme_id: filters.themeId.trim() || undefined,
  };
}

function displayError(error: unknown): string {
  if (error instanceof ApiClientError && [409, 412, 428].includes(error.status)) {
    return "후보 또는 컬렉션이 다른 작업으로 변경되었습니다. 현재 상태를 다시 불러온 뒤 판단하세요.";
  }
  return error instanceof Error ? error.message : String(error);
}

function isStaleCommandError(error: unknown): boolean {
  return error instanceof ApiClientError && [409, 412, 428].includes(error.status);
}

function eligibilityLabel(present: boolean): string {
  return present ? "현재 rule 일치" : "현재 rule 불일치";
}

function reviewStateOptionLabel(state: ReviewStateFilter): string {
  return state === "all" ? "전체" : statusLabel(state);
}

function CandidateFilters({
  draft,
  isFetching,
  setDraft,
  submit,
}: {
  draft: Filters;
  isFetching: boolean;
  setDraft: (value: Filters) => void;
  submit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={submit}>
      <FilterBar>
        <FilterField label="검토 상태">
          <NativeSelect
            value={draft.reviewState}
            onChange={(event) =>
              setDraft({
                ...draft,
                reviewState: event.target.value as ReviewStateFilter,
              })
            }
          >
            {REVIEW_STATES.map((state) => (
              <NativeSelectOption key={state} value={state}>
                {reviewStateOptionLabel(state)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </FilterField>
        <FilterField label="현재 eligibility">
          <NativeSelect
            value={draft.eligibility}
            onChange={(event) =>
              setDraft({
                ...draft,
                eligibility: event.target.value as EligibilityFilter,
              })
            }
          >
            <NativeSelectOption value="all">전체</NativeSelectOption>
            <NativeSelectOption value="present">현재 일치</NativeSelectOption>
            <NativeSelectOption value="missing">현재 불일치</NativeSelectOption>
          </NativeSelect>
        </FilterField>
        {(
          [
            ["ruleId", "Rule ID"],
            ["themeId", "Theme ID"],
            ["sourceId", "Source ID"],
            ["featureId", "Feature ID"],
          ] as const
        ).map(([key, label]) => (
          <FilterField className="w-44" key={key} label={label}>
            <Input
              className="font-mono"
              value={draft[key]}
              onChange={(event) =>
                setDraft({ ...draft, [key]: event.target.value })
              }
            />
          </FilterField>
        ))}
        <FilterActions>
          <Button loading={isFetching} type="submit">
            <SearchIcon data-icon="inline-start" />
            조회
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => setDraft(INITIAL_FILTERS)}
          >
            초기화
          </Button>
        </FilterActions>
      </FilterBar>
    </form>
  );
}

function CandidateList({
  candidates,
  isFetching,
  isFirst,
  isLoading,
  nextCursor,
  onFirst,
  onNext,
  onSelect,
  selectedId,
}: {
  candidates: ThemeCandidate[];
  isFetching: boolean;
  isFirst: boolean;
  isLoading: boolean;
  nextCursor: string | null;
  onFirst: () => void;
  onNext: () => void;
  onSelect: (candidateId: string) => void;
  selectedId: string | null;
}) {
  const columns = useMemo<ColumnDef<ThemeCandidate, unknown>[]>(
    () => [
      {
        id: "candidate",
        header: "후보",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">
              {row.original.proposal_title ?? row.original.feature_name}
            </div>
            <code className="font-mono text-xs text-text-secondary">
              {shortId(row.original.candidate_id, 18)}
            </code>
          </>
        ),
      },
      {
        id: "feature",
        header: "Feature",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div>{row.original.feature_name}</div>
            <div className="text-xs text-text-secondary">
              {row.original.feature_kind} · {row.original.feature_category}
            </div>
          </>
        ),
      },
      {
        id: "theme",
        header: "테마/출처",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div>{row.original.theme_name}</div>
            <div className="text-xs text-text-secondary">{row.original.source_name}</div>
          </>
        ),
      },
      {
        id: "state",
        header: "상태",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-col items-start gap-1">
            <StatusBadge status={row.original.review_state} />
            <span className="text-2xs text-text-secondary">
              {eligibilityLabel(row.original.eligibility_present)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "updated_at",
        header: "갱신",
        enableSorting: false,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(row.original.updated_at)}
          </span>
        ),
      },
    ],
    [],
  );
  return (
    <SectionCard
      description="행을 선택하면 우측에 현재 증거와 감사 전이가 열립니다."
      title="후보 목록"
    >
      <DataTable
        columns={columns}
        data={candidates}
        emptyState={{
          title: "조건에 맞는 후보가 없습니다.",
          description: "검토 상태를 전체로 바꾸거나 rule/theme 필터를 비워 보세요.",
        }}
        getRowId={(row) => row.candidate_id}
        isLoading={isLoading}
        isRowActive={(row) => row.candidate_id === selectedId}
        onRowClick={(row) => onSelect(row.candidate_id)}
      />
      <CursorPager
        ariaPrefix="큐레이션 후보"
        hasNext={nextCursor !== null}
        isFetching={isFetching}
        isFirst={isFirst}
        summary={`이 페이지 ${candidates.length.toLocaleString("ko-KR")}건`}
        onFirst={onFirst}
        onNext={onNext}
      />
    </SectionCard>
  );
}

function CandidateDetail({ candidate }: { candidate: ThemeCandidate }) {
  const items: DetailItem[] = [
    {
      label: "Feature",
      value: <EntityLink id={candidate.feature_id} kind="feature" newTab />,
    },
    { label: "source entity", value: candidate.source_entity_key, mono: true },
    { label: "rule", value: candidate.rule_id, mono: true },
    { label: "source record", value: candidate.source_record_key, mono: true },
    { label: "rank", value: candidate.rank_score, numeric: true },
    { label: "disposition", value: statusLabel(candidate.disposition) },
  ];
  return (
    <SectionCard
      description={
        <>
          후보 rev {candidate.candidate_revision} · Feature rev{" "}
          {candidate.feature_row_revision}
        </>
      }
      title={candidate.proposal_title ?? candidate.feature_name}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge status={candidate.review_state} />
        <StatusBadge
          label={eligibilityLabel(candidate.eligibility_present)}
          status={candidate.eligibility_present ? "ok" : "warning"}
        />
        <StatusBadge status={candidate.lifecycle_state} />
        <StatusBadge status={candidate.publication_state} />
        <StatusBadge status={candidate.quality_state} />
      </div>
      <DetailList items={items} layout="inline" />
      {candidate.proposal_summary ? (
        <p className="text-sm text-text-primary">{candidate.proposal_summary}</p>
      ) : null}
      <div className="flex flex-col gap-3 border-t border-border pt-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-2xs font-medium text-text-secondary">match evidence</h3>
          <JsonViewer aria-label="match evidence" copyable maxHeight="sm" value={candidate.match_evidence ?? {}} />
        </div>
        <div className="flex flex-col gap-1">
          <h3 className="text-2xs font-medium text-text-secondary">effective Feature detail</h3>
          <JsonViewer aria-label="effective feature detail" copyable maxHeight="sm" value={candidate.feature_detail ?? {}} />
        </div>
      </div>
    </SectionCard>
  );
}

function CandidateCommands({
  candidate,
  collectionReady,
  collections,
  form,
  isPromoting,
  isRejecting,
  rejectReason,
  setForm,
  setRejectReason,
  submitPromote,
  submitReject,
}: {
  candidate: ThemeCandidate;
  collectionReady: boolean;
  collections: NonNullable<
    ReturnType<typeof useAdminCurationCollections>["data"]
  >["data"]["items"];
  form: PromoteForm;
  isPromoting: boolean;
  isRejecting: boolean;
  rejectReason: string;
  setForm: (value: PromoteForm) => void;
  setRejectReason: (value: string) => void;
  submitPromote: (event: FormEvent<HTMLFormElement>) => void;
  submitReject: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const isPending = isPromoting || isRejecting;
  const commandAllowed =
    candidate.disposition === "active" && candidate.review_state === "open";
  const commandBlockedReason = !commandAllowed
    ? "열린 상태의 활성 후보만 거절·승격할 수 있습니다."
    : null;
  const rejectBlockedReason =
    commandBlockedReason ??
    (!rejectReason.trim() ? "사유 코드를 입력하면 활성화됩니다." : null);
  const promoteBlockedReason =
    commandBlockedReason ??
    (!candidate.eligibility_present
      ? "현재 rule과 일치하지 않는 후보는 승격할 수 없습니다."
      : !form.collectionId
        ? "컬렉션을 선택하면 활성화됩니다."
        : !collectionReady
          ? "컬렉션 revision을 불러오는 중입니다."
          : null);
  return (
    <>
      <SectionCard
        description="거절 사유는 immutable transition에 기록됩니다."
        headingLevel={3}
        title="후보 거절"
      >
        <form className="flex flex-col gap-1" onSubmit={submitReject}>
          <FormField
            hint="예: operator_reject"
            label="사유 코드"
            required
            value={rejectReason}
            onChange={(event) => setRejectReason(event.target.value)}
          />
          <div className="flex flex-col items-start gap-1">
            <Button
              disabled={rejectBlockedReason !== null || isPending}
              disabledReason={rejectBlockedReason ?? "다른 명령을 처리하는 중입니다"}
              loading={isRejecting}
              type="submit"
              variant="destructive"
            >
              <XIcon data-icon="inline-start" />
              거절 확정
            </Button>
            {rejectBlockedReason ? (
              <span className="text-2xs text-text-secondary">{rejectBlockedReason}</span>
            ) : null}
          </div>
        </form>
      </SectionCard>
      <SectionCard
        description="선택한 collection revision과 후보 CAS를 한 요청에 고정합니다."
        headingLevel={3}
        title="canonical item으로 승격"
      >
        <form className="flex flex-col gap-1" onSubmit={submitPromote}>
          <FormSelect
            label="컬렉션"
            required
            value={form.collectionId}
            onChange={(event) =>
              setForm({ ...form, collectionId: event.target.value })
            }
          >
            <NativeSelectOption value="">선택</NativeSelectOption>
            {collections.map((collection) => (
              <NativeSelectOption
                key={collection.collection_id}
                value={collection.collection_id}
              >
                {collection.title} · rev {collection.row_revision}
              </NativeSelectOption>
            ))}
          </FormSelect>
          {(
            [
              ["externalItemId", "외부 item ID"],
              ["externalComponentId", "외부 component ID"],
              ["placeName", "장소명"],
              ["sortOrder", "정렬 순서"],
              ["itemTitle", "표시 제목"],
              ["addressHint", "주소 힌트"],
              ["reasonCode", "사유 코드"],
            ] as const
          ).map(([key, label]) => (
            <FormField
              key={key}
              label={label}
              required={
                key === "externalItemId" ||
                key === "externalComponentId" ||
                key === "placeName" ||
                key === "reasonCode"
              }
              type={key === "sortOrder" ? "number" : "text"}
              value={form[key]}
              onChange={(event) =>
                setForm({ ...form, [key]: event.target.value })
              }
            />
          ))}
          <FormSelect
            label="관계"
            value={form.relation}
            onChange={(event) =>
              setForm({
                ...form,
                relation: event.target.value as PromoteForm["relation"],
              })
            }
          >
            {RELATIONS.map((relation) => (
              <NativeSelectOption key={relation} value={relation}>
                {RELATION_LABELS[relation]}
              </NativeSelectOption>
            ))}
          </FormSelect>
          <FormSelect
            label="항목 상태"
            value={form.itemStatus}
            onChange={(event) =>
              setForm({
                ...form,
                itemStatus: event.target.value as PromoteForm["itemStatus"],
              })
            }
          >
            <NativeSelectOption value="included">{statusLabel("included")}</NativeSelectOption>
            <NativeSelectOption value="candidate">{statusLabel("candidate")}</NativeSelectOption>
          </FormSelect>
          <FormSelect
            label="재사용 정책"
            value={form.reusePolicy}
            onChange={(event) =>
              setForm({
                ...form,
                reusePolicy: event.target.value as PromoteForm["reusePolicy"],
              })
            }
          >
            <NativeSelectOption value="allowed">{statusLabel("allowed")}</NativeSelectOption>
            <NativeSelectOption value="manual_review">
              {statusLabel("manual_review")}
            </NativeSelectOption>
            <NativeSelectOption value="blocked">{statusLabel("blocked")}</NativeSelectOption>
          </FormSelect>
          <FormTextArea
            label="항목 요약"
            value={form.itemSummary}
            onChange={(event) =>
              setForm({ ...form, itemSummary: event.target.value })
            }
          />
          <div className="flex flex-col items-start gap-1 border-t border-border pt-4">
            <Button
              disabled={promoteBlockedReason !== null || isPending}
              disabledReason={promoteBlockedReason ?? "다른 명령을 처리하는 중입니다"}
              loading={isPromoting}
              type="submit"
            >
              <CheckIcon data-icon="inline-start" />
              승격 확정
            </Button>
            {promoteBlockedReason ? (
              <span className="text-2xs text-text-secondary">{promoteBlockedReason}</span>
            ) : null}
          </div>
        </form>
      </SectionCard>
    </>
  );
}

function boolLabel(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return NULL_GLYPH;
  return value ? "일치" : "불일치";
}

function TransitionTimeline({
  transitions,
  isLoading,
}: {
  transitions: ThemeCandidateTransition[];
  isLoading: boolean;
}) {
  return (
    <SectionCard
      description="immutable candidate transition timeline입니다."
      headingLevel={3}
      title="감사 전이"
    >
      {isLoading ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : transitions.length === 0 ? (
        <p className="text-xs text-text-tertiary">기록된 전이가 없습니다.</p>
      ) : (
        <ol className="flex flex-col divide-y divide-border">
          {transitions.map((transition) => (
            <li className="flex flex-col gap-1 py-2" key={transition.transition_id}>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={transition.transition_kind} />
                <span className="text-sm font-medium">{transition.actor}</span>
                <span className="text-xs text-text-secondary tabular-nums">
                  {formatDateTime(transition.occurred_at)}
                </span>
              </div>
              <p className="text-sm tabular-nums">
                {statusLabel(transition.from_review_state) || NULL_GLYPH} ·{" "}
                {boolLabel(transition.from_eligibility_present)}
                {" → "}
                {statusLabel(transition.to_review_state) || NULL_GLYPH} ·{" "}
                {boolLabel(transition.to_eligibility_present)}
              </p>
              <p className="text-xs text-text-secondary">
                {transition.reason_code} · candidate rev {transition.candidate_revision}
              </p>
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  );
}

export function CurationCandidatesClient() {
  const [draftFilters, setDraftFilters] = useState(INITIAL_FILTERS);
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("operator_reject");
  const [promoteForm, setPromoteForm] = useState(INITIAL_PROMOTE_FORM);

  const candidatesQuery = useThemeCandidates(candidateParams(filters, cursor));
  const detailQuery = useThemeCandidate(selectedId);
  const transitionsQuery = useThemeCandidateTransitions(selectedId);
  const collectionsQuery = useAdminCurationCollections({ page_size: 500 });
  const collectionDetailQuery = useAdminCurationCollection(
    promoteForm.collectionId || null,
  );
  const rejectMutation = useRejectThemeCandidateMutation();
  const promoteMutation = usePromoteThemeCandidateMutation();
  const candidate = detailQuery.data?.data ?? null;
  const collections = collectionsQuery.data?.data.items ?? [];
  const mutationError = rejectMutation.error ?? promoteMutation.error;
  const queryError =
    candidatesQuery.error ??
    detailQuery.error ??
    transitionsQuery.error ??
    collectionsQuery.error ??
    collectionDetailQuery.error;

  const submitFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCursor(null);
    setSelectedId(null);
    setFilters(draftFilters);
  };

  const reloadCurrent = async () => {
    setMessage(null);
    await Promise.all([
      candidatesQuery.refetch(),
      detailQuery.refetch(),
      transitionsQuery.refetch(),
      collectionsQuery.refetch(),
      collectionDetailQuery.refetch(),
    ]);
  };

  const submitReject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!candidate || !rejectReason.trim()) return;
    setMessage(null);
    try {
      await rejectMutation.mutateAsync({
        body: { reason_code: rejectReason.trim() },
        candidateEtag: candidate.candidate_etag,
        candidateId: candidate.candidate_id,
      });
      setMessage("후보를 거절하고 감사 전이를 기록했습니다.");
    } catch {
      // mutationError가 RFC7807 detail을 표시한다.
    }
  };

  const submitPromote = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!candidate) return;
    const collectionDetail = collectionDetailQuery.data;
    if (!collectionDetail) return;
    const collection = collectionDetail.data.collection;
    const existingItem = collectionDetail.data.items.find(
      (item) =>
        item.external_item_id === promoteForm.externalItemId.trim() &&
        item.external_component_id === promoteForm.externalComponentId.trim(),
    );
    setMessage(null);
    try {
      await promoteMutation.mutateAsync({
        body: {
          address_hint: promoteForm.addressHint.trim() || null,
          collection_id: collection.collection_id,
          collection_revision: collection.row_revision,
          curation_relation: promoteForm.relation,
          external_component_id: promoteForm.externalComponentId.trim(),
          external_item_id: promoteForm.externalItemId.trim(),
          item_status: promoteForm.itemStatus,
          item_revision: existingItem?.row_revision,
          item_summary: promoteForm.itemSummary.trim() || null,
          item_title: promoteForm.itemTitle.trim() || null,
          place_name: promoteForm.placeName.trim(),
          reason_code: promoteForm.reasonCode.trim(),
          reuse_policy: promoteForm.reusePolicy,
          sort_order: Number(promoteForm.sortOrder),
        },
        candidateEtag: candidate.candidate_etag,
        candidateId: candidate.candidate_id,
      });
      setMessage("후보를 canonical collection item으로 승격했습니다.");
    } catch {
      // mutationError가 RFC7807 detail을 표시한다.
    }
  };

  const candidates = candidatesQuery.data?.data.items ?? [];
  const nextCursor = candidatesQuery.data?.meta.page?.next_cursor ?? null;
  const selectCandidate = (candidateId: string) => {
    const selected = candidates.find(
      (item) => item.candidate_id === candidateId,
    );
    setSelectedId(candidateId);
    if (!selected) return;
    setPromoteForm((current) => ({
      ...current,
      collectionId: current.collectionId || collections[0]?.collection_id || "",
      externalItemId: selected.candidate_id,
      itemSummary: selected.proposal_summary ?? "",
      itemTitle: selected.proposal_title ?? selected.feature_name,
      placeName: selected.feature_name,
    }));
  };

  return (
    <AdminShell
      breadcrumbs={[
        { href: "/admin/features/curated", label: "큐레이션 관리" },
        { label: "후보 검토" },
      ]}
      description="provider·rule이 만든 후보를 current evidence로 재검증해 거절하거나 canonical item으로 승격합니다."
      section="Feature 관리"
      title="큐레이션 후보 검토"
      actions={
        <Link
          className={buttonVariants({ variant: "outline" })}
          href="/admin/features/curated"
        >
          컬렉션 관리
          <ExternalLinkIcon data-icon="inline-end" />
        </Link>
      }
    >
      <div className="flex flex-col gap-6">
        <CandidateFilters
          draft={draftFilters}
          isFetching={candidatesQuery.isFetching}
          setDraft={setDraftFilters}
          submit={submitFilters}
        />
        {queryError ? (
          <Alert variant="destructive">
            <AlertTitle>후보 정보를 불러오지 못했습니다</AlertTitle>
            <AlertDescription>{displayError(queryError)}</AlertDescription>
            <AlertActions>
              <Button
                loading={candidatesQuery.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => void reloadCurrent()}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}
        {mutationError ? (
          <Alert variant="destructive">
            <AlertTitle>후보 명령을 완료하지 못했습니다</AlertTitle>
            <AlertDescription>{displayError(mutationError)}</AlertDescription>
            {isStaleCommandError(mutationError) ? (
              <AlertActions>
                <Button
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => void reloadCurrent()}
                >
                  <RefreshCwIcon data-icon="inline-start" />
                  현재 상태 다시 불러오기
                </Button>
              </AlertActions>
            ) : null}
          </Alert>
        ) : null}
        {message ? (
          <p
            aria-live="polite"
            className="flex items-center gap-2 text-sm text-text-secondary"
            role="status"
          >
            <CheckIcon aria-hidden="true" className="size-4 text-success" />
            <span>{message}</span>
          </p>
        ) : null}

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
          <CandidateList
            candidates={candidates}
            isFetching={candidatesQuery.isFetching}
            isFirst={cursor === null}
            isLoading={candidatesQuery.isLoading}
            nextCursor={nextCursor}
            selectedId={selectedId}
            onFirst={() => setCursor(null)}
            onNext={() => setCursor(nextCursor)}
            onSelect={selectCandidate}
          />

          <div className="flex flex-col gap-6">
            {candidate ? (
              <>
                <CandidateDetail candidate={candidate} />
                <CandidateCommands
                  candidate={candidate}
                  collectionReady={collectionDetailQuery.data !== undefined}
                  collections={collections}
                  form={promoteForm}
                  isPromoting={promoteMutation.isPending}
                  isRejecting={rejectMutation.isPending}
                  rejectReason={rejectReason}
                  setForm={setPromoteForm}
                  setRejectReason={setRejectReason}
                  submitPromote={submitPromote}
                  submitReject={submitReject}
                />
                <TransitionTimeline
                  isLoading={transitionsQuery.isLoading}
                  transitions={transitionsQuery.data?.data.items ?? []}
                />
              </>
            ) : selectedId && detailQuery.isLoading ? (
              <SectionCard title="후보 상세">
                <div className="flex flex-col gap-2" aria-busy="true">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-4 w-2/3" />
                </div>
              </SectionCard>
            ) : (
              <SectionCard title="후보 상세">
                <EmptyState
                  title="선택된 후보가 없습니다"
                  description="목록에서 행을 선택하면 증거·명령·감사 전이가 열립니다."
                />
              </SectionCard>
            )}
          </div>
        </div>
      </div>
    </AdminShell>
  );
}
