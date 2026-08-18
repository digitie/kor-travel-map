"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

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
  MapIcon,
  MapPinnedIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  ListChecksIcon,
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
 * 작업 지향 nav 그룹 (§1) — nav·섹션 라벨·브레드크럼 라벨의 단일 정본.
 * 그룹 헤더는 비링크이며 href는 존치하는 canonical 화면만 가리킨다.
 */
const NAV_GROUPS = [
  {
    group: null,
    section: "개요",
    items: [{ href: "/", label: "홈", icon: HomeIcon }],
  },
  {
    group: "Feature 관리",
    section: "Feature 관리",
    items: [
      { href: "/features", label: "Feature 지도", icon: MapIcon },
      { href: "/admin/features", label: "Feature 목록", icon: DatabaseIcon },
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
      {
        href: "/admin/curations/candidates",
        label: "큐레이션 후보",
        icon: ListChecksIcon,
      },
      { href: "/curated-features", label: "큐레이션 지도", icon: MapPinnedIcon },
    ],
  },
  {
    group: "수집 파이프라인",
    section: "수집 파이프라인",
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
    section: "모니터링",
    items: [
      { href: "/ops/logs", label: "운영 로그", icon: ActivityIcon },
      { href: "/ops/consistency", label: "정합성 점검", icon: RadarIcon },
    ],
  },
  {
    group: "시스템",
    section: "시스템",
    items: [
      { href: "/admin/files", label: "파일 관리", icon: FolderTreeIcon },
      { href: "/admin/backups", label: "백업", icon: ArchiveIcon },
      { href: "/admin/settings", label: "설정", icon: SettingsIcon },
    ],
  },
] as const;

const navItems = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, section: group.section })),
);

const SIDEBAR_COLLAPSED_KEY = "kor-travel-map:sidebar-collapsed";
const MAIN_CONTENT_ID = "main-content";

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Rail nav row / footer row 레시피 (design.md §Macrostructure N3 · M9).
 * flat row · 30px · 500 · hover paper-2 · pressed rules 색 · focus = 단일 outline 레시피.
 * active 는 색만이 아니라 좌측 2px brand mark + `aria-current="page"`(M11).
 */
const railRowClass =
  "relative flex h-control-sm shrink-0 items-center gap-2.5 rounded-control px-3 text-xs font-medium whitespace-nowrap text-text-secondary transition-[color,background-color] duration-fast ease-out hover:bg-surface-subtle hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus active:bg-surface-muted";

const railRowActiveClass =
  "bg-brand-tint text-text-primary hover:bg-brand-tint before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-brand";

const railRowCollapsedClass = "lg:size-control lg:justify-center lg:gap-0 lg:px-0";

export type AdminBreadcrumb = { label: string; href?: string };

export type AdminShellProps = {
  title: string;
  description?: string;
  /** 명시 오버라이드 — 생략 시 NAV_GROUPS longest-prefix로 유도(§1). breadcrumbs 가 없을 때만 h1 위 한 줄 라벨로 렌더. */
  section?: string;
  breadcrumbs?: AdminBreadcrumb[];
  help?: ReactNode;
  /**
   * h1 아래 한 줄 메타(상태·갱신 시각·건수 등). text-secondary 텍스트 한 줄로만 렌더한다 —
   * 제목을 반복하는 badge 는 넣지 않는다(M30/M31). 구분자는 `·`.
   */
  meta?: ReactNode;
  /** 헤더 밴드 액션 슬롯 — primary ≤ 1 + secondary ≤ 2 (design.md). 나머지 cross-link 는 rail/breadcrumb 로. */
  actions?: ReactNode;
  children: ReactNode;
};

