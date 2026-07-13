import type { components } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";

type FeatureCurationMembership = components["schemas"]["CurationItemView"];
type FeatureObservation = components["schemas"]["FeatureObservationView"];
type AdminFeatureSource = components["schemas"]["AdminFeatureDetailSourceRecord"];
type FeatureSourceAssociation = FeatureObservation | AdminFeatureSource;

function JsonValue({ value }: { value: unknown }) {
  return (
    <pre className="max-h-56 overflow-auto rounded-md bg-muted p-2 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function OptionalValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <>-</>;
  return <>{String(value)}</>;
}

function CurationDetails({ item }: { item: FeatureCurationMembership }) {
  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-xs font-medium">membership 전체 정보</summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="text-muted-foreground">collection</dt>
        <dd className="break-all font-mono">{item.collection_key}</dd>
        <dt className="text-muted-foreground">collection_id</dt>
        <dd className="break-all font-mono">{item.collection_id}</dd>
        <dt className="text-muted-foreground">item_id</dt>
        <dd className="break-all font-mono">{item.curation_item_id}</dd>
        <dt className="text-muted-foreground">theme</dt>
        <dd>{item.theme_group} · {item.theme_slug}</dd>
        <dt className="text-muted-foreground">external_item_id</dt>
        <dd className="break-all font-mono">{item.external_item_id}</dd>
        <dt className="text-muted-foreground">source_record</dt>
        <dd className="break-all font-mono">
          <OptionalValue value={item.source_record_key} />
        </dd>
        <dt className="text-muted-foreground">place</dt>
        <dd>{item.place_name || "-"}</dd>
        <dt className="text-muted-foreground">address_hint</dt>
        <dd>{item.address_hint ?? "-"}</dd>
        <dt className="text-muted-foreground">relation</dt>
        <dd>{item.curation_relation}</dd>
        <dt className="text-muted-foreground">reuse</dt>
        <dd>{item.reuse_policy}</dd>
        <dt className="text-muted-foreground">sort_order</dt>
        <dd>{item.sort_order}</dd>
        <dt className="text-muted-foreground">created</dt>
        <dd>{formatDateTime(item.created_at)}</dd>
        <dt className="text-muted-foreground">updated</dt>
        <dd>{formatDateTime(item.updated_at)}</dd>
        <dt className="text-muted-foreground">archived</dt>
        <dd>{item.archived_at ? formatDateTime(item.archived_at) : "-"}</dd>
      </dl>
      <div className="mt-2">
        <div className="mb-1 text-xs font-medium">metadata</div>
        <JsonValue value={item.metadata} />
      </div>
    </details>
  );
}

function SourceDetails({ item }: { item: FeatureSourceAssociation }) {
  const firstSeenAt = "first_seen_at" in item ? item.first_seen_at : null;
  const entityLastSeenAt =
    "entity_last_seen_at" in item ? item.entity_last_seen_at : item.last_seen_at;
  const recordLastSeenAt =
    "record_last_seen_at" in item ? item.record_last_seen_at : item.last_seen_at;
  const isCurrent = "is_current" in item ? item.is_current : true;

  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-xs font-medium">source 전체 정보</summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="text-muted-foreground">entity type/id</dt>
        <dd className="break-all font-mono">
          {item.source_entity_type}:{item.source_entity_id}
        </dd>
        <dt className="text-muted-foreground">entity key</dt>
        <dd className="break-all font-mono">{item.source_entity_key}</dd>
        <dt className="text-muted-foreground">record key</dt>
        <dd className="break-all font-mono">{item.source_record_key}</dd>
        <dt className="text-muted-foreground">source version</dt>
        <dd><OptionalValue value={item.source_version} /></dd>
        <dt className="text-muted-foreground">raw coord</dt>
        <dd className="font-mono">
          <OptionalValue value={item.raw_longitude} />, {" "}
          <OptionalValue value={item.raw_latitude} />
        </dd>
        <dt className="text-muted-foreground">payload hash</dt>
        <dd className="break-all font-mono">{item.raw_payload_hash}</dd>
        <dt className="text-muted-foreground">first seen</dt>
        <dd>{firstSeenAt ? formatDateTime(firstSeenAt) : "-"}</dd>
        <dt className="text-muted-foreground">entity last seen</dt>
        <dd>{formatDateTime(entityLastSeenAt)}</dd>
        <dt className="text-muted-foreground">record last seen</dt>
        <dd>{formatDateTime(recordLastSeenAt)}</dd>
        <dt className="text-muted-foreground">imported</dt>
        <dd>{formatDateTime(item.imported_at)}</dd>
        <dt className="text-muted-foreground">linked</dt>
        <dd>{formatDateTime(item.linked_at)}</dd>
        <dt className="text-muted-foreground">expires</dt>
        <dd>{item.expires_at ? formatDateTime(item.expires_at) : "-"}</dd>
        <dt className="text-muted-foreground">current</dt>
        <dd>{isCurrent ? "yes" : "no"}</dd>
      </dl>
    </details>
  );
}

