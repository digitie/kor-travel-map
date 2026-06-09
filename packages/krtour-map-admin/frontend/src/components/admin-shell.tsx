"use client";

import {
  ActivityIcon,
  AlertTriangleIcon,
  DatabaseIcon,
  ArchiveIcon,
  ClipboardListIcon,
  GitCompareArrowsIcon,
  HomeIcon,
  LinkIcon,
  ListChecksIcon,
  MapIcon,
  UploadCloudIcon,
  RefreshCwIcon,
  RadarIcon,
  RouteIcon,
  WorkflowIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "홈", icon: HomeIcon },
  { href: "/features", label: "Features", icon: MapIcon },
  { href: "/admin/features", label: "Admin features", icon: DatabaseIcon },
  {
    href: "/admin/features/change-requests",
    label: "Feature changes",
    icon: ClipboardListIcon,
  },
  { href: "/admin/issues", label: "Issues", icon: AlertTriangleIcon },
  { href: "/ops/import-jobs", label: "Import jobs", icon: ListChecksIcon },
  { href: "/ops/consistency", label: "Consistency", icon: RadarIcon },
  { href: "/ops/logs", label: "Logs", icon: ActivityIcon },
  { href: "/admin/dedup-review", label: "Dedup review", icon: GitCompareArrowsIcon },
  {
    href: "/admin/enrichment-review",
    label: "Enrichment review",
    icon: LinkIcon,
  },
  {
    href: "/admin/feature-update-requests",
    label: "Update requests",
    icon: RefreshCwIcon,
  },
  { href: "/admin/poi-cache-targets", label: "POI targets", icon: RouteIcon },
  {
    href: "/admin/offline-uploads",
    label: "Offline uploads",
    icon: UploadCloudIcon,
  },
  { href: "/admin/backups", label: "Backups", icon: ArchiveIcon },
  { href: "/admin/dagster", label: "Dagster", icon: WorkflowIcon },
  { href: "/etl", label: "ETL preview", icon: DatabaseIcon },
] as const;

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminShell({
  title,
  description,
  section,
  actions,
  children,
}: {
  title: string;
  description?: string;
  section?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const activeHref = navItems
    .filter((item) => isActive(pathname, item.href))
    .toSorted((a, b) => b.href.length - a.href.length)[0]?.href;

  return (
    <main className="min-h-screen bg-muted/30 text-foreground">
      <div className="grid min-h-screen lg:grid-cols-[16rem_1fr]">
        <aside className="border-b bg-background/95 lg:border-r lg:border-b-0">
          <div className="flex h-full flex-col gap-4 p-4">
            <Link className="flex items-center gap-2" href="/">
              <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <MapIcon className="size-4" />
              </span>
              <span className="font-semibold">krtour-map</span>
            </Link>
            <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = item.href === activeHref;
                return (
                  <Link
                    className={cn(
                      buttonVariants({
                        variant: active ? "secondary" : "ghost",
                        size: "sm",
                      }),
                      "justify-start whitespace-nowrap",
                    )}
                    href={item.href}
                    key={item.href}
                  >
                    <Icon data-icon="inline-start" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
        </aside>
        <div className="min-w-0">
          <header className="border-b bg-background">
            <div className="flex flex-col gap-3 px-5 py-4 xl:flex-row xl:items-start xl:justify-between">
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  {section ? <Badge variant="secondary">{section}</Badge> : null}
                  <span className="break-all font-mono text-xs text-muted-foreground">
                    {pathname}
                  </span>
                </div>
                <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
                {description ? (
                  <p className="max-w-4xl text-sm text-muted-foreground">
                    {description}
                  </p>
                ) : null}
              </div>
              {actions ? (
                <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>
              ) : null}
            </div>
          </header>
          <div className="p-5">{children}</div>
        </div>
      </div>
    </main>
  );
}
