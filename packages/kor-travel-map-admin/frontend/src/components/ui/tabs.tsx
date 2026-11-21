"use client";

/**
 * 공통 Tabs를 그대로 쓴다. 공통 0.2.4부터 TabsTrigger focus가 FS-7.8 단일 outline 2px·offset 2px
 * (`--kt-focus`)이므로 Map이 0.2.3 때 덧대던 focus override는 지웠다.
 */
export {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  tabsListVariants,
} from "@kor-travel/ui/tabs";
