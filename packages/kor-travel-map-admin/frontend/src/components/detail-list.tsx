// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react";
import Link from "next/link";

import { CopyButton } from "@/components/copy-button";
import { HelpTip } from "@/components/help-tip";
import { NULL_GLYPH } from "@/lib/format";
import { cn } from "@/lib/utils";

type DetailItem = {
  label: string;
  value: React.ReactNode;
  /** 식별자/코드 값 — mono 서체(Geist Mono, slashed-zero)로 표시. */
  mono?: boolean;
  /** true면 값 옆에 복사 버튼(문자열/숫자 값일 때만). */
  copyable?: boolean;
  /** 내부 링크 경로 — 값 전체가 링크가 된다. */
  href?: string;
  /** 라벨 옆 도움말 팝오버 내용. */
  help?: React.ReactNode;
  /** 값이 숫자/시각이면 true — tabular-nums는 기본이고, 이 플래그는 우측 정렬(inline 레이아웃)에 쓴다. */
  numeric?: boolean;
};

type DetailListProps = {
  items: DetailItem[];
  /** stacked 레이아웃의 열 수. */
  columns?: 1 | 2 | "auto";
  /**
   * `stacked`(기본): dt 위 / dd 아래, 그리드 열로 흐름.
   * `inline`: 한 행에 `라벨 | 값`(라벨 열 폭 8rem 고정) — 우측 inspector rail·상세 패널의 유일한 dl 표준(m9).
   */
  layout?: "stacked" | "inline";
  className?: string;
};

/**
 * dt/dd 상세 블록의 단일 표준(design.md §What every page MUST share). 값이 null/undefined면 `—`.
 * 숫자는 tabular-nums, 식별자는 mono. 페이지는 grid dl을 손으로 만들지 않고 이 컴포넌트를 쓴다.
 */
function DetailList({ items, columns = "auto", layout = "stacked", className }: DetailListProps) {
  const inline = layout === "inline";
  return (
    <dl
      className={cn(
        inline
          ? "grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-2"
          : "grid gap-x-4 gap-y-3",
        !inline && columns === 1 && "grid-cols-1",
        !inline && columns === 2 && "grid-cols-1 sm:grid-cols-2",
        !inline && columns === "auto" && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
        className,
      )}
      data-layout={layout}
      data-slot="detail-list"
    >
      {items.map((item) => {
        const isEmpty = item.value === null || item.value === undefined || item.value === "";
        const rawValue: React.ReactNode = isEmpty ? NULL_GLYPH : item.value;
        const copySource =
          !isEmpty && (typeof item.value === "string" || typeof item.value === "number")
            ? String(item.value)
            : null;
        let body: React.ReactNode = rawValue;
        if (item.href && !isEmpty) {
          body = (
            <Link
              className="rounded-control text-brand underline-offset-4 outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              href={item.href}
            >
              {rawValue}
            </Link>
          );
        }
        const dt = (
          <dt
            className={cn(
              "flex items-center gap-1 text-2xs font-medium text-text-secondary",
              inline && "min-h-5 pt-px",
            )}
          >
            {item.label}
            {item.help ? <HelpTip label={item.label}>{item.help}</HelpTip> : null}
          </dt>
        );
        const dd = (
          <dd
            className={cn(
              "flex min-h-5 min-w-0 items-center gap-1 text-sm break-all tabular-nums text-text-primary",
              !inline && "mt-0.5",
              item.mono && "font-mono text-xs slashed-zero",
              item.numeric && inline && "justify-end text-right",
              isEmpty && "text-text-tertiary",
            )}
          >
            {body}
            {item.copyable && copySource ? (
              <CopyButton label={item.label} value={copySource} />
            ) : null}
          </dd>
        );
        if (inline) {
          return (
            <React.Fragment key={item.label}>
              {dt}
              {dd}
            </React.Fragment>
          );
        }
        return (
          <div className="min-w-0" key={item.label}>
            {dt}
            {dd}
          </div>
        );
      })}
    </dl>
  );
}

export { DetailList };
export type { DetailItem, DetailListProps };
