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
import { useDeferredValue, useMemo, useState } from "react";
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
import { AdminShell } from "@/components/admin-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { statusLabel } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import {
  PLACE_KIND_OPTIONS,
  withCurrentOption,
} from "@/lib/feature-form-options";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

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

type StatusFilter = CuratedFeatureStatus | "all";
type EnabledFilter = "all" | "enabled" | "disabled";

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    return {};
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (
    parsed === null ||
    typeof parsed !== "object" ||
    Array.isArray(parsed)
  ) {
    throw new Error(`${label}은 JSON object여야 합니다.`);
  }
  return parsed as Record<string, unknown>;
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
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
  if (typeof feature.lon === "number" && typeof feature.lat === "number") {
    return `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`;
  }
  return "-";
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
    feature.display_title ??
    feature.feature_name ??
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
  const hasCoord =
    typeof feature.lon === "number" && typeof feature.lat === "number";

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="font-medium">Location review</div>
        <div className="text-xs text-muted-foreground">
          위치, 주소, 카테고리 확인
        </div>
      </div>
      <div className="flex flex-col gap-3 p-4">
        {hasCoord ? (
          <div className="relative h-56 overflow-hidden rounded-md border">
            <VWorldMapView
              apiKey={VWORLD_KEY}
              center={[feature.lon as number, feature.lat as number]}
              className="absolute inset-0 h-full w-full"
              key={feature.curated_feature_id}
              navigation
              scale
              zoom={14}
            >
              <VWorldMarker
                lngLat={[feature.lon as number, feature.lat as number]}
                markerColor="#2563eb"
                selected
                title={feature.display_title ?? feature.feature_name}
              />
            </VWorldMapView>
          </div>
        ) : (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            좌표가 없어 지도 marker를 표시할 수 없습니다.
          </div>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">coord</dt>
          <dd className="font-mono">{coordLabel(feature)}</dd>
          <dt className="text-muted-foreground">address</dt>
          <dd>{featureAddressLabel(feature)}</dd>
          <dt className="text-muted-foreground">category</dt>
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
          reuse_policy: "allowed",
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
          toast.success("반영 완료", {
            description: (
              <div className="grid gap-0.5 text-xs">
                <div>display title: {hit.name ?? "—"}</div>
                <div>
                  {hit.provider} · {placeHitAddress(hit)}
                  {coord}
                </div>
                {hit.category ? <div>분류: {hit.category}</div> : null}
              </div>
            ),
          });
        },
        onError: (error) => {
          toast.error("반영 실패", { description: uiLabel(error.message) });
        },
      },
    );
  };

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="font-medium">Place search</div>
        <div className="text-xs text-muted-foreground">
          Google/Kakao/Naver 후보 비교
        </div>
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
        {search.isError ? (
          <Alert variant="destructive">
            <AlertTitle>장소 검색 실패</AlertTitle>
            <AlertDescription>{uiLabel(search.error.message)}</AlertDescription>
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
                        반영
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

export function FeatureEditor({
  feature,
  themes = [],
}: {
  feature: CuratedFeature | null;
  themes?: readonly CuratedTheme[];
}) {
  const patchFeature = usePatchCuratedFeatureMutation();
  const [themeId, setThemeId] = useState(feature?.theme_id ?? "");
  const [title, setTitle] = useState(feature?.display_title ?? "");
  const [summary, setSummary] = useState(feature?.display_summary ?? "");
  const [rankScore, setRankScore] = useState(String(feature?.rank_score ?? 0));
  const [reusePolicy, setReusePolicy] =
    useState<CuratedReusePolicy>(
      (feature?.reuse_policy as CuratedReusePolicy | undefined) ??
        "manual_review",
    );
  const [relation, setRelation] =
    useState<CuratedCurationRelation>(
      (feature?.curation_relation as CuratedCurationRelation | undefined) ??
        "nearby_option",
    );

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!feature) return;
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
          toast.success("저장 완료", {
            description: (
              <div className="grid gap-0.5 text-xs">
                <div>theme: {themeId || feature.theme_id}</div>
                <div>display title: {title.trim() || "—"}</div>
                <div>display summary: {summary.trim() || "—"}</div>
                <div>
                  rank {Number(rankScore)} · {reusePolicy} · {relation}
                </div>
              </div>
            ),
          });
        },
        onError: (error) => {
          toast.error("저장 실패", { description: uiLabel(error.message) });
        },
      },
    );
  };

  if (!feature) {
    return (
      <section className="rounded-lg border bg-background p-4 text-sm text-muted-foreground">
        후보를 선택하면 display text와 공개 재사용 속성을 편집할 수 있습니다.
      </section>
    );
  }

  const hasCurrentTheme = themes.some((theme) => theme.theme_id === feature.theme_id);

  return (
    <section className="rounded-lg border bg-background">
      <div className="border-b px-4 py-3">
        <div className="font-medium">Curated display</div>
        <div className="break-all font-mono text-xs text-muted-foreground">
          {feature.curated_feature_id}
        </div>
      </div>
      <form className="flex flex-col gap-3 p-4" onSubmit={save}>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">curated theme</span>
          <NativeSelect
            className="w-full"
            value={themeId}
            onChange={(event) => setThemeId(event.target.value)}
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
          </NativeSelect>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">display title</span>
          <Input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">display summary</span>
          <Textarea
            className="min-h-24"
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">rank score</span>
            <Input
              min="0"
              step="0.01"
              type="number"
              value={rankScore}
              onChange={(event) => setRankScore(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">reuse policy</span>
            <NativeSelect
              className="w-full"
              value={reusePolicy}
              onChange={(event) =>
                setReusePolicy(event.target.value as CuratedReusePolicy)
              }
            >
              {REUSE_POLICY_OPTIONS.map((option) => (
                <NativeSelectOption key={option} value={option}>
                  {option}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
        </div>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">curation relation</span>
          <NativeSelect
            className="w-full"
            value={relation}
            onChange={(event) =>
              setRelation(event.target.value as CuratedCurationRelation)
            }
          >
            {CURATION_RELATION_OPTIONS.map((option) => (
              <NativeSelectOption key={option} value={option}>
                {option}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </label>
        {patchFeature.isError ? (
          <Alert variant="destructive">
            <AlertTitle>curated feature 저장 실패</AlertTitle>
            <AlertDescription>{patchFeature.error.message}</AlertDescription>
          </Alert>
        ) : null}
        <div className="flex justify-end">
          <Button disabled={patchFeature.isPending} type="submit">
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
          <div className="font-medium">Detail snapshot preview</div>
          <div className="text-xs text-muted-foreground">
            detail snapshot item 미리보기
          </div>
        </div>
        {data ? (
          <Badge variant="outline">etag {shortId(data.etag, 10)}</Badge>
        ) : null}
      </div>
      {!feature ? (
        <div className="p-4 text-sm text-muted-foreground">
          후보를 선택하면 detail snapshot을 조회합니다.
        </div>
      ) : null}
      {snapshot.isLoading ? <Skeleton className="m-4 h-40" /> : null}
      {snapshot.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>detail preview 조회 실패</AlertTitle>
          <AlertDescription>{snapshot.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {data ? (
        <div className="flex flex-col gap-4 p-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">version</dt>
            <dd>{data.version}</dd>
            <dt className="text-muted-foreground">updated</dt>
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

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!rule) return;
    try {
      const regionScope = parseJsonObject(regionScopeJson, "region_scope");
      const metadata = parseJsonObject(metadataJson, "metadata");
      setJsonError(null);
      patchRule.mutate({
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
      });
    } catch (error) {
      setJsonError(error instanceof Error ? error.message : String(error));
    }
  };

  if (!rule) {
    return (
      <section className="rounded-lg border bg-background p-4 text-sm text-muted-foreground">
        source rule을 선택하면 조건과 기본 action을 편집할 수 있습니다.
      </section>
    );
  }

  const source = sourceById.get(rule.source_id);
  const theme = themeById.get(rule.theme_id);

  return (
    <section className="rounded-lg border bg-background">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <div className="font-medium">Source rule editor</div>
          <div className="break-all font-mono text-xs text-muted-foreground">
            {rule.rule_id}
          </div>
        </div>
        <Button
          disabled={applyRule.isPending}
          type="button"
          variant="outline"
          onClick={() => applyRule.mutate({ ruleId: rule.rule_id })}
        >
          <PlayIcon data-icon="inline-start" />
          Apply
        </Button>
      </div>
      <form className="flex flex-col gap-3 p-4" onSubmit={save}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted-foreground">theme</dt>
          <dd>{theme?.theme_name ?? rule.theme_slug}</dd>
          <dt className="text-muted-foreground">source</dt>
          <dd>{uiLabel(source?.source_name ?? rule.source_id)}</dd>
          <dt className="text-muted-foreground">dataset</dt>
          <dd className="break-all font-mono text-xs">{rule.dataset_key}</dd>
          <dt className="text-muted-foreground">provider</dt>
          <dd>{providerLabel(rule.provider)}</dd>
        </dl>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">action</span>
            <NativeSelect
              className="w-full"
              value={defaultAction}
              onChange={(event) =>
                setDefaultAction(event.target.value as CuratedRuleAction)
              }
            >
              {RULE_ACTION_OPTIONS.map((option) => (
                <NativeSelectOption key={option} value={option}>
                  {option}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-muted-foreground">priority</span>
            <Input
              step="1"
              type="number"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
            />
          </label>
          <label className="grid gap-2 text-sm">
            <span className="text-muted-foreground">enabled</span>
            <span className="flex h-8 items-center gap-2 rounded-lg border px-2.5">
              <input
                checked={enabled}
                className="size-4"
                type="checkbox"
                onChange={(event) => setEnabled(event.target.checked)}
              />
              <span>{enabled ? "enabled" : "disabled"}</span>
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
            <span className="text-muted-foreground">category</span>
            <Input
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            />
          </label>
        </div>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">region_scope</span>
          <Textarea
            className="min-h-28 font-mono text-xs"
            value={regionScopeJson}
            onChange={(event) => setRegionScopeJson(event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">metadata</span>
          <Textarea
            className="min-h-28 font-mono text-xs"
            value={metadataJson}
            onChange={(event) => setMetadataJson(event.target.value)}
          />
        </label>
        {jsonError || patchRule.isError || applyRule.isError ? (
          <Alert variant="destructive">
            <AlertTitle>source rule 처리 실패</AlertTitle>
            <AlertDescription>
              {jsonError ??
                patchRule.error?.message ??
                applyRule.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}
        {applyRule.data ? (
          <Alert>
            <CheckIcon data-icon="inline-start" />
            <AlertTitle>source rule apply 완료</AlertTitle>
            <AlertDescription>
              {formatCount(applyRule.data.data.inserted_or_updated)}개 후보를
              반영했습니다.
            </AlertDescription>
          </Alert>
        ) : null}
        <div className="flex justify-end">
          <Button disabled={patchRule.isPending} type="submit">
            <SaveIcon data-icon="inline-start" />
            Rule 저장
          </Button>
        </div>
      </form>
    </section>
  );
}

export function CuratedFeaturesClient() {
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
  const deferredFeatureSearch = useDeferredValue(featureSearch.trim());
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
      page_size: pageSize,
      cursor: cursor ?? undefined,
    }),
    [cursor, datasetKey, includeArchived, pageSize, provider, status, themeSlug],
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

  const filteredItems = useMemo(() => {
    const items = features.data?.data.items ?? [];
    if (deferredFeatureSearch.length === 0) {
      return items;
    }
    const query = deferredFeatureSearch.toLowerCase();
    return items.filter((item) =>
      [
        item.curated_feature_id,
        item.feature_id,
        item.feature_name,
        item.display_title,
        item.source_name,
        item.provider,
        item.dataset_key,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [deferredFeatureSearch, features.data?.data.items]);

  const ruleItems = rules.data?.data.items ?? [];
  const allRuleItems = allRules.data?.data.items ?? [];
  const selectedFeature =
    filteredItems.find(
      (item) => item.curated_feature_id === selectedCuratedFeatureId,
    ) ??
    filteredItems[0] ??
    null;
  const selectedRule =
    ruleItems.find((rule) => rule.rule_id === selectedRuleId) ??
    ruleItems[0] ??
    null;
  const nextCursor = features.data?.meta.page?.next_cursor ?? null;
  const anyFeatureMutationPending =
    selectFeature.isPending || unselectFeature.isPending || archiveFeature.isPending;

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

  const selectCurated = (feature: CuratedFeature) => {
    selectFeature.mutate({
      curatedFeatureId: feature.curated_feature_id,
      body: {
        actor: "admin-ui",
        reason: "admin curated selection",
      },
    });
  };

  const unselectCurated = (feature: CuratedFeature) => {
    unselectFeature.mutate({
      curatedFeatureId: feature.curated_feature_id,
      body: {
        actor: "admin-ui",
        reason: "admin curated unselect",
      },
    });
  };

  const archiveCurated = (feature: CuratedFeature) => {
    const ok = window.confirm(`${feature.feature_name} 후보를 archive할까요?`);
    if (!ok) return;
    archiveFeature.mutate({
      curatedFeatureId: feature.curated_feature_id,
      body: {
        actor: "admin-ui",
        reason: "admin curated archive",
      },
    });
  };

  const featureColumns = useMemo<ColumnDef<CuratedFeature, unknown>[]>(
    // curated 후보는 keyset cursor 목록(next_cursor) + client text 필터 — 서버가 정렬을
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
                {feature.display_title ?? feature.feature_name}
              </div>
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
        header: "재사용",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="flex flex-col gap-1">
              <Badge variant={reusePolicyVariant(feature.reuse_policy)}>
                {feature.reuse_policy}
              </Badge>
              <Badge variant="outline">{feature.curation_relation}</Badge>
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
          return (
            <div className="flex w-52 justify-end gap-1 text-right">
              <Link
                aria-label="curated detail"
                className={cn(
                  buttonVariants({
                    variant: "outline",
                    size: "icon-sm",
                  }),
                )}
                href={curatedFeatureHref(feature.curated_feature_id)}
                onClick={(event) => event.stopPropagation()}
              >
                <EyeIcon />
              </Link>
              <Link
                aria-label="feature detail"
                className={cn(
                  buttonVariants({
                    variant: "ghost",
                    size: "icon-sm",
                  }),
                )}
                href={featureHref(feature.feature_id)}
                onClick={(event) => event.stopPropagation()}
              >
                <ExternalLinkIcon />
              </Link>
              <Button
                aria-label="미리보기"
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  setSelectedCuratedFeatureId(feature.curated_feature_id);
                }}
              >
                <EyeIcon />
              </Button>
              {feature.curation_status === "curated" ? (
                <Button
                  aria-label="unselect"
                  disabled={anyFeatureMutationPending}
                  size="icon-sm"
                  type="button"
                  variant="outline"
                  onClick={(event) => {
                    event.stopPropagation();
                    unselectCurated(feature);
                  }}
                >
                  <RotateCcwIcon />
                </Button>
              ) : (
                <Button
                  aria-label="선택"
                  disabled={anyFeatureMutationPending}
                  size="icon-sm"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    selectCurated(feature);
                  }}
                >
                  <CheckIcon />
                </Button>
              )}
              <Button
                aria-label="보관"
                disabled={anyFeatureMutationPending}
                size="icon-sm"
                type="button"
                variant="destructive"
                onClick={(event) => {
                  event.stopPropagation();
                  archiveCurated(feature);
                }}
              >
                <ArchiveIcon />
              </Button>
            </div>
          );
        },
      },
    ],
    // handlers (selectCurated/unselectCurated/archiveCurated) are stable closures;
    // re-memo only when mutation pending state used inside action cells changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [anyFeatureMutationPending],
  );

  const ruleColumns = useMemo<ColumnDef<CuratedSourceRule, unknown>[]>(
    () => [
      {
        accessorKey: "enabled",
        header: "사용",
        cell: ({ row }) => (
          <Badge variant={row.original.enabled ? "default" : "outline"}>
            {row.original.enabled ? "enabled" : "disabled"}
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
        header: "작업",
        cell: ({ row }) => (
          <Badge variant="outline">{row.original.default_action}</Badge>
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
      description="curated overlay 후보를 검토하고 source rule을 적용하며 detail snapshot을 확인합니다."
      section="관리"
      title="큐레이션 피처"
    >
      <div className="flex flex-col gap-4">
        {features.isError ||
        rules.isError ||
        allRules.isError ||
        sources.isError ||
        themes.isError ||
        selectFeature.isError ||
        unselectFeature.isError ||
        archiveFeature.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>curated admin 처리 실패</AlertTitle>
            <AlertDescription>
              {features.error?.message ??
                rules.error?.message ??
                allRules.error?.message ??
                sources.error?.message ??
                themes.error?.message ??
                selectFeature.error?.message ??
                unselectFeature.error?.message ??
                archiveFeature.error?.message}
            </AlertDescription>
          </Alert>
        ) : null}

        <section className="rounded-lg border bg-background p-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="curated feature search"
                className="pl-8"
                placeholder="feature, source, provider"
                value={featureSearch}
                onChange={(event) => setFeatureSearch(event.target.value)}
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
              <NativeSelectOption value="all">theme 전체</NativeSelectOption>
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
              <NativeSelectOption value="all">provider 전체</NativeSelectOption>
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
              <NativeSelectOption value="all">dataset 전체</NativeSelectOption>
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
              <NativeSelectOption value="all">status 전체</NativeSelectOption>
              {CURATION_STATUS_OPTIONS.map((option) => (
                <NativeSelectOption key={option} value={option}>
                  {option}
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
              <span className="whitespace-nowrap">archived 포함</span>
            </label>
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_25rem]">
          <section className="rounded-lg border bg-background">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="font-medium">후보 목록</div>
                <div className="text-xs text-muted-foreground">
                  page {formatCount(pageIndex)} · {formatCount(filteredItems.length)}개
                  표시 · page size {formatCount(pageSize)}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={pageIndex <= 1}
                  type="button"
                  variant="outline"
                  onClick={goFirstPage}
                >
                  처음
                </Button>
                <Button
                  disabled={nextCursor === null}
                  type="button"
                  variant="outline"
                  onClick={goNextPage}
                >
                  다음
                </Button>
              </div>
            </div>
            <DataTable
              columns={featureColumns}
              data={filteredItems}
              getRowId={(feature) => feature.curated_feature_id}
              isLoading={features.isLoading}
              emptyMessage="조건에 맞는 curated 후보가 없습니다."
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
                      for (const row of rows) {
                        selectFeature.mutate({
                          curatedFeatureId: row.original.curated_feature_id,
                          body: {
                            actor: "admin-ui",
                            reason: "admin curated selection",
                          },
                        });
                      }
                      setRowSelection({});
                    }}
                  >
                    <CheckIcon data-icon="inline-start" />
                    선택 채택
                  </Button>
                  <Button
                    disabled={archiveFeature.isPending}
                    size="sm"
                    type="button"
                    variant="destructive"
                    onClick={() => {
                      // bulk 보관은 되돌리기 부담이 있어 일괄 confirm 1회(단일 행
                      // archive의 per-row confirm 대체).
                      if (!window.confirm(`선택한 ${rows.length}건을 보관할까요?`)) {
                        return;
                      }
                      for (const row of rows) {
                        archiveFeature.mutate({
                          curatedFeatureId: row.original.curated_feature_id,
                          body: {
                            actor: "admin-ui",
                            reason: "admin curated archive",
                          },
                        });
                      }
                      setRowSelection({});
                    }}
                  >
                    <ArchiveIcon data-icon="inline-start" />
                    선택 보관
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
          </section>

          <div className="flex flex-col gap-4">
            <section className="rounded-lg border bg-background p-4">
              {selectedFeature ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-lg font-semibold">
                        {selectedFeature.display_title ??
                          selectedFeature.feature_name}
                      </div>
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
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
                    <dt className="text-muted-foreground">selected</dt>
                    <dd>{formatDateTime(selectedFeature.selected_at)}</dd>
                    <dt className="text-muted-foreground">content version</dt>
                    <dd>{selectedFeature.content_version}</dd>
                    <dt className="text-muted-foreground">rank</dt>
                    <dd>{selectedFeature.rank_score.toFixed(2)}</dd>
                    <dt className="text-muted-foreground">source record</dt>
                    <dd className="break-all font-mono text-xs">
                      {selectedFeature.source_record_key ?? "-"}
                    </dd>
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
                panel instead of resetting it on reselect. The editor key adds
                updated_at so it remounts and re-syncs its inputs after a
                patch/save (same curated_feature_id, new data). */}
            <CuratedPlaceSearchPanel
              feature={selectedFeature}
              key={`${selectedFeature?.curated_feature_id ?? "empty"}:place-search`}
            />
            <FeatureEditor
              feature={selectedFeature}
              key={`${selectedFeature?.curated_feature_id ?? "empty"}:${selectedFeature?.updated_at ?? ""}:editor`}
              themes={themes.data?.data.items ?? []}
            />
            <CuratedFeatureDetailPreview feature={selectedFeature} />
          </div>
        </div>

        <section className="rounded-lg border bg-background">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
            <div>
              <div className="font-medium">Source rules</div>
              <div className="text-xs text-muted-foreground">
                provider source를 curated 후보로 끌어올리는 규칙
              </div>
            </div>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
              <Link
                className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                href={`/admin/dagster?schedule=${encodeURIComponent(
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
                <NativeSelectOption value="all">enabled 전체</NativeSelectOption>
                <NativeSelectOption value="enabled">enabled</NativeSelectOption>
                <NativeSelectOption value="disabled">disabled</NativeSelectOption>
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
                emptyMessage="조건에 맞는 source rule이 없습니다."
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
      </div>
    </AdminShell>
  );
}
