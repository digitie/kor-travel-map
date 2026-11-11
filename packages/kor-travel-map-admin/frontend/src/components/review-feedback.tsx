"use client";
import type { ReactNode } from "react";
import {
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Alert,
  AlertTitle,
  AlertDescription,
  AlertActions,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function ReviewDialogHeading({
  title,
  description,
  onClose,
}: {
  title: ReactNode;
  description: ReactNode;
  onClose: () => void;
}) {
  return (
    <DialogHeader>
      <div className="flex min-w-0 flex-col gap-0.5">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </div>
      <Button size="sm" type="button" variant="ghost" onClick={onClose}>
        닫기
      </Button>
    </DialogHeader>
  );
}

export function ReviewDetailLoading() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      <Skeleton className="h-control w-full" />
      <Skeleton className="h-80 w-full" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    </div>
  );
}

export function ReviewMapLegend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-2xs font-medium text-text-secondary">
      <span>위치 비교</span>
      <span className="flex items-center gap-1">
        <span aria-hidden="true" className="size-2 rounded-full bg-compare-a" />
        A
      </span>
      <span className="flex items-center gap-1">
        <span aria-hidden="true" className="size-2 rounded-full bg-compare-b" />
        B
      </span>
    </div>
  );
}

export function ReviewErrorAlert({
  title,
  lines,
  pending,
  onRetry,
}: {
  title: ReactNode;
  lines: string[];
  pending: boolean;
  onRetry: () => void;
}) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        {lines.map((line) => (
          <p key={line}>{line}</p>
        ))}
        <p>잠시 후 다시 시도하세요.</p>
      </AlertDescription>
      <AlertActions>
        <Button
          loading={pending}
          size="sm"
          type="button"
          variant="outline"
          onClick={onRetry}
        >
          다시 시도
        </Button>
      </AlertActions>
    </Alert>
  );
}
