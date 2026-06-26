"use client";

import {
  ActivityIcon,
  AlertTriangleIcon,
  DatabaseIcon,
  ArchiveIcon,
  ClipboardListIcon,
  GaugeIcon,
  GitCompareArrowsIcon,
  HomeIcon,
  LinkIcon,
  ListChecksIcon,
  MapIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  UploadCloudIcon,
  RefreshCwIcon,
  RadarIcon,
  RouteIcon,
  LogOutIcon,
  SettingsIcon,
  SparklesIcon,
  WorkflowIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button-variants";
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
  {
    href: "/admin/curated-features",
    label: "Curated features",
    icon: SparklesIcon,
  },
  { href: "/admin/issues", label: "Issues", icon: AlertTriangleIcon },
  { href: "/ops/import-jobs", label: "Import jobs", icon: ListChecksIcon },
  { href: "/ops/providers", label: "Providers", icon: GaugeIcon },
  { href: "/ops/consistency", label: "Consistency", icon: RadarIcon },
  { href: "/ops/logs", label: "Logs", icon: ActivityIcon },
  { href: "/admin/dedup-reviews", label: "Dedup reviews", icon: GitCompareArrowsIcon },
  {
    href: "/admin/enrichment-reviews",
    label: "Enrichment reviews",
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
  { href: "/admin/settings", label: "Settings", icon: SettingsIcon },
  { href: "/etl", label: "ETL preview", icon: DatabaseIcon },
] as const;

const SIDEBAR_COLLAPSED_KEY = "kor-travel-map:sidebar-collapsed";

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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  });
  const activeHref = navItems
    .filter((item) => isActive(pathname, item.href))
    .toSorted((a, b) => b.href.length - a.href.length)[0]?.href;

  const toggleSidebar = () => {
    setSidebarCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      return next;
    });
  };

  return (
    <main className="min-h-screen bg-surface-page text-text-primary">
      <div
        className={cn(
          "grid min-h-screen min-w-0",
          sidebarCollapsed
            ? "lg:grid-cols-[4.75rem_1fr]"
            : "lg:grid-cols-[17rem_1fr]",
        )}
      >
        <aside className="min-w-0 border-b border-surface-muted bg-card shadow-[var(--shadow-card)] lg:border-r lg:border-b-0">
          <div
            className={cn(
              "flex h-full min-w-0 flex-col gap-5 p-5",
              sidebarCollapsed && "lg:items-center lg:p-3",
            )}
          >
            <div
              className={cn(
                "flex w-full items-center justify-between gap-2",
                sidebarCollapsed && "lg:flex-col",
              )}
            >
              <Link
                className={cn(
                  "flex min-w-0 items-center gap-2 text-text-primary",
                  sidebarCollapsed && "lg:justify-center",
                )}
                href="/"
                title="kor-travel-map"
              >
                <span className="flex size-10 items-center justify-center rounded-xl bg-brand-tint text-brand">
                  <MapIcon className="size-4" />
                </span>
                <span
                  className={cn(
                    "truncate text-[14px] font-bold",
                    sidebarCollapsed && "lg:hidden",
                  )}
                >
                  kor-travel-map
                </span>
              </Link>
              <button
                aria-label={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"}
                className={cn(
                  buttonVariants({ variant: "ghost", size: "icon-sm" }),
                  "hidden lg:inline-flex",
                )}
                title={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"}
                type="button"
                onClick={toggleSidebar}
              >
                {sidebarCollapsed ? <PanelLeftOpenIcon /> : <PanelLeftCloseIcon />}
              </button>
            </div>
            <nav
              className={cn(
                "flex max-w-full gap-1 overflow-x-auto lg:max-h-[calc(100vh-6rem)] lg:flex-col lg:overflow-y-auto lg:pr-1",
                sidebarCollapsed && "lg:items-center lg:pr-0",
              )}
            >
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = item.href === activeHref;
                return (
                  <Link
                    aria-label={sidebarCollapsed ? item.label : undefined}
                    className={cn(
                      buttonVariants({
                        variant: active ? "secondary" : "ghost",
                        size: "sm",
                      }),
                      "justify-start whitespace-nowrap",
                      sidebarCollapsed && "lg:size-10 lg:justify-center lg:p-0",
                    )}
                    href={item.href}
                    key={item.href}
                    title={item.label}
                  >
                    <Icon data-icon="inline-start" />
                    <span className={cn(sidebarCollapsed && "lg:hidden")}>
                      {item.label}
                    </span>
                  </Link>
                );
              })}
            </nav>
            <ButtonLogout collapsed={sidebarCollapsed} />
          </div>
        </aside>
        <div className="min-w-0">
          <header className="px-6 pt-6">
            <div className="flex flex-col gap-4 rounded-2xl bg-card p-6 shadow-[var(--shadow-card)] ring-1 ring-border/70 xl:flex-row xl:items-start xl:justify-between">
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  {section ? <Badge variant="secondary">{section}</Badge> : null}
                  <span className="break-all font-mono text-[12px] text-text-secondary">
                    {pathname}
                  </span>
                </div>
                <h1 className="text-[24px] leading-snug font-bold">{title}</h1>
                {description ? (
                  <p className="max-w-4xl text-[13px] leading-normal text-text-secondary">
                    {description}
                  </p>
                ) : null}
              </div>
              {actions ? (
                <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>
              ) : null}
            </div>
          </header>
          <div className="px-6 py-6">{children}</div>
        </div>
      </div>
    </main>
  );
}

function ButtonLogout({ collapsed }: { collapsed: boolean }) {
  return (
    <button
      aria-label={collapsed ? "로그아웃" : undefined}
      className={cn(
        buttonVariants({ variant: "ghost", size: "sm" }),
        "mt-auto justify-start text-text-secondary",
        collapsed && "lg:size-10 lg:justify-center lg:p-0",
      )}
      title="로그아웃"
      type="button"
      onClick={() => void logout()}
    >
      <LogOutIcon data-icon="inline-start" />
      <span className={cn(collapsed && "lg:hidden")}>로그아웃</span>
    </button>
  );
}

async function logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } finally {
    window.location.assign("/login");
  }
}
