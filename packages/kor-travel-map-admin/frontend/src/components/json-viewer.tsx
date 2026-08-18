// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import { CopyButton } from "@/components/copy-button";
import { NULL_GLYPH } from "@/lib/format";
import { cn } from "@/lib/utils";

type JsonViewerProps = {
  value: unknown;
  maxHeight?: "sm" | "md" | "lg";
  tone?: "default" | "destructive";
  /** true면 우상단에 복사 버튼. */
  copyable?: boolean;
  className?: string;
  "aria-label"?: string;
};

function stringify(value: unknown): string {
  if (value === null || value === undefined) return NULL_GLYPH;
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/**
 * JSON/raw payload 표시 표준 블록 — 그룹 안의 유일한 JSON 렌더러(M42).
 * Geist Mono 12px, `--surface-subtle` 위 hairline, 값 없음은 `—`.
 */
function JsonViewer({
  value,
  maxHeight = "md",
  tone = "default",
  copyable = false,
  className,
  "aria-label": ariaLabel,
}: JsonViewerProps) {
  const text = stringify(value);
  const isEmpty = text === NULL_GLYPH;
  return (
    <div className={cn("relative min-w-0", className)} data-slot="json-viewer">
      <pre
        aria-label={ariaLabel}
        className={cn(
          "overflow-auto rounded-control border p-3 font-mono text-2xs leading-relaxed break-all whitespace-pre-wrap slashed-zero",
          tone === "default" && "border-border bg-surface-subtle text-text-primary",
          tone === "destructive" && "border-destructive bg-destructive-tint text-destructive",
          isEmpty && "text-text-tertiary",
          copyable && !isEmpty && "pr-10",
          maxHeight === "sm" && "max-h-40",
          maxHeight === "md" && "max-h-72",
          maxHeight === "lg" && "max-h-[32rem]",
        )}
      >
        {text}
      </pre>
      {copyable && !isEmpty ? (
        <div className="absolute top-2 right-2">
          <CopyButton label="JSON" value={text} />
        </div>
      ) : null}
    </div>
  );
}

export { JsonViewer };
export type { JsonViewerProps };
