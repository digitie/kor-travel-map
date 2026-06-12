"use client";

import {
  AlertTriangleIcon,
  DatabaseIcon,
  FileTextIcon,
  GitBranchIcon,
  LinkIcon,
  MapPinIcon,
  ScrollTextIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  useAdminFeatureDetail,
  useNearbyFeatures,
  type AdminFeatureDetailData,
  type NearbyFeatureSummary,
} from "@/api/features";
import { FeatureWeatherPanel } from "@/components/feature-weather-panel";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, shortId } from "@/lib/format";

function featureHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function coordLabel(lon: number | null | undefined, lat: number | null | undefined) {
  if (typeof lon === "number" && typeof lat === "number") {
    return `${lon.toFixed(5)}, ${lat.toFixed(5)}`;
  }
  return "-";
}

function distanceLabel(distanceM: number): string {
  if (distanceM >= 1000) {
    return `${(distanceM / 1000).toFixed(2)} km`;
  }
  return `${Math.round(distanceM)} m`;
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Section({
  title,
  count,
  icon: Icon,
  children,
}: {
  title: string;
  count?: number;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-background">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-2 font-medium">
          <Icon className="size-4 text-muted-foreground" />
          <span>{title}</span>
        </div>
        {typeof count === "number" ? <Badge variant="secondary">{count}</Badge> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function EmptyRow({ colSpan }: { colSpan: number }) {
  return (
    <TableRow>
      <TableCell className="h-20 text-center text-muted-foreground" colSpan={colSpan}>
        데이터가 없습니다.
      </TableCell>
    </TableRow>
  );
}

function SourcesTable({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section count={data.sources.length} icon={DatabaseIcon} title="Sources">
      <div className="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>provider</TableHead>
              <TableHead>role</TableHead>
              <TableHead>entity</TableHead>
              <TableHead>raw</TableHead>
              <TableHead>imported</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.sources.map((source) => (
              <TableRow key={source.source_record_key}>
                <TableCell>
                  <div className="font-medium">{source.provider}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {source.dataset_key}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    <Badge variant="outline">{source.source_role}</Badge>
                    {source.is_primary_source ? (
                      <Badge variant="secondary">primary</Badge>
                    ) : null}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {source.match_method} · {source.confidence}
                  </div>
                </TableCell>
                <TableCell>
                  <div>{source.source_entity_type}</div>
                  <div className="break-all font-mono text-xs text-muted-foreground">
                    {source.source_entity_id}
                  </div>
                </TableCell>
                <TableCell>
                  <details>
                    <summary className="cursor-pointer font-mono text-xs">
                      {shortId(source.source_record_key, 18)}
                    </summary>
                    <div className="mt-2 min-w-72">
                      <JsonBlock value={source.raw_data} />
                    </div>
                  </details>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(source.imported_at)}
                </TableCell>
              </TableRow>
            ))}
            {data.sources.length === 0 ? <EmptyRow colSpan={5} /> : null}
          </TableBody>
        </Table>
      </div>
    </Section>
  );
}

function IssuesTable({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section count={data.issues.length} icon={AlertTriangleIcon} title="Issues">
      <div className="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>status</TableHead>
              <TableHead>severity</TableHead>
              <TableHead>type</TableHead>
              <TableHead>message</TableHead>
              <TableHead>detected</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.issues.map((issue) => (
              <TableRow key={issue.issue_id}>
                <TableCell>
                  <StatusBadge status={issue.status} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={issue.severity} />
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {issue.violation_type}
                </TableCell>
                <TableCell className="max-w-md">
                  <div className="truncate">{issue.message}</div>
                  {Object.keys(issue.payload).length > 0 ? (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-xs text-muted-foreground">
                        payload
                      </summary>
                      <JsonBlock value={issue.payload} />
                    </details>
                  ) : null}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(issue.detected_at)}
                </TableCell>
              </TableRow>
            ))}
            {data.issues.length === 0 ? <EmptyRow colSpan={5} /> : null}
          </TableBody>
        </Table>
      </div>
    </Section>
  );
}

