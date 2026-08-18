// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
/**
 * 표시용 포맷 유틸(design.md §Copy).
 *
 * - 빈 값 글리프는 `NULL_GLYPH`(U+2014 em dash) 하나만 쓴다 — `-`(hyphen) 금지.
 * - `formatCount`는 미지 값(null/undefined) 또는 loading 중에 `—`를 돌려준다.
 *   숫자를 0으로 coalesce하지 않는다(가짜 0 = "all clear"로 읽힘, M36).
 */

/** 빈 값/미지 값 글리프. `-`가 아니라 em dash. */
export const NULL_GLYPH = "—";

const dateTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "short",
  timeStyle: "medium",
});

const compactNumberFormatter = new Intl.NumberFormat("ko-KR");

export function formatDateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return NULL_GLYPH;
  }
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return NULL_GLYPH;
  }
  return dateTimeFormatter.format(date);
}

export interface FormatCountOptions {
  /** query가 아직 resolve되지 않았으면 true — 값이 있어도 `—`를 돌려준다. */
  loading?: boolean;
}

/**
 * 정수/실수를 ko-KR 천 단위 구분으로 표기한다. null/undefined/NaN 또는 `loading`이면
 * `—`(NULL_GLYPH) — 절대 가짜 0을 만들지 않는다.
 */
export function formatCount(
  value: number | null | undefined,
  options: FormatCountOptions = {},
): string {
  if (options.loading) {
    return NULL_GLYPH;
  }
  if (value === null || value === undefined || Number.isNaN(value)) {
    return NULL_GLYPH;
  }
  return compactNumberFormatter.format(value);
}

/**
 * 긴 식별자를 앞 `size`자로 자른다. 빈 값은 `—`.
 * 말줄임은 ASCII `...`를 유지한다 — e2e/consistency-drilldown.spec.ts가
 * `slice(0, 12) + "..."`를 단언하므로 그 계약이 바뀌기 전까지 U+2026로 바꾸지 않는다.
 */
export function shortId(value: string | null | undefined, size = 12): string {
  if (!value) {
    return NULL_GLYPH;
  }
  return value.length > size ? `${value.slice(0, size)}...` : value;
}
