/**
 * 관리자 nav 정본 — 그룹(= 상단 바 "영역")·메뉴 라벨·href의 단일 출처.
 * 셸(`components/admin-shell.tsx`)은 여기에 아이콘만 붙이고, 페이지 metadata는
 * `adminDocumentTitle`로 상단 바와 같은 "영역 - 페이지" 형식의 문서 제목을 만든다.
 * 그룹 헤더는 비링크이며 href는 존치하는 canonical 화면만 가리킨다.
 */
export const ADMIN_NAV_GROUPS = [
  {
    group: null,
    section: "개요",
    items: [{ href: "/", label: "운영 홈" }],
  },
  {
    group: "Feature 관리",
    section: "Feature 관리",
    items: [
      { href: "/features", label: "Feature 지도" },
      { href: "/admin/features", label: "Feature 목록" },
      { href: "/admin/features/dedup-reviews", label: "중복 검토" },
      { href: "/admin/manual-provider-dedup", label: "수동/provider 중복 판정" },
      { href: "/admin/features/enrichment-reviews", label: "보강 검토" },
      { href: "/admin/issues", label: "이슈" },
      { href: "/admin/features/curated", label: "큐레이션 관리" },
      { href: "/admin/curations/candidates", label: "큐레이션 후보 검토" },
      { href: "/curated-features", label: "큐레이션 지도" },
    ],
  },
  {
    group: "수집 파이프라인",
    section: "수집 파이프라인",
    items: [
      { href: "/ops/pipeline", label: "파이프라인" },
      { href: "/ops/datasets", label: "데이터셋" },
      { href: "/admin/offline-uploads", label: "오프라인 업로드" },
      { href: "/admin/poi-cache-targets", label: "POI 캐시 대상" },
      { href: "/ops/cache-target-streams", label: "캐시 전파 스트림" },
      { href: "/admin/ops/geo-releases", label: "geo 릴리스" },
    ],
  },
  {
    group: "모니터링",
    section: "모니터링",
    items: [
      { href: "/ops/logs", label: "운영 로그" },
      { href: "/ops/consistency", label: "정합성 점검" },
    ],
  },
  {
    group: "시스템",
    section: "시스템",
    items: [
      { href: "/admin/files", label: "파일 관리" },
      { href: "/admin/backups", label: "백업" },
      { href: "/admin/settings", label: "설정" },
    ],
  },
] as const;

export type AdminNavHref =
  (typeof ADMIN_NAV_GROUPS)[number]["items"][number]["href"];

const ADMIN_NAV_ITEMS = ADMIN_NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, section: group.section })),
);

function matchesNavHref(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** pathname에 가장 길게 맞는 nav 항목(하위 경로 포함). 없으면 undefined. */
export function activeAdminNavItem(pathname: string) {
  return ADMIN_NAV_ITEMS.filter((item) => matchesNavHref(pathname, item.href))
    .toSorted((a, b) => b.href.length - a.href.length)
    .at(0);
}

/** 상단 바 "영역" — pathname이 속한 nav 그룹 이름. */
export function adminAreaFor(pathname: string): string | undefined {
  return activeAdminNavItem(pathname)?.section;
}

const DOCUMENT_TITLE_SUFFIX = "kor-travel-map";

/**
 * 공통 `formatAdminTitle`(`@kor-travel/ui/admin-shell`)과 같은 규칙의 "영역 - 페이지".
 * 그 모듈은 `"use client"`라 서버 컴포넌트의 `metadata`에서 호출할 수 없어 여기 둔다 —
 * 두 구현이 같은 문자열을 내는지는 `admin-nav.test.ts`가 고정한다.
 */
export function formatAreaTitle(
  area: string | null | undefined,
  page: string | null | undefined,
): string {
  const left = area?.trim() ?? "";
  const right = page?.trim() ?? "";
  if (!left) return right;
  if (!right || left === right) return left;
  return `${left} - ${right}`;
}

/**
 * 페이지 metadata용 문서 제목. 상단 바 h1과 같은 "영역 - 페이지"에 서비스 이름을 붙여
 * 여러 관리자 탭 사이에서도 구분되게 한다. 영역은 `href`의 nav 그룹에서 유도한다.
 */
export function adminDocumentTitle(href: string, page: string): string {
  return `${formatAreaTitle(adminAreaFor(href), page)} | ${DOCUMENT_TITLE_SUFFIX}`;
}
