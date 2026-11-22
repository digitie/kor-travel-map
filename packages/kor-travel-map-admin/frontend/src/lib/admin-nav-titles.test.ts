import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { ADMIN_NAV_GROUPS } from "./admin-nav";

/**
 * nav 라벨 = 페이지 제목 고정.
 *
 * 셸은 루트 레이아웃에 한 번만 있고(`AdminShellFrame`), 서버 렌더 첫 화면의 상단 바 제목은
 * nav 정본의 라벨이다. hydration 뒤에는 페이지의 `<AdminShell title=…>`이 `AdminPageTitle`로
 * 등록한 제목으로 바뀐다. 둘이 다르면 첫 화면에서 제목이 한 번 바뀐다(깜빡임) — 그래서 nav
 * 항목마다 (1) `page.tsx` metadata의 `adminDocumentTitle(href, 제목)`과 (2) 그 페이지가
 * 그리는 `<AdminShell>`의 정적 `title`이 nav 라벨과 같아야 한다.
 *
 * 렌더 없이 소스를 읽는다: 페이지 하나를 그리려면 react-query·라우터·지도까지 대역이 필요해
 * 그 대역이 계약보다 쉽게 낡는다. 대신 "찾지 못함"도 실패로 둬서 추출이 조용히 빈 값으로
 * 통과하지 않게 한다.
 */

const APP_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../app");

type NavItem = { href: string; label: string };

const NAV_ITEMS: NavItem[] = ADMIN_NAV_GROUPS.flatMap((group): NavItem[] => [
  ...group.items,
]);

function pageFileFor(href: string): string {
  return join(APP_DIR, href === "/" ? "" : href.slice(1), "page.tsx");
}

function metadataTitle(source: string, href: string): string | undefined {
  const match = source.match(
    /adminDocumentTitle\(\s*"([^"]+)",\s*"([^"]+)",?\s*\)/,
  );
  if (!match) return undefined;
  expect(match[1]).toBe(href);
  return match[2];
}

/** page.tsx가 상대 경로로 가져오는 같은 화면의 클라이언트 파일들. */
function relativeImports(pageFile: string, source: string): string[] {
  return [...source.matchAll(/from "(\.[^"]+)"/g)]
    .map((match) => resolve(dirname(pageFile), `${match[1]}.tsx`))
    .filter((file) => existsSync(file));
}

/**
 * `<AdminShell` 요소의 **최상위** `title="…"` 속성만 읽는다 — 여는 줄보다 정확히 두 칸 더
 * 들여쓴 속성 줄이고, 같은 들여쓰기의 `>`에서 속성 목록이 끝난다(중첩 JSX의 title은 무시).
 */
function adminShellTitles(source: string): string[] {
  const lines = source.split("\n");
  const titles: string[] = [];
  lines.forEach((line, index) => {
    const opening = line.match(/^(\s*)<AdminShell$/);
    if (!opening) return;
    const indent = opening[1];
    for (const attr of lines.slice(index + 1)) {
      if (attr === `${indent}>` || attr === `${indent}/>`) break;
      const title = attr.match(new RegExp(`^${indent}  title="([^"]+)"$`));
      if (title) titles.push(title[1]);
    }
  });
  return titles;
}

describe("admin nav 라벨 = 페이지 제목 (SSR·hydration 제목 일치)", () => {
  it.each(NAV_ITEMS.map((item) => [item.href, item.label] as const))(
    "%s: metadata와 AdminShell 제목이 nav 라벨 %j와 같다",
    (href, label) => {
      const pageFile = pageFileFor(href);
      const pageSource = readFileSync(pageFile, "utf8");

      expect(metadataTitle(pageSource, href)).toBe(label);

      const shellTitles = [pageFile, ...relativeImports(pageFile, pageSource)]
        .flatMap((file) => adminShellTitles(readFileSync(file, "utf8")));
      expect(shellTitles.length).toBeGreaterThan(0);
      expect(new Set(shellTitles)).toEqual(new Set([label]));
    },
  );

  it("검사 대상은 nav 21개 전부다", () => {
    expect(NAV_ITEMS).toHaveLength(21);
  });
});
