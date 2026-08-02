"use client";

import {
  ActivityIcon,
  AlertTriangleIcon,
  DatabaseIcon,
  ArchiveIcon,
  FolderTreeIcon,
  GitCompareArrowsIcon,
  HomeIcon,
  LayersIcon,
  LinkIcon,
  ListChecksIcon,
  MapIcon,
  MapPinnedIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  UploadCloudIcon,
  RadarIcon,
  RouteIcon,
  LogOutIcon,
  SettingsIcon,
  SparklesIcon,
  WorkflowIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { withOccurrenceKeys } from "@/lib/occurrence-key";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { buttonVariants } from "@/components/ui/button-variants";
import { HelpTip } from "@/components/help-tip";
import { publishAdminLogout } from "@/lib/admin-auth-events";
import { cn } from "@/lib/utils";

/**
 * 작업 지향 nav 그룹 (§1) — nav·섹션 배지·브레드크럼 라벨의 단일 정본.
 * 그룹 헤더는 비링크이며 href 18개는 존치하는 canonical 화면만 가리킨다.
 */
const NAV_GROUPS = [
  {
    group: null,
    badge: "개요",
    items: [{ href: "/", label: "홈", icon: HomeIcon }],
  },
  {
    group: "Feature 관리",
    badge: "Feature 관리",
    items: [
      { href: "/features", label: "Feature 지도", icon: MapIcon },
      { href: "/admin/features", label: "Feature 목록", icon: DatabaseIcon },
      {
        href: "/admin/features/change-reviews",
        label: "Feature 검수",
        icon: ListChecksIcon,
      },
      {
        href: "/admin/features/dedup-reviews",
        label: "중복 검토",
        icon: GitCompareArrowsIcon,
      },
      {
        href: "/admin/features/enrichment-reviews",
        label: "보강 검토",
        icon: LinkIcon,
      },
      { href: "/admin/issues", label: "이슈", icon: AlertTriangleIcon },
      {
        href: "/admin/features/curated",
        label: "큐레이션 관리",
        icon: SparklesIcon,
      },
      { href: "/curated-features", label: "큐레이션 지도", icon: MapPinnedIcon },
    ],
  },
  {
    group: "수집 파이프라인",
    badge: "수집 파이프라인",
    items: [
      { href: "/ops/pipeline", label: "파이프라인", icon: WorkflowIcon },
      { href: "/ops/datasets", label: "데이터셋", icon: LayersIcon },
      {
        href: "/admin/offline-uploads",
        label: "오프라인 업로드",
        icon: UploadCloudIcon,
      },
      {
        href: "/admin/poi-cache-targets",
        label: "POI 캐시 대상",
        icon: RouteIcon,
      },
      {
        href: "/ops/cache-target-streams",
        label: "캐시 전파",
        icon: ActivityIcon,
      },
    ],
  },
  {
    group: "모니터링",
    badge: "모니터링",
    items: [
      { href: "/ops/logs", label: "운영 로그", icon: ActivityIcon },
      { href: "/ops/consistency", label: "정합성 점검", icon: RadarIcon },
    ],
  },
  {
    group: "시스템",
    badge: "시스템",
    items: [
      { href: "/admin/files", label: "파일 관리", icon: FolderTreeIcon },
      { href: "/admin/backups", label: "백업", icon: ArchiveIcon },
      { href: "/admin/settings", label: "설정", icon: SettingsIcon },
    ],
  },
] as const;

const navItems = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, badge: group.badge })),
);

const SIDEBAR_COLLAPSED_KEY = "kor-travel-map:sidebar-collapsed";

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export type AdminBreadcrumb = { label: string; href?: string };

export function AdminShell({
  title,
  description,
  section,
  breadcrumbs,
  help,
  actions,
  children,
}: {
  title: string;
  description?: string;
  /** 명시 오버라이드 — 생략 시 NAV_GROUPS longest-prefix로 유도(§1). */
  section?: string;
  breadcrumbs?: AdminBreadcrumb[];
  help?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const activeNavItemRef = useRef<HTMLAnchorElement | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  });
  const activeItem = navItems
    .filter((item) => isActive(pathname, item.href))
    .toSorted((a, b) => b.href.length - a.href.length)[0];
  const activeHref = activeItem?.href;
  const sectionBadge = section ?? activeItem?.badge;

  useEffect(() => {
    if (typeof window === "undefined" || window.innerWidth >= 1024) return;
    activeNavItemRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [activeHref]);

  useEffect(() => {
    window.localStorage.setItem(
      SIDEBAR_COLLAPSED_KEY,
      sidebarCollapsed ? "1" : "0",
    );
  }, [sidebarCollapsed]);

  const toggleSidebar = () => {
    setSidebarCollapsed((current) => !current);
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
              {NAV_GROUPS.map((group) => (
                <div
                  className={cn(
                    "flex gap-1 lg:flex-col",
                    sidebarCollapsed && "lg:items-center",
                  )}
                  key={group.group ?? "root"}
                >
                  {group.group ? (
                    <div
                      className={cn(
                        "hidden px-3 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-text-secondary uppercase lg:block",
                        sidebarCollapsed && "lg:hidden",
                      )}
                    >
                      {group.group}
                    </div>
                  ) : null}
                  {group.items.map((item) => {
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
                          sidebarCollapsed &&
                            "lg:size-10 lg:justify-center lg:p-0",
                        )}
                        href={item.href}
                        key={item.href}
                        ref={active ? activeNavItemRef : undefined}
                        title={item.label}
                      >
                        <Icon data-icon="inline-start" />
                        <span className={cn(sidebarCollapsed && "lg:hidden")}>
                          {item.label}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              ))}
            </nav>
            <ButtonLogout collapsed={sidebarCollapsed} />
          </div>
        </aside>
        <div className="min-w-0">
          <header className="px-6 pt-6">
            <div className="flex flex-col gap-4 rounded-2xl bg-card p-6 shadow-[var(--shadow-card)] ring-1 ring-border/70 xl:flex-row xl:items-start xl:justify-between">
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  {sectionBadge ? (
                    <Badge variant="secondary">{sectionBadge}</Badge>
                  ) : null}
                  <span className="break-all font-mono text-[12px] text-text-secondary">
                    {pathname}
                  </span>
                </div>
                {breadcrumbs && breadcrumbs.length > 0 ? (
                  <Breadcrumb>
                    <BreadcrumbList>
                      {withOccurrenceKeys(breadcrumbs, (crumb) =>
                        JSON.stringify([crumb.href ?? null, crumb.label]),
                      ).map(({ key, value: crumb }, index) => (
                        <Fragment key={key}>
                          {index > 0 ? <BreadcrumbSeparator /> : null}
                          <BreadcrumbItem>
                            {crumb.href ? (
                              <BreadcrumbLink href={crumb.href}>
                                {crumb.label}
                              </BreadcrumbLink>
                            ) : index === breadcrumbs.length - 1 ? (
                              <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                            ) : (
                              <span>{crumb.label}</span>
                            )}
                          </BreadcrumbItem>
                        </Fragment>
                      ))}
                    </BreadcrumbList>
                  </Breadcrumb>
                ) : null}
                <div className="flex items-center gap-2">
                  <h1 className="text-[24px] leading-snug font-bold">{title}</h1>
                  {help ? <HelpTip label={title}>{help}</HelpTip> : null}
                </div>
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
  publishAdminLogout();
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } finally {
    window.location.assign("/login");
  }
}
