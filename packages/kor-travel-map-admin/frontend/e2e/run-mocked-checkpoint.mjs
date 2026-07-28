import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

const checkpoints = new Set(["A", "B", "C", "D"]);
const [checkpoint, ...playwrightArgs] = process.argv.slice(2);

if (!checkpoint || !checkpoints.has(checkpoint)) {
  console.error(
    "사용법: npm run e2e:mocked:checkpoint -- <A|B|C|D> [--workers=<양의 정수>]",
  );
  process.exit(2);
}

const unsafeArgs = playwrightArgs.filter(
  (argument) => !/^--workers=[1-9][0-9]*$/.test(argument),
);
if (unsafeArgs.length > 0) {
  console.error(
    "checkpoint는 전체 suite를 보존하는 --workers=<양의 정수> 외 Playwright 인자를 허용하지 않습니다.",
  );
  process.exit(2);
}

const revision = process.env.MOCKED_E2E_REVISION ?? process.env.GITHUB_SHA;
if (!revision || !/^[0-9a-f]{40}$/.test(revision)) {
  console.error(
    "MOCKED_E2E_REVISION 또는 GITHUB_SHA에 exact 40자 SHA가 필요합니다.",
  );
  process.exit(2);
}

const headResult = spawnSync("git", ["rev-parse", "HEAD"], {
  cwd: process.cwd(),
  encoding: "utf8",
});
const headRevision = headResult.stdout?.trim();
if (
  headResult.status !== 0 ||
  !headRevision ||
  !/^[0-9a-f]{40}$/.test(headRevision)
) {
  console.error(
    "checkpoint 실행 worktree의 exact Git HEAD를 확인할 수 없습니다.",
  );
  process.exit(2);
}
if (revision !== headRevision) {
  console.error(
    `checkpoint revision이 Git HEAD와 다릅니다: declared=${revision}, head=${headRevision}`,
  );
  process.exit(2);
}
const statusResult = spawnSync(
  "git",
  ["status", "--porcelain", "--untracked-files=normal"],
  {
    cwd: process.cwd(),
    encoding: "utf8",
  },
);
if (statusResult.status !== 0 || statusResult.stdout.trim()) {
  console.error(
    "checkpoint는 tracked/untracked 변경이 없는 exact Git worktree에서만 실행할 수 있습니다.",
  );
  process.exit(2);
}

const frontendBaseUrl = process.env.E2E_BASE_URL ?? "http://127.0.0.1:12705";
let frontendRevision;
let frontendSourceDigest;
try {
  const response = await fetch(new URL("/api/build-info", frontendBaseUrl), {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  frontendRevision =
    typeof payload === "object" &&
    payload !== null &&
    "revision" in payload &&
    typeof payload.revision === "string"
      ? payload.revision
      : undefined;
  frontendSourceDigest =
    typeof payload === "object" &&
    payload !== null &&
    "source_digest" in payload &&
    typeof payload.source_digest === "string"
      ? payload.source_digest
      : undefined;
} catch (error) {
  console.error(
    `실제 frontend build revision을 확인할 수 없습니다: ${
      error instanceof Error ? error.message : String(error)
    }`,
  );
  process.exit(2);
}
if (frontendRevision !== revision) {
  console.error(
    `실제 frontend revision이 checkpoint와 다릅니다: declared=${revision}, frontend=${frontendRevision ?? "unknown"}`,
  );
  process.exit(2);
}
const sourceDigestResult = spawnSync(
  process.execPath,
  [path.resolve(process.cwd(), "../../../scripts/frontend-source-digest.mjs")],
  {
    cwd: path.resolve(process.cwd(), "../../.."),
    encoding: "utf8",
  },
);
const sourceDigest = sourceDigestResult.stdout?.trim();
if (
  sourceDigestResult.status !== 0 ||
  !sourceDigest ||
  !/^[0-9a-f]{64}$/.test(sourceDigest)
) {
  console.error("현재 frontend source digest를 계산할 수 없습니다.");
  process.exit(2);
}
if (frontendSourceDigest !== sourceDigest) {
  console.error(
    `실제 frontend source digest가 checkpoint worktree와 다릅니다: expected=${sourceDigest}, frontend=${frontendSourceDigest ?? "unknown"}`,
  );
  process.exit(2);
}

const require = createRequire(import.meta.url);
const playwrightCli = require.resolve("@playwright/test/cli");
const result = spawnSync(
  process.execPath,
  [
    playwrightCli,
    "test",
    ...playwrightArgs,
    "--reporter=list,./e2e/mocked-failure-reporter.ts",
  ],
  {
    env: {
      ...process.env,
      MOCKED_E2E_CHECKPOINT: checkpoint,
      MOCKED_E2E_REVISION: revision,
      MOCKED_E2E_VERIFIED_REVISION: headRevision,
      MOCKED_E2E_VERIFIED_FRONTEND_REVISION: frontendRevision,
      MOCKED_E2E_VERIFIED_FRONTEND_SOURCE_DIGEST: frontendSourceDigest,
    },
    stdio: "inherit",
  },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
