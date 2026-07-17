"use client";

import {
  type ColumnDef,
  type Row,
  type RowSelectionState,
} from "@tanstack/react-table";
import {
  AlertTriangleIcon,
  ArchiveIcon,
  CheckIcon,
  ExternalLinkIcon,
  EyeIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SaveIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import {
  useAdminCuratedFeatures,
  useAdminCuratedSourceRules,
  useAdminCuratedSources,
  useAdminCuratedThemes,
  useApplyCuratedSourceRuleMutation,
  useArchiveCuratedFeatureMutation,
  useCuratedFeaturePlaceSearch,
  usePatchCuratedFeatureMutation,
  usePatchCuratedSourceRuleMutation,
  useSelectCuratedFeatureMutation,
  useCuratedFeatureDetailSnapshot,
  useUnselectCuratedFeatureMutation,
  type AdminCuratedFeaturesParams,
  type AdminCuratedSourceRulesParams,
  type CuratedFeature,
  type CuratedFeatureStatus,
  type CuratedPlaceSearchHit,
  type CuratedRuleAction,
  type CuratedSource,
  type CuratedSourceRule,
  type CuratedTheme,
  type CuratedReusePolicy,
  type CuratedCurationRelation,
} from "@/api/curated";
import { useCategories } from "@/api/categories";
import { AdminRegionAutoSearch } from "@/components/admin-region-autosearch";
import { AdminShell } from "@/components/admin-shell";
import { useConfirm } from "@/components/confirm-dialog";
import { JsonViewer } from "@/components/json-viewer";
import { CursorPager } from "@/components/pagination-bar";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { statusLabel } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable } from "@/components/ui/data-table";
import {
  FormField,
  FormSelect,
  FormTextArea,
} from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import {
  curationRelationLabel,
  enumOption,
  notifyStatusTransition,
  reusePolicyLabel,
  ruleActionLabel,
  CURATION_RELATION_LABELS,
  REUSE_POLICY_LABELS,
  RULE_ACTION_LABELS,
} from "@/lib/curated-labels";
import {
  PLACE_KIND_OPTIONS,
  withCurrentOption,
} from "@/lib/feature-form-options";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import {
  integerString,
  jsonObject,
  parseJsonObjectField,
} from "@/lib/form-validation";
import { cn } from "@/lib/utils";

