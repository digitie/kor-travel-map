// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react";

import { cn } from "@/lib/utils";

/** `<option>` — 팝업 리스트가 토큰 표면(card/ink)으로 렌더되도록 고정(시스템 색 리터럴 금지). */
function NativeSelectOption({
  className,
  ...props
}: React.ComponentProps<"option">) {
  return (
    <option
      data-slot="native-select-option"
      className={cn("bg-card text-text-primary", className)}
      {...props}
    />
  );
}

export { NativeSelectOption };
