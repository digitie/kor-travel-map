"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { AlertTriangleIcon, SaveIcon, SearchIcon } from "lucide-react";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import {
  useCuratedFeatureDetailSnapshot,
  useCuratedFeaturePlaceSearch,
  usePatchCuratedFeatureMutation,
  type CuratedCurationRelation,
  type CuratedFeature,
  type CuratedPlaceSearchHit,
  type CuratedReusePolicy,
  type CuratedTheme,
} from "@/api/curated";
import { JsonViewer } from "@/components/json-viewer";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import {
  FormField,
  FormSelect,
  FormTextArea,
} from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import {
  curationRelationLabel,
  enumOption,
  reusePolicyLabel,
  CURATION_RELATION_LABELS,
  REUSE_POLICY_LABELS,
} from "@/lib/curated-labels";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { withOccurrenceKeys } from "@/lib/occurrence-key";

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
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;
const PLACE_SEARCH_PROVIDERS = ["google", "kakao", "naver"] as const;
const PLACE_SEARCH_PROVIDER_LABELS: Record<string, string> = {
  google: "Google",
  kakao: "Kakao",
  naver: "Naver",
};
/** 서버 검색(q) 디바운스 — 타이핑마다 keyset 재조회하지 않게 300ms. */

function JsonBlock({ value }: { value: unknown }) {
  return <JsonViewer value={value} maxHeight="lg" copyable />;
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
                {withOccurrenceKeys(hits, (hit) =>
                  JSON.stringify([provider, hit]),
                ).map(({ key, value: hit }) => (
                  <div className="flex flex-col gap-2 px-3 py-3" key={key}>
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
