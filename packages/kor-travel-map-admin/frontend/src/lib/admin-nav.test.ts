import { formatAdminTitle } from "@kor-travel/ui/admin-shell";
import { describe, expect, it } from "vitest";

import {
  ADMIN_NAV_GROUPS,
  activeAdminNavItem,
  adminAreaFor,
  adminDocumentTitle,
  formatAreaTitle,
} from "./admin-nav";

describe("admin nav 정본", () => {
  it.each([
    ["Feature 관리", "중복 검토"],
    ["", "운영 홈"],
    [undefined, "운영 홈"],
    ["개요", ""],
    ["설정", "설정"],
    ["  시스템 ", " 백업  "],
    [null, null],
  ])("formatAreaTitle(%j, %j)는 공통 formatAdminTitle과 같다", (area, page) => {
    expect(formatAreaTitle(area, page)).toBe(formatAdminTitle(area, page));
  });

  it.each([
    ["/", "개요"],
    ["/features", "Feature 관리"],
    ["/features/abc-123", "Feature 관리"],
    ["/admin/features/new", "Feature 관리"],
    ["/admin/features/dedup-reviews", "Feature 관리"],
    ["/ops/pipeline", "수집 파이프라인"],
    ["/admin/ops/geo-releases", "수집 파이프라인"],
    ["/ops/logs", "모니터링"],
    ["/admin/settings", "시스템"],
  ])("%s의 영역은 %s", (pathname, area) => {
    expect(adminAreaFor(pathname)).toBe(area);
  });

  it("하위 경로는 가장 긴 prefix nav 항목을 고른다", () => {
    expect(activeAdminNavItem("/admin/features/curated/x")?.href).toBe(
      "/admin/features/curated",
    );
    // `/features`가 `/admin/features`의 접두가 아니듯, 이름만 비슷한 경로는 맞지 않는다.
    expect(activeAdminNavItem("/featuresX")).toBeUndefined();
    expect(adminAreaFor("/login")).toBeUndefined();
  });

  it("문서 제목은 상단 바와 같은 '영역 - 페이지'에 서비스 이름을 붙인다", () => {
    expect(adminDocumentTitle("/admin/backups", "백업")).toBe(
      "시스템 - 백업 | kor-travel-map",
    );
    expect(adminDocumentTitle("/", "운영 홈")).toBe(
      "개요 - 운영 홈 | kor-travel-map",
    );
  });

  it("nav href는 중복이 없다", () => {
    const hrefs = ADMIN_NAV_GROUPS.flatMap((group) =>
      group.items.map((item) => item.href),
    );
    expect(new Set(hrefs).size).toBe(hrefs.length);
    expect(hrefs).toHaveLength(21);
  });
});
