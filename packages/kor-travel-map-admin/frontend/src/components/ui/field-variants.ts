/* Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app */

/**
 * 라벨 recipe 1종(M43): 13.5px 500 ink-2 — Field가 invalid면 destructive, disabled면 opacity 55.
 * FieldLabel/FieldTitle뿐 아니라 FilterField·request-dialog처럼 직접 `<label>`/`<span>`을 조합하는
 * 곳도 이 문자열만 쓴다. 컴포넌트 파일(`field.tsx`)은 컴포넌트만 export한다(react-refresh
 * only-export-components) — recipe는 button-variants.ts와 같은 방식으로 여기 둔다.
 */
export const fieldLabelClassName =
  "text-xs leading-snug font-medium text-text-secondary group-data-[invalid=true]/field:text-destructive group-data-[disabled=true]/field:opacity-55";
