"use client";

export {
  Card,
  CardHeader,
  CardFooter,
  CardAction,
  CardDescription,
  CardContent,
} from "@kor-travel/ui/card";

import type { ComponentProps } from "react";
import { CardTitle as CommonCardTitle } from "@kor-travel/ui/card";

/** 기존 Map의 section 제목 탐색 계약을 공통 registry 표면에서도 유지한다. */
export function CardTitle({
  role = "heading",
  "aria-level": level = 2,
  ...props
}: ComponentProps<typeof CommonCardTitle>) {
  return <CommonCardTitle role={role} aria-level={level} {...props} />;
}
