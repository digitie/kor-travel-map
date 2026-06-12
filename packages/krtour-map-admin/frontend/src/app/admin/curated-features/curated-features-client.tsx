"use client";

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

import {
  useAdminCuratedFeatures,
  useAdminCuratedSourceRules,
  useAdminCuratedSources,
  useAdminCuratedThemes,
  useApplyCuratedSourceRuleMutation,
  useArchiveCuratedFeatureMutation,
  usePatchCuratedFeatureMutation,
  usePatchCuratedSourceRuleMutation,
  useSelectCuratedFeatureMutation,
  useTripmateCopySnapshot,
  useUnselectCuratedFeatureMutation,
  type AdminCuratedFeaturesParams,
  type AdminCuratedSourceRulesParams,
  type CuratedFeature,
  type CuratedFeatureStatus,
  type CuratedRuleAction,
  type CuratedSource,
  type CuratedSourceRule,
  type CuratedTheme,
  type CuratedTripmateCopyPolicy,
  type CuratedTripmateRelation,
} from "@/api/curated";
import { AdminShell } from "@/components/admin-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const CURATION_STATUS_OPTIONS: CuratedFeatureStatus[] = [
  "candidate",
  "curated",
  "rejected",
  "archived",
];
const COPY_POLICY_OPTIONS: CuratedTripmateCopyPolicy[] = [
  "copy_allowed",
  "copy_blocked",
  "manual_review",
];
const TRIPMATE_RELATION_OPTIONS: CuratedTripmateRelation[] = [
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

function copyPolicyVariant(policy: string) {
  if (policy === "copy_allowed") return "default";
  if (policy === "copy_blocked") return "destructive";
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

function FeatureEditor({ feature }: { feature: CuratedFeature | null }) {
  const patchFeature = usePatchCuratedFeatureMutation();
  const [title, setTitle] = useState(feature?.display_title ?? "");
  const [summary, setSummary] = useState(feature?.display_summary ?? "");
  const [rankScore, setRankScore] = useState(String(feature?.rank_score ?? 0));
  const [copyPolicy, setCopyPolicy] =
    useState<CuratedTripmateCopyPolicy>(
      (feature?.tripmate_copy_policy as CuratedTripmateCopyPolicy | undefined) ??
        "manual_review",
    );
  const [relation, setRelation] =
    useState<CuratedTripmateRelation>(
      (feature?.tripmate_relation as CuratedTripmateRelation | undefined) ??
        "nearby_option",
    );

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!feature) return;
    patchFeature.mutate({
      curatedFeatureId: feature.curated_feature_id,
      body: {
        display_title: title.trim().length > 0 ? title.trim() : null,
        display_summary: summary.trim().length > 0 ? summary.trim() : null,
        rank_score: Number(rankScore),
        tripmate_copy_policy: copyPolicy,
        tripmate_relation: relation,
      },
    });
  };

  if (!feature) {
    return (
      <section className="rounded-lg border bg-background p-4 text-sm text-muted-foreground">
        후보를 선택하면 display text와 TripMate copy 속성을 편집할 수 있습니다.
      </section>
    );
  }

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
            <span className="text-muted-foreground">copy policy</span>
            <NativeSelect
              className="w-full"
              value={copyPolicy}
              onChange={(event) =>
                setCopyPolicy(event.target.value as CuratedTripmateCopyPolicy)
              }
            >
              {COPY_POLICY_OPTIONS.map((option) => (
                <NativeSelectOption key={option} value={option}>
                  {option}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
        </div>
        <label className="grid gap-1 text-sm">
          <span className="text-muted-foreground">TripMate relation</span>
          <NativeSelect
            className="w-full"
            value={relation}
            onChange={(event) =>
              setRelation(event.target.value as CuratedTripmateRelation)
            }
          >
            {TRIPMATE_RELATION_OPTIONS.map((option) => (
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

function TripmateCopyPreview({ feature }: { feature: CuratedFeature | null }) {
  const snapshot = useTripmateCopySnapshot(feature?.curated_feature_id ?? null);
  const data = snapshot.data?.data;

  return (
    <section className="rounded-lg border bg-background">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div>
          <div className="font-medium">TripMate copy preview</div>
          <div className="text-xs text-muted-foreground">
            copy snapshot과 curated_plan_pois item 미리보기
          </div>
        </div>
        {data ? (
          <Badge variant="outline">etag {shortId(data.etag, 10)}</Badge>
        ) : null}
      </div>
      {!feature ? (
        <div className="p-4 text-sm text-muted-foreground">
          후보를 선택하면 copy snapshot을 조회합니다.
        </div>
      ) : null}
      {snapshot.isLoading ? <Skeleton className="m-4 h-40" /> : null}
      {snapshot.isError ? (
        <Alert className="m-4" variant="destructive">
          <AlertTitle>copy preview 조회 실패</AlertTitle>
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
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>order</TableHead>
                <TableHead>relation</TableHead>
                <TableHead>feature</TableHead>
                <TableHead>memo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((item) => (
                <TableRow key={item.curated_feature_item_id}>
                  <TableCell>{item.sort_order}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{item.relation}</Badge>
                  </TableCell>
                  <TableCell className="max-w-[12rem] whitespace-normal break-all font-mono text-xs">
                    {item.feature_id}
                  </TableCell>
                  <TableCell className="max-w-[12rem] whitespace-normal">
                    {item.memo ?? "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <details>
            <summary className="cursor-pointer text-sm font-medium">plan</summary>
            <JsonBlock value={data.plan} />
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
          <dd>{source?.source_name ?? rule.source_id}</dd>
          <dt className="text-muted-foreground">dataset</dt>
          <dd className="break-all font-mono text-xs">{rule.dataset_key}</dd>
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
            <span className="text-muted-foreground">place_kind</span>
            <Input
              value={placeKind}
              onChange={(event) => setPlaceKind(event.target.value)}
            />
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
  const [featureSearch, setFeatureSearch] = useState("");
  const deferredFeatureSearch = useDeferredValue(featureSearch.trim());
  const [selectedCuratedFeatureId, setSelectedCuratedFeatureId] =
    useState<string | null>(null);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [ruleEnabled, setRuleEnabled] = useState<EnabledFilter>("all");

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

  const resetCursor = () => setCursor(null);
  const refresh = () => {
    void features.refetch();
    void rules.refetch();
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

  return (
    <AdminShell
      actions={
        <Button
          disabled={
            features.isFetching ||
            rules.isFetching ||
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
      description="curated overlay 후보를 검토하고 source rule을 적용하며 TripMate copy snapshot을 확인합니다."
      section="Admin"
      title="Curated features"
    >
      <div className="flex flex-col gap-4">
        {features.isError ||
        rules.isError ||
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
                setProvider(event.target.value);
                setDatasetKey("all");
                resetCursor();
              }}
            >
              <NativeSelectOption value="all">provider 전체</NativeSelectOption>
              {providerOptions.map((option) => (
                <NativeSelectOption key={option} value={option}>
                  {option}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="dataset filter"
              className="w-full"
              value={datasetKey}
              onChange={(event) => {
                setDatasetKey(event.target.value);
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
                  {formatCount(filteredItems.length)}개 표시, page size{" "}
                  {formatCount(pageSize)}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={cursor === null}
                  type="button"
                  variant="outline"
                  onClick={() => setCursor(null)}
                >
                  처음
                </Button>
                <Button
                  disabled={nextCursor === null}
                  type="button"
                  variant="outline"
                  onClick={() => setCursor(nextCursor)}
                >
                  다음
                </Button>
              </div>
            </div>
            {features.isLoading ? <Skeleton className="m-4 h-80" /> : null}
            {!features.isLoading && filteredItems.length === 0 ? (
              <div className="p-8 text-center text-sm text-muted-foreground">
                조건에 맞는 curated 후보가 없습니다.
              </div>
            ) : null}
            {filteredItems.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>status</TableHead>
                    <TableHead>feature</TableHead>
                    <TableHead>source</TableHead>
                    <TableHead>theme</TableHead>
                    <TableHead>copy</TableHead>
                    <TableHead>updated</TableHead>
                    <TableHead className="w-44 text-right">actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.map((feature) => {
                    const selected =
                      feature.curated_feature_id ===
                      selectedFeature?.curated_feature_id;
                    return (
                      <TableRow
                        className="cursor-pointer"
                        data-state={selected ? "selected" : undefined}
                        key={feature.curated_feature_id}
                        onClick={() =>
                          setSelectedCuratedFeatureId(
                            feature.curated_feature_id,
                          )
                        }
                      >
                        <TableCell>
                          <Badge variant={featureStatusVariant(feature.curation_status)}>
                            {feature.curation_status}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-[20rem] whitespace-normal">
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
                        </TableCell>
                        <TableCell className="max-w-[16rem] whitespace-normal">
                          <div>{feature.source_name}</div>
                          <div className="break-all font-mono text-xs text-muted-foreground">
                            {feature.provider}:{feature.dataset_key}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div>{feature.theme_name}</div>
                          <div className="text-xs text-muted-foreground">
                            {feature.theme_group}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1">
                            <Badge
                              variant={copyPolicyVariant(
                                feature.tripmate_copy_policy,
                              )}
                            >
                              {feature.tripmate_copy_policy}
                            </Badge>
                            <Badge variant="outline">
                              {feature.tripmate_relation}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell>{formatDateTime(feature.updated_at)}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
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
                              aria-label="preview"
                              size="icon-sm"
                              type="button"
                              variant="ghost"
                              onClick={(event) => {
                                event.stopPropagation();
                                setSelectedCuratedFeatureId(
                                  feature.curated_feature_id,
                                );
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
                                aria-label="select"
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
                              aria-label="archive"
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
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            ) : null}
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
                      {selectedFeature.curation_status}
                    </Badge>
                  </div>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
                    <dt className="text-muted-foreground">selected</dt>
                    <dd>{formatDateTime(selectedFeature.selected_at)}</dd>
                    <dt className="text-muted-foreground">copy version</dt>
                    <dd>{selectedFeature.copy_version}</dd>
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
            <FeatureEditor
              feature={selectedFeature}
              key={selectedFeature?.curated_feature_id ?? "empty-feature"}
            />
            <TripmateCopyPreview feature={selectedFeature} />
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
          <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_32rem]">
            <div className="rounded-lg border">
              {rules.isLoading ? <Skeleton className="m-4 h-64" /> : null}
              {!rules.isLoading && ruleItems.length === 0 ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  조건에 맞는 source rule이 없습니다.
                </div>
              ) : null}
              {ruleItems.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>enabled</TableHead>
                      <TableHead>theme</TableHead>
                      <TableHead>source</TableHead>
                      <TableHead>action</TableHead>
                      <TableHead>priority</TableHead>
                      <TableHead>updated</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {ruleItems.map((rule) => {
                      const source = sourceById.get(rule.source_id);
                      const selected = rule.rule_id === selectedRule?.rule_id;
                      return (
                        <TableRow
                          className="cursor-pointer"
                          data-state={selected ? "selected" : undefined}
                          key={rule.rule_id}
                          onClick={() => setSelectedRuleId(rule.rule_id)}
                        >
                          <TableCell>
                            <Badge variant={rule.enabled ? "default" : "outline"}>
                              {rule.enabled ? "enabled" : "disabled"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div>{rule.theme_slug}</div>
                            <div className="text-xs text-muted-foreground">
                              {shortId(rule.theme_id, 10)}
                            </div>
                          </TableCell>
                          <TableCell className="max-w-[18rem] whitespace-normal">
                            <div>{source?.source_name ?? rule.source_id}</div>
                            <div className="break-all font-mono text-xs text-muted-foreground">
                              {rule.provider}:{rule.dataset_key}
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">{rule.default_action}</Badge>
                          </TableCell>
                          <TableCell>{rule.priority}</TableCell>
                          <TableCell>{formatDateTime(rule.updated_at)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              ) : null}
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