export function FeatureAssociations({
  curations,
  observations,
  compact = false,
}: {
  curations?: readonly FeatureCurationMembership[];
  observations?: readonly FeatureSourceAssociation[];
  compact?: boolean;
}) {
  const curationItems = curations ?? [];
  const observationItems = observations ?? [];

  return (
    <div className="flex flex-col gap-4" data-testid="feature-associations">
      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">큐레이션 소속</h3>
          <Badge variant="secondary">{curationItems.length}</Badge>
        </div>
        {curationItems.length === 0 ? (
          <p className="text-sm text-muted-foreground">연결된 큐레이션이 없습니다.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {curationItems.map((item) => (
              <article
                className="rounded-md border p-3 text-sm"
                key={item.curation_item_id}
              >
                <div className="flex flex-wrap items-center gap-1">
                  <strong>{item.theme_name}</strong>
                  {item.edition_key ? (
                    <Badge variant="outline">{item.edition_key}</Badge>
                  ) : null}
                  <Badge variant="outline">{item.status}</Badge>
                </div>
                <p className="mt-1 font-medium">{item.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.source_url ? (
                    <a
                      className="underline-offset-4 hover:underline"
                      href={item.source_url}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {item.source_name ?? "출처 링크"}
                    </a>
                  ) : (
                    item.source_name ?? "출처 없음"
                  )}
                  {item.provider ? ` · ${item.provider}` : ""}
                  {item.dataset_key ? `/${item.dataset_key}` : ""}
                </p>
                <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                  {item.external_item_id}
                </p>
                {item.item_title || item.item_summary ? (
                  <p className="mt-2 text-xs">
                    {[item.item_title, item.item_summary].filter(Boolean).join(" · ")}
                  </p>
                ) : null}
                <CurationDetails item={item} />
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">제공기관 현재 관측</h3>
          <Badge variant="secondary">{observationItems.length}</Badge>
        </div>
        {observationItems.length === 0 ? (
          <p className="text-sm text-muted-foreground">연결된 관측값이 없습니다.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {observationItems.map((item) => (
              <article
                className="rounded-md border p-3 text-sm"
                key={item.source_entity_key}
              >
                <div className="flex flex-wrap items-center gap-1">
                  <strong>{item.provider}</strong>
                  <Badge variant="outline">{item.dataset_key}</Badge>
                  <Badge variant="outline">{item.source_role}</Badge>
                  {item.is_primary_source ? <Badge>primary</Badge> : null}
                </div>
                <p className="mt-1">
                  {item.raw_name ?? `${item.source_entity_type}:${item.source_entity_id}`}
                </p>
                {item.raw_address ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {item.raw_address}
                  </p>
                ) : null}
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs">
                  <dt className="text-muted-foreground">entity</dt>
                  <dd className="break-all font-mono">{item.source_entity_key}</dd>
                  <dt className="text-muted-foreground">record</dt>
                  <dd className="break-all font-mono">{item.source_record_key}</dd>
                  <dt className="text-muted-foreground">match</dt>
                  <dd>{item.match_method} · {item.confidence}</dd>
                  <dt className="text-muted-foreground">fetched</dt>
                  <dd>{formatDateTime(item.fetched_at)}</dd>
                </dl>
                <SourceDetails item={item} />
                <details className="mt-2" open={!compact}>
                  <summary className="cursor-pointer text-xs font-medium">
                    raw payload
                  </summary>
                  <JsonValue value={item.raw_data} />
                </details>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
