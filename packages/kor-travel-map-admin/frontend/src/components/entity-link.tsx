import Link from "next/link";
import { ExternalLinkIcon } from "lucide-react";

import { DAGSTER_UI_URL } from "@/api/dagster";
import { cn } from "@/lib/utils";

/**
 * 관리 화면 엔티티 딥링크의 단일 URL 테이블 (§2/§3).
 * 모든 크로스링크는 이 컴포넌트로만 렌더링해 경로가 한 곳에서 관리되게 한다.
 */

type EntityKind =
  | "feature"
  | "importJob"
  | "updateRequest"
  | "provider"
  | "issue"
  | "dagsterRun"
  | "loadBatch"
  | "changeRequest";

type EntityParams = Record<string, string | null | undefined>;

function withQuery(path: string, params?: EntityParams): string {
  if (!params) return path;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, value);
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

/**
 * kind별 링크 경로. `dagsterRun`은 외부 Dagster UI라 base(env)까지 포함한
 * 절대 URL을 돌려준다(없으면 null → 호출부는 링크 대신 텍스트 유지).
 */
function hrefFor(
  kind: EntityKind,
  id: string,
  params?: EntityParams,
): string | null {
  switch (kind) {
    case "feature":
      return `/features/${encodeURIComponent(id)}`;
    case "importJob":
      return `/ops/import-jobs/${encodeURIComponent(id)}`;
    case "updateRequest":
      return `/admin/features/update-requests/${encodeURIComponent(id)}`;
    case "provider":
      // id = provider명; dataset_key 등은 params로.
      return withQuery("/ops/providers", { provider: id, ...params });
    case "issue":
      return withQuery("/admin/issues", { ...params });
    case "loadBatch":
      return withQuery("/ops/import-jobs", { load_batch_id: id, ...params });
    case "changeRequest":
      return withQuery("/admin/features/change-requests", {
        request_id: id,
        ...params,
      });
    case "dagsterRun":
      // import-job-detail의 기존 규약과 동일: public Dagster UI /runs/{id}.
      return `${DAGSTER_UI_URL.replace(/\/+$/, "")}/runs/${encodeURIComponent(id)}`;
  }
}

type EntityLinkProps = {
  kind: EntityKind;
  id: string;
  params?: EntityParams;
  /** 새 탭에서 열기(비교 작업 흐름용). 외부 링크는 항상 새 탭. */
  newTab?: boolean;
  className?: string;
  children?: React.ReactNode;
};

/** id 링크는 mono, 외부 링크는 ExternalLinkIcon + 새 탭 (§2 배치 규칙). */
function EntityLink({
  kind,
  id,
  params,
  newTab = false,
  className,
  children,
}: EntityLinkProps) {
  const href = hrefFor(kind, id, params);
  const label = children ?? id;
  if (href === null) {
    return <span className={cn("font-mono", className)}>{label}</span>;
  }
  const external = kind === "dagsterRun";
  const linkClassName = cn(
    "text-primary underline-offset-2 hover:underline",
    children === undefined && "font-mono",
    className,
  );
  if (external || newTab) {
    return (
      <a
        className={linkClassName}
        href={href}
        rel="noreferrer"
        target="_blank"
      >
        {label}
        {external ? (
          <ExternalLinkIcon aria-hidden className="ml-1 inline size-3.5 align-text-top" />
        ) : null}
      </a>
    );
  }
  return (
    <Link className={linkClassName} href={href}>
      {label}
    </Link>
  );
}

export { EntityLink, hrefFor };
export type { EntityKind, EntityLinkProps, EntityParams };
