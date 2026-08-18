// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react";

import { toneBadgeVariant } from "@/components/status-badge-variants";
import { Badge } from "@/components/ui/badge";
import { NULL_GLYPH } from "@/lib/format";
import {
  httpStatusTone,
  statusLabel,
  toneFor,
  type StatusTone,
} from "@/lib/status-label";
import { cn } from "@/lib/utils";

/**
 * 상태 배지 계열 — 톤은 전부 `src/lib/status-label.ts`의 단일 tone 테이블에서 읽는다(M20/M28).
 * 색 + dot + 한글 라벨을 함께 써 의미가 색에만 실리지 않는다. enum 값은 raw로 렌더하지 않는다.
 *
 *  - `StatusBadge`     lifecycle/작업 상태(pending/running/failed …).
 *  - `LevelBadge`      로그 level·severity(critical/error → destructive, warning, info, debug → neutral).
 *  - `HttpStatusBadge` HTTP status code(2xx neutral · 3xx info · 4xx warning · 5xx destructive), mono.
 *  - `LiveBadge`       live 연결/갱신 상태 — `role="status"`로 변화를 조용히 알린다(M37).
 */

type StatusBadgeProps = Omit<React.ComponentProps<"span">, "children"> & {
  status: string | null | undefined;
  /** tone 테이블 대신 강제할 tone(예: 도메인 규칙으로 이미 결정된 경우). */
  tone?: StatusTone;
  /** 표시 라벨을 직접 줄 때(기본은 statusLabel(status)). */
  label?: React.ReactNode;
  /** 앞의 상태 dot 숨김. */
  hideDot?: boolean;
};

export function StatusBadge({
  status,
  tone,
  label,
  hideDot = false,
  className,
  ...props
}: StatusBadgeProps) {
  const resolvedTone = tone ?? toneFor(status);
  const text = label ?? (status == null ? NULL_GLYPH : statusLabel(status));
  return (
    <Badge
      className={cn("gap-1.5", className)}
      data-tone={resolvedTone}
      variant={toneBadgeVariant(resolvedTone)}
      {...props}
    >
      {hideDot ? null : (
        <span className="size-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
      )}
      {text}
    </Badge>
  );
}

/** 로그 level / issue severity 배지 — 톤 테이블의 level 키(critical·error·warning·info·debug)를 읽는다. */
export function LevelBadge({
  level,
  ...props
}: Omit<StatusBadgeProps, "status"> & { level: string | null | undefined }) {
  return <StatusBadge status={level} {...props} />;
}

/** severity 별칭 — LevelBadge와 동일 규칙. */
export const SeverityBadge = LevelBadge;

/** HTTP status code 배지 — 코드 자체를 mono로 표기, 톤은 httpStatusTone. */
export function HttpStatusBadge({
  code,
  className,
  ...props
}: Omit<StatusBadgeProps, "status" | "label" | "tone"> & {
  code: number | string | null | undefined;
}) {
  const text = code === null || code === undefined || code === "" ? NULL_GLYPH : String(code);
  return (
    <StatusBadge
      className={cn("font-mono", className)}
      hideDot
      label={text}
      status={text === NULL_GLYPH ? null : text}
      tone={httpStatusTone(code)}
      {...props}
    />
  );
}

/**
 * live 연결/자동 갱신 상태 배지. 상태 문자열(live/connecting/reconnecting/polling/disabled/
 * unauthorized/unavailable …)로 톤을 정하고 라벨은 호출부의 사전(`label`)을 우선한다.
 * 갱신 시 재정렬·깜빡임 없이 텍스트만 바뀐다.
 */
export function LiveBadge({
  state,
  label,
  ...props
}: Omit<StatusBadgeProps, "status"> & { state: string | null | undefined }) {
  return (
    <StatusBadge
      aria-live="polite"
      label={label}
      role="status"
      status={state}
      {...props}
    />
  );
}