function OverridesTable({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section count={data.overrides.length} icon={GitBranchIcon} title="Overrides">
      <div className="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>status</TableHead>
              <TableHead>field</TableHead>
              <TableHead>value</TableHead>
              <TableHead>reason</TableHead>
              <TableHead>created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.overrides.map((override) => (
              <TableRow key={override.override_id}>
                <TableCell>
                  <StatusBadge status={override.status} />
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {override.field_path}
                </TableCell>
                <TableCell>
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground">
                      override
                    </summary>
                    <div className="mt-2 min-w-72">
                      <JsonBlock
                        value={{
                          source: override.source_value,
                          override: override.override_value,
                        }}
                      />
                    </div>
                  </details>
                </TableCell>
                <TableCell>{override.reason ?? "-"}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(override.created_at)}
                </TableCell>
              </TableRow>
            ))}
            {data.overrides.length === 0 ? <EmptyRow colSpan={5} /> : null}
          </TableBody>
        </Table>
      </div>
    </Section>
  );
}

function FilesTable({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section count={data.files.length} icon={FileTextIcon} title="Files">
      <div className="overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>role</TableHead>
              <TableHead>object</TableHead>
              <TableHead>provider</TableHead>
              <TableHead>size</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.files.map((file) => (
              <TableRow key={file.file_id}>
                <TableCell>
                  <Badge variant="outline">{file.role}</Badge>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {file.file_type}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="break-all font-mono text-xs">{file.object_key}</div>
                  {file.public_url ? (
                    <Link
                      className="mt-1 inline-flex text-xs text-primary underline-offset-4 hover:underline"
                      href={file.public_url}
                      rel="noreferrer"
                      target="_blank"
                    >
                      public_url
                    </Link>
                  ) : null}
                </TableCell>
                <TableCell>
                  <div>{file.provider ?? "-"}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {file.dataset_key ?? "-"}
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {file.byte_size ?? "-"}
                </TableCell>
              </TableRow>
            ))}
            {data.files.length === 0 ? <EmptyRow colSpan={4} /> : null}
          </TableBody>
        </Table>
      </div>
    </Section>
  );
}

function HistoryPanel({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section
      count={data.versions.length + data.change_requests.length}
      icon={ScrollTextIcon}
      title="History"
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>version</TableHead>
                <TableHead>origin</TableHead>
                <TableHead>change</TableHead>
                <TableHead>created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.versions.map((version) => (
                <TableRow key={`${version.feature_id}:${version.version}`}>
                  <TableCell className="font-mono">{version.version}</TableCell>
                  <TableCell>{version.origin}</TableCell>
                  <TableCell>{version.change_kind}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(version.created_at)}
                  </TableCell>
                </TableRow>
              ))}
              {data.versions.length === 0 ? <EmptyRow colSpan={4} /> : null}
            </TableBody>
          </Table>
        </div>
        <div className="overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>request</TableHead>
                <TableHead>action</TableHead>
                <TableHead>status</TableHead>
                <TableHead>created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.change_requests.map((request) => (
                <TableRow key={request.request_id}>
                  <TableCell className="font-mono text-xs">
                    {shortId(request.request_id, 12)}
                  </TableCell>
                  <TableCell>{request.action}</TableCell>
                  <TableCell>
                    <StatusBadge status={request.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(request.created_at)}
                  </TableCell>
                </TableRow>
              ))}
              {data.change_requests.length === 0 ? <EmptyRow colSpan={4} /> : null}
            </TableBody>
          </Table>
        </div>
      </div>
    </Section>
  );
}