export function AdminShell({
  title,
  description,
  section,
  breadcrumbs,
  help,
  meta,
  actions,
  children,
}: AdminShellProps) {
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
  const sectionLabel = section ?? activeItem?.section;
  const hasBreadcrumbs = Boolean(breadcrumbs && breadcrumbs.length > 0);

  useEffect(() => {
    if (typeof window === "undefined" || window.innerWidth >= 1024) return;
    // M14: reduced-motion 이면 smooth scroll 대신 즉시 이동.
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    activeNavItemRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
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
    <div className="min-h-dvh bg-surface-page text-text-primary">
      {/* M11: skip link — rail 19개 항목을 건너뛰어 <main> 으로. nav 밖(링크 수 보존). */}
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-control focus:border focus:border-border focus:bg-card focus:px-3 focus:py-2 focus:text-xs focus:font-medium focus:text-text-primary focus:shadow-elevated focus:outline-2 focus:outline-offset-2 focus:outline-focus"
        href={`#${MAIN_CONTENT_ID}`}
      >
        본문으로 건너뛰기
      </a>
      <div
        className={cn(
          "grid min-h-dvh min-w-0",
          sidebarCollapsed
            ? "lg:grid-cols-[4rem_minmax(0,1fr)]"
            : "lg:grid-cols-[16rem_minmax(0,1fr)]",
        )}
      >
        {/* Rail (N3): paper-2 위 hairline 분리, rest shadow 없음. lg 에서 sticky 전체 높이. */}
        <aside
          className="min-w-0 border-b border-border bg-card lg:sticky lg:top-0 lg:h-dvh lg:self-start lg:border-r lg:border-b-0"
          data-slot="admin-shell-rail"
        >
          <div className="flex h-full min-w-0 flex-col">
            <div
              className={cn(
                "flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4",
                sidebarCollapsed &&
                  "lg:h-auto lg:flex-col lg:justify-center lg:gap-1 lg:px-0 lg:py-2",
              )}
            >
              {/* 타이포 워드마크 — 아이콘 타일 없음(M9). 접힘 시 축약형 `ktm`. */}
              <Link
                aria-label="kor-travel-map admin"
                className={cn(
                  "flex min-w-0 items-baseline gap-1.5 rounded-control text-text-primary no-underline hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                  sidebarCollapsed && "lg:justify-center",
                )}
                href="/"
              >
                <span
                  className={cn(
                    "truncate text-sm font-semibold tracking-tight",
                    sidebarCollapsed && "lg:hidden",
                  )}
                >
                  kor-travel-map
                </span>
                <span
                  className={cn(
                    "text-2xs font-medium text-text-tertiary",
                    sidebarCollapsed && "lg:hidden",
                  )}
                >
                  admin
                </span>
                <span
                  aria-hidden="true"
                  className={cn(
                    "hidden text-xs font-semibold tracking-tight",
                    sidebarCollapsed && "lg:inline",
                  )}
                >
                  ktm
                </span>
              </Link>
              <div className="flex shrink-0 items-center gap-1">
                <ButtonLogout className="lg:hidden" iconOnly />
                <button
                  aria-label={
                    sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"
                  }
                  className={cn(
                    buttonVariants({ variant: "ghost", size: "icon-sm" }),
                    "hidden lg:inline-flex",
                  )}
                  title={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"}
                  type="button"
                  onClick={toggleSidebar}
                >
                  {sidebarCollapsed ? (
                    <PanelLeftOpenIcon aria-hidden="true" />
                  ) : (
                    <PanelLeftCloseIcon aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>
            <nav
              aria-label="주요 메뉴"
              className={cn(
                "flex min-h-0 max-w-full gap-1 overflow-x-auto px-3 py-2 lg:flex-1 lg:flex-col lg:gap-0.5 lg:overflow-x-hidden lg:overflow-y-auto lg:py-3",
                sidebarCollapsed && "lg:items-center lg:px-2",
              )}
            >
              {NAV_GROUPS.map((group) => (
                <div
                  className={cn(
                    "flex shrink-0 items-center gap-1 lg:flex-col lg:items-stretch lg:gap-0.5",
                    sidebarCollapsed && "lg:items-center",
                  )}
                  key={group.group ?? "root"}
                >
                  {group.group ? (
                    <>
                      {/* 그룹 라벨 12px/500 + hairline rule — 한글이라 uppercase/tracking 없음(m3). <lg 에서는 strip 안 인라인 라벨. */}
                      <div
                        className={cn(
                          "ml-1 flex shrink-0 items-center gap-2 border-l border-border pl-3 text-2xs font-medium whitespace-nowrap text-text-secondary",
                          "lg:ml-0 lg:border-l-0 lg:px-3 lg:pt-4 lg:pb-1 lg:after:h-px lg:after:flex-1 lg:after:bg-border",
                          sidebarCollapsed && "lg:hidden",
                        )}
                      >
                        {group.group}
                      </div>
                      {sidebarCollapsed ? (
                        <span
                          aria-hidden="true"
                          className="mx-auto my-2 hidden h-px w-6 bg-border lg:block"
                        />
                      ) : null}
                    </>
                  ) : null}
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const active = item.href === activeHref;
                    return (
                      <Link
                        aria-current={active ? "page" : undefined}
                        aria-label={sidebarCollapsed ? item.label : undefined}
                        className={cn(
                          railRowClass,
                          "no-underline hover:no-underline",
                          active && railRowActiveClass,
                          sidebarCollapsed && railRowCollapsedClass,
                        )}
                        href={item.href}
                        key={item.href}
                        ref={active ? activeNavItemRef : undefined}
                        title={sidebarCollapsed ? item.label : undefined}
                      >
                        <Icon
                          aria-hidden="true"
                          className={cn(
                            "size-4 shrink-0",
                            active ? "text-brand" : "text-icon-default",
                          )}
                        />
                        <span className={cn(sidebarCollapsed && "lg:hidden")}>
                          {item.label}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              ))}
            </nav>
            {/* 로그아웃 = rail footer 의 plain row(M9). <lg 에서는 상단 워드마크 행의 아이콘 버튼이 대신한다. */}
            <div
              className={cn(
                "hidden shrink-0 border-t border-border p-2 lg:block",
                sidebarCollapsed && "lg:flex lg:justify-center",
              )}
            >
              <ButtonLogout collapsed={sidebarCollapsed} />
            </div>
          </div>
        </aside>
        <div className="flex min-w-0 flex-col">
          {/* Flush header band: breadcrumb/section → h1(+help) + actions 한 baseline → meta → description, 아래 hairline(M9/M30/m1). */}
          <header
            className="border-b border-border px-6 pt-5 pb-4"
            data-slot="admin-shell-header"
          >
            <div className="flex min-w-0 flex-col gap-1">
              {hasBreadcrumbs && breadcrumbs ? (
                <Breadcrumb>
                  <BreadcrumbList className="text-xs">
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
              ) : sectionLabel ? (
                <p className="text-2xs font-medium text-text-secondary">
                  {sectionLabel}
                </p>
              ) : null}
              <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center md:justify-between md:gap-6">
                <div className="flex min-w-0 items-center gap-2">
                  <h1 className="text-xl leading-tight font-bold tracking-tight text-text-primary">
                    {title}
                  </h1>
                  {help ? <HelpTip label={title}>{help}</HelpTip> : null}
                </div>
                {actions ? (
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {actions}
                  </div>
                ) : null}
              </div>
              {meta ? (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">
                  {meta}
                </div>
              ) : null}
              {description ? (
                <p className="max-w-3xl text-xs text-text-secondary">
                  {description}
                </p>
              ) : null}
            </div>
          </header>
          {/*
            M11: <main> 은 children 만 감싼다(aside/header 밖). skip link 대상.
            `focus-visible:outline-0` — design.md §Focus 닫힌 목록 4번. skip link(Enter)로
            프로그램 포커스를 받으면 마지막 입력이 키보드라 `:focus-visible`이 매칭돼 **페이지 폭
            2px 링**이 본문 전체에 그려진다. 사용자가 키로 이동한 요소가 아니라 링이 "어디로
            갔는지"를 알리지 못하고, 도착 사실은 스크롤 점프와 본문 첫 heading 이 알린다.
            `outline-none` 은 금지(§금지 패턴 6 — v4에서 `--tw-outline-style: none` 이 안쪽 컨트롤
            까지 오염) — 폭만 0으로 끄는 `outline-0` 이라야 자식 컨트롤 링이 살아 있다.
          */}
          <main
            className="min-w-0 flex-1 px-6 py-6 focus-visible:outline-0"
            data-slot="admin-shell-main"
            id={MAIN_CONTENT_ID}
            tabIndex={-1}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}

function ButtonLogout({
  collapsed = false,
  iconOnly = false,
  className,
}: {
  /** lg rail 접힘 — 라벨을 lg 에서만 숨긴다. */
  collapsed?: boolean;
  /** 모든 breakpoint 에서 아이콘만(<lg 상단 행). */
  iconOnly?: boolean;
  className?: string;
}) {
  const labelHidden = iconOnly || collapsed;
  return (
    <button
      aria-label={labelHidden ? "로그아웃" : undefined}
      className={cn(
        railRowClass,
        iconOnly ? "size-control-sm justify-center gap-0 px-0" : "w-full",
        !iconOnly && collapsed && railRowCollapsedClass,
        className,
      )}
      title={labelHidden ? "로그아웃" : undefined}
      type="button"
      onClick={() => void logout()}
    >
      <LogOutIcon aria-hidden="true" className="size-4 shrink-0 text-icon-default" />
      <span className={cn(iconOnly ? "sr-only" : collapsed && "lg:hidden")}>
        로그아웃
      </span>
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
