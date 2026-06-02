"use client";

import {
  ActivityIcon,
  DatabaseIcon,
  MapIcon,
  MoveDiagonal2Icon,
  RotateCcwIcon,
} from "lucide-react";
import Link from "next/link";

import { useHealth, useVersion } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useMapStore } from "@/state/map";

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function HomePageClient() {
  const health = useHealth();
  const version = useVersion();
  const viewport = useMapStore((state) => state.viewport);
  const resetViewport = useMapStore((state) => state.resetViewport);
  const setViewport = useMapStore((state) => state.setViewport);

  const healthState = health.data?.status ?? (health.isError ? "error" : "loading");

  return (
    <main className="min-h-screen bg-muted/30">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-6">
        <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">Admin</Badge>
              <Badge variant={health.isError ? "destructive" : "outline"}>
                {healthState}
              </Badge>
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">
              krtour-map admin
            </h1>
            <p className="max-w-2xl text-sm text-muted-foreground">
              feature 운영과 provider 변환 확인을 위한 내부망 관리 화면입니다.
            </p>
          </div>
          <nav className="flex flex-wrap gap-2">
            <Link
              className={cn(buttonVariants({ variant: "outline" }))}
              href="/features"
            >
              <MapIcon data-icon="inline-start" />
              Feature 지도
            </Link>
            <Link
              className={cn(buttonVariants({ variant: "outline" }))}
              href="/etl"
            >
              <DatabaseIcon data-icon="inline-start" />
              ETL preview
            </Link>
          </nav>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Backend health</CardTitle>
              <CardDescription>FastAPI liveness</CardDescription>
              <CardAction>
                <ActivityIcon className="text-muted-foreground" />
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {health.isLoading ? <Skeleton className="h-24 w-full" /> : null}
              {health.isError ? (
                <p className="text-sm text-destructive">
                  health 호출 실패: {health.error.message}
                </p>
              ) : null}
              {health.data ? <JsonBlock value={health.data} /> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Versions</CardTitle>
              <CardDescription>backend package versions</CardDescription>
              <CardAction>
                <DatabaseIcon className="text-muted-foreground" />
              </CardAction>
            </CardHeader>
            <CardContent>
              {version.isLoading ? <Skeleton className="h-24 w-full" /> : null}
              {version.isError ? (
                <p className="text-sm text-destructive">
                  version 호출 실패: {version.error.message}
                </p>
              ) : null}
              {version.data ? (
                <dl
                  className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm"
                  data-testid="version-list"
                >
                  <dt className="text-muted-foreground">admin</dt>
                  <dd className="font-mono">{version.data.debug_ui}</dd>
                  <dt className="text-muted-foreground">krtour.map</dt>
                  <dd className="font-mono">{version.data.krtour_map}</dd>
                </dl>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Map viewport</CardTitle>
              <CardDescription>Zustand UI state</CardDescription>
              <CardAction>
                <MapIcon className="text-muted-foreground" />
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <JsonBlock value={viewport} />
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    setViewport({
                      lon: viewport.lon + 0.1,
                      lat: viewport.lat + 0.1,
                    })
                  }
                >
                  <MoveDiagonal2Icon data-icon="inline-start" />
                  미세 이동
                </Button>
                <Button type="button" variant="ghost" onClick={resetViewport}>
                  <RotateCcwIcon data-icon="inline-start" />
                  기본값으로 초기화
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}
