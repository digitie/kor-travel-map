import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * maplibre worker 배선이 **실제로 성립하는지** 센다.
 *
 * 2026-09-18 prod 실측: worker가 조용히 죽어 GeoJSON source가 tile을 하나도 만들지
 * 못했고, zoom 14 이상에서 마커가 한 개도 그려지지 않았다. 원인은 Turbopack이 URL
 * import를 해시된 단일 asset으로 내보내며 **형제 파일을 함께 내보내지 않는다**는
 * 것이다 — worker(`maplibre-gl-worker.mjs`)가 `maplibre-gl-shared.mjs`를 상대
 * 경로로 import하는데 blob URL에서는 그것을 풀 수 없다.
 *
 * 그래서 이 검사들은 이름을 손으로 적지 않고 **세 조각이 서로 맞는지**를 센다:
 * 복사 스크립트가 옮기는 파일 목록, 소스가 가리키는 URL, 빌드 훅. 하나만 바뀌어도
 * 빨개진다.
 */

const FRONTEND_ROOT = path.resolve(__dirname, "..", "..");
const SCRIPT = path.join(FRONTEND_ROOT, "scripts", "copy-maplibre-worker.mjs");
const MAP_VIEW = path.join(FRONTEND_ROOT, "src", "components", "vworld-map-view.tsx");
const PACKAGE_JSON = path.join(FRONTEND_ROOT, "package.json");

function copiedFileNames(): string[] {
  const source = readFileSync(SCRIPT, "utf8");
  const match = source.match(/WORKER_FILES\s*=\s*\[([^\]]+)\]/);
  if (match === null) throw new Error("복사 스크립트에서 WORKER_FILES를 찾지 못했다");
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function configuredWorkerUrl(): string {
  const source = readFileSync(MAP_VIEW, "utf8");
  const match = source.match(/setWorkerUrl\(\s*"([^"]+)"\s*\)/);
  if (match === null) throw new Error("vworld-map-view.tsx가 setWorkerUrl을 부르지 않는다");
  return match[1];
}

describe("maplibre worker 배선", () => {
  it("worker와 그 형제 파일을 **함께** 옮긴다", () => {
    const files = copiedFileNames();
    // 둘 중 하나만 옮기면 worker가 상대 import를 풀지 못해 조용히 죽는다.
    expect(files).toContain("maplibre-gl-worker.mjs");
    expect(files).toContain("maplibre-gl-shared.mjs");
  });

  it("소스가 가리키는 URL이 실제로 복사되는 파일이다", () => {
    const url = configuredWorkerUrl();
    expect(url.startsWith("/maplibre/")).toBe(true);
    expect(copiedFileNames()).toContain(path.posix.basename(url));
  });

  it("빌드/개발 훅이 그 스크립트를 부른다", () => {
    const pkg = JSON.parse(readFileSync(PACKAGE_JSON, "utf8")) as {
      scripts: Record<string, string>;
    };
    for (const hook of ["prebuild", "predev"]) {
      expect(pkg.scripts[hook] ?? "").toContain("copy-maplibre-worker.mjs");
    }
  });

  it("스크립트를 실제로 돌리면 두 파일이 모두 생긴다", () => {
    // 선언이 아니라 **효과**를 센다 — 설치된 maplibre가 그 파일들을 더 이상 내보내지
    // 않으면(경로/이름 변경) 여기서 빨개진다. 그때는 배선 전체를 다시 봐야 한다.
    const workdir = mkdtempSync(path.join(tmpdir(), "maplibre-worker-"));
    execFileSync(process.execPath, [SCRIPT], { cwd: workdir, stdio: "pipe" });
    for (const file of copiedFileNames()) {
      expect(existsSync(path.join(workdir, "public", "maplibre", file))).toBe(true);
    }
  });
});
