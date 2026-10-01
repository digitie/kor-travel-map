import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { FEATURE_KINDS } from "@/api/features";
import { DEFAULT_FEATURE_MAP_KINDS } from "@/state/map";

/**
 * Map UI는 weather 기능을 제공하지 않는다 (owner 결정 2026-10-01 — 날씨 정본은
 * kor-travel-weather, Map은 `weather` kind **정의**만 남긴다).
 *
 * 금지할 kind는 손으로 적지 않고 core enum(`kortravelmap.dto._enums.FeatureKind`)에서
 * 읽는다 — 정의는 남고 기능만 빠졌으므로 그 값이 곧 weather 신원이다. 선택지 쪽은
 * "weather 없음"만이 아니라 "core kind 집합 − weather와 **정확히 같음**"을 센다. 목록을
 * 비워 초록을 만드는 길을 막기 위해서다.
 *
 * main에서 빨개지는 자리(2026-10-01 이 브랜치 이전):
 * - `src/state/map.ts` `DEFAULT_FEATURE_MAP_KINDS = ["weather", "notice"]`
 * - `src/api/features.ts` `FEATURE_KINDS`에 `"weather"` + `fetchAdminFeatureWeather`의
 *   `` `/v1/admin/features/${...}/weather` `` 경로 리터럴
 * - `src/components/feature-weather-panel.tsx` 파일 자체와
 *   `feature-kind-detail-panel.tsx`의 그 import
 * - `src/app/admin/dedup-reviews/dedup-review-client.tsx` `DEDUP_KINDS`의 `"weather"`
 * - `src/api/types.ts`의 `/v1/features/weather/*`·`.../{feature_id}/weather` path 키
 */

const FRONTEND_ROOT = path.resolve(__dirname, "..", "..");
const SRC_ROOT = path.join(FRONTEND_ROOT, "src");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..", "..", "..");
const CORE_ENUMS = path.join(REPO_ROOT, "src", "kortravelmap", "dto", "_enums.py");
const GENERATED_TYPES = path.join(SRC_ROOT, "api", "types.ts");

function coreFeatureKinds(): Map<string, string> {
  const source = readFileSync(CORE_ENUMS, "utf8");
  const body = source.match(/class FeatureKind\(StrEnum\):([\s\S]*?)\n\n\n/);
  if (body === null) throw new Error("core FeatureKind enum을 찾지 못했다");
  const members = new Map<string, string>();
  for (const m of body[1].matchAll(/^\s+([A-Z_]+)\s*=\s*"([a-z_]+)"/gm)) {
    members.set(m[1], m[2]);
  }
  return members;
}

function weatherKind(): string {
  const value = coreFeatureKinds().get("WEATHER");
  if (value === undefined) {
    throw new Error("core FeatureKind.WEATHER 정의가 사라졌다 — 정의는 남겨야 한다");
  }
  return value;
}

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

// 생성 타입과 테스트 자신은 본문 스캔에서 뺀다(types.ts는 아래에서 path 키로 따로 센다).
function productionSources(): string[] {
  return sourceFiles(SRC_ROOT).filter(
    (file) =>
      file !== GENERATED_TYPES && !/\.test\.(ts|tsx)$/.test(path.basename(file)),
  );
}

/** 문자열/템플릿 리터럴 안의 `/weather` path segment. */
const WEATHER_PATH_LITERAL = /["'`][^"'`\n]*\/weather(?=[/?"'`]|$)/m;
/** import 경로 specifier에 weather가 들어간 모듈. */
const WEATHER_IMPORT = /\bfrom\s+["'][^"']*weather[^"']*["']/i;

describe("Map UI는 weather 기능을 제공하지 않는다", () => {
  it("core 정의에는 weather kind가 남아 있다 (기능만 제거, 정의는 유지)", () => {
    expect(weatherKind()).toBe("weather");
  });

  it("kind 토글/필터 선택지 = core kind − weather", () => {
    const forbidden = weatherKind();
    const expected = [...coreFeatureKinds().values()].filter(
      (kind) => kind !== forbidden,
    );
    expect(new Set<string>(FEATURE_KINDS)).toEqual(new Set(expected));
    expect(DEFAULT_FEATURE_MAP_KINDS as readonly string[]).not.toContain(forbidden);
    expect(DEFAULT_FEATURE_MAP_KINDS.length).toBeGreaterThan(0);
  });

  it("검사한 FEATURE_KINDS가 실제로 화면 선택지를 그린다", () => {
    // 위 단언이 화면과 무관한 상수만 보고 초록이 되지 않도록, 지도 kind 토글과 admin
    // kind select가 이 목록을 그대로 렌더하는지 센다.
    for (const rel of [
      "app/features/features-client.tsx",
      "app/admin/features/admin-features-client.tsx",
    ]) {
      const source = readFileSync(path.join(SRC_ROOT, rel), "utf8");
      expect(source, rel).toMatch(/import\s*\{[^}]*\bFEATURE_KINDS\b[^}]*\}\s*from\s*"@\/api\/features"/);
      expect(source, rel).toContain("FEATURE_KINDS.map(");
    }
  });

  it("dedup review kind 필터도 weather를 내지 않는다", () => {
    const source = readFileSync(
      path.join(SRC_ROOT, "app", "admin", "dedup-reviews", "dedup-review-client.tsx"),
      "utf8",
    );
    const list = source.match(/const DEDUP_KINDS = \[([\s\S]*?)\] as const;/);
    if (list === null) throw new Error("DEDUP_KINDS 선언을 찾지 못했다");
    const kinds = [...list[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(kinds.length).toBeGreaterThan(0);
    expect(kinds).not.toContain(weatherKind());
  });

  it("어떤 src 파일도 weather API 경로·weather 모듈을 참조하지 않는다", () => {
    // 탐지식 자체가 main의 실제 리터럴을 잡는지 먼저 확인한다(항진 방지).
    expect(
      WEATHER_PATH_LITERAL.test(
        "`/v1/admin/features/${encodeURIComponent(featureId)}/weather`",
      ),
    ).toBe(true);
    expect(
      WEATHER_IMPORT.test(
        'import { FeatureWeatherPanel } from "@/components/feature-weather-panel";',
      ),
    ).toBe(true);
    expect(WEATHER_PATH_LITERAL.test('"/v1/features/in-bounds"')).toBe(false);

    const files = productionSources();
    // 스캔이 실제로 소스를 봤는지 — 경로가 어긋나 0개를 보고 초록이 되는 것을 막는다.
    expect(files.length).toBeGreaterThan(50);
    expect(files.some((f) => f.endsWith(path.join("components", "vworld-map-view.tsx")))).toBe(
      true,
    );

    const offenders: string[] = [];
    for (const file of files) {
      const rel = path.relative(SRC_ROOT, file);
      if (/weather/i.test(path.basename(file))) offenders.push(`${rel}: weather 파일`);
      const source = readFileSync(file, "utf8");
      if (WEATHER_PATH_LITERAL.test(source)) offenders.push(`${rel}: /weather 경로`);
      if (WEATHER_IMPORT.test(source)) offenders.push(`${rel}: weather import`);
    }
    expect(offenders).toEqual([]);
  });

  it("생성 OpenAPI 타입에 weather path가 없다", () => {
    const source = readFileSync(GENERATED_TYPES, "utf8");
    const pathKeys = [...source.matchAll(/^ {4}"(\/[^"]+)": \{$/gm)].map((m) => m[1]);
    expect(pathKeys).toContain("/v1/features/in-bounds");
    expect(pathKeys.filter((key) => /\/weather(\/|$)/.test(key))).toEqual([]);
  });
});
