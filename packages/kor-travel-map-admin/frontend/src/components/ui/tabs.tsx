"use client";

import { TabsTrigger as CommonTabsTrigger } from "@kor-travel/ui/tabs";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export { Tabs, TabsList, TabsContent } from "@kor-travel/ui/tabs";
export { tabsListVariants } from "@kor-travel/ui/tabs";

/**
 * 공통 0.2.3 TabsTrigger recipe는 아직 shadcn focus(테두리 색 + 3px 반투명 ring + 1px outline)를
 * 한꺼번에 그려 Tab 포커스 때 테두리가 굵고 겹쳐 보인다(FS-7.8, 버튼과 같은 증상). Button recipe와
 * 같은 단일 outline 2px·offset 2px로 덮는다 — 공통 className 병합(twMerge)이 뒤의 값을 남긴다.
 * 링은 전환 대상이 아니므로 `transition-all`도 색 전환으로 좁힌다.
 */
const SINGLE_FOCUS_OUTLINE =
  "transition-[color,background-color] focus-visible:border-transparent focus-visible:ring-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function TabsTrigger({
  className,
  ...props
}: ComponentProps<typeof CommonTabsTrigger>) {
  return (
    <CommonTabsTrigger
      className={cn(SINGLE_FOCUS_OUTLINE, className)}
      {...props}
    />
  );
}

export { TabsTrigger };
