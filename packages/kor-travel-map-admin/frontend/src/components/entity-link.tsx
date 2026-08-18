// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
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

/**
 * prose 링크 레시피 (design.md §CTA voice): brand 잉크, hover 에 underline, focus 는 단일 outline.
 * id 링크는 mono + tabular-nums, 외부 링크는 ExternalLinkIcon + 새 탭 (§2 배치 규칙).
 */
const entityLinkClass =
  "rounded-control text-brand underline-offset-4 transition-[color] duration-fast ease-out hover:text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus active:text-brand-hover";

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
  const monoClassName = children === undefined ? "font-mono tabular-nums" : null;
  if (href === null) {
    // 링크를 만들 수 없는 엔티티는 식별자 텍스트로만 — 항상 mono(기존 계약).
    return (
      <span className={cn("font-mono tabular-nums", className)}>{label}</span>
    );
  }
  const external = kind === "dagsterRun";
  const linkClassName = cn(entityLinkClass, monoClassName, className);
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
          <ExternalLinkIcon
            aria-hidden="true"
            className="ml-1 inline size-3.5 align-text-top"
          />
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
