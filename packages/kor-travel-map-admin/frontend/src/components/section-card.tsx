// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
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
  /** 헤더 우측 액션 영역(새로고침 버튼 등) — primary ≤ 1. */
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  size?: "default" | "sm";
  /** 제목의 heading level(기본 2). 페이지 안의 하위 패널이면 3. */
  headingLevel?: 2 | 3 | 4;
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
};

/**
 * 페이지 섹션의 유일한 컨테이너(design.md §Macrostructure — containment 1층).
 * 제목 행 + 아래 hairline(카드 폭 전체) + flat body. 이 안에 Card/bordered box를 다시 넣지 않는다:
 * 요약 dl은 DetailList, 선택 목록은 SelectableRow, 표는 DataTable(Card 안에서는 자동 flush).
 */
function SectionCard({
  title,
  description,
  actions,
  footer,
  size = "sm",
  headingLevel = 2,
  className,
  contentClassName,
  children,
}: SectionCardProps) {
  return (
    <Card className={className} size={size}>
      <CardHeader className="border-b">
        <CardTitle aria-level={headingLevel}>{title}</CardTitle>
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
