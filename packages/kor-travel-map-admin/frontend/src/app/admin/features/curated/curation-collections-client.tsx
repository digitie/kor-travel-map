"use client";

import {
  CheckCircle2Icon,
  DatabaseIcon,
  DownloadIcon,
  FileSearchIcon,
  LinkIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react";
import { useRef, useState, type FormEvent, type MouseEvent } from "react";

import { useAdminCuratedSources, useAdminCuratedThemes } from "@/api/curated";
import {
  CURATION_IMPORT_TEMPLATE_URL,
  useAddCurationItemMutation,
  useArchiveCurationItemMutation,
  useAdminCurationCollection,
  useAdminCurationCollections,
  useCreateCurationCollectionMutation,
  useImportCurationCsvMutation,
  usePatchCurationItemMutation,
  type ActiveCurationCollectionStatus,
  type CurationCollectionVisibility,
  type CurationImportResponse,
  type CurationImportRowStatus,
} from "@/api/curations";
import { CurationQuarantinePanel } from "@/app/admin/features/curated/curation-quarantine-panel";
import { AdminShell } from "@/components/admin-shell";
import { CopyButton } from "@/components/copy-button";
import { EmptyState } from "@/components/empty-state";
import { SectionCard } from "@/components/section-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { FormField } from "@/components/ui/form-field-input";
import { FormSelect } from "@/components/ui/form-select";
import { FormTextArea } from "@/components/ui/form-textarea";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, shortId } from "@/lib/format";
import { withOccurrenceKeys } from "@/lib/occurrence-key";
import { cn } from "@/lib/utils";

interface CollectionFormState {
  collectionKey: string;
  themeId: string;
  sourceId: string;
  title: string;
  editionKey: string;
  description: string;
  status: ActiveCurationCollectionStatus;
  visibility: CurationCollectionVisibility;
}

interface ItemFormState {
  featureId: string;
  placeName: string;
  addressHint: string;
  externalItemId: string;
  externalComponentId: string;
  sortOrder: string;
  itemTitle: string;
  itemSummary: string;
}

const INITIAL_COLLECTION_FORM: CollectionFormState = {
  collectionKey: "",
  themeId: "",
  sourceId: "",
  title: "",
  editionKey: "",
  description: "",
  status: "draft",
  visibility: "admin_only",
};

const INITIAL_ITEM_FORM: ItemFormState = {
  featureId: "",
  placeName: "",
  addressHint: "",
  externalItemId: "",
  externalComponentId: "primary",
  sortOrder: "0",
  itemTitle: "",
  itemSummary: "",
};

function statusVariant(status: string) {
  if (status === "published" || status === "included" || status === "imported") {
    return "success" as const;
  }
  if (status === "draft" || status === "candidate" || status === "valid") {
    return "info" as const;
  }
  if (
    status === "invalid" ||
    status === "unmatched" ||
    status === "review_required" ||
    status === "ambiguous"
  ) {
    return "destructive" as const;
  }
  return "outline" as const;
}

function importStatusLabel(status: CurationImportRowStatus): string {
  return {
    valid: "유효",
    invalid: "형식 오류",
    unmatched: "미일치",
    review_required: "수동 검토",
    ambiguous: "후보 다수",
    imported: "반영됨",
  }[status];
}