function NearbyPanel({
  featureId,
  feature,
}: {
  featureId: string;
  feature: AdminFeatureDetailData["feature"];
}) {
  const hasCoord = typeof feature.lon === "number" && typeof feature.lat === "number";
  const nearby = useNearbyFeatures(
    hasCoord
      ? {
          lon: feature.lon as number,
          lat: feature.lat as number,
          radius_m: 3000,
          page_size: 12,
          sort: "distance",
          status: ["active"],
        }
      : null,
  );
  const items = (nearby.data?.data.items ?? [])
    .filter((item: NearbyFeatureSummary) => item.feature_id !== featureId)
    .slice(0, 10);

  return (
    <Section count={items.length} icon={MapPinIcon} title="Nearby">
      {nearby.isLoading ? <Skeleton className="h-36 w-full" /> : null}
      {nearby.isError ? (
        <Alert variant="destructive">
          <AlertTitle>nearby 호출 실패</AlertTitle>
          <AlertDescription>{nearby.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {!hasCoord ? (
        <div className="text-sm text-muted-foreground">좌표가 없습니다.</div>
      ) : null}
      {items.length > 0 ? (
        <div className="overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>feature</TableHead>
                <TableHead>kind</TableHead>
                <TableHead>distance</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.feature_id}>
                  <TableCell>
                    <Link
                      className="font-medium text-primary underline-offset-4 hover:underline"
                      href={featureHref(item.feature_id)}
                    >
                      {item.name}
                    </Link>
                    <div className="font-mono text-xs text-muted-foreground">
                      {shortId(item.feature_id, 16)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{item.kind}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {distanceLabel(item.distance_m)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      {hasCoord && !nearby.isLoading && !nearby.isError && items.length === 0 ? (
        <div className="text-sm text-muted-foreground">주변 feature가 없습니다.</div>
      ) : null}
    </Section>
  );
}

function RawPanels({ data }: { data: AdminFeatureDetailData }) {
  return (
    <Section icon={LinkIcon} title="Raw">
      <div className="flex flex-col gap-3">
        <details open>
          <summary className="cursor-pointer text-sm font-medium">detail</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.detail} />
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">raw_refs</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.raw_refs} />
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">urls</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.urls} />
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">address</summary>
          <div className="mt-2">
            <JsonBlock value={data.feature.address} />
          </div>
        </details>
      </div>
    </Section>
  );
}

export function FeatureDetailView({ featureId }: { featureId: string }) {
  const detail = useAdminFeatureDetail(featureId);
  const data = detail.data?.data;
  const feature = data?.feature;

  if (detail.isLoading) {
    return <Skeleton className="h-[36rem] w-full" />;
  }

  if (detail.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>feature 상세 조회 실패</AlertTitle>
        <AlertDescription>{detail.error.message}</AlertDescription>
      </Alert>
    );
  }

  if (!data || !feature) {
    return null;
  }

  const primarySource = data.sources.find((source) => source.is_primary_source);

  return (
    <div className="flex flex-col gap-4" data-testid="feature-detail-view">
      <section className="rounded-lg border bg-background p-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-2">
              <StatusBadge status={feature.status} />
              <Badge variant="outline">{feature.kind}</Badge>
              <Badge variant="outline">{feature.category}</Badge>
              <Badge variant="secondary">{feature.data_origin}</Badge>
            </div>
            <h2 className="mt-3 break-keep text-xl font-semibold">{feature.name}</h2>
            <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
              {feature.feature_id}
            </div>
          </div>
          <dl className="grid min-w-64 grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">coord</dt>
            <dd className="font-mono">{coordLabel(feature.lon, feature.lat)}</dd>
            <dt className="text-muted-foreground">sigungu</dt>
            <dd>{feature.sigungu_code ?? "-"}</dd>
            <dt className="text-muted-foreground">updated</dt>
            <dd>{formatDateTime(feature.updated_at)}</dd>
            <dt className="text-muted-foreground">provider</dt>
            <dd>{primarySource?.provider ?? "-"}</dd>
          </dl>
        </div>
      </section>

      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_28rem]">
        <div className="flex min-w-0 flex-col gap-4">
          <SourcesTable data={data} />
          <IssuesTable data={data} />
          <OverridesTable data={data} />
          <HistoryPanel data={data} />
          <FilesTable data={data} />
        </div>
        <aside className="flex min-w-0 flex-col gap-4">
          <FeatureWeatherPanel featureId={featureId} />
          <NearbyPanel feature={feature} featureId={featureId} />
          <RawPanels data={data} />
        </aside>
      </div>
    </div>
  );
}
