// dev 포함 npm audit 게이트의 한시 완화(docs/dev-environment.md §10.6, 2026-11-18).
//
// `npm audit --audit-level=high`(= `audit:dev`)를 그대로 돌리되, high/critical 근원
// advisory가 **아래 목록에만** 있을 때 통과시킨다. 목록 밖 advisory가 high 이상으로
// 하나라도 나오면 지금도 빨갛다. 배포 의존성 게이트(`audit:high`, `--omit=dev`)는 이
// 스크립트와 무관하게 그대로 막는다.
//
// 다시 조일 조건: 패치된 picomatch가 나와 lockfile·overrides로 소비되면 CI 스텝과
// verify-all-gates.sh를 `npm run audit:dev`로 되돌리고 이 파일과 `audit:dev:known`을 지운다.
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

// advisory id → 완화 근거. 새 항목은 §10.6에 원인·범위·다시 조일 조건을 적은 PR로만 넣는다.
export const KNOWN_DEV_ONLY_ADVISORIES = {
  "GHSA-fc5q-39xc-vjpf":
    "2026-11-18: picomatch ReDoS. 2026-11-17 범위가 <=4.0.7(최신)로 넓어져 패치 없음. dev 도구 전용.",
};

const BLOCKING = new Set(["high", "critical"]);

function advisoryId(via) {
  const match = /(GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})/.exec(String(via.url ?? ""));
  return match ? match[1] : `source:${via.source ?? "?"}`;
}

export function evaluate(report) {
  if (!report || typeof report !== "object" || report.error || !report.vulnerabilities) {
    return { ok: false, unknown: ["npm audit 결과를 읽지 못했습니다."], known: [] };
  }
  const unknown = new Set();
  const known = new Set();
  for (const [name, entry] of Object.entries(report.vulnerabilities)) {
    for (const via of entry.via ?? []) {
      // 문자열 via는 다른 패키지를 거친 전파다. 근원 advisory는 그 패키지 항목에서 센다.
      if (typeof via !== "object" || via === null || !BLOCKING.has(via.severity)) continue;
      const id = advisoryId(via);
      (id in KNOWN_DEV_ONLY_ADVISORIES ? known : unknown).add(`${id} (${name}, ${via.severity})`);
    }
  }
  return { ok: unknown.size === 0, unknown: [...unknown], known: [...known] };
}

function runAudit() {
  const npmExecPath = process.env.npm_execpath;
  if (!npmExecPath) {
    throw new Error("audit:dev:known은 exact npm run 경계에서 실행해야 합니다.");
  }
  const result = spawnSync(
    process.execPath,
    [npmExecPath, "audit", "--audit-level=high", "--json"],
    { cwd: process.cwd(), encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  if (result.error) throw result.error;
  return JSON.parse(result.stdout);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const inputIndex = process.argv.indexOf("--input");
  let report;
  try {
    report =
      inputIndex > 0
        ? JSON.parse(readFileSync(process.argv[inputIndex + 1], "utf8"))
        : runAudit();
  } catch (error) {
    console.error(`npm audit 실행·해석 실패: ${error.message}`);
    process.exit(2);
  }
  const { ok, unknown, known } = evaluate(report);
  for (const line of known) console.log(`한시 완화된 dev advisory: ${line}`);
  if (!ok) {
    for (const line of unknown) console.error(`차단: 완화 목록 밖 high 이상 advisory: ${line}`);
    process.exit(1);
  }
  console.log("dev 포함 audit: 완화 목록 밖 high 이상 advisory 0건");
}