function addressLabel(address: Record<string, unknown>): string {
  for (const key of ["road", "legal", "admin", "road_address", "address"]) {
    const value = address[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "-";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function useCurationCollectionsClientController() {
  const collectionsQuery = useAdminCurationCollections({ page_size: 500 });
  const themesQuery = useAdminCuratedThemes({ limit: 500 });
  const sourcesQuery = useAdminCuratedSources({ limit: 500 });
  const createCollection = useCreateCurationCollectionMutation();
  const addItem = useAddCurationItemMutation();
  const patchItem = usePatchCurationItemMutation();
  const archiveItem = useArchiveCurationItemMutation();
  const importCsv = useImportCurationCsvMutation();
  const submitCollectionInFlightRef = useRef(false);
  const submitItemInFlightRef = useRef(false);

  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(
    null,
  );
  const [collectionForm, setCollectionForm] = useState<CollectionFormState>(
    INITIAL_COLLECTION_FORM,
  );
  const [itemForm, setItemForm] = useState<ItemFormState>(INITIAL_ITEM_FORM);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [importReport, setImportReport] =
    useState<CurationImportResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [resolveFeatureIds, setResolveFeatureIds] = useState<
    Record<string, string>
  >({});

  const collections = collectionsQuery.data?.data.items ?? [];
  const activeCollectionId =
    selectedCollectionId ?? collections[0]?.collection_id ?? null;
  const collectionQuery = useAdminCurationCollection(activeCollectionId);
  const detail = collectionQuery.data?.data;
  const mutationError =
    createCollection.error ??
    addItem.error ??
    patchItem.error ??
    archiveItem.error ??
    importCsv.error ??
    null;

  const submitCollection = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitCollectionInFlightRef.current) return;
    setLocalError(null);
    setMessage(null);
    const collectionKey = collectionForm.collectionKey.trim();
    const themeId = collectionForm.themeId.trim();
    const title = collectionForm.title.trim();
    if (!collectionKey || !themeId || !title) {
      setLocalError("컬렉션 키, 제목과 기존 테마 선택은 필수입니다.");
      return;
    }
    submitCollectionInFlightRef.current = true;
    try {
      const response = await createCollection.mutateAsync({
        collection_key: collectionKey,
        theme_id: themeId,
        source_id: collectionForm.sourceId.trim() || null,
        title,
        edition_key: collectionForm.editionKey.trim(),
        description: collectionForm.description.trim() || null,
        status: collectionForm.status,
        visibility: collectionForm.visibility,
        metadata: {},
      });
      setSelectedCollectionId(response.data.collection.collection_id);
      setCollectionForm(INITIAL_COLLECTION_FORM);
      setMessage(`컬렉션 “${response.data.collection.title}”을 만들었습니다.`);
    } catch {
      // mutationError에서 API 응답을 표시한다.
    } finally {
      submitCollectionInFlightRef.current = false;
    }
  };

  const submitItem = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitItemInFlightRef.current) return;
    setLocalError(null);
    setMessage(null);
    if (!activeCollectionId) {
      setLocalError("먼저 컬렉션을 선택하세요.");
      return;
    }
    const featureId = itemForm.featureId.trim();
    const placeName = itemForm.placeName.trim();
    const externalItemId = itemForm.externalItemId.trim();
    const externalComponentId = itemForm.externalComponentId.trim();
    const sortOrder = Number(itemForm.sortOrder);
    if ((!featureId && !placeName) || !externalItemId || !externalComponentId) {
      setLocalError(
        "Feature ID 또는 장소명과 외부 항목 ID·구성요소 ID는 필수입니다.",
      );
      return;
    }
    if (!Number.isInteger(sortOrder) || sortOrder < 0) {
      setLocalError("정렬 순서는 0 이상의 정수여야 합니다.");
      return;
    }
    submitItemInFlightRef.current = true;
    try {
      const response = await addItem.mutateAsync({
        collectionId: activeCollectionId,
        body: {
          feature_id: featureId || null,
          place_name: placeName || null,
          address_hint: itemForm.addressHint.trim() || null,
          external_item_id: externalItemId,
          external_component_id: externalComponentId,
          status: "included",
          sort_order: sortOrder,
          item_title: itemForm.itemTitle.trim() || null,
          item_summary: itemForm.itemSummary.trim() || null,
          curation_relation: "nearby_option",
          reuse_policy: "manual_review",
          metadata: {},
        },
      });
      setItemForm(INITIAL_ITEM_FORM);
      setMessage(
        `“${response.data.feature_name ?? response.data.place_name}” 항목을 추가했습니다.`,
      );
    } catch {
      // mutationError에서 API 응답을 표시한다.
    } finally {
      submitItemInFlightRef.current = false;
    }
  };

  const previewCsv = async () => {
    if (!csvFile) {
      setLocalError("먼저 CSV 파일을 선택하세요.");
      return;
    }
    setLocalError(null);
    setMessage(null);
    try {
      setImportReport(
        await importCsv.mutateAsync({
          file: csvFile,
          dryRun: true,
        }),
      );
    } catch {
      // mutationError에서 API 응답을 표시한다.
    }
  };

  const commitCsv = async () => {
    if (
      !csvFile ||
      !importReport ||
      importReport.data.invalid_rows > 0 ||
      importReport.data.issues.length > 0
    )
      return;
    const removalWarning =
      importReport.data.removed > 0
        ? `\nCSV에 없는 기존 항목 ${importReport.data.removed}개가 제거됩니다.`
        : "";
    if (
      !window.confirm(
        `${importReport.data.rows_total}개 행을 DB에 반영할까요?${removalWarning}`,
      )
    ) {
      return;
    }
    setLocalError(null);
    setMessage(null);
    try {
      const response = await importCsv.mutateAsync({
        file: csvFile,
        dryRun: false,
      });
      setImportReport(response);
      setMessage(
        `CSV 반영 완료: 신규 ${response.data.inserted}개, 갱신 ${response.data.updated}개, 제거 ${response.data.removed}개`,
      );
    } catch {
      // mutationError에서 API 응답을 표시한다.
    }
  };

  const resolveItem = async (
    curationItemId: string,
    placeName: string,
    commandEtag: string,
  ) => {
    if (!activeCollectionId) return;
    const featureId = resolveFeatureIds[curationItemId]?.trim() ?? "";
    if (!featureId) {
      setLocalError(`“${placeName}”에 연결할 Feature ID를 입력하세요.`);
      return;
    }
    setLocalError(null);
    setMessage(null);
    try {
      await patchItem.mutateAsync({
        collectionId: activeCollectionId,
        curationItemId,
        commandEtag,
        body: { feature_id: featureId },
      });
      setResolveFeatureIds((current) => {
        const next = { ...current };
        delete next[curationItemId];
        return next;
      });
      setMessage(`“${placeName}”을 Feature ${featureId}에 연결했습니다.`);
    } catch {
      // mutationError에서 API 응답을 표시한다.
    }
  };

  const removeItem = async (
    curationItemId: string,
    placeName: string,
    commandEtag: string,
  ) => {
    if (!activeCollectionId) return;
    if (!window.confirm(`“${placeName}” 큐레이션 항목을 보관 처리할까요?`)) {
      return;
    }
    setLocalError(null);
    setMessage(null);
    try {
      await archiveItem.mutateAsync({
        collectionId: activeCollectionId,
        curationItemId,
        commandEtag,
      });
      setMessage(`“${placeName}” 항목을 보관 처리했습니다.`);
    } catch {
      // mutationError에서 API 응답을 표시한다.
    }
  };

  const downloadTemplate = async (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    setLocalError(null);
    try {
      const response = await fetch(CURATION_IMPORT_TEMPLATE_URL, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        if (response.status === 401) {
          window.location.assign(
            `/login?next=${encodeURIComponent(window.location.pathname)}`,
          );
          return;
        }
        throw new Error(`CSV 양식 다운로드 실패 (HTTP ${response.status})`);
      }
      const blobUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = "kor-travel-map-curations-template.csv";
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (error) {
      setLocalError(errorMessage(error));
    }
  };

  return {
    activeCollectionId,
    addItem,
    archiveItem,
    collectionForm,
    collectionQuery,
    collections,
    collectionsQuery,
    commitCsv,
    createCollection,
    csvFile,
    detail,
    downloadTemplate,
    importCsv,
    importReport,
    itemForm,
    localError,
    message,
    mutationError,
    patchItem,
    previewCsv,
    removeItem,
    resolveFeatureIds,
    resolveItem,
    setCollectionForm,
    setCsvFile,
    setImportReport,
    setItemForm,
    setLocalError,
    setMessage,
    setResolveFeatureIds,
    setSelectedCollectionId,
    sourcesQuery,
    submitCollection,
    submitItem,
    themesQuery,
  };
}

