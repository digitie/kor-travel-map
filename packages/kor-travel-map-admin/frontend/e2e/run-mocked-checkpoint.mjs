import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const checkpoints = new Set(["A", "B", "C", "D"]);
const [checkpoint, ...playwrightArgs] = process.argv.slice(2);

if (!checkpoint || !checkpoints.has(checkpoint)) {
  console.error(
    "사용법: npm run e2e:mocked:checkpoint -- <A|B|C|D> [Playwright 인자]",
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

const require = createRequire(import.meta.url);
const playwrightCli = require.resolve("@playwright/test/cli");
const result = spawnSync(
  process.execPath,
  [
    playwrightCli,
    "test",
    "--reporter=list,./e2e/mocked-failure-reporter.ts",
    ...playwrightArgs,
  ],
  {
    env: {
      ...process.env,
      MOCKED_E2E_CHECKPOINT: checkpoint,
      MOCKED_E2E_REVISION: revision,
    },
    stdio: "inherit",
  },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
