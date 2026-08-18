// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app
import type { ReactNode } from "react";

import type { components } from "@/api/types";
import { DetailList, type DetailItem } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { JsonViewer } from "@/components/json-viewer";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { formatCount, formatDateTime } from "@/lib/format";

type FeatureCurationMembership = components["schemas"]["AdminCurationItemView"];
type FeatureObservation = components["schemas"]["FeatureObservationView"];
type AdminFeatureSource = components["schemas"]["AdminFeatureDetailSourceRecord"];
type FeatureSourceAssociation = FeatureObservation | AdminFeatureSource;

/** 접이식 상세 블록 — summary는 12px/500, 열리면 DetailList/JsonViewer(그룹 유일 JSON 렌더러). */
function Disclosure({
  summary,
  defaultOpen = false,
  children,
}: {
  summary: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="group/details" open={defaultOpen}>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-control py-1 text-xs font-medium text-text-secondary outline-none select-none hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className="w-3 text-text-tertiary group-open/details:hidden">
          +
        </span>
        <span aria-hidden="true" className="hidden w-3 text-text-tertiary group-open/details:inline">
          −
        </span>
        {summary}
      </summary>
      <div className="flex flex-col gap-2 pt-1">{children}</div>
    </details>
  );
}

function CurationDetails({ item }: { item: FeatureCurationMembership }) {
  const items: DetailItem[] = [
    { label: "collection", value: item.collection_key, mono: true },
    { label: "collection_id", value: item.collection_id, mono: true },
    { label: "item_id", value: item.curation_item_id, mono: true },
    { label: "theme", value: `${item.theme_group} · ${item.theme_slug}` },
    { label: "external_item_id", value: item.external_item_id, mono: true },
    { label: "source_record", value: item.source_record_key ?? null, mono: true },
    { label: "place", value: item.place_name || null },
    { label: "address_hint", value: item.address_hint ?? null },
    { label: "relation", value: item.curation_relation, mono: true },
    { label: "reuse", value: item.reuse_policy, mono: true },
    { label: "sort_order", value: item.sort_order, numeric: true },
    { label: "created", value: formatDateTime(item.created_at) },
    { label: "updated", value: formatDateTime(item.updated_at) },
    { label: "archived", value: item.archived_at ? formatDateTime(item.archived_at) : null },
  ];
  return (
    <Disclosure summary="membership 전체 정보">
      <DetailList items={items} layout="inline" />
      <div className="flex flex-col gap-1">
        <span className="text-2xs font-medium text-text-secondary">metadata</span>
        <JsonViewer maxHeight="sm" value={item.metadata} />
      </div>
    </Disclosure>
  );
}

function SourceDetails({ item }: { item: FeatureSourceAssociation }) {
  const firstSeenAt = "first_seen_at" in item ? item.first_seen_at : null;
  const entityLastSeenAt =
    "entity_last_seen_at" in item ? item.entity_last_seen_at : null;
  const isCurrent = "is_current" in item ? item.is_current : true;

  const items: DetailItem[] = [
    {
      label: "entity type/id",
      value: `${item.source_entity_type}:${item.source_entity_id}`,
      mono: true,
    },
    { label: "entity key", value: item.source_entity_key, mono: true },
    { label: "record key", value: item.source_record_key, mono: true },
    { label: "payload hash", value: item.raw_payload_hash, mono: true },
    { label: "first seen", value: firstSeenAt ? formatDateTime(firstSeenAt) : null },
    {
      label: "entity last seen",
      value: entityLastSeenAt ? formatDateTime(entityLastSeenAt) : null,
    },
    { label: "observed", value: formatDateTime(item.observed_at) },
    { label: "imported", value: formatDateTime(item.imported_at) },
    { label: "linked", value: formatDateTime(item.linked_at) },
    { label: "expires", value: item.expires_at ? formatDateTime(item.expires_at) : null },
    { label: "current", value: isCurrent ? "현재 관측" : "과거 관측" },
  ];
  return (
    <Disclosure summary="source 전체 정보">
      <DetailList items={items} layout="inline" />
    </Disclosure>
  );
}

function AssociationSection({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <h3 className="text-sm leading-snug font-semibold text-text-primary">{title}</h3>
        <span
          aria-label={`${title} ${formatCount(count)}건`}
          className="text-xs text-text-secondary tabular-nums"
        >
          {formatCount(count)}
        </span>
      </div>
      {children}
    </section>
  );
}

/**
 * feature의 큐레이션 소속·제공기관 관측 목록(design.md detail — hairline으로 나눈 flat 목록,
 * 항목 박스 없음). 상태는 StatusBadge 1개, 나머지 metadata는 muted/mono 텍스트(M22).
 */
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
    <div className="flex flex-col gap-5" data-testid="feature-associations">
      <AssociationSection count={curationItems.length} title="큐레이션 소속">
        {curationItems.length === 0 ? (
          <EmptyState
            description="큐레이션 collection에서 이 feature를 연결하면 표시됩니다."
            size="sm"
            title="연결된 큐레이션이 없습니다."
          />
        ) : (
          <ul className="divide-y divide-border">
            {curationItems.map((item) => (
              <li className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0" key={item.curation_item_id}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-medium text-text-primary">{item.theme_name}</span>
                  {item.edition_key ? (
                    <span className="text-xs text-text-secondary tabular-nums">
                      {item.edition_key}
                    </span>
                  ) : null}
                  <StatusBadge status={item.status} />
                </div>
                <p className="text-sm text-text-primary">{item.title}</p>
                <p className="text-xs text-text-secondary">
                  {item.source_url ? (
                    <a
                      className="rounded-control text-brand underline-offset-4 outline-none hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
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
                <p className="font-mono text-2xs break-all text-text-secondary slashed-zero">
                  {item.external_item_id}
                </p>
                {item.item_title || item.item_summary ? (
                  <p className="text-xs text-text-primary">
                    {[item.item_title, item.item_summary].filter(Boolean).join(" · ")}
                  </p>
                ) : null}
                <CurationDetails item={item} />
              </li>
            ))}
          </ul>
        )}
      </AssociationSection>

      <AssociationSection count={observationItems.length} title="제공기관 현재 관측">
        {observationItems.length === 0 ? (
          <EmptyState
            description="provider 적재가 이 feature에 연결되면 표시됩니다."
            size="sm"
            title="연결된 관측값이 없습니다."
          />
        ) : (
          <ul className="divide-y divide-border">
            {observationItems.map((item) => (
              <li className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0" key={item.source_entity_key}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-medium text-text-primary">{item.provider}</span>
                  <span className="font-mono text-2xs text-text-secondary slashed-zero">
                    {item.dataset_key}
                  </span>
                  <Badge variant={item.source_role === "primary" ? "secondary" : "outline"}>
                    {item.source_role}
                  </Badge>
                </div>
                <p className="font-mono text-xs break-all text-text-primary slashed-zero">
                  {item.source_entity_type}:{item.source_entity_id}
                </p>
                <DetailList
                  items={[
                    { label: "entity", value: item.source_entity_key, mono: true },
                    { label: "record", value: item.source_record_key, mono: true },
                    { label: "match", value: `${item.match_method} · ${item.confidence}` },
                    { label: "fetched", value: formatDateTime(item.fetched_at) },
                  ]}
                  layout="inline"
                />
                <SourceDetails item={item} />
                <Disclosure defaultOpen={!compact} summary="raw payload">
                  <JsonViewer maxHeight="sm" value={item.raw_data} />
                </Disclosure>
              </li>
            ))}
          </ul>
        )}
      </AssociationSection>
    </div>
  );
}
