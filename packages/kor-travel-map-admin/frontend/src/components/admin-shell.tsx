"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import {
  ActivityIcon,
  AlertTriangleIcon,
  ArchiveIcon,
  DatabaseIcon,
  FolderTreeIcon,
  GitCompareArrowsIcon,
  HomeIcon,
  LayersIcon,
  LinkIcon,
  ListChecksIcon,
  LogOutIcon,
  MapIcon,
  MapPinnedIcon,
  RadarIcon,
  RouteIcon,
  SettingsIcon,
  SparklesIcon,
  UploadCloudIcon,
  WorkflowIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import {
  AdminPageTitle,
  AdminShell as CommonAdminShell,
} from "@kor-travel/ui/admin-shell";
import { AppMenu, type AppMenuLinkProps } from "@kor-travel/ui/app-menu";
import { usePathname } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";

import { HelpTip } from "@/components/help-tip";
import {
  beginAdminLogout,
  cancelPendingAdminLogout,
  publishAdminLogout,
} from "@/lib/admin-auth-events";
import {
  ADMIN_NAV_GROUPS,
  activeAdminNavItem,
  type AdminNavHref,
} from "@/lib/admin-nav";
import { cn } from "@/lib/utils";

/** nav 항목 아이콘 — 라벨·그룹·href 정본은 `lib/admin-nav.ts`. */
const NAV_ICONS: Record<AdminNavHref, LucideIcon> = {
  "/": HomeIcon,
  "/features": MapIcon,
  "/admin/features": DatabaseIcon,
  "/admin/features/dedup-reviews": GitCompareArrowsIcon,
  "/admin/manual-provider-dedup": GitCompareArrowsIcon,
  "/admin/features/enrichment-reviews": LinkIcon,
  "/admin/issues": AlertTriangleIcon,
  "/admin/features/curated": SparklesIcon,
  "/admin/curations/candidates": ListChecksIcon,
  "/curated-features": MapPinnedIcon,
  "/ops/pipeline": WorkflowIcon,
  "/ops/datasets": LayersIcon,
  "/admin/offline-uploads": UploadCloudIcon,
  "/admin/poi-cache-targets": RouteIcon,
  "/ops/cache-target-streams": ActivityIcon,
  "/admin/ops/geo-releases": RadarIcon,
  "/ops/logs": ActivityIcon,
  "/ops/consistency": RadarIcon,
  "/admin/files": FolderTreeIcon,
  "/admin/backups": ArchiveIcon,
  "/admin/settings": SettingsIcon,
};

function MapMenuLink(props: AppMenuLinkProps) {
  return <Link {...props} />;
}

const COMMON_MENU_GROUPS = ADMIN_NAV_GROUPS.map((group) => ({
  id: group.group ?? "root",
  label: group.group ?? undefined,
  items: group.items.map(({ href, label }) => {
    const Icon = NAV_ICONS[href];
    return {
      id: href,
      href,
      label,
      icon: <Icon aria-hidden="true" className="size-4" />,
    };
  }),
}));

/** 기존 접힘 저장 키("1"/"0")를 그대로 쓴다 — 공통 셸이 같은 형식을 유지한다. */
const SIDEBAR_COLLAPSED_KEY = "kor-travel-map:sidebar-collapsed";
const MAIN_CONTENT_ID = "main-content";

const SHELL_LABELS = {
  openMenu: "메뉴 열기",
  closeMenu: "메뉴 닫기",
  menu: "주요 메뉴",
  skipToContent: "본문으로 건너뛰기",
  collapseRail: "좌측 메뉴 접기",
  expandRail: "좌측 메뉴 펼치기",
} as const;

/**
 * Rail footer row 레시피 (design.md §Macrostructure N3 · M9).
 * flat row · 30px · 500 · hover paper-2 · pressed rules 색 · focus는 base의 단일 outline.
 */
const railRowClass =
  "relative flex h-control-sm shrink-0 items-center gap-2.5 rounded-control px-3 text-xs font-medium whitespace-nowrap text-text-secondary transition-[color,background-color] duration-fast ease-out hover:bg-surface-subtle hover:text-text-primary active:bg-surface-muted";

/** 상단 바 동작의 모든 버튼에 모바일 터치 표적 하한(44px)을 건다. */
const shellActionTouchTargetClasses =
  "max-md:[&_button]:min-h-11 max-md:[&_button]:min-w-11";

export type AdminShellProps = {
  /** 페이지 이름. 상단 바 h1은 "영역 - 페이지" 한 줄이다. */
  title: string;
  /** 상단 바의 작은 한 줄 설명(좁은 폭에서는 말줄임, 전체 문장은 title 속성). */
  description?: string;
  /** "영역" 명시 오버라이드 — 생략하면 nav 그룹을 pathname longest-prefix로 유도한다. */
  section?: string;
  help?: ReactNode;
  helpVariant?: "help" | "info";
  /** 지도처럼 작업면을 먼저 보여야 하는 화면의 본문 여백만 줄인다. */
  compact?: boolean;
  /**
   * 본문 맨 위 한 줄 메타(상태·저장소 경로·건수 묶음 등). 상단 바는 한 줄이라 여러 값을
   * 담는 요약은 여기 둔다. text-secondary 한 줄 — 제목을 반복하는 badge는 넣지 않는다.
   */
  meta?: ReactNode;
  /**
   * 상단 바 오른쪽 동작. 라벨은 `ShellActionLabel`로 감싸 좁은 폭에서 아이콘만 남긴다
   * (접근성 이름은 유지). primary ≤ 1 + secondary ≤ 2 (design.md).
   */
  actions?: ReactNode;
  children: ReactNode;
};