function CurationCollectionCommands({
  collectionForm,
  commitCsv,
  createCollection,
  csvFile,
  importCsv,
  importReport,
  localError,
  message,
  mutationError,
  previewCsv,
  setCollectionForm,
  setCsvFile,
  setImportReport,
  setLocalError,
  setMessage,
  sourcesQuery,
  submitCollection,
  themesQuery,
}: Pick<ReturnType<typeof useCurationCollectionsClientController>, "collectionForm" | "commitCsv" | "createCollection" | "csvFile" | "importCsv" | "importReport" | "localError" | "message" | "mutationError" | "previewCsv" | "setCollectionForm" | "setCsvFile" | "setImportReport" | "setLocalError" | "setMessage" | "sourcesQuery" | "submitCollection" | "themesQuery">) {
  return (
    <>
{localError || mutationError ? (
          <Alert variant="destructive">
            <AlertTitle>작업 실패</AlertTitle>
            <AlertDescription>
              {localError ?? errorMessage(mutationError)}
            </AlertDescription>
          </Alert>
        ) : null}
        {message ? (
          <Alert>
            <CheckCircle2Icon />
            <AlertTitle>완료</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-6 xl:grid-cols-2">
          <SectionCard
            description="typed catalog에서 만든 기존 테마와 출처를 선택합니다."
            title="컬렉션 수동 생성"
          >
            <form className="grid gap-4 md:grid-cols-2" onSubmit={submitCollection}>
              <FormField
                required
                label="컬렉션 키"
                placeholder="tourism-100-2025-2026"
                value={collectionForm.collectionKey}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    collectionKey: event.target.value,
                  }))
                }
              />
              <FormField
                required
                label="테마"
                list="curation-theme-options"
                placeholder="테마 ID"
                value={collectionForm.themeId}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    themeId: event.target.value,
                  }))
                }
              />
              <datalist id="curation-theme-options">
                {(themesQuery.data?.data.items ?? []).map((theme) => (
                  <option key={theme.theme_id} value={theme.theme_id}>
                    {theme.theme_name} · {theme.theme_slug}
                  </option>
                ))}
              </datalist>
              <FormField
                required
                className="md:col-span-2"
                label="제목"
                placeholder="2025~2026 한국관광 100선"
                value={collectionForm.title}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    title: event.target.value,
                  }))
                }
              />
              <FormField
                label="회차/년도"
                placeholder="2025-2026"
                value={collectionForm.editionKey}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    editionKey: event.target.value,
                  }))
                }
              />
              <FormField
                label="출처"
                list="curation-source-options"
                placeholder="출처 ID (선택)"
                value={collectionForm.sourceId}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    sourceId: event.target.value,
                  }))
                }
              />
              <datalist id="curation-source-options">
                {(sourcesQuery.data?.data.items ?? []).map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {source.source_name} · {source.provider}/{source.dataset_key}
                  </option>
                ))}
              </datalist>
              <FormSelect
                label="상태"
                value={collectionForm.status}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    status: event.target.value as ActiveCurationCollectionStatus,
                  }))
                }
              >
                <NativeSelectOption value="draft">초안</NativeSelectOption>
                <NativeSelectOption value="published">게시</NativeSelectOption>
              </FormSelect>
              <FormSelect
                label="공개 범위"
                value={collectionForm.visibility}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    visibility: event.target.value as CurationCollectionVisibility,
                  }))
                }
              >
                <NativeSelectOption value="admin_only">관리자 전용</NativeSelectOption>
                <NativeSelectOption value="public">공개</NativeSelectOption>
              </FormSelect>
              <FormTextArea
                className="md:col-span-2"
                label="설명"
                value={collectionForm.description}
                onChange={(event) =>
                  setCollectionForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
              />
              <div className="md:col-span-2">
                <Button disabled={createCollection.isPending} type="submit">
                  <PlusIcon data-icon="inline-start" />
                  {createCollection.isPending ? "생성 중" : "컬렉션 생성"}
                </Button>
              </div>
            </form>
          </SectionCard>

          <SectionCard
            description="먼저 전체 행의 Feature 매칭을 확인한 뒤 오류가 없을 때만 원자적으로 반영합니다."
            title="CSV 업로드"
          >
            <FormField
              accept=".csv,text/csv"
              label="CSV 파일"
              type="file"
              onChange={(event) => {
                setCsvFile(event.target.files?.[0] ?? null);
                setImportReport(null);
                setMessage(null);
                setLocalError(null);
              }}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!csvFile || importCsv.isPending}
                type="button"
                variant="outline"
                onClick={() => void previewCsv()}
              >
                <FileSearchIcon data-icon="inline-start" />
                매칭 미리보기
              </Button>
              <Button
                disabled={
                  !csvFile ||
                  !importReport?.data.dry_run ||
                  importReport.data.invalid_rows > 0 ||
                  importReport.data.issues.length > 0 ||
                  importCsv.isPending
                }
                type="button"
                onClick={() => void commitCsv()}
              >
                <UploadCloudIcon data-icon="inline-start" />
                전체 반영
              </Button>
            </div>
            {importReport ? <ImportReport report={importReport} /> : null}
          </SectionCard>
        </div>
    </>
  );
}

