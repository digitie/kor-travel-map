import { CopyButton } from "@/components/copy-button";
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
  if (value === null || value === undefined) return "-";
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

/** JSON/raw payload 표시 표준 블록 (§3). */
function JsonViewer({
  value,
  maxHeight = "md",
  tone = "default",
  copyable = false,
  className,
  "aria-label": ariaLabel,
}: JsonViewerProps) {
  const text = stringify(value);
  return (
    <div className={cn("relative min-w-0", className)}>
      <pre
        aria-label={ariaLabel}
        className={cn(
          "overflow-auto rounded-md border p-3 font-mono text-xs leading-relaxed break-all whitespace-pre-wrap",
          tone === "default" && "border-border bg-muted/40 text-foreground",
          tone === "destructive" &&
            "border-destructive/30 bg-destructive/5 text-destructive",
          maxHeight === "sm" && "max-h-40",
          maxHeight === "md" && "max-h-72",
          maxHeight === "lg" && "max-h-[32rem]",
        )}
      >
        {text}
      </pre>
      {copyable && text !== "-" ? (
        <div className="absolute top-2 right-2">
          <CopyButton label="JSON" value={text} />
        </div>
      ) : null}
    </div>
  );
}

export { JsonViewer };
export type { JsonViewerProps };