/** 셸 없이 그리는 경로 — 로그인 화면은 인증 전이라 메뉴를 보이지 않는다. */
const SHELL_FREE_PATHS: ReadonlySet<string> = new Set(["/login"]);

/**
 * 관리자 화면 공통 프레임. 루트 레이아웃에 **한 번만** 두어 페이지 이동 사이에도 같은 셸이
 * 살아 있게 한다. 페이지마다 셸을 그리면 이동할 때 셸이 다시 마운트되어, 공통 셸의
 * "drawer로 이동하면 본문에 포커스" 상태가 사라지고 포커스가 BODY로 떨어진다.
 * 이동은 `navigationKey={pathname}`으로 알린다. 제목·설명·동작은 페이지의 `AdminShell`이
 * `AdminPageTitle`로 채우고, 서버 렌더 첫 화면에는 nav 정본의 영역·라벨을 쓴다.
 */
export function AdminShellFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (SHELL_FREE_PATHS.has(pathname)) return children;
  const activeItem = activeAdminNavItem(pathname);
  return (
    <CommonAdminShell
      area={activeItem?.section}
      brand={({ collapsed }) => <MapBrand collapsed={collapsed} />}
      collapsedStorageKey={SIDEBAR_COLLAPSED_KEY}
      labels={SHELL_LABELS}
      mainId={MAIN_CONTENT_ID}
      menu={
        <AppMenu
          groups={COMMON_MENU_GROUPS}
          activeItemId={activeItem?.href ?? null}
          pathname={pathname}
          label="주요 메뉴"
          linkComponent={MapMenuLink}
          testId="map-common-menu"
        />
      }
      navigationKey={pathname}
      railFooter={({ collapsed }) => <ButtonLogout collapsed={collapsed} />}
      testId="map-admin-shell"
      title={activeItem?.label}
    >
      {children}
    </CommonAdminShell>
  );
}

/**
 * 페이지 쪽 셸 내용. 상단 바(제목·설명·동작)는 레이아웃의 `AdminShellFrame`에 등록하고,
 * 본문 여백·meta 줄은 여기서 그린다. 프레임 밖에서는 상단 바만 직접 그린다.
 */
export function AdminShell({
  title,
  description,
  section,
  help,
  helpVariant,
  compact = false,
  meta,
  actions,
  children,
}: AdminShellProps) {
  const pathname = usePathname();
  const area = section ?? activeAdminNavItem(pathname)?.section;
  // md 미만에서는 상단 바 동작 라벨이 숨어(`ShellActionLabel`) 32px 아이콘 버튼만 남는다.
  // 터치 표적 하한 44px(WCAG 2.5.5)을 그 폭에서만 min-size로 보장한다 — 데스크톱 밀도는
  // 그대로다. 상단 바는 min-h-12(48px)라 한 줄을 유지한다.
  const shellActions =
    help || actions ? (
      <div
        className={cn("flex items-center gap-1", shellActionTouchTargetClasses)}
        data-slot="map-shell-actions"
      >
        {help ? (
          <HelpTip label={title} variant={helpVariant}>
            {help}
          </HelpTip>
        ) : null}
        {actions}
      </div>
    ) : undefined;

  return (
    <>
      <AdminPageTitle
        actions={shellActions}
        area={area}
        description={description}
        title={title}
      />
      <div
        className={cn(
          "min-w-0 px-4 md:px-6",
          compact ? "py-3" : "py-4 md:py-6",
        )}
        data-slot="admin-shell-content"
      >
        {meta ? (
          <div
            className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary"
            data-slot="admin-shell-meta"
          >
            {meta}
          </div>
        ) : null}
        {children}
      </div>
    </>
  );
}

/** 타이포 워드마크 — 아이콘 타일·앱 설명 없음(M9). 접힘 rail에서는 축약형 `ktm`. */
function MapBrand({ collapsed }: { collapsed: boolean }) {
  return (
    <Link
      aria-label="kor-travel-map"
      className="flex min-w-0 items-baseline rounded-control text-text-primary no-underline hover:no-underline"
      href="/"
      title={collapsed ? "kor-travel-map" : undefined}
    >
      <span
        className={cn(
          "truncate font-semibold tracking-tight",
          collapsed ? "text-xs" : "text-sm",
        )}
      >
        {collapsed ? "ktm" : "kor-travel-map"}
      </span>
    </Link>
  );
}

function ButtonLogout({ collapsed = false }: { collapsed?: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  async function logout() {
    if (inFlight.current || !beginAdminLogout()) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error("logout failed");
      publishAdminLogout();
      window.location.assign("/login");
    } catch {
      cancelPendingAdminLogout();
      setError("로그아웃하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <div className={cn(collapsed && "flex flex-col items-center")}>
      <button
        aria-busy={busy}
        aria-disabled={busy}
        aria-label={collapsed ? "로그아웃" : undefined}
        className={cn(
          railRowClass,
          collapsed ? "size-control justify-center gap-0 px-0" : "w-full",
        )}
        title={collapsed ? "로그아웃" : undefined}
        type="button"
        onClick={() => void logout()}
      >
        <LogOutIcon
          aria-hidden="true"
          className="size-4 shrink-0 text-icon-default"
        />
        <span className={cn(collapsed && "sr-only")}>로그아웃</span>
      </button>
      {error ? (
        <p role="alert" className="px-2 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
