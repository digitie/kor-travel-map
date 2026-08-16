"use client";

import {
  CheckIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ApiClientError } from "@/api/client";
import {
  type ThemeCandidate,
  type ThemeCandidateListParams,
  type ThemeCandidatePromoteRequest,
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
import { CursorPager } from "@/components/pagination-bar";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { formatDateTime, shortId } from "@/lib/format";

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

function JsonEvidence({ value }: { value: unknown }) {
  return (
    <pre className="max-h-56 overflow-auto rounded-lg bg-surface-subtle p-3 text-xs leading-relaxed whitespace-pre-wrap break-all">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
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
    <Card>
      <CardHeader>
        <CardTitle>후보 검색</CardTitle>
        <CardDescription>
          검토 상태와 현재 rule eligibility를 함께 좁힙니다.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" onSubmit={submit}>
          <label className="space-y-1 text-sm">
            <span className="font-medium">검토 상태</span>
            <NativeSelect
              className="w-full"
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
                  {state === "all" ? "전체" : state}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium">현재 eligibility</span>
            <NativeSelect
              className="w-full"
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
          </label>
          {(
            [
              ["ruleId", "Rule ID"],
              ["themeId", "Theme ID"],
              ["sourceId", "Source ID"],
              ["featureId", "Feature ID"],
            ] as const
          ).map(([key, label]) => (
            <label className="space-y-1 text-sm" key={key}>
              <span className="font-medium">{label}</span>
              <Input
                placeholder={label}
                value={draft[key]}
                onChange={(event) =>
                  setDraft({ ...draft, [key]: event.target.value })
                }
              />
            </label>
          ))}
          <div className="flex items-end gap-2 md:col-span-2 xl:col-span-4">
            <Button disabled={isFetching} type="submit">
              <SearchIcon data-icon="inline-start" />
              {isFetching ? "조회 중" : "조회"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDraft(INITIAL_FILTERS)}
            >
              초기화
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function CandidateList({
  candidates,
  isFetching,
  isFirst,
  nextCursor,
  onFirst,
  onNext,
  onSelect,
  selectedId,
}: {
  candidates: ThemeCandidate[];
  isFetching: boolean;
  isFirst: boolean;
  nextCursor: string | null;
  onFirst: () => void;
  onNext: () => void;
  onSelect: (candidateId: string) => void;
  selectedId: string | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>후보 목록</CardTitle>
        <CardDescription>행을 선택하면 현재 증거와 감사 전이를 확인합니다.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {candidates.length === 0 ? (
          <div className="rounded-lg border border-dashed p-8 text-center text-text-secondary">
            조건에 맞는 후보가 없습니다.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>후보</TableHead>
                  <TableHead>Feature</TableHead>
                  <TableHead>테마/출처</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>갱신</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {candidates.map((candidate) => (
                  <TableRow
                    className="cursor-pointer"
                    data-state={
                      selectedId === candidate.candidate_id ? "selected" : undefined
                    }
                    key={candidate.candidate_id}
                    onClick={() => onSelect(candidate.candidate_id)}
                  >
                    <TableCell>
                      <div className="font-medium">
                        {candidate.proposal_title ?? candidate.feature_name}
                      </div>
                      <code className="text-xs text-text-secondary">
                        {shortId(candidate.candidate_id, 18)}
                      </code>
                    </TableCell>
                    <TableCell>
                      <div>{candidate.feature_name}</div>
                      <div className="text-xs text-text-secondary">
                        {candidate.feature_kind} · {candidate.feature_category}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div>{candidate.theme_name}</div>
                      <div className="text-xs text-text-secondary">
                        {candidate.source_name}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        <StatusBadge status={candidate.review_state} />
                        <Badge variant={candidate.eligibility_present ? "success" : "outline"}>
                          {candidate.eligibility_present ? "eligible" : "not eligible"}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell>{formatDateTime(candidate.updated_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <CursorPager
          ariaPrefix="큐레이션 후보"
          hasNext={nextCursor !== null}
          isFetching={isFetching}
          isFirst={isFirst}
          summary={`이 페이지 ${candidates.length.toLocaleString("ko-KR")}건`}
          onFirst={onFirst}
          onNext={onNext}
        />
      </CardContent>
    </Card>
  );
}

function CandidateDetail({ candidate }: { candidate: ThemeCandidate }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{candidate.proposal_title ?? candidate.feature_name}</CardTitle>
        <CardDescription>
          후보 revision {candidate.candidate_revision} · Feature revision {candidate.feature_row_revision}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap gap-2">
          <StatusBadge status={candidate.review_state} />
          <Badge variant={candidate.eligibility_present ? "success" : "outline"}>
            {candidate.eligibility_present ? "현재 rule 일치" : "현재 rule 불일치"}
          </Badge>
          <StatusBadge status={candidate.lifecycle_state} />
          <StatusBadge status={candidate.publication_state} />
          <StatusBadge status={candidate.quality_state} />
        </div>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-text-secondary">Feature</dt>
            <dd className="break-all font-mono">{candidate.feature_id}</dd>
          </div>
          <div>
            <dt className="text-text-secondary">source entity</dt>
            <dd className="break-all font-mono">{candidate.source_entity_key}</dd>
          </div>
          <div>
            <dt className="text-text-secondary">rule</dt>
            <dd className="break-all font-mono">{candidate.rule_id}</dd>
          </div>
          <div>
            <dt className="text-text-secondary">source record</dt>
            <dd className="break-all font-mono">{candidate.source_record_key}</dd>
          </div>
          <div>
            <dt className="text-text-secondary">rank</dt>
            <dd>{candidate.rank_score}</dd>
          </div>
          <div>
            <dt className="text-text-secondary">disposition</dt>
            <dd>{candidate.disposition}</dd>
          </div>
        </dl>
        {candidate.proposal_summary ? (
          <p className="rounded-lg bg-surface-subtle p-3 text-sm">
            {candidate.proposal_summary}
          </p>
        ) : null}
        <div className="grid gap-4 xl:grid-cols-2">
          <div>
            <h3 className="mb-2 font-semibold">match evidence</h3>
            <JsonEvidence value={candidate.match_evidence} />
          </div>
          <div>
            <h3 className="mb-2 font-semibold">effective Feature detail</h3>
            <JsonEvidence value={candidate.feature_detail} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CandidateCommands({
  candidate,
  collectionReady,
  collections,
  form,
  isPending,
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
  isPending: boolean;
  rejectReason: string;
  setForm: (value: PromoteForm) => void;
  setRejectReason: (value: string) => void;
  submitPromote: (event: FormEvent<HTMLFormElement>) => void;
  submitReject: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const commandAllowed =
    candidate.disposition === "active" && candidate.review_state === "open";
  const promoteAllowed = commandAllowed && candidate.eligibility_present;
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>후보 거절</CardTitle>
          <CardDescription>거절 사유는 immutable transition에 기록됩니다.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={submitReject}>
            <label className="block space-y-1 text-sm">
              <span className="font-medium">사유 코드</span>
              <Input
                required
                value={rejectReason}
                onChange={(event) => setRejectReason(event.target.value)}
              />
            </label>
            <Button
              disabled={!commandAllowed || isPending || !rejectReason.trim()}
              type="submit"
              variant="destructive"
            >
              <XIcon data-icon="inline-start" />
              거절 확정
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>canonical item으로 승격</CardTitle>
          <CardDescription>
            선택한 collection revision과 후보 CAS를 한 요청에 고정합니다.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 sm:grid-cols-2" onSubmit={submitPromote}>
            <label className="space-y-1 text-sm sm:col-span-2">
              <span className="font-medium">컬렉션</span>
              <NativeSelect
                className="w-full"
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
              </NativeSelect>
            </label>
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
              <label className="space-y-1 text-sm" key={key}>
                <span className="font-medium">{label}</span>
                <Input
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
              </label>
            ))}
            <label className="space-y-1 text-sm">
              <span className="font-medium">관계</span>
              <NativeSelect
                className="w-full"
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
                    {relation}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium">항목 상태</span>
              <NativeSelect
                className="w-full"
                value={form.itemStatus}
                onChange={(event) =>
                  setForm({
                    ...form,
                    itemStatus: event.target.value as PromoteForm["itemStatus"],
                  })
                }
              >
                <NativeSelectOption value="included">included</NativeSelectOption>
                <NativeSelectOption value="candidate">candidate</NativeSelectOption>
              </NativeSelect>
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium">재사용 정책</span>
              <NativeSelect
                className="w-full"
                value={form.reusePolicy}
                onChange={(event) =>
                  setForm({
                    ...form,
                    reusePolicy: event.target.value as PromoteForm["reusePolicy"],
                  })
                }
              >
                <NativeSelectOption value="allowed">allowed</NativeSelectOption>
                <NativeSelectOption value="manual_review">manual_review</NativeSelectOption>
                <NativeSelectOption value="blocked">blocked</NativeSelectOption>
              </NativeSelect>
            </label>
            <label className="space-y-1 text-sm sm:col-span-2">
              <span className="font-medium">항목 요약</span>
              <Textarea
                value={form.itemSummary}
                onChange={(event) =>
                  setForm({ ...form, itemSummary: event.target.value })
                }
              />
            </label>
            <div className="sm:col-span-2">
              <Button
                disabled={
                  !promoteAllowed ||
                  isPending ||
                  !form.collectionId ||
                  !collectionReady
                }
                type="submit"
              >
                <CheckIcon data-icon="inline-start" />
                승격 확정
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
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
      <div className="space-y-5">
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
          </Alert>
        ) : null}
        {mutationError ? (
          <Alert variant="destructive">
            <AlertTitle>후보 명령을 완료하지 못했습니다</AlertTitle>
            <AlertDescription className="space-y-3">
              <p>{displayError(mutationError)}</p>
              {isStaleCommandError(mutationError) ? (
                <Button type="button" variant="outline" onClick={() => void reloadCurrent()}>
                  <RefreshCwIcon data-icon="inline-start" />
                  현재 상태 다시 불러오기
                </Button>
              ) : null}
            </AlertDescription>
          </Alert>
        ) : null}
        {message ? (
          <Alert>
            <AlertTitle>처리 완료</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        ) : null}
        <CandidateList
          candidates={candidates}
          isFetching={candidatesQuery.isFetching}
          isFirst={cursor === null}
          nextCursor={nextCursor}
          selectedId={selectedId}
          onFirst={() => setCursor(null)}
          onNext={() => setCursor(nextCursor)}
          onSelect={selectCandidate}
        />
        {candidate ? (
          <>
            <CandidateDetail candidate={candidate} />
            <CandidateCommands
              candidate={candidate}
              collectionReady={collectionDetailQuery.data !== undefined}
              collections={collections}
              form={promoteForm}
              isPending={rejectMutation.isPending || promoteMutation.isPending}
              rejectReason={rejectReason}
              setForm={setPromoteForm}
              setRejectReason={setRejectReason}
              submitPromote={submitPromote}
              submitReject={submitReject}
            />
            <Card>
              <CardHeader>
                <CardTitle>감사 전이</CardTitle>
                <CardDescription>immutable candidate transition timeline입니다.</CardDescription>
              </CardHeader>
              <CardContent>
                {(transitionsQuery.data?.data.items ?? []).length === 0 ? (
                  <p className="text-sm text-text-secondary">기록된 전이가 없습니다.</p>
                ) : (
                  <ol className="space-y-3">
                    {(transitionsQuery.data?.data.items ?? []).map((transition) => (
                      <li className="rounded-lg border p-4" key={transition.transition_id}>
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={transition.transition_kind} />
                          <span className="text-sm font-medium">{transition.actor}</span>
                          <span className="text-xs text-text-secondary">
                            {formatDateTime(transition.occurred_at)}
                          </span>
                        </div>
                        <p className="mt-2 text-sm">
                          {transition.from_review_state ?? "∅"} / {String(transition.from_eligibility_present)}
                          {" → "}
                          {transition.to_review_state} / {String(transition.to_eligibility_present)}
                        </p>
                        <p className="text-xs text-text-secondary">
                          {transition.reason_code} · candidate rev {transition.candidate_revision}
                        </p>
                      </li>
                    ))}
                  </ol>
                )}
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </AdminShell>
  );
}