import { CuratedLifecycleStrip } from "./curated-lifecycle";

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const CURATION_STATUS_OPTIONS: CuratedFeatureStatus[] = [
  "candidate",
  "curated",
  "rejected",
  "archived",
];
const REUSE_POLICY_OPTIONS: CuratedReusePolicy[] = [
  "allowed",
  "blocked",
  "manual_review",
];
const CURATION_RELATION_OPTIONS: CuratedCurationRelation[] = [
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
const RULE_ACTION_OPTIONS: CuratedRuleAction[] = ["candidate", "curated", "ignore"];
const CURATED_FEATURES_REFRESH_SCHEDULE =
  "curated_features_refresh_daily_schedule";
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const PLACE_SEARCH_PROVIDERS = ["google", "kakao", "naver"] as const;
const PLACE_SEARCH_PROVIDER_LABELS: Record<string, string> = {
  google: "Google",
  kakao: "Kakao",
  naver: "Naver",
};
/** 서버 검색(q) 디바운스 — 타이핑마다 keyset 재조회하지 않게 300ms. */
const SEARCH_DEBOUNCE_MS = 300;

type StatusFilter = CuratedFeatureStatus | "all";
type EnabledFilter = "all" | "enabled" | "disabled";
type ConsoleTab = "review" | "rules";

function JsonBlock({ value }: { value: unknown }) {
  return <JsonViewer value={value} maxHeight="lg" copyable />;
}

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  // §4: 제출 변환은 parseJsonObjectField로 통일(raw SyntaxError 누출 방지).
  const parsed = parseJsonObjectField(value, label);
  if (parsed.error) {
    throw new Error(`${label}: ${parsed.error}`);
  }
  return parsed.value ?? {};
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

/** region_scope 미니폼용 — 유효하지 않은 JSON이면 빈 object로 degrade한다. */
function safeParseObject(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function featureStatusVariant(status: string) {
  if (status === "curated") return "default";
  if (status === "rejected" || status === "archived") return "destructive";
  return "secondary";
}

function reusePolicyVariant(policy: string) {
  if (policy === "allowed") return "default";
  if (policy === "blocked") return "destructive";
  return "outline";
}

function coordLabel(feature: CuratedFeature): string {
  const coord = featureCoord(feature);
  if (coord) {
    const [lon, lat] = coord;
    return `${lon.toFixed(5)}, ${lat.toFixed(5)}`;
  }
  return "-";
}

function featureCoord(feature: CuratedFeature): [number, number] | null {
  if (feature.lon == null || feature.lat == null) return null;
  const lon = Number(feature.lon);
  const lat = Number(feature.lat);
  return Number.isFinite(lon) && Number.isFinite(lat) ? [lon, lat] : null;
}

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function curatedFeatureHref(curatedFeatureId: string): string {
  return `/admin/features/curated/${encodeURIComponent(curatedFeatureId)}`;
}

function isPlaceCandidateProvider(value: string): boolean {
  return value.toLowerCase().includes("concierge");
}

function uiLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value
    .replace(/kor-travel-concierge/gi, "place-candidate")
    .replace(/concierge/gi, "place-candidate")
    .replace(/컨시어지/g, "장소 후보");
}

function providerLabel(value: string | null | undefined): string {
  return uiLabel(value);
}

function themeSlugForProvider(
  provider: string,
  datasetKey: string,
  sources: readonly CuratedSource[],
  rules: readonly CuratedSourceRule[],
): string | null {
  if (provider === "all" || !isPlaceCandidateProvider(provider)) {
    return null;
  }
  const sourceIds = new Set(
    sources
      .filter(
        (source) =>
          source.provider === provider &&
          (datasetKey === "all" || source.dataset_key === datasetKey),
      )
      .map((source) => source.source_id),
  );
  return rules.find((rule) => sourceIds.has(rule.source_id))?.theme_slug ?? null;
}

function featureAddressLabel(feature: CuratedFeature): string {
  const address = feature.address as Record<string, unknown>;
  for (const key of ["road_address", "jibun_address", "full_address", "address"]) {
    const value = address[key];
    if (typeof value === "string" && value.trim().length > 0) return value;
  }
  return "-";
}

function featureSearchQuery(feature: CuratedFeature | null): string {
  if (!feature) return "";
  return (
    feature.feature_name ??
    feature.display_title ??
    feature.source_name ??
    ""
  ).trim();
}

function placeHitAddress(hit: CuratedPlaceSearchHit): string {
  return hit.road_address ?? hit.address ?? "-";
}

export function CuratedFeatureLocationPanel({
  feature,
}: {
  feature: CuratedFeature | null;
}) {
  if (!feature) return null;
  const coord = featureCoord(feature);

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="font-medium">위치 확인</div>
      </div>
      <div className="flex flex-col gap-3 p-4">
        {coord ? (
          <div className="relative h-80 overflow-hidden rounded-md border 2xl:h-96">
            <VWorldMapView
              apiKey={VWORLD_KEY}
              center={coord}
              className="absolute inset-0 h-full w-full"
              key={feature.curated_feature_id}
              navigation
              scale
              zoom={14}
            >
              <VWorldMarker
                lngLat={coord}
                markerColor="#2563eb"
                selected
                size={30}
                title={feature.feature_name}
              />
            </VWorldMapView>
          </div>
        ) : (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            좌표가 없어 지도 marker를 표시할 수 없습니다.
          </div>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">좌표</dt>
          <dd className="font-mono">{coordLabel(feature)}</dd>
          <dt className="text-muted-foreground">주소</dt>
          <dd>{featureAddressLabel(feature)}</dd>
          <dt className="text-muted-foreground">카테고리</dt>
          <dd>
            <Badge variant="outline">{feature.feature_category}</Badge>
          </dd>
          <dt className="text-muted-foreground">provider</dt>
          <dd>
            {providerLabel(feature.provider)} / {feature.dataset_key}
          </dd>
        </dl>
      </div>
    </section>
  );
}

export function CuratedPlaceSearchPanel({
  feature,
}: {
  feature: CuratedFeature | null;
}) {
  const patchFeature = usePatchCuratedFeatureMutation();
  const defaultQuery = featureSearchQuery(feature);
  const [query, setQuery] = useState(defaultQuery);
  const [activeQuery, setActiveQuery] = useState("");
  // 결과 적용 시 재사용 정책을 '재사용 허용'으로 바꿀지의 opt-out — 기본 체크.
  // 해제하면 PATCH body에서 reuse_policy 키 자체를 뺀다(기존 값 유지).
  const [applyAllowedPolicy, setApplyAllowedPolicy] = useState(true);
  const search = useCuratedFeaturePlaceSearch(
    feature?.curated_feature_id ?? null,
    activeQuery,
    feature !== null && activeQuery.trim().length > 0,
  );

  if (!feature) return null;

  const providerHits = PLACE_SEARCH_PROVIDERS.map((provider) => ({
    provider,
    hits: search.data?.data[provider] ?? [],
  }));
  const applyHit = (hit: CuratedPlaceSearchHit) => {
    patchFeature.mutate(
      {
        curatedFeatureId: feature.curated_feature_id,
        body: {
          display_title: hit.name ?? feature.display_title,
          ...(applyAllowedPolicy ? { reuse_policy: "allowed" as const } : {}),
          metadata: {
            ...feature.metadata,
            place_search_review: {
              provider: hit.provider,
              query: search.data?.data.query ?? activeQuery,
              name: hit.name ?? null,
              address: placeHitAddress(hit),
              latitude: hit.latitude ?? null,
              longitude: hit.longitude ?? null,
              category: hit.category ?? null,
              reviewed_at: new Date().toISOString(),
            },
          },
        },
      },
      {
        onSuccess: () => {
          const coord =
            hit.latitude != null && hit.longitude != null
              ? ` · ${hit.latitude.toFixed(5)}, ${hit.longitude.toFixed(5)}`
              : "";
          toast.success("적용 완료", {
            description: (
              <div className="grid gap-0.5 text-xs">
                <div>표시 제목: {hit.name ?? "—"}</div>
                <div>
                  {hit.provider} · {placeHitAddress(hit)}
                  {coord}
                </div>
                {hit.category ? <div>분류: {hit.category}</div> : null}
                {applyAllowedPolicy ? (
                  <div>재사용 정책: 재사용 허용으로 설정됨</div>
                ) : null}
              </div>
            ),
          });
        },
        onError: (error) => {
          toast.error("적용 실패", { description: error.message });
        },
      },
    );
  };

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="font-medium">장소 대조 검색</div>
      </div>
      <div className="flex flex-col gap-3 p-4">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setActiveQuery(query.trim());
          }}
        >
          <Input
            aria-label="place search query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <Button disabled={search.isFetching} type="submit" variant="outline">
            <SearchIcon data-icon="inline-start" />
            검색
          </Button>
        </form>
        <label className="flex items-center gap-2 text-sm">
          <input
            checked={applyAllowedPolicy}
            className="size-4"
            type="checkbox"
            onChange={(event) => setApplyAllowedPolicy(event.target.checked)}
          />
          <span>적용 시 재사용 정책을 &lsquo;재사용 허용&rsquo;으로 변경</span>
        </label>
        {search.isError ? (
          <Alert variant="destructive">
            <AlertTitle>장소 검색 실패</AlertTitle>
            <AlertDescription>{search.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {!search.data && !search.isFetching && !search.isError ? (
          <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            검색어를 확인하고 검색을 누르세요.
          </div>
        ) : null}
        {search.data && Object.keys(search.data.data.errors).length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {Object.entries(search.data.data.errors).map(([provider, message]) => (
              <Badge key={provider} variant="outline">
                {provider}: {uiLabel(message)}
              </Badge>
            ))}
          </div>
        ) : null}
        {providerHits.map(({ provider, hits }) => (
          <div className="rounded-md border" key={provider}>
            <div className="flex items-center justify-between border-b px-3 py-2">
              <div className="text-sm font-medium">
                {PLACE_SEARCH_PROVIDER_LABELS[provider]}
              </div>
              <Badge variant="secondary">{hits.length}</Badge>
            </div>
            {hits.length === 0 ? (
              <div className="px-3 py-3 text-sm text-muted-foreground">
                후보가 없습니다.
              </div>
            ) : (
              <div className="divide-y">
                {hits.map((hit, index) => (
                  <div
                    className="flex flex-col gap-2 px-3 py-3"
                    key={`${provider}-${index}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-medium">{hit.name ?? "-"}</div>
                        <div className="text-xs text-muted-foreground">
                          {placeHitAddress(hit)}
                        </div>
                      </div>
                      <Button
                        disabled={patchFeature.isPending}
                        size="sm"
                        type="button"
                        variant="outline"
                        onClick={() => applyHit(hit)}
                      >
                        결과 적용
                      </Button>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs">
                      {hit.category ? (
                        <Badge variant="outline">{hit.category}</Badge>
                      ) : null}
                      {typeof hit.longitude === "number" &&
                      typeof hit.latitude === "number" ? (
                        <Badge variant="ghost">
                          {hit.longitude.toFixed(5)}, {hit.latitude.toFixed(5)}
                        </Badge>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/** FeatureEditor의 사용자 입력 override — null/부재 = 서버 값 그대로(pristine). */
interface EditorOverrides {
  themeId?: string;
  title?: string;
  summary?: string;
  rankScore?: string;
  reusePolicy?: CuratedReusePolicy;
  relation?: CuratedCurationRelation;
}

export function FeatureEditor({
  feature,
  themes = [],
}: {
  feature: CuratedFeature | null;
  themes?: readonly CuratedTheme[];
}) {
  const patchFeature = usePatchCuratedFeatureMutation();
  // override 패턴: 입력 전(pristine)에는 항상 서버 값을 렌더해 refetch를 자동
  // 반영하고(effect-없는 resync), 입력이 생기면(dirty) 사용자의 값을 유지한다.
  // editBaseline은 첫 입력 시점의 updated_at — 이후 서버가 움직이면(다른 작업의
  // patch) 아래 Alert로 알리고 '최신 값 불러오기'로만 교체한다.
  const [overrides, setOverrides] = useState<EditorOverrides>({});
  const [editBaseline, setEditBaseline] = useState<string | null>(null);

  const dirty = Object.keys(overrides).length > 0;
  const serverMoved =
    dirty &&
    feature !== null &&
    editBaseline !== null &&
    feature.updated_at !== editBaseline;

  const setField = <K extends keyof EditorOverrides>(
    key: K,
    value: EditorOverrides[K],
  ) => {
    setOverrides((prev) => ({ ...prev, [key]: value }));
    setEditBaseline((prev) => prev ?? feature?.updated_at ?? null);
  };
  const resetToServer = () => {
    setOverrides({});
    setEditBaseline(null);
  };

  const themeId = overrides.themeId ?? feature?.theme_id ?? "";
  const title = overrides.title ?? feature?.display_title ?? "";
  const summary = overrides.summary ?? feature?.display_summary ?? "";
  const rankScore = overrides.rankScore ?? String(feature?.rank_score ?? 0);
  const reusePolicy =
    overrides.reusePolicy ??
    ((feature?.reuse_policy as CuratedReusePolicy | undefined) ??
      "manual_review");
  const relation =
    overrides.relation ??
    ((feature?.curation_relation as CuratedCurationRelation | undefined) ??
      "nearby_option");
  const rankInvalid = !Number.isFinite(Number(rankScore));

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!feature || rankInvalid) return;
    patchFeature.mutate(
      {
        curatedFeatureId: feature.curated_feature_id,
        body: {
          theme_id: themeId || feature.theme_id,
          display_title: title.trim().length > 0 ? title.trim() : null,
          display_summary: summary.trim().length > 0 ? summary.trim() : null,
          rank_score: Number(rankScore),
          reuse_policy: reusePolicy,
          curation_relation: relation,
        },
      },
      {
        onSuccess: () => {
          // 저장 후 override를 비워 입력이 refetch된 서버 값을 따라가게 한다.
          resetToServer();
          toast.success("저장 완료", {
            description: (
              <div className="grid gap-0.5 text-xs">
                <div>테마: {themeId || feature.theme_id}</div>
                <div>표시 제목: {title.trim() || "—"}</div>
                <div>표시 요약: {summary.trim() || "—"}</div>
                <div>
                  순위 {Number(rankScore)} · {reusePolicyLabel(reusePolicy)} ·{" "}
                  {curationRelationLabel(relation)}
                </div>
              </div>
            ),
          });
        },
        onError: (error) => {
          toast.error("저장 실패", { description: error.message });
        },
      },
    );
  };

  if (!feature) {
    return (
      <section className="rounded-lg border bg-background p-4 text-sm text-muted-foreground">
        후보를 선택하면 노출 정보를 편집할 수 있습니다.
      </section>
    );
  }

  const hasCurrentTheme = themes.some((theme) => theme.theme_id === feature.theme_id);

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="font-medium">노출 정보 편집</div>
          {dirty ? <Badge variant="secondary">수정됨</Badge> : null}
        </div>
        <div className="break-all font-mono text-xs text-muted-foreground">
          {feature.curated_feature_id}
        </div>
      </div>
      <form className="flex flex-col gap-3 p-4" onSubmit={save}>
        {serverMoved ? (
          <Alert>
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>다른 작업이 이 항목을 수정했습니다.</AlertTitle>
            <AlertDescription>
              <div className="flex flex-col gap-2">
                <span>
                  &lsquo;최신 값 불러오기&rsquo;를 누르면 입력이 서버 값으로
                  교체됩니다.
                </span>
                <Button
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={resetToServer}
                >
                  최신 값 불러오기
                </Button>
              </div>
            </AlertDescription>
          </Alert>
        ) : null}
        <FormSelect
          label="테마"
          value={themeId}
          onChange={(event) => setField("themeId", event.target.value)}
        >
          {!hasCurrentTheme ? (
            <NativeSelectOption value={feature.theme_id}>
              {feature.theme_name} · {feature.theme_slug}
            </NativeSelectOption>
          ) : null}
          {themes.map((theme) => (
            <NativeSelectOption key={theme.theme_id} value={theme.theme_id}>
              {theme.theme_name} · {theme.theme_slug}
            </NativeSelectOption>
          ))}
        </FormSelect>
        <FormField
          help="비우면 원본 feature 이름이 사용됩니다. 규칙 재적용은 관리자가 넣은 제목을 덮어쓰지 않습니다."
          label="표시 제목"
          value={title}
          onChange={(event) => setField("title", event.target.value)}
        />
        <FormTextArea
          className="min-h-24"
          label="표시 요약"
          value={summary}
          onChange={(event) => setField("summary", event.target.value)}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          {/* type=number는 브라우저가 비숫자 입력을 조용히 버려 검증이 무의미해진다
              — text+decimal 키패드로 받고 Number.isFinite로 검증해 저장을 막는다. */}
          <FormField
            error={rankInvalid ? "숫자를 입력하세요" : undefined}
            inputMode="decimal"
            label="노출 순위"
            value={rankScore}
            onChange={(event) => setField("rankScore", event.target.value)}
          />
          <FormSelect
            help="다운스트림(PinVi 등)이 이 항목을 복사해 가도 되는지의 계약입니다."
            label="재사용 정책"
            value={reusePolicy}
            onChange={(event) =>
              setField("reusePolicy", event.target.value as CuratedReusePolicy)
            }
          >
            {REUSE_POLICY_OPTIONS.map((option) => (
              <NativeSelectOption key={option} value={option}>
                {enumOption(REUSE_POLICY_LABELS[option] ?? option, option)}
              </NativeSelectOption>
            ))}
          </FormSelect>
        </div>
        <FormSelect
          help="테마 안에서 이 장소가 맡는 역할입니다."
          label="큐레이션 관계"
          value={relation}
          onChange={(event) =>
            setField("relation", event.target.value as CuratedCurationRelation)
          }
        >
          {CURATION_RELATION_OPTIONS.map((option) => (
            <NativeSelectOption key={option} value={option}>
              {enumOption(CURATION_RELATION_LABELS[option] ?? option, option)}
            </NativeSelectOption>
          ))}
        </FormSelect>
        {patchFeature.isError ? (
          <Alert variant="destructive">
            <AlertTitle>저장 실패</AlertTitle>
            <AlertDescription>{patchFeature.error.message}</AlertDescription>
          </Alert>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            disabled={!dirty}
            type="button"
            variant="ghost"
            onClick={resetToServer}
          >
            초기화
          </Button>
          <Button disabled={patchFeature.isPending || rankInvalid} type="submit">
            <SaveIcon data-icon="inline-start" />
            저장
          </Button>
        </div>
      </form>
    </section>
  );
}

type CuratedFeatureDetailItem = NonNullable<
  ReturnType<typeof useCuratedFeatureDetailSnapshot>["data"]
>["data"]["items"][number];

export function CuratedFeatureDetailPreview({
  feature,
}: {
  feature: CuratedFeature | null;
}) {
  const snapshot = useCuratedFeatureDetailSnapshot(feature?.curated_feature_id ?? null);
  const data = snapshot.data?.data;

  const itemColumns = useMemo<ColumnDef<CuratedFeatureDetailItem, unknown>[]>(
    () => [
      {
        accessorKey: "sort_order",
        header: "순서",
        cell: ({ row }) => row.original.sort_order,
      },
      {
        accessorKey: "relation",
        header: "관계",
        cell: ({ row }) => (
          <Badge variant="outline">{row.original.relation}</Badge>
        ),
      },
      {
        accessorKey: "feature_id",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-[12rem] whitespace-normal break-all font-mono text-xs">
            {row.original.feature_id}
          </span>
        ),
      },
      {
        id: "memo",
        header: "메모",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-[12rem] whitespace-normal">
            {row.original.memo ?? "-"}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <section className="rounded-lg border bg-background">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div>
          <div className="font-medium">배포 스냅샷 미리보기</div>
          <div className="text-xs text-muted-foreground">
            다운스트림(PinVi 등)이 복사해 가는 최종 payload — version/etag로
            변경을 감지합니다.
          </div>
        </div>
        {data ? (
          <Badge variant="outline">etag {shortId(data.etag, 10)}</Badge>
        ) : null}
      </div>
      {!feature ? (
        <div className="p-4 text-sm text-muted-foreground">
          후보를 선택하면 배포 스냅샷을 조회합니다.
        </div>
      ) : null}
      {snapshot.isLoading ? <Skeleton className="m-4 h-40" /> : null}
      {snapshot.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>배포 스냅샷 조회 실패</AlertTitle>
          <AlertDescription>{snapshot.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {data ? (
        <div className="flex flex-col gap-4 p-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">version</dt>
            <dd>{data.version}</dd>
            <dt className="text-muted-foreground">수정 시각</dt>
            <dd>{formatDateTime(data.updated_at)}</dd>
            <dt className="text-muted-foreground">items</dt>
            <dd>{formatCount(data.items.length)}</dd>
          </dl>
          <DataTable
            columns={itemColumns}
            data={data.items}
            getRowId={(item) => item.curated_feature_item_id}
            emptyMessage="detail item이 없습니다."
            manualSorting={false}
          />
          <details>
            <summary className="cursor-pointer text-sm font-medium">content</summary>
            <JsonBlock value={data.content} />
          </details>
          <details>
            <summary className="cursor-pointer text-sm font-medium">source</summary>
            <JsonBlock value={data.source} />
          </details>
          <details>
            <summary className="cursor-pointer text-sm font-medium">theme</summary>
            <JsonBlock value={data.theme} />
          </details>
        </div>
      ) : null}
    </section>
  );
}

function RuleEditor({
  rule,
  sourceById,
  themeById,
}: {
  rule: CuratedSourceRule | null;
  sourceById: Map<string, CuratedSource>;
  themeById: Map<string, CuratedTheme>;
}) {
  const patchRule = usePatchCuratedSourceRuleMutation();
  const confirm = useConfirm();
  const applyRule = useApplyCuratedSourceRuleMutation();
  const [defaultAction, setDefaultAction] =
    useState<CuratedRuleAction>(
      (rule?.default_action as CuratedRuleAction | undefined) ?? "candidate",
    );
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [priority, setPriority] = useState(String(rule?.priority ?? 0));
  const [placeKind, setPlaceKind] = useState(rule?.place_kind ?? "");
  const [category, setCategory] = useState(rule?.category ?? "");
  const [regionScopeJson, setRegionScopeJson] = useState(
    stringifyJson(rule?.region_scope ?? {}),
  );
  const [metadataJson, setMetadataJson] = useState(
    stringifyJson(rule?.metadata ?? {}),
  );
  const [jsonError, setJsonError] = useState<string | null>(null);
  const categories = useCategories();
  const categoryItems = categories.data?.data.items ?? [];
  // §4: 인라인 검증 — 저장 전에 필드 옆에서 바로 보여준다.
  const priorityError = integerString<Record<string, unknown>>({
    message: "정수를 입력하세요.",
  })(priority, {});
  const priorityEmpty = priority.trim().length === 0;
  const regionScopeError = jsonObject<Record<string, unknown>>()(
    regionScopeJson,
    {},
  );
  const metadataError = jsonObject<Record<string, unknown>>()(metadataJson, {});
  // region_scope 구조화 미니폼 — JSON을 직접 편집하지 않고 시도/시군구 코드로 입력.
  const regionScopeObj = useMemo(
    () => safeParseObject(regionScopeJson),
    [regionScopeJson],
  );
  const regionSido =
    typeof regionScopeObj.sido_code === "string" ? regionScopeObj.sido_code : "";
  const regionSigungu =
    typeof regionScopeObj.sigungu_code === "string"
      ? regionScopeObj.sigungu_code
      : "";
  const setRegionCode = (key: "sido_code" | "sigungu_code", next: string) => {
    const base = { ...regionScopeObj };
    if (next.trim().length > 0) base[key] = next.trim();
    else delete base[key];
    setRegionScopeJson(stringifyJson(base));
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!rule) return;
    if (priorityError || priorityEmpty) {
      // §4: Number("")===0으로 우선순위가 조용히 0이 되던 버그 방지.
      setJsonError(
        priorityError ?? "우선순위를 입력하세요(정수).",
      );
      return;
    }
    try {
      const regionScope = parseJsonObject(regionScopeJson, "region_scope");
      const metadata = parseJsonObject(metadataJson, "metadata");
      setJsonError(null);
      patchRule.mutate(
        {
          ruleId: rule.rule_id,
          body: {
            category: category.trim().length > 0 ? category.trim() : null,
            default_action: defaultAction,
            enabled,
            metadata,
            place_kind: placeKind.trim().length > 0 ? placeKind.trim() : null,
            priority: Number(priority),
            region_scope: regionScope,
          },
        },
        {
          onSuccess: () => {
            toast.success("규칙 저장 완료");
          },
          onError: (error) => {
            toast.error("규칙 저장 실패", { description: error.message });
          },
        },
      );
    } catch (error) {
      setJsonError(error instanceof Error ? error.message : String(error));
    }
  };

  const applyNow = async () => {
    if (!rule) return;
    // 규칙 적용은 조건에 맞는 feature를 일괄 등록하는 대량 mutation — 1회 확인.
    const ok = await confirm({
      title: "규칙을 지금 적용할까요?",
      description: `조건에 맞는 feature가 '${ruleActionLabel(
        defaultAction,
      )}' 상태로 등록됩니다. 이미 거절·보관된 항목은 되살아나지 않습니다.`,
      confirmLabel: "규칙 적용",
    });
    if (!ok) return;
    applyRule.mutate(
      { ruleId: rule.rule_id },
      {
        onSuccess: (response) => {
          toast.success("규칙 적용 완료", {
            description: `${formatCount(
              response.data.inserted_or_updated,
            )}개 후보를 생성/갱신했습니다 — '후보 검토' 탭에서 확인하세요.`,
          });
        },
        onError: (error) => {
          toast.error("규칙 적용 실패", { description: error.message });
        },
      },
    );
  };

  if (!rule) {
    return (
      <section className="rounded-lg border bg-background p-4 text-sm text-muted-foreground">
        소스 규칙을 선택하면 조건과 기본 동작을 편집할 수 있습니다.
      </section>
    );
  }

  const source = sourceById.get(rule.source_id);
  const theme = themeById.get(rule.theme_id);

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="font-medium">소스 규칙 편집</div>
        <div className="break-all font-mono text-xs text-muted-foreground">
          {rule.rule_id}
        </div>
      </div>
      <form className="flex flex-col gap-3 p-4" onSubmit={save}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">테마</dt>
          <dd>{theme?.theme_name ?? rule.theme_slug}</dd>
          <dt className="text-muted-foreground">소스</dt>
          <dd>{uiLabel(source?.source_name ?? rule.source_id)}</dd>
          <dt className="text-muted-foreground">데이터셋</dt>
          <dd className="break-all font-mono text-xs">{rule.dataset_key}</dd>
          <dt className="text-muted-foreground">provider</dt>
          <dd>{providerLabel(rule.provider)}</dd>
        </dl>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">기본 동작</span>
            <NativeSelect
              className="w-full"
              value={defaultAction}
              onChange={(event) =>
                setDefaultAction(event.target.value as CuratedRuleAction)
              }
            >
              {RULE_ACTION_OPTIONS.map((option) => (
                <NativeSelectOption key={option} value={option}>
                  {enumOption(RULE_ACTION_LABELS[option] ?? option, option)}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">우선순위</span>
            <Input
              aria-invalid={Boolean(priorityError)}
              inputMode="numeric"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
            />
            {priorityError ? (
              <span className="text-xs text-destructive">{priorityError}</span>
            ) : null}
          </label>
          <label className="grid gap-2 text-sm">
            <span className="text-muted-foreground">사용</span>
            <span className="flex h-8 items-center gap-2 rounded-lg border px-2.5">
              <input
                checked={enabled}
                className="size-4"
                type="checkbox"
                onChange={(event) => setEnabled(event.target.checked)}
              />
              <span>{enabled ? "사용 중" : "사용 안 함"}</span>
            </span>
          </label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">장소 종류</span>
            <NativeSelect
              value={placeKind}
              onChange={(event) => setPlaceKind(event.target.value)}
            >
              {withCurrentOption(
                PLACE_KIND_OPTIONS,
                placeKind,
                "현재 장소 종류",
              ).map((option) => (
                <NativeSelectOption key={option.value} value={option.value}>
                  {option.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">카테고리</span>
            <Input
              list="curated-rule-category-options"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            />
            <datalist id="curated-rule-category-options">
              {categoryItems.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </datalist>
          </label>
        </div>
        <div className="grid gap-2 text-sm">
          <span className="text-muted-foreground">
            지역 범위 (region_scope) — 비우면 전국
          </span>
          <div className="grid gap-2 sm:grid-cols-2">
            <AdminRegionAutoSearch
              id={`rule-region-sido-${rule?.rule_id ?? "new"}`}
              kind="sido"
              label="시도 코드"
              value={regionSido}
              onChange={(next) => setRegionCode("sido_code", next)}
            />
            <AdminRegionAutoSearch
              id={`rule-region-sigungu-${rule?.rule_id ?? "new"}`}
              kind="sigungu"
              label="시군구 코드"
              value={regionSigungu}
              onChange={(next) => setRegionCode("sigungu_code", next)}
            />
          </div>
          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground">
              고급 — region_scope JSON 직접 편집
            </summary>
            <Textarea
              aria-invalid={Boolean(regionScopeError)}
              aria-label="region_scope"
              className="mt-1 min-h-28 font-mono text-xs"
              value={regionScopeJson}
              onChange={(event) => setRegionScopeJson(event.target.value)}
            />
            {regionScopeError ? (
              <span className="text-xs text-destructive">{regionScopeError}</span>
            ) : (
              <span className="text-xs text-muted-foreground">
                JSON object — 예: {"{"}&quot;sido_code&quot;: &quot;11&quot;{"}"}
              </span>
            )}
          </details>
        </div>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">metadata</span>
          <Textarea
            aria-invalid={Boolean(metadataError)}
            className="min-h-28 font-mono text-xs"
            value={metadataJson}
            onChange={(event) => setMetadataJson(event.target.value)}
          />
          {metadataError ? (
            <span className="text-xs text-destructive">{metadataError}</span>
          ) : (
            <span className="text-xs text-muted-foreground">
              JSON object — 규칙 운영 메모 등 자유 필드
            </span>
          )}
        </label>
        {jsonError || patchRule.isError || applyRule.isError ? (
          <Alert variant="destructive">
            <AlertTitle>소스 규칙 처리 실패</AlertTitle>
            <AlertDescription>
              {jsonError ??
                patchRule.error?.message ??
                applyRule.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            disabled={applyRule.isPending}
            type="button"
            variant="outline"
            onClick={() => void applyNow()}
          >
            <PlayIcon data-icon="inline-start" />
            규칙 적용 (후보 생성)
          </Button>
          <Button disabled={patchRule.isPending} type="submit">
            <SaveIcon data-icon="inline-start" />
            규칙 저장
          </Button>
        </div>
      </form>
    </section>
  );
}

export function CuratedFeaturesClient() {
  const [activeTab, setActiveTab] = useState<ConsoleTab>("review");
  const [provider, setProvider] = useState("all");
  const [datasetKey, setDatasetKey] = useState("all");
  const [themeSlug, setThemeSlug] = useState("all");
  const [status, setStatus] = useState<StatusFilter>("candidate");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [cursor, setCursor] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(1);
  const [featureSearch, setFeatureSearch] = useState("");
  // 서버 검색(q) — 300ms 디바운스 후 keyset 목록을 재조회한다(전 페이지 검색).
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [selectedCuratedFeatureId, setSelectedCuratedFeatureId] =
    useState<string | null>(null);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [ruleEnabled, setRuleEnabled] = useState<EnabledFilter>("all");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const themes = useAdminCuratedThemes({ limit: 200 });
  const sources = useAdminCuratedSources({ limit: 500 });

  const providerOptions = useMemo(() => {
    const providers = new Set(
      (sources.data?.data.items ?? []).map((source) => source.provider),
    );
    return Array.from(providers).sort();
  }, [sources.data?.data.items]);

  const datasetOptions = useMemo(() => {
    const datasets = new Set(
      (sources.data?.data.items ?? [])
        .filter((source) => provider === "all" || source.provider === provider)
        .map((source) => source.dataset_key),
    );
    return Array.from(datasets).sort();
  }, [provider, sources.data?.data.items]);

  const sourceById = useMemo(() => {
    return new Map(
      (sources.data?.data.items ?? []).map((source) => [
        source.source_id,
        source,
      ]),
    );
  }, [sources.data?.data.items]);

  const themeById = useMemo(() => {
    return new Map(
      (themes.data?.data.items ?? []).map((theme) => [theme.theme_id, theme]),
    );
  }, [themes.data?.data.items]);

  const featureParams = useMemo<AdminCuratedFeaturesParams>(
    () => ({
      theme_slug: themeSlug === "all" ? undefined : themeSlug,
      provider: provider === "all" ? undefined : provider,
      dataset_key: datasetKey === "all" ? undefined : datasetKey,
      curation_status: status === "all" ? undefined : status,
      include_archived: includeArchived,
      q: debouncedSearch.length > 0 ? debouncedSearch : undefined,
      page_size: pageSize,
      cursor: cursor ?? undefined,
    }),
    [
      cursor,
      datasetKey,
      debouncedSearch,
      includeArchived,
      pageSize,
      provider,
      status,
      themeSlug,
    ],
  );

  const ruleParams = useMemo<AdminCuratedSourceRulesParams>(
    () => ({
      theme_slug: themeSlug === "all" ? undefined : themeSlug,
      provider: provider === "all" ? undefined : provider,
      dataset_key: datasetKey === "all" ? undefined : datasetKey,
      enabled:
        ruleEnabled === "all" ? undefined : ruleEnabled === "enabled",
      limit: 200,
    }),
    [datasetKey, provider, ruleEnabled, themeSlug],
  );

  const features = useAdminCuratedFeatures(featureParams);
  const rules = useAdminCuratedSourceRules(ruleParams);
  const allRules = useAdminCuratedSourceRules({ limit: 500 });
  const selectFeature = useSelectCuratedFeatureMutation();
  const unselectFeature = useUnselectCuratedFeatureMutation();
  const archiveFeature = useArchiveCuratedFeatureMutation();
  const confirm = useConfirm();

  const items = features.data?.data.items ?? [];
  const ruleItems = rules.data?.data.items ?? [];
  const allRuleItems = allRules.data?.data.items ?? [];
  const selectedFeature =
    items.find(
      (item) => item.curated_feature_id === selectedCuratedFeatureId,
    ) ??
    items[0] ??
    null;
  const selectedRule =
    ruleItems.find((rule) => rule.rule_id === selectedRuleId) ??
    ruleItems[0] ??
    null;
  const nextCursor = features.data?.meta.page?.next_cursor ?? null;
  // 행 단위 pending — 진행 중인 mutation의 variables로 해당 행만 잠근다
  // (전역 잠금은 다른 행의 버튼까지 회색으로 만들어 오해를 줬다).
  const pendingRowId =
    (selectFeature.isPending
      ? selectFeature.variables?.curatedFeatureId
      : null) ??
    (unselectFeature.isPending
      ? unselectFeature.variables?.curatedFeatureId
      : null) ??
    (archiveFeature.isPending
      ? archiveFeature.variables?.curatedFeatureId
      : null) ??
    null;

  const resetCursor = () => {
    setCursor(null);
    setPageIndex(1);
  };
  const goFirstPage = () => {
    setCursor(null);
    setPageIndex(1);
  };
  const goNextPage = () => {
    if (!nextCursor) return;
    setCursor(nextCursor);
    setPageIndex((page) => page + 1);
  };
  const refresh = () => {
    void features.refetch();
    void rules.refetch();
    void allRules.refetch();
    void sources.refetch();
    void themes.refetch();
  };

  const onSearchChange = (value: string) => {
    setFeatureSearch(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setDebouncedSearch(value.trim());
      setCursor(null);
      setPageIndex(1);
    }, SEARCH_DEBOUNCE_MS);
  };

  const jumpToCurated = () => {
    setStatus("curated");
    resetCursor();
    setActiveTab("review");
  };

  const selectCurated = (feature: CuratedFeature) => {
    selectFeature.mutate(
      {
        curatedFeatureId: feature.curated_feature_id,
        body: {
          actor: "admin-ui",
          reason: "admin curated selection",
        },
      },
      {
        onSuccess: () => {
          notifyStatusTransition("select", feature.feature_name, jumpToCurated);
        },
        onError: (error) => {
          toast.error("채택 실패", { description: error.message });
        },
      },
    );
  };

  const unselectCurated = (feature: CuratedFeature) => {
    unselectFeature.mutate(
      {
        curatedFeatureId: feature.curated_feature_id,
        body: {
          actor: "admin-ui",
          reason: "admin curated unselect",
        },
      },
      {
        onSuccess: () => {
          notifyStatusTransition("unselect", feature.feature_name);
        },
        onError: (error) => {
          toast.error("채택 해제 실패", { description: error.message });
        },
      },
    );
  };

  const archiveCurated = async (feature: CuratedFeature) => {
    const ok = await confirm({
      title: `"${feature.feature_name}"을(를) 보관할까요?`,
      description:
        "보관하면 규칙 재적용으로 되살아나지 않으며, '보관됨 포함' 필터로만 조회됩니다.",
      confirmLabel: "보관",
      destructive: true,
    });
    if (!ok) return;
    archiveFeature.mutate(
      {
        curatedFeatureId: feature.curated_feature_id,
        body: {
          actor: "admin-ui",
          reason: "admin curated archive",
        },
      },
      {
        onSuccess: () => {
          notifyStatusTransition("archive", feature.feature_name);
        },
        onError: (error) => {
          toast.error("보관 실패", { description: error.message });
        },
      },
    );
  };

  /** bulk 채택/보관 — allSettled로 전 행을 시도하고 성공/실패를 집계 보고한다. */
  const runBulk = async (
    rows: Row<CuratedFeature>[],
    kind: "select" | "archive",
  ) => {
    const mutateAsync =
      kind === "select" ? selectFeature.mutateAsync : archiveFeature.mutateAsync;
    const reason =
      kind === "select" ? "admin curated selection" : "admin curated archive";
    const results = await Promise.allSettled(
      rows.map((row) =>
        mutateAsync({
          curatedFeatureId: row.original.curated_feature_id,
          body: { actor: "admin-ui", reason },
        }),
      ),
    );
    const failedIds = rows
      .filter((_, index) => results[index]?.status === "rejected")
      .map((row) => row.original.curated_feature_id);
    const ok = results.length - failedIds.length;
    if (failedIds.length > 0) {
      const firstError = results.find(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );
      const message =
        firstError?.reason instanceof Error ? firstError.reason.message : "";
      toast.warning("일괄 처리 일부 실패", {
        description: `성공 ${ok}건 · 실패 ${failedIds.length}건${
          message ? ` — ${message}` : ""
        }`,
      });
    } else {
      toast.success("일괄 처리 완료", {
        description: `성공 ${ok}건 · 실패 0건`,
      });
    }
    // 실패한 행만 체크 상태를 유지해 재시도가 쉽게 한다.
    setRowSelection(
      Object.fromEntries(failedIds.map((id) => [id, true] as const)),
    );
  };

  const featureColumns = useMemo<ColumnDef<CuratedFeature, unknown>[]>(
    // curated 후보는 keyset cursor 목록(next_cursor) + 서버 검색(q) — 서버가 정렬을
    // 소유하므로 컬럼 정렬을 끈다(#502: client 정렬은 현재 페이지만 재배열해 오해를 줌).
    () => [
      {
        accessorKey: "curation_status",
        header: "상태",
        enableSorting: false,
        cell: ({ row }) => (
          <Badge variant={featureStatusVariant(row.original.curation_status)}>
            {statusLabel(row.original.curation_status)}
          </Badge>
        ),
      },
      {
        accessorKey: "feature_name",
        header: "feature",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="max-w-[20rem] whitespace-normal">
              <div className="font-medium">
                {feature.feature_name}
              </div>
              {feature.display_title ? (
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {feature.display_title}
                </div>
              ) : null}
              <div className="break-all font-mono text-xs text-muted-foreground">
                {shortId(feature.feature_id, 18)}
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                <Badge variant="outline">{feature.feature_kind}</Badge>
                <Badge variant="outline">{feature.feature_category}</Badge>
                <Badge variant="ghost">{coordLabel(feature)}</Badge>
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: "source_name",
        header: "소스",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="max-w-[16rem] whitespace-normal">
              <div>{uiLabel(feature.source_name)}</div>
              <div className="break-all font-mono text-xs text-muted-foreground">
                {providerLabel(feature.provider)}:{feature.dataset_key}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: "theme_name",
        header: "테마",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <>
              <div>{feature.theme_name}</div>
              <div className="text-xs text-muted-foreground">
                {feature.theme_group}
              </div>
            </>
          );
        },
      },
      {
        id: "reuse",
        header: "정책·관계",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="flex flex-col gap-1">
              <Badge
                title={feature.reuse_policy}
                variant={reusePolicyVariant(feature.reuse_policy)}
              >
                {reusePolicyLabel(feature.reuse_policy)}
              </Badge>
              <Badge title={feature.curation_relation} variant="outline">
                {curationRelationLabel(feature.curation_relation)}
              </Badge>
            </div>
          );
        },
      },
      {
        accessorKey: "updated_at",
        header: "수정",
        enableSorting: false,
        cell: ({ row }) => formatDateTime(row.original.updated_at),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          const rowPending = pendingRowId === feature.curated_feature_id;
          return (
            <div className="flex w-72 flex-wrap justify-end gap-1 text-right">
              <Link
                className={cn(
                  buttonVariants({
                    variant: "outline",
                    size: "sm",
                  }),
                )}
                href={curatedFeatureHref(feature.curated_feature_id)}
                onClick={(event) => event.stopPropagation()}
              >
                상세
              </Link>
              <Link
                aria-label="원본 feature 열기"
                className={cn(
                  buttonVariants({
                    variant: "ghost",
                    size: "icon-sm",
                  }),
                )}
                href={featureHref(feature.feature_id)}
                title="원본 feature 열기"
                onClick={(event) => event.stopPropagation()}
              >
                <ExternalLinkIcon />
              </Link>
              {feature.curation_status === "curated" ? (
                <Button
                  disabled={rowPending}
                  size="sm"
                  title="공개에서 제외(거절)"
                  type="button"
                  variant="outline"
                  onClick={(event) => {
                    event.stopPropagation();
                    unselectCurated(feature);
                  }}
                >
                  <RotateCcwIcon data-icon="inline-start" />
                  채택 해제
                </Button>
              ) : (
                <Button
                  disabled={rowPending}
                  size="sm"
                  title="공개 목록에 추가"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    selectCurated(feature);
                  }}
                >
                  <CheckIcon data-icon="inline-start" />
                  채택
                </Button>
              )}
              <Button
                disabled={rowPending}
                size="sm"
                title="소프트 삭제"
                type="button"
                variant="destructive"
                onClick={(event) => {
                  event.stopPropagation();
                  void archiveCurated(feature);
                }}
              >
                <ArchiveIcon data-icon="inline-start" />
                보관
              </Button>
            </div>
          );
        },
      },
    ],
    // handlers (selectCurated/unselectCurated/archiveCurated) are stable closures;
    // re-memo only when the per-row pending id used inside action cells changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pendingRowId],
  );

  const ruleColumns = useMemo<ColumnDef<CuratedSourceRule, unknown>[]>(
    () => [
      {
        accessorKey: "enabled",
        header: "사용",
        cell: ({ row }) => (
          <Badge variant={row.original.enabled ? "default" : "outline"}>
            {row.original.enabled ? "사용 중" : "사용 안 함"}
          </Badge>
        ),
      },
      {
        accessorKey: "theme_slug",
        header: "테마",
        cell: ({ row }) => (
          <>
            <div>{row.original.theme_slug}</div>
            <div className="text-xs text-muted-foreground">
              {shortId(row.original.theme_id, 10)}
            </div>
          </>
        ),
      },
      {
        id: "source",
        header: "소스",
        enableSorting: false,
        cell: ({ row }) => {
          const rule = row.original;
          const source = sourceById.get(rule.source_id);
          return (
            <div className="max-w-[18rem] whitespace-normal">
              <div>{uiLabel(source?.source_name ?? rule.source_id)}</div>
              <div className="break-all font-mono text-xs text-muted-foreground">
                {providerLabel(rule.provider)}:{rule.dataset_key}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: "default_action",
        header: "기본 동작",
        cell: ({ row }) => (
          <Badge title={row.original.default_action} variant="outline">
            {ruleActionLabel(row.original.default_action)}
          </Badge>
        ),
      },
      {
        accessorKey: "priority",
        header: "우선순위",
        cell: ({ row }) => row.original.priority,
      },
      {
        accessorKey: "updated_at",
        header: "수정",
        cell: ({ row }) => formatDateTime(row.original.updated_at),
      },
    ],
    [sourceById],
  );

  const emptyMessage =
    status === "curated"
      ? "채택된 항목이 없습니다. '후보' 상태에서 채택하면 여기에 표시됩니다."
      : status === "rejected" || status === "archived"
        ? "이 상태의 항목이 없습니다. 거절·보관된 항목은 자동으로 되살아나지 않습니다."
        : "조건에 맞는 후보가 없습니다.";

  return (
    <AdminShell
      actions={
        <Button
          disabled={
            features.isFetching ||
            rules.isFetching ||
            allRules.isFetching ||
            sources.isFetching ||
            themes.isFetching
          }
          type="button"
          variant="outline"
          onClick={refresh}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      title="큐레이션 관리"
    >
      <div className="flex flex-col gap-4">
        {features.isError ||
        rules.isError ||
        allRules.isError ||
        sources.isError ||
        themes.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>큐레이션 데이터 조회 실패</AlertTitle>
            <AlertDescription>
              {features.error?.message ??
                rules.error?.message ??
                allRules.error?.message ??
                sources.error?.message ??
                themes.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}

        <CuratedLifecycleStrip
          activeStatus={status === "all" ? null : status}
          onSelectStatus={(next) => {
            setStatus(next);
            resetCursor();
            setActiveTab("review");
          }}
        />

        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as ConsoleTab)}
        >
          <TabsList>
            <TabsTrigger value="review">후보 검토</TabsTrigger>
            <TabsTrigger value="rules">소스 규칙</TabsTrigger>
          </TabsList>

          <TabsContent className="flex flex-col gap-4" value="review">
            <section className="rounded-lg border bg-background p-4">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="relative">
                  <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                  <Input
                    aria-label="curated feature search"
                    className="pl-8"
                    placeholder="이름·제목·소스·provider 서버 검색"
                    value={featureSearch}
                    onChange={(event) => onSearchChange(event.target.value)}
                  />
                </div>
                <NativeSelect
                  aria-label="theme filter"
                  className="w-full"
                  value={themeSlug}
                  onChange={(event) => {
                    setThemeSlug(event.target.value);
                    resetCursor();
                  }}
                >
                  <NativeSelectOption value="all">테마 전체</NativeSelectOption>
                  {(themes.data?.data.items ?? []).map((theme) => (
                    <NativeSelectOption
                      key={theme.theme_id}
                      value={theme.theme_slug}
                    >
                      {theme.theme_name}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <NativeSelect
                  aria-label="provider filter"
                  className="w-full"
                  value={provider}
                  onChange={(event) => {
                    const nextProvider = event.target.value;
                    setProvider(nextProvider);
                    setDatasetKey("all");
                    if (isPlaceCandidateProvider(nextProvider)) {
                      setThemeSlug(
                        themeSlugForProvider(
                          nextProvider,
                          "all",
                          sources.data?.data.items ?? [],
                          allRuleItems.length > 0 ? allRuleItems : ruleItems,
                        ) ?? "all",
                      );
                    }
                    resetCursor();
                  }}
                >
                  <NativeSelectOption value="all">
                    provider 전체
                  </NativeSelectOption>
                  {providerOptions.map((option) => (
                    <NativeSelectOption key={option} value={option}>
                      {providerLabel(option)}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <NativeSelect
                  aria-label="dataset filter"
                  className="w-full"
                  value={datasetKey}
                  onChange={(event) => {
                    const nextDatasetKey = event.target.value;
                    setDatasetKey(nextDatasetKey);
                    if (isPlaceCandidateProvider(provider)) {
                      setThemeSlug(
                        themeSlugForProvider(
                          provider,
                          nextDatasetKey,
                          sources.data?.data.items ?? [],
                          allRuleItems.length > 0 ? allRuleItems : ruleItems,
                        ) ?? "all",
                      );
                    }
                    resetCursor();
                  }}
                >
                  <NativeSelectOption value="all">
                    데이터셋 전체
                  </NativeSelectOption>
                  {datasetOptions.map((option) => (
                    <NativeSelectOption key={option} value={option}>
                      {option}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <NativeSelect
                  aria-label="curation status filter"
                  className="w-full"
                  value={status}
                  onChange={(event) => {
                    setStatus(event.target.value as StatusFilter);
                    resetCursor();
                  }}
                >
                  <NativeSelectOption value="all">상태 전체</NativeSelectOption>
                  {CURATION_STATUS_OPTIONS.map((option) => (
                    <NativeSelectOption key={option} value={option}>
                      {statusLabel(option)}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <NativeSelect
                  aria-label="page size"
                  className="w-full"
                  value={String(pageSize)}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value) as typeof pageSize);
                    resetCursor();
                  }}
                >
                  {PAGE_SIZE_OPTIONS.map((option) => (
                    <NativeSelectOption key={option} value={option}>
                      {option}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <label className="flex h-8 items-center gap-2 rounded-lg border px-2.5 text-sm">
                  <input
                    checked={includeArchived}
                    className="size-4"
                    type="checkbox"
                    onChange={(event) => {
                      setIncludeArchived(event.target.checked);
                      resetCursor();
                    }}
                  />
                  <span className="whitespace-nowrap">보관됨 포함</span>
                </label>
              </div>
            </section>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_25rem]">
              <section className="rounded-lg border bg-background">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
                  <div>
                    <div className="font-medium">후보 목록</div>
                    <div className="text-xs text-muted-foreground">
                      page {formatCount(pageIndex)} · 이 페이지{" "}
                      {formatCount(items.length)}개 · 페이지 크기{" "}
                      {formatCount(pageSize)}
                    </div>
                  </div>
                  <CursorPager
                    hasNext={nextCursor !== null}
                    isFetching={features.isFetching}
                    onFirst={goFirstPage}
                    onNext={goNextPage}
                  />
                </div>
                <DataTable
                  columns={featureColumns}
                  data={items}
                  getRowId={(feature) => feature.curated_feature_id}
                  isLoading={features.isLoading}
                  emptyMessage={emptyMessage}
                  enableRowSelection
                  rowSelection={rowSelection}
                  onRowSelectionChange={setRowSelection}
                  renderBulkActions={(rows: Row<CuratedFeature>[]) => (
                    <>
                      <Button
                        disabled={selectFeature.isPending}
                        size="sm"
                        type="button"
                        onClick={() => {
                          void runBulk(rows, "select");
                        }}
                      >
                        <CheckIcon data-icon="inline-start" />
                        체크한 {rows.length}건 채택
                      </Button>
                      <Button
                        disabled={archiveFeature.isPending}
                        size="sm"
                        type="button"
                        variant="destructive"
                        onClick={() => {
                          // bulk 보관은 되돌리기 부담이 있어 일괄 confirm 1회.
                          void (async () => {
                            const ok = await confirm({
                              title: `체크한 ${rows.length}건을 보관할까요?`,
                              description:
                                "보관은 규칙 재적용으로 되살아나지 않습니다.",
                              confirmLabel: "보관",
                              destructive: true,
                            });
                            if (!ok) return;
                            await runBulk(rows, "archive");
                          })();
                        }}
                      >
                        <ArchiveIcon data-icon="inline-start" />
                        체크한 {rows.length}건 보관
                      </Button>
                    </>
                  )}
                  onRowClick={(feature) =>
                    setSelectedCuratedFeatureId(feature.curated_feature_id)
                  }
                  rowTestId={() => "curated-feature-row"}
                  isRowActive={(feature) =>
                    feature.curated_feature_id ===
                    selectedFeature?.curated_feature_id
                  }
                />
                {!features.isLoading && items.length === 0 ? (
                  <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3">
                    <Button
                      size="sm"
                      type="button"
                      variant="outline"
                      onClick={() => setActiveTab("rules")}
                    >
                      소스 규칙 탭 열기
                    </Button>
                    <Link
                      className={cn(
                        buttonVariants({ variant: "ghost", size: "sm" }),
                      )}
                      href={`/ops/pipeline?tab=schedules&schedule=${encodeURIComponent(
                        CURATED_FEATURES_REFRESH_SCHEDULE,
                      )}`}
                    >
                      <PlayIcon data-icon="inline-start" />
                      새로고침 job 실행
                    </Link>
                  </div>
                ) : null}
              </section>

              <div className="flex flex-col gap-4">
                <section className="rounded-lg border bg-background p-3">
                  {selectedFeature ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold">
                            {selectedFeature.feature_name}
                          </div>
                          {selectedFeature.display_title ? (
                            <div className="truncate text-xs text-muted-foreground">
                              {selectedFeature.display_title}
                            </div>
                          ) : null}
                          <div className="break-all font-mono text-xs text-muted-foreground">
                            {selectedFeature.curated_feature_id}
                          </div>
                        </div>
                        <Badge
                          variant={featureStatusVariant(
                            selectedFeature.curation_status,
                          )}
                        >
                          {statusLabel(selectedFeature.curation_status)}
                        </Badge>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Link
                          className={cn(
                            buttonVariants({ variant: "outline", size: "sm" }),
                          )}
                          href={curatedFeatureHref(
                            selectedFeature.curated_feature_id,
                          )}
                        >
                          <EyeIcon data-icon="inline-start" />
                          상세
                        </Link>
                        <Link
                          className={cn(
                            buttonVariants({ variant: "ghost", size: "sm" }),
                          )}
                          href={featureHref(selectedFeature.feature_id)}
                        >
                          <ExternalLinkIcon data-icon="inline-start" />
                          feature
                        </Link>
                      </div>
                      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                        <dt className="text-muted-foreground">채택 시각</dt>
                        <dd>{formatDateTime(selectedFeature.selected_at)}</dd>
                        <dt className="text-muted-foreground">콘텐츠 버전</dt>
                        <dd>{selectedFeature.content_version}</dd>
                        <dt className="text-muted-foreground">순위</dt>
                        <dd>{selectedFeature.rank_score.toFixed(2)}</dd>
                      </dl>
                      <details>
                        <summary className="cursor-pointer text-sm font-medium">
                          metadata
                        </summary>
                        <JsonBlock value={selectedFeature.metadata} />
                      </details>
                      <details>
                        <summary className="cursor-pointer text-sm font-medium">
                          detail
                        </summary>
                        <JsonBlock value={selectedFeature.detail} />
                      </details>
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      후보를 선택하면 상세를 확인할 수 있습니다.
                    </div>
                  )}
                </section>
                <CuratedFeatureLocationPanel feature={selectedFeature} />
                {/* Sibling keys MUST be distinct (`:place-search` vs `:editor`): the
                    same key on two siblings duplicates React keys and stacks the
                    panel instead of resetting it on reselect. The editor keeps its
                    inputs in an override state that follows the server values while
                    pristine, so the key no longer needs updated_at to re-sync. */}
                <CuratedPlaceSearchPanel
                  feature={selectedFeature}
                  key={`${selectedFeature?.curated_feature_id ?? "empty"}:place-search`}
                />
                <FeatureEditor
                  feature={selectedFeature}
                  key={`${selectedFeature?.curated_feature_id ?? "empty"}:editor`}
                  themes={themes.data?.data.items ?? []}
                />
                <CuratedFeatureDetailPreview feature={selectedFeature} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="rules">
            <section className="rounded-lg border bg-background">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
                <div>
                  <div className="font-medium">소스 규칙</div>
                  <div className="text-xs text-muted-foreground">
                    provider source를 curated 후보로 끌어올리는 규칙 — 매일 새벽
                    배치로도 실행됩니다.
                  </div>
                </div>
                <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
                  <Link
                    className={cn(
                      buttonVariants({ variant: "outline", size: "sm" }),
                    )}
                    href={`/ops/pipeline?tab=schedules&schedule=${encodeURIComponent(
                      CURATED_FEATURES_REFRESH_SCHEDULE,
                    )}`}
                  >
                    <PlayIcon data-icon="inline-start" />
                    관련 job 실행
                  </Link>
                  <NativeSelect
                    aria-label="rule enabled filter"
                    className="w-full sm:w-40"
                    value={ruleEnabled}
                    onChange={(event) =>
                      setRuleEnabled(event.target.value as EnabledFilter)
                    }
                  >
                    <NativeSelectOption value="all">
                      사용 전체
                    </NativeSelectOption>
                    <NativeSelectOption value="enabled">
                      사용 중
                    </NativeSelectOption>
                    <NativeSelectOption value="disabled">
                      사용 안 함
                    </NativeSelectOption>
                  </NativeSelect>
                </div>
              </div>
              <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_32rem]">
                <div className="rounded-lg border">
                  <DataTable
                    columns={ruleColumns}
                    data={ruleItems}
                    getRowId={(rule) => rule.rule_id}
                    isLoading={rules.isLoading}
                    emptyMessage="조건에 맞는 소스 규칙이 없습니다."
                    onRowClick={(rule) => setSelectedRuleId(rule.rule_id)}
                    isRowActive={(rule) => rule.rule_id === selectedRule?.rule_id}
                    manualSorting={false}
                  />
                </div>
                <RuleEditor
                  key={selectedRule?.rule_id ?? "empty-rule"}
                  rule={selectedRule}
                  sourceById={sourceById}
                  themeById={themeById}
                />
              </div>
            </section>
          </TabsContent>
        </Tabs>
      </div>
    </AdminShell>
  );
}
