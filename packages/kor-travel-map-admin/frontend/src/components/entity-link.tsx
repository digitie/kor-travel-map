import Link from "next/link";
import { ExternalLinkIcon } from "lucide-react";

import { hrefFor, type EntityKind, type EntityParams } from "@/lib/entity-href";
import { cn } from "@/lib/utils";

/**
 * 관리 화면 엔티티 딥링크의 단일 URL 테이블 (§2/§3).
 * 모든 크로스링크는 이 컴포넌트로만 렌더링해 경로가 한 곳에서 관리되게 한다.
 */


type EntityLinkProps = {
  kind: EntityKind;
  id: string | number;
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
  const label = children ?? String(id);
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

export { EntityLink };