function CurationSourceCatalog({
  activeCollectionId,
  collections,
  collectionsQuery,
  setSelectedCollectionId,
}: Pick<ReturnType<typeof useCurationCollectionsClientController>, "activeCollectionId" | "collections" | "collectionsQuery" | "setSelectedCollectionId">) {
  return (
    <>
<SectionCard
            actions={
              <Button
                aria-label="컬렉션 목록 새로고침"
                disabled={collectionsQuery.isFetching}
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={() => void collectionsQuery.refetch()}
              >
                <RefreshCwIcon />
              </Button>
            }
            description={`최대 500개 · 현재 ${collections.length}개`}
            title="컬렉션"
          >
            {collectionsQuery.isError ? (
              <Alert variant="destructive">
                <AlertTitle>목록 조회 실패</AlertTitle>
                <AlertDescription>{collectionsQuery.error.message}</AlertDescription>
              </Alert>
            ) : collections.length === 0 ? (
              <EmptyState
                description="위 폼이나 CSV 업로드로 첫 컬렉션을 만드세요."
                icon={<DatabaseIcon />}
                title="컬렉션이 없습니다"
              />
            ) : (
              <div className="space-y-2" data-testid="curation-collection-list">
                {collections.map((collection) => (
                  <button
                    className={cn(
                      "w-full rounded-xl border p-3 text-left transition-colors hover:bg-surface-subtle",
                      activeCollectionId === collection.collection_id &&
                        "border-brand bg-brand-tint",
                    )}
                    key={collection.collection_id}
                    type="button"
                    onClick={() => setSelectedCollectionId(collection.collection_id)}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-bold">
                          {collection.title}
                        </span>
                        <span className="block truncate text-xs text-text-secondary">
                          {collection.theme_name} · {collection.edition_key || "회차 없음"}
                        </span>
                      </span>
                      <Badge variant={statusVariant(collection.status)}>
                        {collection.status}
                      </Badge>
                    </span>
                    <span className="mt-2 block text-xs text-text-secondary">
                      {collection.item_count}개 · {collection.collection_key}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </SectionCard>
    </>
  );
}

type CurationCollectionsController = ReturnType<
  typeof useCurationCollectionsClientController
>;
type SelectedCurationCollection = NonNullable<
  CurationCollectionsController["detail"]
>;

function CurationCollectionSummary({
  detail,
}: {
  detail: SelectedCurationCollection;
}) {
  return (
    <>
<div className="flex flex-wrap gap-2">
                  <Badge variant={statusVariant(detail.collection.status)}>
                    {detail.collection.status}
                  </Badge>
                  <Badge variant="outline">{detail.collection.visibility}</Badge>
                  <Badge variant="secondary">{detail.collection.theme_name}</Badge>
                  {detail.collection.edition_key ? (
                    <Badge variant="outline">{detail.collection.edition_key}</Badge>
                  ) : null}
                  {detail.collection.source_name ? (
                    <Badge variant="outline">{detail.collection.source_name}</Badge>
                  ) : null}
                </div>
                {detail.collection.description ? (
                  <p className="text-sm text-text-secondary">
                    {detail.collection.description}
                  </p>
                ) : null}
                <dl className="grid gap-2 rounded-xl border p-3 text-xs md:grid-cols-2">
                  <div>
                    <dt className="font-medium">테마</dt>
                    <dd>
                      {detail.collection.theme_slug} · {detail.collection.theme_group}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-medium">출처 dataset</dt>
                    <dd>
                      {detail.collection.provider ?? "-"}/
                      {detail.collection.dataset_key ?? "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-medium">항목</dt>
                    <dd>
                      전체 {detail.collection.item_count} · 공개 가능{" "}
                      {detail.collection.public_item_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-medium">감사</dt>
                    <dd>
                      생성 {detail.collection.created_by ?? "-"} · 갱신{" "}
                      {detail.collection.updated_by ?? "-"}
                    </dd>
                  </div>
                  {detail.collection.source_url ? (
                    <div className="md:col-span-2">
                      <dt className="font-medium">공식 출처</dt>
                      <dd>
                        <a
                          className="break-all text-brand underline"
                          href={detail.collection.source_url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {detail.collection.source_url}
                        </a>
                      </dd>
                    </div>
                  ) : null}
                  <div className="md:col-span-2">
                    <dt className="font-medium">metadata</dt>
                    <dd>
                      <pre className="overflow-auto whitespace-pre-wrap break-all rounded bg-surface-subtle p-2">
                        {JSON.stringify(detail.collection.metadata, null, 2)}
                      </pre>
                    </dd>
                  </div>
                </dl>
    </>
  );
}

function CurationCollectionEditor({
  addItem,
  itemForm,
  setItemForm,
  submitItem,
}: Pick<ReturnType<typeof useCurationCollectionsClientController>, "addItem" | "itemForm" | "setItemForm" | "submitItem">) {
  return (
    <>
<form
                  className="grid gap-4 rounded-xl border p-4 md:grid-cols-2"
                  onSubmit={submitItem}
                >
                  <div className="md:col-span-2">
                    <h3 className="text-sm font-bold">큐레이션 항목 추가</h3>
                    <p className="text-xs text-text-secondary">
                      기존 Feature ID를 연결하거나, 아직 위치가 없는 공식 장소를
                      미연결 항목으로 보존합니다.
                    </p>
                  </div>
                  <FormField
                    label="Feature ID (선택)"
                    value={itemForm.featureId}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        featureId: event.target.value,
                      }))
                    }
                  />
                  <FormField
                    label="장소명 (Feature ID가 없으면 필수)"
                    value={itemForm.placeName}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        placeName: event.target.value,
                      }))
                    }
                  />
                  <FormField
                    className="md:col-span-2"
                    label="주소 힌트"
                    value={itemForm.addressHint}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        addressHint: event.target.value,
                      }))
                    }
                  />
                  <FormField
                    required
                    label="외부 항목 ID"
                    placeholder="공식 목록 내 식별자"
                    value={itemForm.externalItemId}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        externalItemId: event.target.value,
                      }))
                    }
                  />
                  <FormField
                    required
                    label="외부 구성요소 ID"
                    placeholder="primary 또는 component-01"
                    value={itemForm.externalComponentId}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        externalComponentId: event.target.value,
                      }))
                    }
                  />
                  <FormField
                    label="표시 제목"
                    value={itemForm.itemTitle}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        itemTitle: event.target.value,
                      }))
                    }
                  />
                  <FormField
                    label="정렬 순서"
                    min="0"
                    step="1"
                    type="number"
                    value={itemForm.sortOrder}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        sortOrder: event.target.value,
                      }))
                    }
                  />
                  <FormTextArea
                    className="md:col-span-2"
                    label="요약"
                    value={itemForm.itemSummary}
                    onChange={(event) =>
                      setItemForm((current) => ({
                        ...current,
                        itemSummary: event.target.value,
                      }))
                    }
                  />
                  <div className="md:col-span-2">
                    <Button disabled={addItem.isPending} type="submit">
                      <PlusIcon data-icon="inline-start" />
                      {addItem.isPending ? "추가 중" : "항목 추가"}
                    </Button>
                  </div>
                </form>
    </>
  );
}

