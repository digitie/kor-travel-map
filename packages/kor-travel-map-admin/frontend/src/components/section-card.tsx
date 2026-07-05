import * as React from "react";

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

type SectionCardProps = {
  title: React.ReactNode;
  /** 제목 아래 한 문장 보조 설명(불필요하면 생략). */
  description?: React.ReactNode;
  /** 헤더 우측 액션 영역(새로고침 버튼 등). */
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  size?: "default" | "sm";
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
};

/**
 * 페이지 섹션의 단일 표준 표면 (§6 look&feel canon).
 * 회색 평면 박스(`rounded-lg border bg-background`) 대신 ui/card 크롬을 쓴다.
 */
function SectionCard({
  title,
  description,
  actions,
  footer,
  size = "sm",
  className,
  contentClassName,
  children,
}: SectionCardProps) {
  return (
    <Card className={className} size={size}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
        {actions ? <CardAction>{actions}</CardAction> : null}
      </CardHeader>
      <CardContent className={cn("space-y-4", contentClassName)}>
        {children}
      </CardContent>
      {footer ? <CardFooter>{footer}</CardFooter> : null}
    </Card>
  );
}

export { SectionCard };
export type { SectionCardProps };
