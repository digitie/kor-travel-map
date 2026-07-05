import * as React from "react";
import Link from "next/link";

import { CopyButton } from "@/components/copy-button";
import { HelpTip } from "@/components/help-tip";
import { cn } from "@/lib/utils";

type DetailItem = {
  label: string;
  value: React.ReactNode;
  /** 식별자/코드 값 — mono 서체로 표시. */
  mono?: boolean;
  /** true면 값 옆에 복사 버튼(문자열 값일 때만). */
  copyable?: boolean;
  /** 내부 링크 경로 — 값 전체가 링크가 된다. */
  href?: string;
  /** 라벨 옆 도움말 팝오버 내용. */
  help?: React.ReactNode;
};

type DetailListProps = {
  items: DetailItem[];
  columns?: 1 | 2 | "auto";
  className?: string;
};

/**
 * dt/dd 상세 블록의 단일 표준 (§3). 값이 null/undefined면 "-"로 표기.
 */
function DetailList({ items, columns = "auto", className }: DetailListProps) {
  return (
    <dl
      className={cn(
        "grid gap-x-3 gap-y-2",
        columns === 1 && "grid-cols-1",
        columns === 2 && "grid-cols-1 sm:grid-cols-2",
        columns === "auto" && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
        className,
      )}
    >
      {items.map((item) => {
        const rawValue = item.value ?? "-";
        const copySource =
          typeof item.value === "string" || typeof item.value === "number"
            ? String(item.value)
            : null;
        let body: React.ReactNode = rawValue;
        if (item.href && item.value !== null && item.value !== undefined) {
          body = (
            <Link
              className="text-primary underline-offset-2 hover:underline"
              href={item.href}
            >
              {rawValue}
            </Link>
          );
        }
        return (
          <div className="min-w-0" key={item.label}>
            <dt className="flex items-center gap-1 text-xs text-muted-foreground">
              {item.label}
              {item.help ? <HelpTip label={item.label}>{item.help}</HelpTip> : null}
            </dt>
            <dd
              className={cn(
                "mt-1 flex min-h-5 items-center gap-1 text-sm break-all",
                item.mono && "font-mono text-xs",
              )}
            >
              {body}
              {item.copyable && copySource ? (
                <CopyButton label={item.label} value={copySource} />
              ) : null}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export { DetailList };
export type { DetailItem, DetailListProps };