function CurationCollectionTable({
  archiveItem,
  detail,
  patchItem,
  removeItem,
  resolveFeatureIds,
  resolveItem,
  setResolveFeatureIds,
}: Omit<
  Pick<
    CurationCollectionsController,
    | "archiveItem"
    | "detail"
    | "patchItem"
    | "removeItem"
    | "resolveFeatureIds"
    | "resolveItem"
    | "setResolveFeatureIds"
  >,
  "detail"
> & {
  detail: SelectedCurationCollection;
}) {
  return (
    <>
{detail.items.length === 0 ? (
                  <EmptyState
                    description="위 폼이나 CSV 업로드로 기존 Feature를 연결하세요."
                    title="항목이 없습니다"
                  />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>순서</TableHead>
                        <TableHead>Feature</TableHead>
                        <TableHead>큐레이션 정보</TableHead>
                        <TableHead>출처 항목</TableHead>
                        <TableHead>상태/관계</TableHead>
                        <TableHead>작업</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.items.map((item) => (
                        <TableRow key={item.curation_item_id}>
                          <TableCell>{item.sort_order}</TableCell>
                          <TableCell>
                            <div className="max-w-64 whitespace-normal">
                              <div className="font-medium">
                                {item.feature_name ?? item.place_name}
                              </div>
                              {item.feature_name && item.feature_name !== item.place_name ? (
                                <div className="text-xs text-text-secondary">
                                  공식 명칭 {item.place_name}
                                </div>
                              ) : null}
                              <div className="font-mono text-xs text-text-secondary">
                                {item.feature_id
                                  ? shortId(item.feature_id, 20)
                                  : "Feature 미연결"}
                              </div>
                              <div className="text-xs text-text-secondary">
                                {addressLabel(item.address)}
                              </div>
                              {item.address_hint ? (
                                <div className="text-xs text-text-secondary">
                                  주소 힌트 {item.address_hint}
                                </div>
                              ) : null}
                              {item.feature_kind || item.feature_category ? (
                                <div className="font-mono text-xs text-text-secondary">
                                  {item.feature_kind ?? "-"} · {item.feature_category ?? "-"}
                                </div>
                              ) : null}
                              {item.lon !== null && item.lat !== null ? (
                                <div className="font-mono text-xs text-text-secondary">
                                  {item.lon.toFixed(6)}, {item.lat.toFixed(6)}
                                </div>
                              ) : null}
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="max-w-72 whitespace-normal">
                              <div>{item.item_title || "-"}</div>
                              <div className="text-xs text-text-secondary">
                                {item.item_summary || "요약 없음"}
                              </div>
                              <pre className="mt-2 max-w-72 overflow-auto whitespace-pre-wrap break-all rounded bg-surface-subtle p-2 text-xs">
                                {JSON.stringify(item.metadata, null, 2)}
                              </pre>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="max-w-64 space-y-1 whitespace-normal text-xs">
                              <div className="font-mono">
                                {item.external_item_id}/{item.external_component_id}
                              </div>
                              <div>
                                {item.source_name ?? "수동 입력"} · {item.provider ?? "-"}/
                                {item.dataset_key ?? "-"}
                              </div>
                              {item.source_record_key ? (
                                <div className="break-all font-mono text-text-secondary">
                                  {item.source_record_key}
                                </div>
                              ) : null}
                              {item.source_url ? (
                                <a
                                  className="break-all text-brand underline"
                                  href={item.source_url}
                                  rel="noreferrer"
                                  target="_blank"
                                >
                                  공식 출처
                                </a>
                              ) : null}
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col items-start gap-1">
                              <Badge variant={statusVariant(item.status)}>
                                {item.status}
                              </Badge>
                              {item.source_present ? null : (
                                <Badge variant="outline">원천 누락</Badge>
                              )}
                              <span className="text-xs text-text-secondary">
                                {item.curation_relation}
                              </span>
                              <span className="text-xs text-text-secondary">
                                재사용 {item.reuse_policy}
                              </span>
                              <span className="text-xs text-text-secondary">
                                생성 {formatDateTime(item.created_at)} · {item.created_by ?? "-"}
                              </span>
                              <span className="text-xs text-text-secondary">
                                갱신 {formatDateTime(item.updated_at)} · {item.updated_by ?? "-"}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="min-w-56 space-y-2">
                              {item.feature_id ? null : (
                                <div className="space-y-2">
                                  <FormField
                                    aria-label={`${item.place_name} Feature 연결`}
                                    label="연결할 Feature ID"
                                    labelClassName="sr-only"
                                    placeholder="Feature ID"
                                    value={resolveFeatureIds[item.curation_item_id] ?? ""}
                                    onChange={(event) =>
                                      setResolveFeatureIds((current) => ({
                                        ...current,
                                        [item.curation_item_id]: event.target.value,
                                      }))
                                    }
                                  />
                                  <Button
                                    disabled={patchItem.isPending}
                                    size="sm"
                                    type="button"
                                    variant="outline"
                                    onClick={() =>
                                      void resolveItem(
                                        item.curation_item_id,
                                        item.place_name,
                                        item.command_etag,
                                      )
                                    }
                                  >
                                    <LinkIcon data-icon="inline-start" />
                                    Feature 연결
                                  </Button>
                                </div>
                              )}
                              <Button
                                disabled={archiveItem.isPending}
                                size="sm"
                                type="button"
                                variant="destructive"
                                onClick={() =>
                                  void removeItem(
                                    item.curation_item_id,
                                    item.place_name,
                                    item.command_etag,
                                  )
                                }
                              >
                                <Trash2Icon data-icon="inline-start" />
                                항목 보관
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
    </>
  );
}

function CurationCollectionWorkspace({
  addItem,
  archiveItem,
  collectionQuery,
  detail,
  itemForm,
  patchItem,
  removeItem,
  resolveFeatureIds,
  resolveItem,
  setItemForm,
  setResolveFeatureIds,
  submitItem,
}: Pick<ReturnType<typeof useCurationCollectionsClientController>, "addItem" | "archiveItem" | "collectionQuery" | "detail" | "itemForm" | "patchItem" | "removeItem" | "resolveFeatureIds" | "resolveItem" | "setItemForm" | "setResolveFeatureIds" | "submitItem">) {
  return (
    <>
<SectionCard
            description={
              detail
                ? `${detail.collection.collection_key} · 갱신 ${formatDateTime(detail.collection.updated_at)}`
                : "왼쪽에서 컬렉션을 선택하세요."
            }
            title={detail?.collection.title ?? "컬렉션 상세"}
          >
            {collectionQuery.isError ? (
              <Alert variant="destructive">
                <AlertTitle>상세 조회 실패</AlertTitle>
                <AlertDescription>{collectionQuery.error.message}</AlertDescription>
              </Alert>
            ) : detail ? (
              <div className="space-y-6" data-testid="curation-collection-detail">
                <CurationCollectionSummary detail={detail} />
                <CurationCollectionEditor addItem={addItem} itemForm={itemForm} setItemForm={setItemForm} submitItem={submitItem} />

                <CurationCollectionTable archiveItem={archiveItem} detail={detail} patchItem={patchItem} removeItem={removeItem} resolveFeatureIds={resolveFeatureIds} resolveItem={resolveItem} setResolveFeatureIds={setResolveFeatureIds} />
              </div>
            ) : (
              <EmptyState title="컬렉션을 선택하세요" />
            )}
          </SectionCard>
    </>
  );
}

function CurationCollectionCatalog({
  activeCollectionId,
  addItem,
  archiveItem,
  collectionQuery,
  collections,
  collectionsQuery,
  detail,
  itemForm,
  patchItem,
  removeItem,
  resolveFeatureIds,
  resolveItem,
  setItemForm,
  setResolveFeatureIds,
  setSelectedCollectionId,
  submitItem,
}: Pick<ReturnType<typeof useCurationCollectionsClientController>, "activeCollectionId" | "addItem" | "archiveItem" | "collectionQuery" | "collections" | "collectionsQuery" | "detail" | "itemForm" | "patchItem" | "removeItem" | "resolveFeatureIds" | "resolveItem" | "setItemForm" | "setResolveFeatureIds" | "setSelectedCollectionId" | "submitItem">) {
  return (
    <>
<div className="grid gap-6 xl:grid-cols-[24rem_minmax(0,1fr)]">
          <CurationSourceCatalog activeCollectionId={activeCollectionId} collections={collections} collectionsQuery={collectionsQuery} setSelectedCollectionId={setSelectedCollectionId} />

          <CurationCollectionWorkspace addItem={addItem} archiveItem={archiveItem} collectionQuery={collectionQuery} detail={detail} itemForm={itemForm} patchItem={patchItem} removeItem={removeItem} resolveFeatureIds={resolveFeatureIds} resolveItem={resolveItem} setItemForm={setItemForm} setResolveFeatureIds={setResolveFeatureIds} submitItem={submitItem} />
        </div>
    </>
  );
}

function CurationCollectionsClientView({
  activeCollectionId,
  addItem,
  archiveItem,
  collectionForm,
  collectionQuery,
  collections,
  collectionsQuery,
  commitCsv,
  createCollection,
  csvFile,
  detail,
  downloadTemplate,
  importCsv,
  importReport,
  itemForm,
  localError,
  message,
  mutationError,
  patchItem,
  previewCsv,
  removeItem,
  resolveFeatureIds,
  resolveItem,
  setCollectionForm,
  setCsvFile,
  setImportReport,
  setItemForm,
  setLocalError,
  setMessage,
  setResolveFeatureIds,
  setSelectedCollectionId,
  sourcesQuery,
  submitCollection,
  submitItem,
  themesQuery,
}: ReturnType<typeof useCurationCollectionsClientController>) {
  return (
    <AdminShell
      actions={
        <a
          className={buttonVariants({ variant: "outline" })}
          download
          href={CURATION_IMPORT_TEMPLATE_URL}
          onClick={(event) => void downloadTemplate(event)}
        >
          <DownloadIcon data-icon="inline-start" />
          CSV 양식 다운로드
        </a>
      }
      description="테마·회차별 컬렉션을 만들고 기존 Feature에 여러 큐레이션 정보를 연결합니다."
      title="큐레이션 관리"
    >
      <div className="space-y-6">
        <CurationCollectionCommands collectionForm={collectionForm} commitCsv={commitCsv} createCollection={createCollection} csvFile={csvFile} importCsv={importCsv} importReport={importReport} localError={localError} message={message} mutationError={mutationError} previewCsv={previewCsv} setCollectionForm={setCollectionForm} setCsvFile={setCsvFile} setImportReport={setImportReport} setLocalError={setLocalError} setMessage={setMessage} sourcesQuery={sourcesQuery} submitCollection={submitCollection} themesQuery={themesQuery} />

        <CurationCollectionCatalog activeCollectionId={activeCollectionId} addItem={addItem} archiveItem={archiveItem} collectionQuery={collectionQuery} collections={collections} collectionsQuery={collectionsQuery} detail={detail} itemForm={itemForm} patchItem={patchItem} removeItem={removeItem} resolveFeatureIds={resolveFeatureIds} resolveItem={resolveItem} setItemForm={setItemForm} setResolveFeatureIds={setResolveFeatureIds} setSelectedCollectionId={setSelectedCollectionId} submitItem={submitItem} />

        <CurationQuarantinePanel />
      </div>
    </AdminShell>
  );
}

export function CurationCollectionsClient() {
  const controller = useCurationCollectionsClientController();
  return <CurationCollectionsClientView {...controller} />;
}

function ImportReport({ report }: { report: CurationImportResponse }) {
  const { data } = report;
  return (
    <div className="space-y-3" data-testid="curation-import-report">
      <div className="flex flex-wrap gap-2">
        <Badge variant={data.invalid_rows === 0 ? "success" : "destructive"}>
          {data.dry_run ? "미리보기" : "반영 결과"}
        </Badge>
        <Badge variant="outline">전체 {data.rows_total}</Badge>
        <Badge variant="success">유효 {data.valid_rows}</Badge>
        <Badge variant={data.invalid_rows > 0 ? "destructive" : "outline"}>
          오류 {data.invalid_rows}
        </Badge>
        <Badge variant={data.unresolved_rows > 0 ? "warning" : "outline"}>
          미연결 {data.unresolved_rows}
        </Badge>
        <Badge variant="outline">
          {data.dry_run ? "신규 예정" : "신규"} {data.inserted}
        </Badge>
        <Badge variant="outline">
          {data.dry_run ? "갱신 예정" : "갱신"} {data.updated}
        </Badge>
        <Badge variant={data.removed > 0 ? "destructive" : "outline"}>
          {data.dry_run ? "제거 예정" : "제거"} {data.removed}
        </Badge>
      </div>
      {data.removals.length > 0 ? (
        <Alert variant="destructive">
          <AlertTitle>
            CSV에 없는 기존 항목 {data.removals.length}개가 제거됩니다
          </AlertTitle>
          <AlertDescription>
            <ul className="mt-2 max-h-64 list-disc space-y-1 overflow-auto pl-4">
              {data.removals.map((item) => (
                <li key={item.curation_item_id}>
                  <span className="font-medium">{item.title}</span> · {item.place_name}
                  {" · "}
                  <span className="font-mono text-xs">{item.external_item_id}</span>
                  <span className="font-mono text-xs">
                    /{item.external_component_id}
                  </span>
                  {item.feature_id ? (
                    <span className="font-mono text-xs"> · {item.feature_id}</span>
                  ) : (
                    " · Feature 미연결"
                  )}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      {data.issues.length > 0 ? (
        <Alert variant="destructive">
          <AlertTitle>파일 오류</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-4">
              {withOccurrenceKeys(data.issues, (issue) =>
                JSON.stringify([
                  issue.code,
                  issue.row_number ?? "file",
                  issue.column,
                  issue.message,
                ]),
              ).map(({ key, value: issue }) => (
                <li key={key}>
                  {issue.row_number ? `${issue.row_number}행 · ` : ""}
                  {issue.column ? `${issue.column} · ` : ""}
                  {issue.message}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>행</TableHead>
            <TableHead>상태</TableHead>
            <TableHead>컬렉션/장소</TableHead>
            <TableHead>Feature 매칭</TableHead>
            <TableHead>문제</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.items.map((row) => (
            <TableRow
              key={`${row.row_number}-${row.source_item_key}-${row.source_component_key}`}
            >
              <TableCell>{row.row_number}</TableCell>
              <TableCell>
                <Badge variant={statusVariant(row.status)}>
                  {importStatusLabel(row.status)}
                </Badge>
              </TableCell>
              <TableCell>
                <div className="max-w-64 whitespace-normal">
                  <div className="font-medium">{row.title}</div>
                  <div className="text-xs text-text-secondary">
                    {row.collection_key} · {row.place_name || row.source_item_key}
                  </div>
                  <div className="font-mono text-xs text-text-secondary">
                    {row.source_item_key}/{row.source_component_key}
                  </div>
                </div>
              </TableCell>
              <TableCell>
                <div className="max-w-72 space-y-1 whitespace-normal">
                  {row.resolved_feature_id ? (
                    <div className="font-mono text-xs">
                      {row.resolved_feature_id}
                    </div>
                  ) : null}
                  {row.candidates.map((candidate) => (
                    <div className="text-xs" key={candidate.feature_id}>
                      <span className="font-medium">{candidate.name}</span>
                      <span className="flex items-start gap-1">
                        <code className="break-all font-mono">
                          {candidate.feature_id}
                        </code>
                        <CopyButton
                          label={`${candidate.name} 후보 Feature ID`}
                          value={candidate.feature_id}
                        />
                      </span>
                      <span className="block text-text-secondary">
                        {addressLabel(candidate.address)}
                      </span>
                    </div>
                  ))}
                  {!row.resolved_feature_id && row.candidates.length === 0 ? "-" : null}
                </div>
              </TableCell>
              <TableCell>
                <ul className="max-w-72 space-y-1 whitespace-normal text-xs text-destructive">
                  {withOccurrenceKeys(row.issues, (issue) =>
                    JSON.stringify([issue.code, issue.column, issue.message]),
                  ).map(({ key, value: issue }) => (
                    <li key={key}>
                      {issue.column ? `${issue.column}: ` : ""}
                      {issue.message}
                    </li>
                  ))}
                </ul>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
